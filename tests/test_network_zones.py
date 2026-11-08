"""The lab's network zones: a topology's `zones`, and what each zone is deployed as.

A zone is a management network of its own, a containerlab topology of its own
and a worker attached only to that network, so discovery shows routing on real
devices. Devices without a zone sit in `default` on `lab-net`, as in every
other scenario.
"""

import io
import ipaddress
import json
import os
import pathlib
import re
import subprocess

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


def _worker(state="online", zones=None):
    """A worker as the per-block workers route lists it."""
    worker = {"state": state}
    if zones is not None:
        worker["networkZones"] = zones
    return worker


def _engine(monkeypatch, workers, engine_license=None):
    """Answer the per-block workers route with `workers` and /license with `engine_license`; return the URLs read."""
    seen = []

    def urlopen(req, *_args, **_kwargs):
        seen.append(req.full_url)
        body = engine_license if req.full_url.endswith("/license") else workers
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(wait_ready.request, "urlopen", urlopen)
    return seen


def test_a_zone_is_ready_once_an_online_worker_serves_it():
    workers = [_worker(zones=["zone-a"]), _worker(state="offline", zones=["zone-b"])]
    assert wait_ready.zones_ready(workers, ["zone-a", "zone-b"]) == {"zone-a"}


def test_default_is_served_only_by_a_worker_the_engine_names_in_it():
    """Engines from 0.46 echo `default` for a worker that registered no zones, so
    an empty or missing list serves nothing."""
    assert wait_ready.zones_ready([_worker(zones=["default"])], ["default"]) == {"default"}
    assert wait_ready.zones_ready([_worker(zones=[])], ["default"]) == set()
    assert wait_ready.zones_ready([_worker()], ["default"]) == set()


def test_zone_readiness_reads_the_workers_of_the_block(monkeypatch):
    """The per-block route carries each worker's zones, so no other list is read."""
    seen = _engine(monkeypatch, [_worker(zones=["zone-a"])])
    assert wait_ready.ready_now("http://engine", [(FB_ID, "zone-a"), (FB_ID, "zone-b")]) == {
        (FB_ID, "zone-a"): "zone zone-a"
    }
    assert seen == ["http://engine/function-blocks/fb.base.neops.io/global_discover_network/0.2.0/workers"]


def test_the_license_is_read_and_nothing_else_decided(monkeypatch):
    _engine(monkeypatch, [], engine_license=PREVIEW_LICENSE)
    assert wait_ready.engine_license("http://engine") == PREVIEW_LICENSE


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


@pytest.fixture
def zoned_lab(tmp_path, monkeypatch):
    """A `demo` scenario with zone-a, its sources and its generated tree under tmp_path."""
    resolver = gen.gen_device_configs.resolve_scenario
    demo = tmp_path / "scenarios" / "demo"
    demo.mkdir(parents=True)
    (demo / "scenario.json").write_text("{}")
    (demo / "topology.json").write_text(json.dumps({"zones": ZONES, "devices": DEVICES}))
    monkeypatch.setattr(resolver, "SCENARIOS_DIR", tmp_path / "scenarios")
    monkeypatch.setattr(resolver, "GENERATED_DIR", tmp_path / "generated")
    stale = gen.clab_file("demo", "zone-gone")
    stale.parent.mkdir(parents=True)
    stale.write_text("{}")
    return stale


def _zone_labs(keep_topologies):
    zones = {"zone-a": gen.zone_deployment(DEPLOYMENT, "zone-a", ZONES["zone-a"])}
    gen._write_zone_labs("demo", gen.group_by_zone(DEVICES, ZONES), zones, keep_topologies=keep_topologies)


def test_a_removed_zones_topology_is_pruned_while_nothing_is_deployed(zoned_lab):
    _zone_labs(keep_topologies=False)
    assert not zoned_lab.exists()
    assert gen.clab_file("demo", "zone-a").exists()


def test_a_removed_zones_topology_stays_while_its_scenario_is_deployed(zoned_lab):
    """local-lab-down destroys what the topologies name, so a deployed zone keeps its file until then."""
    _zone_labs(keep_topologies=True)
    assert zoned_lab.exists()


def test_generate_keeps_the_topologies_of_the_deployed_scenario():
    body = MAKEFILE[MAKEFILE.index("\ngenerate:") :]
    body = body[: body.index("\n\n")]
    assert "--keep-topologies" in body
    assert "$(CLAB_DEPLOYED_MARKER)" in body


STUB = """#!/bin/sh
echo "$(basename "$0") $*" >> "$STUB_LOG"
"""


@pytest.fixture
def lab_copy(tmp_path):
    """The repo seen through symlinks, with a `generated/` of its own, so a recipe runs without touching it."""
    lab = tmp_path / "lab"
    lab.mkdir()
    for entry in LAB_DIR.iterdir():
        if entry.name not in ("generated", ".git"):
            (lab / entry.name).symlink_to(entry)
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name in ("docker", "containerlab"):
        (stubs / name).write_text(STUB)
        (stubs / name).chmod(0o755)
    return lab, stubs, tmp_path / "calls.log"


def _deployed_topology(lab, name, network):
    path = lab / "generated" / "network-zones" / "clab" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"name": name, "mgmt": {"network": network}}))
    return path


def test_local_lab_down_removes_a_removed_zones_worker_network_and_topology(lab_copy):
    """containerlab keeps a network a worker is still on, and compose down only removes the networks
    its current zones.yml declares, so the zone that left the topology goes by name."""
    lab, stubs, log = lab_copy
    kept = _deployed_topology(lab, "neops-lab.clab.json", "lab-net")
    removed = _deployed_topology(lab, "neops-lab-zone-gone.clab.json", "lab-net-zone-gone")
    (lab / "generated" / ".deployed-scenario-clab").write_text("network-zones\n")

    subprocess.run(
        ["make", "-s", "local-lab-down", f"CONTAINERLAB={stubs / 'containerlab'}"],
        cwd=lab,
        env={**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}", "STUB_LOG": str(log)},
        capture_output=True,
        check=True,
    )

    calls = log.read_text().splitlines()
    assert f"containerlab destroy -t generated/network-zones/clab/{removed.name} --cleanup" in calls
    assert "docker compose down --remove-orphans" in calls
    assert "docker network rm lab-net-zone-gone" in calls
    assert calls.index("docker compose down --remove-orphans") < calls.index("docker network rm lab-net-zone-gone")
    assert not kept.exists()
    assert not removed.exists()
    assert not (lab / "generated" / ".deployed-scenario-clab").exists()


@pytest.mark.parametrize(
    ("target", "flavour"),
    [("local-lab-up", "clab"), ("kind-lab-up", "kind"), ("kind-lab-discover", "kind"), ("kind-lab-cms-config", "kind")],
)
def test_a_lab_target_refuses_a_scenario_without_its_flavour(target, flavour):
    body = MAKEFILE[MAKEFILE.index(f"\n{target}:") :]
    recipe = body[body.index("\n\t") :]
    assert recipe.startswith(f"\n\t@./resolve_scenario --scenario $(SCENARIO) --require-flavour {flavour}\n")


def test_the_deployed_scenario_is_recorded_before_anything_starts():
    """A local-lab-up that fails half way has to be torn down with the zones it started."""
    body = MAKEFILE[MAKEFILE.index("\nlocal-lab-up:") :]
    assert body.index("> $(CLAB_DEPLOYED_MARKER)") < body.index("docker compose up -d --wait cms;")


def test_the_admin_role_writes_network_zones_through_core():
    """core's bootstrap_admin_role grants it, as compose and Helm do; called unconditionally."""
    assert re.search(r'^call_command\("bootstrap_admin_role", user=', APPLY_SCRIPT, re.MULTILINE), "not at top level"
    assert "element_grants" not in APPLY_SCRIPT
    permissions = json.loads((SCENARIOS_DIR / "_base" / "cms" / "permissions.json").read_text())
    assert "element_grants" not in permissions


# --- the zone facts the lab targets read --------------------------------------


def _query(*flags, scenario="network-zones"):
    return subprocess.run(
        [str(LAB_DIR / "gen_clab_topology"), "--scenario", scenario, *flags],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _make_value(name, scenario="network-zones"):
    """What a variable of the Makefile expands to for a scenario."""
    probe = f"print-value: ; @printf '%s\\n' '$({name})'"
    result = subprocess.run(
        ["make", "-s", "--no-print-directory", "--eval", probe, "print-value", f"SCENARIO={scenario}"],
        cwd=LAB_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_the_generator_names_each_zones_worker():
    assert _query("--zone-workers") == "zone-a:worker-zone-a zone-b:worker-zone-b"
    assert _query("--zone-workers", scenario="wan-and-fabric") == ""


def test_the_generator_names_the_zones_the_lab_waits_for():
    """Once zones exist, default needs an online worker of its own too."""
    assert _query("--ready-zones") == "default zone-a zone-b"
    assert _query("--ready-zones", scenario="wan-and-fabric") == ""


def test_the_generator_names_the_topologies_the_lab_deploys():
    clab = "generated/network-zones/clab"
    assert _query("--topologies") == (
        f"{clab}/neops-lab.clab.json {clab}/neops-lab-zone-a.clab.json {clab}/neops-lab-zone-b.clab.json"
    )
    assert _query("--topologies", scenario="frr-only") == "generated/frr-only/clab/neops-lab.clab.json"


def test_local_lab_up_deploys_the_declared_topologies_only():
    """A zone removed while deployed keeps its file for local-lab-down; up must not bring it back."""
    body = MAKEFILE[MAKEFILE.index("\nlocal-lab-up:") :]
    body = body[: body.index("\n\n")]
    assert "for topo in $(CLAB_TOPOLOGIES); do $(CONTAINERLAB) deploy" in body
    assert "*.clab.json" not in body


def test_the_lab_targets_take_the_zones_from_the_generator():
    assert _make_value("ZONE_NAMES") == "zone-a zone-b"
    assert _make_value("LAB_WORKERS") == "worker worker-zone-a worker-zone-b"
    assert _make_value("ZONE_READY_ARGS") == "--zone default --zone zone-a --zone zone-b"
    assert _make_value("LAB_WORKERS", scenario="wan-and-fabric") == "worker"
    assert _make_value("ZONE_READY_ARGS", scenario="wan-and-fabric") == ""


def test_each_zone_is_discovered_with_the_one_discovery_workflow():
    body = MAKEFILE[MAKEFILE.index("\nlocal-lab-discover:") :]
    body = body[: body.index("\n\n")]
    assert "$(DISCOVER_WORKFLOW) @$(ZONE_PARAMS_DIR)/$(zone).json" in body
    assert "ZONE_DISCOVER_WORKFLOW" not in MAKEFILE


def _top_level_field(text, key):
    match = re.search(rf"^{key}: (\S+)$", text, re.MULTILINE)
    assert match, f"the workflow declares no {key}"
    return match.group(1)


def _workflow_identity(path):
    text = path.read_text()
    version = ".".join(_top_level_field(text, key) for key in ("majorVersion", "minorVersion", "patchVersion"))
    return f"{_top_level_field(text, 'package')}/{_top_level_field(text, 'name')}:{version}"


# --- the engine a scenario with zones needs -----------------------------------

COMPOSE = (LAB_DIR / "docker-compose.yml").read_text()
PREVIEW_LICENSE = {"flavor": "developer-preview", "displayName": "Developer Preview", "limits": {"maxWorkers": 2}}


def _manifest(scenario):
    return json.loads((SCENARIOS_DIR / scenario / "scenario.json").read_text())


def _exported_engine_repository(scenario):
    """What the Makefile exports to docker compose as NEOPS_ENGINE_REPOSITORY for a scenario."""
    probe = "print-engine-repository: ; @printf '%s\\n' \"$$NEOPS_ENGINE_REPOSITORY\""
    result = subprocess.run(
        ["make", "-s", "--no-print-directory", "--eval", probe, "print-engine-repository", f"SCENARIO={scenario}"],
        cwd=LAB_DIR,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_the_network_zones_scenario_asks_for_the_licensed_engine():
    """It runs a worker per zone beside the central one, more than the developer preview admits."""
    assert _manifest("network-zones")["engine"] == "enterprise"


def test_the_compose_file_takes_the_engine_repository_from_the_makefile():
    assert "quay.io/zebbra/${NEOPS_ENGINE_REPOSITORY:-neops-workflow-engine-preview}:" in COMPOSE


def test_a_scenario_asking_for_the_licensed_engine_gets_its_repository():
    assert _exported_engine_repository("network-zones") == "neops-workflow-engine"


def test_any_other_scenario_keeps_the_developer_preview():
    assert _exported_engine_repository("wan-and-fabric") == ""


def test_an_engine_that_admits_fewer_workers_than_the_lab_starts_is_refused():
    refusal = wait_ready.worker_cap_refusal(PREVIEW_LICENSE, 3)
    assert refusal is not None
    for named in (
        "3 workers",
        "Developer Preview license admits 2",
        "NEOPS_WORKFLOW_ENGINE_IMAGE",
        "docker login quay.io",
    ):
        assert named in refusal


@pytest.mark.parametrize("cap", [3, "unlimited"])
def test_an_engine_that_admits_every_worker_passes(cap):
    assert wait_ready.worker_cap_refusal({**PREVIEW_LICENSE, "limits": {"maxWorkers": cap}}, 3) is None


def test_wait_ready_stops_at_once_on_an_engine_short_of_workers(monkeypatch):
    """Instead of timing out on the worker the engine refused."""

    def urlopen(req, *_args, **_kwargs):
        body = PREVIEW_LICENSE if req.full_url.endswith("/license") else []
        return io.BytesIO(json.dumps(body).encode())

    argv = ["wait_ready", "--workers", "3", "--zone", "default", "--timeout", "600", FB_ID]
    monkeypatch.setattr(wait_ready.request, "urlopen", urlopen)
    monkeypatch.setattr(wait_ready.sys, "argv", argv)
    monkeypatch.setattr(wait_ready.time, "sleep", lambda _s: pytest.fail("polled instead of stopping"))
    with pytest.raises(SystemExit, match="admits 2"):
        wait_ready.main()


def test_the_lab_tells_wait_ready_how_many_workers_it_starts():
    for target in ("\nlocal-lab-up:", "\nlocal-lab-discover:"):
        body = MAKEFILE[MAKEFILE.index(target) :]
        assert "./wait_ready $(LAB_ENGINE_ARG) --workers $(words $(LAB_WORKERS))" in body[: body.index("\n\n")]


def test_the_move_example_moves_one_device_with_the_zone_it_is_given():
    move = (SCENARIOS_DIR / "network-zones" / "workflows" / "move-device.workflow.yaml").read_text()
    assert _workflow_identity(SCENARIOS_DIR / "network-zones" / "workflows" / "move-device.workflow.yaml") == (
        "wf.lab.neops.io/move_device_to_zone:1.0.0"
    )
    assert _top_level_field(move, "seedEntity") == "device"
    assert '    functionBlock: "fb.base.neops.io/device_update_device:0.2.0"\n' in move
    assert '      network_zone: "{{ parameters.zone }}"\n' in move
