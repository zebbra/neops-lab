"""Unit tests for the device readiness poller.

`wait_devices` is an executable script (no `.py` extension) living at the repo
root, so we load it through `labscripts`.

Nothing here opens a socket: the tests cover which hosts get waited on, which is
where the scenario restructure broke it.
"""

import json

import pytest

import labscripts

gen = labscripts.load("wait_devices")
resolve_scenario = labscripts.load("resolve_scenario")

SCENARIOS = resolve_scenario.available()


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_hosts_come_from_the_scenario_topology(scenario):
    """Every device with a mgmt_ip is waited on, and only those."""
    topology = json.loads((resolve_scenario.SCENARIOS_DIR / scenario / "topology.json").read_text())
    expected = [d["mgmt_ip"] for d in topology["devices"].values() if d.get("mgmt_ip")]

    assert gen.hosts_from_topology(scenario) == expected
    assert expected, f"{scenario} has no reachable devices"


def test_scenario_defaults_to_the_environment(monkeypatch):
    """No argument means $SCENARIO, the same variable make exports."""
    monkeypatch.setenv("SCENARIO", SCENARIOS[0])
    assert gen.hosts_from_topology() == gen.hosts_from_topology(SCENARIOS[0])


def test_scenarios_do_not_share_a_host_list():
    """A regression guard: reading one fixed topology for every scenario is the bug."""
    if len(SCENARIOS) < 2:
        pytest.skip("needs two scenarios")
    lists = {s: gen.hosts_from_topology(s) for s in SCENARIOS}
    assert len({len(v) for v in lists.values()}) > 1, f"every scenario returned the same count: {lists}"


def test_params_take_only_single_addresses(tmp_path):
    """A wider prefix enumerates candidates, so waiting on it would always time out."""
    params = tmp_path / "p.json"
    params.write_text(json.dumps({"subnets": [{"cidr": "172.30.0.11/32"}, {"cidr": "172.30.0.0/24"}]}))
    assert gen.hosts_from_params(params) == ["172.30.0.11"]


@pytest.mark.parametrize(
    ("target", "expected"),
    [("172.30.0.11", ("172.30.0.11", 22)), ("172.30.0.11:830", ("172.30.0.11", 830))],
)
def test_parse_target(target, expected):
    assert gen.parse_target(target) == expected
