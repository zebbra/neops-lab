"""Fail when a docker network overlaps the lab's fixed subnets.

The lab needs 172.30.0.0/24 (lab-net, the device mgmt network) and
172.30.1.0/24 (the compose default network); both live in 172.30.0.0/23.
A scenario with network zones also needs each zone's subnet, on the network
`lab-net-<zone>`, read from the topology of $SCENARIO.
Exit 1 with the conflicting networks named, 0 otherwise.
"""

from __future__ import annotations

import ipaddress
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import labscripts  # noqa: E402  (needs ROOT on sys.path first)

gen = labscripts.load("gen_clab_topology")

LAB_NET = "lab-net"
LAB_RANGE = ipaddress.ip_network("172.30.0.0/23")
# The lab's own networks are allowed to hold exactly their subnet.
EXPECTED = {LAB_NET: "172.30.0.0/24", "neops-lab_default": "172.30.1.0/24"}


def lab_networks(scenario: str | None) -> dict[str, str]:
    """Every network the lab creates, with its subnet; a scenario's zones add one each."""
    zones = gen.gen_device_configs.load_zones(scenario) if scenario else {}
    return {**EXPECTED, **{gen.zone_network(LAB_NET, zone): spec["subnet"] for zone, spec in zones.items()}}


def conflicts(networks: list, expected: dict[str, str]) -> list[str]:
    """Name each docker network on a lab subnet that is not the lab's own network on its own subnet."""
    lab_ranges = [LAB_RANGE, *(ipaddress.ip_network(subnet) for subnet in expected.values())]
    found = []
    for net in networks:
        for cfg in (net.get("IPAM") or {}).get("Config") or []:
            try:
                subnet = ipaddress.ip_network(cfg.get("Subnet", ""))
            except ValueError:
                continue
            if subnet.version != 4 or not any(subnet.overlaps(lab) for lab in lab_ranges):
                continue
            if str(subnet) == expected.get(net["Name"]):
                continue
            found.append(f"{net['Name']} ({subnet})")
    return found


def main() -> int:
    expected = lab_networks(os.environ.get("SCENARIO"))
    ids = subprocess.run(["docker", "network", "ls", "-q"], capture_output=True, text=True, check=True).stdout.split()
    raw = subprocess.run(["docker", "network", "inspect", *ids], capture_output=True, text=True, check=True).stdout
    found = conflicts(json.loads(raw), expected)
    subnets = ", ".join(sorted(set(expected.values())))
    if found:
        print(f"docker networks overlapping the lab's subnets ({subnets}): " + ", ".join(found))
        print("fix: docker network rm <name> for unused leftovers (their project's next 'up' recreates them)")
        return 1
    print(f"no docker network overlaps the lab's subnets ({subnets})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
