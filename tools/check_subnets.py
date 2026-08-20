"""Fail when a docker network overlaps the lab's fixed subnets.

The lab needs 172.30.0.0/24 (lab-net, the device mgmt network) and
172.30.1.0/24 (the compose default network); both live in 172.30.0.0/23.
Exit 1 with the conflicting networks named, 0 otherwise.
"""

import ipaddress
import json
import subprocess
import sys

LAB_RANGE = ipaddress.ip_network("172.30.0.0/23")
# The lab's own networks are allowed to hold exactly their subnet.
EXPECTED = {"lab-net": "172.30.0.0/24", "neops-lab_default": "172.30.1.0/24"}


def main() -> int:
    ids = subprocess.run(["docker", "network", "ls", "-q"], capture_output=True, text=True, check=True).stdout.split()
    raw = subprocess.run(["docker", "network", "inspect", *ids], capture_output=True, text=True, check=True).stdout
    conflicts = []
    for net in json.loads(raw):
        for cfg in (net.get("IPAM") or {}).get("Config") or []:
            try:
                subnet = ipaddress.ip_network(cfg.get("Subnet", ""))
            except ValueError:
                continue
            if subnet.version != 4 or not subnet.overlaps(LAB_RANGE):
                continue
            if str(subnet) == EXPECTED.get(net["Name"]):
                continue
            conflicts.append(f"{net['Name']} ({subnet})")
    if conflicts:
        print("docker networks overlapping " + str(LAB_RANGE) + ": " + ", ".join(conflicts))
        print("fix: docker network rm <name> for unused leftovers (their project's next 'up' recreates them)")
        return 1
    print(f"no docker network overlaps {LAB_RANGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
