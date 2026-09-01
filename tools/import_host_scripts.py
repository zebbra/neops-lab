"""Import every extension-less host script; exit non-zero on failure.

Run under the oldest supported interpreter to prove the scripts import there,
e.g. the stock macOS /usr/bin/python3 (3.9):

    /usr/bin/python3 tools/import_host_scripts.py
"""

import importlib.machinery
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ("gen_clab_topology", "gen_device_configs", "lab_token", "run_workflow", "wait_ready", "wait_devices")


def main() -> int:
    for name in SCRIPTS:
        loader = importlib.machinery.SourceFileLoader(name, str(ROOT / name))
        spec = importlib.util.spec_from_loader(name, loader)
        if spec is None:  # spec_from_loader with an explicit loader always returns a spec
            raise SystemExit(f"could not load {name}")
        loader.exec_module(importlib.util.module_from_spec(spec))
    print("host scripts import under", sys.version.split()[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
