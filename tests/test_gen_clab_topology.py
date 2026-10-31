"""Unit tests for the containerlab topology generator.

`gen_clab_topology` is an executable script (no `.py` extension) living at the repo
root, so we load it through `labscripts` (same pattern as
`test_gen_device_configs.py`).
"""

import json
import pathlib

import pytest

import labscripts

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
gen = labscripts.load("gen_clab_topology")

# The byte-for-byte guard runs against every scenario, so adding one extends it
# automatically. These helpers read the scenario *source* tree, never
# `generated/`, which keeps the suite hermetic and independent of a resolve.
SCENARIOS = sorted(p.name for p in (LAB_DIR / "scenarios").iterdir() if p.is_dir() and p.name != "_base")


def _topology(scenario):
    return json.loads((LAB_DIR / "scenarios" / scenario / "topology.json").read_text())


def _default_devices(scenario):
    """The devices the default parameter files cover: those in no network zone."""
    topology = _topology(scenario)
    return gen.group_by_zone(topology["devices"], topology.get("zones", {}))[gen.DEFAULT_ZONE]


DEPLOYMENT = gen.Deployment(name="neops-lab", network="lab-net", subnet=gen.TOPOLOGY_SUBNET)


def _committed(scenario, filename):
    return json.loads((LAB_DIR / "scenarios" / scenario / "workflow-execution-parameters" / filename).read_text())


def test_clab_iface_srl_mapping():
    assert gen.clab_iface("srl", "ethernet-1/3") == "e1-3"
    assert gen.clab_iface("frr", "swp2") == "swp2"


def test_veth_link_deduped():
    devices = {
        "a": {
            "mgmt_ip": "172.30.0.11",
            "vendor": "frr",
            "loopback": "lo",
            "interfaces": [{"name": "swp1", "to": "b:swp1"}],
        },
        "b": {
            "mgmt_ip": "172.30.0.12",
            "vendor": "frr",
            "loopback": "lo",
            "interfaces": [{"name": "swp1", "to": "a:swp1"}],
        },
    }
    veth, dummy = gen.build_links(devices)
    assert dummy == []
    assert len(veth) == 1
    assert set(veth[0]["endpoints"]) == {"a:swp1", "b:swp1"}


def test_stub_becomes_dummy():
    devices = {
        "leaf-01": {
            "mgmt_ip": "172.30.0.33",
            "vendor": "srl",
            "loopback": None,
            "interfaces": [{"name": "ethernet-1/3", "to": "server web-01"}],
        },
        "pe-rtr-01": {
            "mgmt_ip": "172.30.0.15",
            "vendor": "frr",
            "loopback": "lo",
            "interfaces": [{"name": "swp2", "to": "cust-a-ce:ge0/0"}],
        },
    }
    veth, dummy = gen.build_links(devices)
    assert veth == []
    assert len(dummy) == 2
    by_node = {d["endpoint"]["node"]: d for d in dummy}
    assert by_node["leaf-01"]["type"] == "dummy"
    assert by_node["leaf-01"]["endpoint"]["interface"] == "e1-3"
    assert by_node["pe-rtr-01"]["endpoint"]["interface"] == "swp2"


def test_srl_srl_link_uses_e1_dash():
    devices = {
        "spine-01": {
            "mgmt_ip": "172.30.0.31",
            "vendor": "srl",
            "loopback": None,
            "interfaces": [{"name": "ethernet-1/1", "to": "leaf-01:e1/1"}],
        },
        "leaf-01": {
            "mgmt_ip": "172.30.0.33",
            "vendor": "srl",
            "loopback": None,
            "interfaces": [{"name": "ethernet-1/1", "to": "spine-01:e1/1"}],
        },
    }
    veth, dummy = gen.build_links(devices)
    assert dummy == []
    assert len(veth) == 1
    assert set(veth[0]["endpoints"]) == {"spine-01:e1-1", "leaf-01:e1-1"}


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_discover_params_matches_committed(scenario):
    devices = _default_devices(scenario)
    result = gen.render_discover_params(devices)
    assert result == _committed(scenario, "discover-params.json")
    assert len(result["subnets"]) == len(devices)


def test_discover_params_supply_credentials_once_per_vendor():
    """A host is a /32 subnet; credentials are a list on the document, not
    repeated per subnet. With platforms declared, each credential is scoped so
    discovery never tries a login against the other vendor's devices.

    Pinned to the two-vendor scenario rather than parametrised: a single-vendor
    scenario legitimately carries one credential."""
    result = gen.render_discover_params(_topology("wan-and-fabric")["devices"])

    assert result["credentials"] == [
        {"username": "frr", "password": "frr", "platform": "frr"},
        {"username": "admin", "password": "NokiaSrl1!", "platform": "srl"},
    ]
    assert all(set(s) == {"cidr", "platform"} for s in result["subnets"]), (
        "subnets carry no credentials of their own; the credentials list covers them"
    )
    assert all(s["cidr"].endswith("/32") for s in result["subnets"])


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_autodetect_params_match_committed_and_omit_platform(scenario):
    """The autodetect targeting variant: address + shared credentials only, so
    discovery has to detect the platform itself. ("Scenario" means a lab under
    scenarios/ — these four files are targeting variants within one.)"""
    devices = _default_devices(scenario)
    result = gen.render_autodetect_params(devices)

    assert result == _committed(scenario, "discover-params-autodetect.json")
    assert len(result["subnets"]) == len(devices)
    assert all(set(s) == {"cidr"} for s in result["subnets"]), "no platform, no per-subnet login"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_both_parameter_files_target_the_same_hosts(scenario):
    """They differ only in what is declared, never in which devices are probed."""
    devices = _default_devices(scenario)
    declared = gen.render_discover_params(devices)
    autodetect = gen.render_autodetect_params(devices)

    assert [s["cidr"] for s in declared["subnets"]] == [s["cidr"] for s in autodetect["subnets"]]
    # Same logins; only the declared file scopes them (autodetect knows no platforms).
    assert [(c["username"], c["password"]) for c in declared["credentials"]] == [
        (c["username"], c["password"]) for c in autodetect["credentials"]
    ]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_subnet_params_match_committed(scenario):
    assert gen.render_subnet_params(_default_devices(scenario)) == _committed(scenario, "discover-params-subnet.json")


def test_frr_nodes_mount_the_scenario_config_at_lab():
    """frr.conf and daemons are no longer baked into the image, so every FRR
    node binds them from the resolved scenario tree. The paths are relative to
    the topology file's own directory (generated/<scenario>/clab), not the repo
    root — containerlab resolves them from there before handing absolute host
    paths to the daemon."""
    devices = {"r1": {"mgmt_ip": "172.30.0.11", "vendor": "frr", "loopback": "lo", "interfaces": []}}
    node = gen.render_clab(devices, DEPLOYMENT)["topology"]["nodes"]["r1"]

    assert "../scenario/devices/frr/frr.conf:/lab/frr.conf:ro" in node["binds"]
    assert "../scenario/devices/frr/daemons:/lab/daemons:ro" in node["binds"]
    assert "../scenario/devices/frr/set-aliases.sh:/lab/set-aliases.sh:ro" in node["binds"]
    assert node["exec"] == ["sh /lab/set-aliases.sh"]
    assert "frr/r1.iface:/etc/frr/lab-interfaces/r1.iface:ro" in node["binds"]


def test_relocate_keeps_each_host_offset():
    devices = {"r1": {"mgmt_ip": "172.30.0.11", "vendor": "frr"}, "s1": {"mgmt_ip": "172.30.0.31", "vendor": "srl"}}
    moved = gen.relocate(devices, "10.131.0.0/24")
    assert {host: dev["mgmt_ip"] for host, dev in moved.items()} == {"r1": "10.131.0.11", "s1": "10.131.0.31"}
    assert devices["r1"]["mgmt_ip"] == "172.30.0.11", "the topology itself is left as it was"


def test_relocate_refuses_a_subnet_too_small_for_the_topology():
    with pytest.raises(ValueError, match="smaller than"):
        gen.relocate({"r1": {"mgmt_ip": "172.30.0.11", "vendor": "frr"}}, "10.131.0.0/28")


def test_a_relocated_lab_carries_its_own_name_network_and_subnet():
    """Two labs on one host differ in lab name, network and node container names."""
    deployment = gen.Deployment(name="lab-b", network="lab-b-net", subnet="10.131.0.0/24")
    devices = gen.relocate(
        {"r1": {"mgmt_ip": "172.30.0.11", "vendor": "frr", "loopback": "lo", "interfaces": []}}, deployment.subnet
    )
    clab = gen.render_clab(devices, deployment)
    assert clab["name"] == "lab-b"
    assert clab["prefix"] == "__lab-name"
    assert clab["mgmt"] == {"network": "lab-b-net", "ipv4-subnet": "10.131.0.0/24"}
    assert clab["topology"]["nodes"]["r1"]["mgmt-ipv4"] == "10.131.0.11"
    assert gen.render_subnet_params(devices, deployment.subnet)["subnets"][0]["cidr"] == "10.131.0.0/24"


def test_the_generator_refuses_an_unset_deployment(monkeypatch):
    for key in ("LAB_NAME", "LAB_NET", "LAB_SUBNET"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SystemExit):
        gen.deployment_from_env()
