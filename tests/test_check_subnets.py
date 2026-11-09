"""Unit tests for `tools/check_subnets.py`, the docker-network check `make doctor` runs.

A scenario with network zones adds one fixed network per zone, so those
subnets are the lab's too.
"""

import labscripts

check = labscripts.load("tools/check_subnets.py")


def _network(name, subnet):
    return {"Name": name, "IPAM": {"Config": [{"Subnet": subnet}]}}


def test_a_scenario_without_zones_needs_only_the_lab_networks():
    assert check.lab_networks("wan-and-fabric") == check.EXPECTED


def test_each_zone_adds_its_network_and_subnet():
    networks = check.lab_networks("network-zones")
    assert networks["lab-net-zone-a"] == "172.30.10.0/24"
    assert networks["lab-net-zone-b"] == "172.30.20.0/24"


def test_a_network_on_a_zone_subnet_is_a_conflict():
    expected = check.lab_networks("network-zones")
    found = check.conflicts([_network("other_default", "172.30.10.0/24")], expected)
    assert found == ["other_default (172.30.10.0/24)"]


def test_the_lab_networks_on_their_own_subnets_are_no_conflict():
    expected = check.lab_networks("network-zones")
    networks = [_network(name, subnet) for name, subnet in expected.items()]
    assert check.conflicts(networks, expected) == []


def test_a_network_beside_every_lab_subnet_is_no_conflict():
    assert check.conflicts([_network("elsewhere", "172.30.30.0/24")], check.lab_networks("network-zones")) == []
