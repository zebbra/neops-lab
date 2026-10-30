"""The lab's network zones: a topology's `zones`, and what each zone is deployed as.

A zone is a management network of its own, a containerlab topology of its own
and a worker attached only to that network, so discovery shows routing on real
devices. Devices without a zone sit in `default` on `lab-net`, as in every
other scenario.
"""

import ipaddress
import json
import pathlib
import re

import pytest

import labscripts

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
gen = labscripts.load("gen_clab_topology")
wait_ready = labscripts.load("wait_ready")

SCENARIOS_DIR = LAB_DIR / "scenarios"
SCENARIOS = sorted(p.name for p in SCENARIOS_DIR.iterdir() if p.is_dir() and p.name != "_base")
MAKEFILE = (LAB_DIR / "Makefile").read_text()
WORKER_COMPOSE = (LAB_DIR / "docker-compose.worker.yml").read_text()
APPLY_SCRIPT = (LAB_DIR / "apply_cms_config").read_text()

DEPLOYMENT = gen.Deployment(name="neops-lab", network="lab-net", subnet=gen.TOPOLOGY_SUBNET)
FB_ID = "fb.base.neops.io/global_discover_network:0.2.0"


def _topology(scenario):
    return json.loads((SCENARIOS_DIR / scenario / "topology.json").read_text())


def _zoned(scenario):
    return bool(_topology(scenario).get("zones"))


ZONED = [name for name in SCENARIOS if _zoned(name)]


def _frr(mgmt_ip, zone=None):
    device = {"mgmt_ip": mgmt_ip, "vendor": "frr", "loopback": "lo", "interfaces": []}
    if zone:
        device["zone"] = zone
    return device


ZONES = {"zone-a": {"subnet": "172.30.10.0/24", "description": "Site A"}}
DEVICES = {"r1": _frr("172.30.0.11"), "a1": _frr("172.30.10.11", "zone-a")}


def test_the_network_zones_scenario_ships():
    assert "network-zones" in ZONED


def test_devices_are_grouped_by_zone_with_default_first():
    groups = gen.group_by_zone(DEVICES, ZONES)
    assert list(groups) == ["default", "zone-a"]
    assert list(groups["default"]) == ["r1"]
    assert list(groups["zone-a"]) == ["a1"]


def test_a_scenario_without_zones_is_one_default_group():
    assert gen.group_by_zone({"r1": _frr("172.30.0.11")}, {}) == {"default": {"r1": _frr("172.30.0.11")}}


def test_a_device_naming_an_undeclared_zone_is_refused():
    with pytest.raises(SystemExit, match="zone-x"):
        gen.group_by_zone({"r1": _frr("172.30.10.11", "zone-x")}, ZONES)


def test_default_cannot_be_declared_as_a_zone():
    """default has no row in the CMS and no network of its own: it is lab-net."""
    with pytest.raises(SystemExit, match="default"):
        gen.group_by_zone(DEVICES, {"default": {"subnet": "172.30.10.0/24"}})


def test_a_zone_deploys_on_its_own_network_under_its_own_lab_name():
    zone = gen.zone_deployment(DEPLOYMENT, "zone-a", ZONES["zone-a"])
    assert zone == gen.Deployment(name="neops-lab-zone-a", network="lab-net-zone-a", subnet="172.30.10.0/24")
    clab = gen.render_clab(gen.group_by_zone(DEVICES, ZONES)["zone-a"], zone)
    assert clab["mgmt"] == {"network": "lab-net-zone-a", "ipv4-subnet": "172.30.10.0/24"}
    assert list(clab["topology"]["nodes"]) == ["a1"]


def test_each_zone_has_its_own_topology_file_and_default_keeps_the_old_one():
    assert gen.clab_file("demo", "default").name == "neops-lab.clab.json"
    assert gen.clab_file("demo", "zone-a").name == "neops-lab-zone-a.clab.json"
    assert gen.clab_file("demo", "zone-a").parent == gen.clab_file("demo", "default").parent, (
        "the FRR binds are relative to the topology file's directory, so every zone's file sits beside default's"
    )


def test_zone_parameters_name_their_zone_and_its_devices_only():
    params = gen.render_zone_params("zone-a", gen.group_by_zone(DEVICES, ZONES)["zone-a"])
    assert params["zone"] == "zone-a"
    assert [s["cidr"] for s in params["subnets"]] == ["172.30.10.11/32"]
    assert params["credentials"] == [{"username": "frr", "password": "frr", "platform": "frr"}]


def test_the_zone_compose_overlay_adds_one_worker_per_zone_on_its_network_alone():
    zones = {"zone-a": gen.zone_deployment(DEPLOYMENT, "zone-a", ZONES["zone-a"])}
    overlay = gen.render_zone_compose(zones, pathlib.Path("/repo/docker-compose.worker.yml"))

    assert "  worker-zone-a:\n" in overlay
    assert '      file: "/repo/docker-compose.worker.yml"\n      service: worker\n' in overlay
    assert "      NEOPS_WORKER_NETWORK_ZONES: zone-a\n" in overlay
    assert "      WORKER_NAME: simple-lab-worker-zone-a\n" in overlay
    # Without !override compose would merge the central worker's lab-net into the list.
    assert "    networks: !override\n      - default\n      - zone-a\n" in overlay
    assert "    name: lab-net-zone-a\n" in overlay
    assert "        - subnet: 172.30.10.0/24\n" in overlay


@pytest.mark.parametrize("scenario", ZONED)
def test_committed_zone_parameters_match_the_topology(scenario):
    topology = _topology(scenario)
    groups = gen.group_by_zone(topology["devices"], topology["zones"])
    for zone in topology["zones"]:
        committed = SCENARIOS_DIR / scenario / "workflow-execution-parameters" / "zones" / f"{zone}.json"
        assert json.loads(committed.read_text()) == gen.render_zone_params(zone, groups[zone])


@pytest.mark.parametrize("scenario", ZONED)
def test_zone_devices_sit_in_their_zones_subnet(scenario):
    topology = _topology(scenario)
    for host, device in topology["devices"].items():
        zone = device.get("zone")
        subnet = topology["zones"][zone]["subnet"] if zone else gen.TOPOLOGY_SUBNET
        assert ipaddress.ip_address(device["mgmt_ip"]) in ipaddress.ip_network(subnet), f"{host} is outside {subnet}"


@pytest.mark.parametrize("scenario", ZONED)
def test_zone_subnets_overlap_neither_each_other_nor_the_lab(scenario):
    """One Docker daemon refuses overlapping subnets; overlap stays with the engine's e2e playbook."""
    lab = [ipaddress.ip_network(gen.TOPOLOGY_SUBNET), ipaddress.ip_network("172.30.1.0/24")]
    seen = list(lab)
    for zone, spec in _topology(scenario)["zones"].items():
        subnet = ipaddress.ip_network(spec["subnet"])
        assert not any(subnet.overlaps(other) for other in seen), f"{zone} {subnet} overlaps {seen}"
        seen.append(subnet)


@pytest.mark.parametrize("scenario", ZONED)
def test_no_link_crosses_a_zone(scenario):
    """Each zone is its own containerlab topology, so a crossing link would render as a dummy."""
    devices = _topology(scenario)["devices"]
    for host, device in devices.items():
        for iface in device["interfaces"]:
            peer = iface["to"].partition(":")[0]
            if peer in devices:
                assert devices[peer].get("zone") == device.get("zone"), f"{host} -> {peer} crosses a zone"


@pytest.mark.parametrize("scenario", ZONED)
def test_zoned_scenarios_run_on_containerlab_only(scenario):
    """The Kubernetes flavour renders every FRR device into one namespace and knows no zones."""
    manifest = json.loads((SCENARIOS_DIR / scenario / "scenario.json").read_text())
    assert manifest["flavours"] == ["clab"]


@pytest.mark.parametrize("scenario", ZONED)
def test_zone_names_follow_the_cms_rule(scenario):
    for zone in _topology(scenario)["zones"]:
        assert re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", zone), zone


# --- readiness per zone ------------------------------------------------------


def _worker(state="online", zones=None, blocks=(FB_ID,)):
    worker = {"state": state, "functionBlockIds": list(blocks)}
    if zones is not None:
        worker["networkZones"] = zones
    return worker


def test_a_zone_is_ready_once_an_online_worker_serving_it_holds_the_block():
    workers = [_worker(zones=["zone-a"]), _worker(state="offline", zones=["zone-b"])]
    assert wait_ready.zones_ready(workers, FB_ID, ["zone-a", "zone-b"]) == {"zone-a"}


def test_a_worker_that_registered_no_zones_serves_default():
    assert wait_ready.zones_ready([_worker(zones=[])], FB_ID, ["default", "zone-a"]) == {"default"}
    assert wait_ready.zones_ready([_worker()], FB_ID, ["default"]) == {"default"}


def test_a_zone_worker_without_the_block_does_not_count():
    assert wait_ready.zones_ready([_worker(zones=["zone-a"], blocks=())], FB_ID, ["zone-a"]) == set()


def test_zone_readiness_reads_every_worker_with_its_blocks(monkeypatch):
    seen = []

    def urlopen(req, *_args, **_kwargs):
        seen.append(req.full_url)
        return __import__("io").BytesIO(json.dumps([_worker(zones=["zone-a"])]).encode())

    monkeypatch.setattr(wait_ready.request, "urlopen", urlopen)
    assert wait_ready.workers_with_blocks("http://engine") == [_worker(zones=["zone-a"])]
    assert seen == ["http://engine/workers?populateFunctionBlocks=true"]


# --- what the lab itself does with zones --------------------------------------


def test_the_central_worker_serves_default_in_its_own_service_definition():
    """Once a zone exists an unzoned worker is refused; the setting must not live
    in an .env a remote site copies, so a remote worker missing its own still stops."""
    assert "      NEOPS_WORKER_NETWORK_ZONES: default\n" in WORKER_COMPOSE
    for name in (".env.example",):
        text = (LAB_DIR / name).read_text()
        assert not re.search(r"^\s*#?\s*NEOPS_WORKER_NETWORK_ZONES\s*=", text, re.MULTILINE), name


def test_apply_cms_config_seeds_zones_from_the_resolved_topology():
    assert '"${SCENARIO_DIR}/topology.json"' in APPLY_SCRIPT
    assert "NetworkZone.objects.get_or_create" in APPLY_SCRIPT


def test_zones_are_seeded_before_the_workers_start():
    """A zone worker is refused while its zone does not exist."""
    body = MAKEFILE[MAKEFILE.index("\nlocal-lab-up:") :]
    assert body.index("./apply_cms_config") < body.index("docker compose up -d;")


def test_lab_admin_is_granted_write_on_network_zones():
    config = json.loads((SCENARIOS_DIR / "_base" / "cms" / "permissions.json").read_text())
    assert config["element_grants"]["lab-admin"] == {"network-zones": "write"}
    assert "RolePermissionElement" in APPLY_SCRIPT


def _make_var(name):
    match = re.search(rf"^{name} := (\S+)$", MAKEFILE, re.MULTILINE)
    assert match, f"the Makefile declares no {name}"
    return match.group(1)


def _top_level_field(text, key):
    match = re.search(rf"^{key}: (\S+)$", text, re.MULTILINE)
    assert match, f"the workflow declares no {key}"
    return match.group(1)


def _workflow_identity(path):
    text = path.read_text()
    version = ".".join(_top_level_field(text, key) for key in ("majorVersion", "minorVersion", "patchVersion"))
    return f"{_top_level_field(text, 'package')}/{_top_level_field(text, 'name')}:{version}"


def test_the_discovery_pins_agree():
    """Published workflows are immutable, so the file's version and the Makefile move together."""
    base = SCENARIOS_DIR / "_base" / "workflows" / "simple-lab-discovery.workflow.yaml"
    assert _make_var("DISCOVER_WORKFLOW") == _workflow_identity(base)
    assert f'functionBlock: "{_make_var("DISCOVER_FB")}"' in base.read_text()
    zone = SCENARIOS_DIR / "network-zones" / "workflows" / "zone-discovery.workflow.yaml"
    assert _make_var("ZONE_DISCOVER_WORKFLOW") == _workflow_identity(zone)
    assert f'functionBlock: "{_make_var("DISCOVER_FB")}"' in zone.read_text()


def test_the_zone_discovery_step_runs_in_the_zone_it_is_given():
    zone = (SCENARIOS_DIR / "network-zones" / "workflows" / "zone-discovery.workflow.yaml").read_text()
    assert '    networkZone: "{{ parameters.zone }}"\n' in zone
