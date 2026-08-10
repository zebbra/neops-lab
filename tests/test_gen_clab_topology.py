"""Unit tests for the containerlab topology generator.

`gen_clab_topology` is an executable script (no `.py` extension) living at the repo
root, so we load it by path via `importlib.util` (same pattern as
`test_gen_device_configs.py`).
"""

import importlib.machinery
import importlib.util
import json
import pathlib

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = LAB_DIR / "gen_clab_topology"

_loader = importlib.machinery.SourceFileLoader("gen_clab_topology", str(SCRIPT_PATH))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
assert _spec is not None
gen = importlib.util.module_from_spec(_spec)
_loader.exec_module(gen)


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


def test_discover_params_matches_committed():
    topology = json.loads((LAB_DIR / "topology.json").read_text())
    committed = json.loads((LAB_DIR / "workflow-execution-parameters" / "discover-params.json").read_text())
    result = gen.render_discover_params(topology["devices"])
    assert result == committed
    assert len(result["subnets"]) == 15


def test_discover_params_supply_credentials_once_per_vendor():
    """A host is a /32 subnet; credentials are a list on the document, not
    repeated per subnet. With platforms declared, each credential is scoped so
    discovery never tries a login against the other vendor's devices."""
    topology = json.loads((LAB_DIR / "topology.json").read_text())
    result = gen.render_discover_params(topology["devices"])

    assert result["credentials"] == [
        {"username": "frr", "password": "frr", "platform": "frr"},
        {"username": "admin", "password": "NokiaSrl1!", "platform": "srl"},
    ]
    assert all(set(s) == {"cidr", "platform"} for s in result["subnets"]), (
        "subnets carry no credentials of their own; the credentials list covers them"
    )
    assert all(s["cidr"].endswith("/32") for s in result["subnets"])


def test_autodetect_params_match_committed_and_omit_platform():
    """The second scenario: address + shared credentials only, so discovery has
    to detect the platform itself."""
    topology = json.loads((LAB_DIR / "topology.json").read_text())
    committed = json.loads((LAB_DIR / "workflow-execution-parameters" / "discover-params-autodetect.json").read_text())
    result = gen.render_autodetect_params(topology["devices"])

    assert result == committed
    assert len(result["subnets"]) == 15
    assert all(set(s) == {"cidr"} for s in result["subnets"]), "no platform, no per-subnet login"
    assert result["credentials"] == [
        {"username": "frr", "password": "frr"},
        {"username": "admin", "password": "NokiaSrl1!"},
    ]


def test_both_parameter_files_target_the_same_hosts():
    """They differ only in what is declared, never in which devices are probed."""
    topology = json.loads((LAB_DIR / "topology.json").read_text())
    declared = gen.render_discover_params(topology["devices"])
    autodetect = gen.render_autodetect_params(topology["devices"])

    assert [s["cidr"] for s in declared["subnets"]] == [s["cidr"] for s in autodetect["subnets"]]
    # Same logins; only the declared file scopes them (autodetect knows no platforms).
    assert [(c["username"], c["password"]) for c in declared["credentials"]] == [
        (c["username"], c["password"]) for c in autodetect["credentials"]
    ]


def test_subnet_params_match_committed():
    topology = json.loads((LAB_DIR / "topology.json").read_text())
    committed = json.loads((LAB_DIR / "workflow-execution-parameters" / "discover-params-subnet.json").read_text())

    assert gen.render_subnet_params(topology["devices"]) == committed
