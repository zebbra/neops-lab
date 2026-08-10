"""Register every workflow YAML in /workflows with the engine. Idempotent."""

import os
import pathlib
import sys
import time

import requests
import yaml

ENGINE_URL = os.environ.get("ENGINE_URL", "http://workflow_engine:3030")
WORKFLOWS_DIR = pathlib.Path(os.environ.get("WORKFLOWS_DIR", "/workflows"))
MAX_WAIT_SECONDS = int(os.environ.get("ENGINE_WAIT_SECONDS", "60"))


def wait_for_engine() -> None:
    deadline = time.monotonic() + MAX_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            r = requests.get(f"{ENGINE_URL}/health", timeout=2)
            if r.status_code == 200:
                print(f"engine reachable at {ENGINE_URL}", flush=True)
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    print(f"engine did not become reachable within {MAX_WAIT_SECONDS}s; trying anyway", flush=True)


def register_one(path: pathlib.Path) -> bool:
    print(f"-> {path.name}", flush=True)
    with path.open() as fh:
        wf = yaml.safe_load(fh)
    resp = requests.post(
        f"{ENGINE_URL}/workflow-definition",
        json={"workflow": wf},
        timeout=15,
    )
    if resp.status_code in (200, 201):
        print(f"   registered ({resp.status_code})", flush=True)
        return True
    if resp.status_code == 409 or "already exists" in resp.text.lower():
        print(f"   already registered ({resp.status_code}), skipping", flush=True)
        return True
    print(f"   FAILED {resp.status_code}: {resp.text[:300]}", flush=True)
    return False


def main() -> int:
    wait_for_engine()
    yamls = sorted(WORKFLOWS_DIR.glob("*.yaml")) + sorted(WORKFLOWS_DIR.glob("*.yml"))
    if not yamls:
        print(f"no workflow files found in {WORKFLOWS_DIR}", flush=True)
        return 0
    ok = all(register_one(p) for p in yamls)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
