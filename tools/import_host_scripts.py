"""Import every extension-less host script; exit non-zero on failure.

Run under the oldest supported interpreter to prove the scripts import there,
e.g. the stock macOS /usr/bin/python3 (3.9):

    /usr/bin/python3 tools/import_host_scripts.py
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import labscripts  # noqa: E402  (needs ROOT on sys.path first)

SCRIPTS = (
    "gen_clab_topology",
    "gen_device_configs",
    "gen_kind_discover_params",
    "gen_kind_manifests",
    "lab_token",
    "resolve_scenario",
    "run_workflow",
    "wait_ready",
    "wait_devices",
)


def main() -> int:
    for name in SCRIPTS:
        labscripts.load(name)
    print("host scripts import under", sys.version.split()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
