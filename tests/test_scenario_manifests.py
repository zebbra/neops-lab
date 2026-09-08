"""Every scenario declares itself the same way, so `make scenarios` can list it."""

import json
import pathlib

import pytest

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
SCENARIOS_DIR = LAB_DIR / "scenarios"
SCENARIOS = sorted(p.name for p in SCENARIOS_DIR.iterdir() if p.is_dir() and p.name != "_base")

REQUIRED_KEYS = {"name", "title", "summary", "flavours", "demonstrates"}
FLAVOURS = {"clab"}


def _manifest(scenario):
    return json.loads((SCENARIOS_DIR / scenario / "scenario.json").read_text())


def _devices(scenario):
    return json.loads((SCENARIOS_DIR / scenario / "topology.json").read_text())["devices"]


def test_at_least_one_scenario_exists():
    assert SCENARIOS


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_manifest_is_complete(scenario):
    manifest = _manifest(scenario)
    assert set(manifest) >= REQUIRED_KEYS, f"missing {REQUIRED_KEYS - set(manifest)}"
    assert manifest["name"] == scenario, "the manifest name must match its directory"
    assert set(manifest["flavours"]) <= FLAVOURS
    assert manifest["flavours"], "a scenario that runs on neither flavour cannot be deployed"
    assert manifest["summary"].strip()
    assert manifest["demonstrates"], "say what the scenario is for"


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_scenario_carries_a_topology_and_a_readme(scenario):
    assert (SCENARIOS_DIR / scenario / "topology.json").is_file()
    assert (SCENARIOS_DIR / scenario / "README.md").is_file()


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_device_to_device_links_are_symmetric(scenario):
    """If a:swp1 points at b, then b must point back at a:swp1.

    This is what breaks when a scenario is derived by deleting devices: the
    survivors keep an interface aimed at something that is gone, and
    `gen_clab_topology` silently renders it as a dummy link rather than a veth.
    """
    devices = _devices(scenario)
    for host, dev in devices.items():
        for iface in dev["interfaces"]:
            peer_host = iface["to"].partition(":")[0]
            if peer_host not in devices:
                continue  # a stub: "server web-01", "isp-upstream", "cust-a-ce:ge0/0"
            back = {i["to"] for i in devices[peer_host]["interfaces"]}
            expected = f"{host}:{_short(iface['name'])}"
            assert expected in back, f"{host}:{iface['name']} -> {iface['to']} is not mirrored (peer has {back})"


def _short(name):
    """`ethernet-1/3` is written `e1/3` on the far side of a link."""
    return "e" + name[len("ethernet-") :] if name.startswith("ethernet-") else name


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_management_addresses_are_unique(scenario):
    addresses = [dev["mgmt_ip"] for dev in _devices(scenario).values() if dev.get("mgmt_ip")]
    assert len(addresses) == len(set(addresses))
