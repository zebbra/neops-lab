"""Register every workflow YAML in /workflows with the engine. Idempotent.

Engine contract
---------------
Since neops-workflow-engine 0.42.2-beta.3 (develop 2026-07-30, commit 068753a0)
the only write route for definitions is ``POST /workflow-definition/publish``
with the body ``{"workflow": <document>}``. Its semantics differ from the legacy
``POST /workflow-definition`` it replaced, and getting them right matters:

* 201 — the definition was written.
* 200 — nothing to do: this exact document is already published at the version
  it declares (``status: "unchanged"``). **This** is the idempotent case.
* 409 — this version already exists *with different content* (published
  versions are immutable). That means someone edited the YAML without bumping
  its version; skipping it silently would make the lab run the OLD definition.
  Hard failure, printing the engine's ``suggestedVersion``.
* 422 — the version bump is smaller than the change warrants (``BelowFloor``);
  the engine's ``hint`` names the fix. Hard failure.

Older engines (< 0.42.2-beta.3) answer 404 for the publish route; we then fall
back to the legacy ``POST /workflow-definition`` with the identical body, where
409 / "already exists" *is* the idempotent case.
"""

import json
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


def _body(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _describe(wf: dict) -> str:
    return f"{wf.get('package')}/{wf.get('name')}:{wf.get('majorVersion')}.{wf.get('minorVersion')}.{wf.get('patchVersion')}"


def publish(wf: dict) -> bool | None:
    """Publish via the current API. Returns True/False, or None if the route does not exist (legacy engine)."""
    resp = requests.post(f"{ENGINE_URL}/workflow-definition/publish", json={"workflow": wf}, timeout=15)
    body = _body(resp)
    if resp.status_code == 201:
        print("   published (201)", flush=True)
        return True
    if resp.status_code == 200:
        print(f"   unchanged — already published as {_describe(wf)} (200), skipping", flush=True)
        return True
    if resp.status_code == 404:
        return None
    if resp.status_code == 409:
        print(f"   FAILED 409: {_describe(wf)} already exists with DIFFERENT content.", flush=True)
        print("   Published versions are immutable — bump the version in the YAML.", flush=True)
        if body.get("suggestedVersion"):
            print(f"   engine suggests: {json.dumps(body['suggestedVersion'])}", flush=True)
        if body.get("findings"):
            print(f"   findings: {json.dumps(body['findings'])[:600]}", flush=True)
        return False
    if resp.status_code == 422:
        print(f"   FAILED 422: version bump too small for the change ({body.get('code', 'BelowFloor')}).", flush=True)
        if body.get("hint"):
            print(f"   hint: {body['hint']}", flush=True)
        if body.get("suggestedVersion"):
            print(f"   engine suggests: {json.dumps(body['suggestedVersion'])}", flush=True)
        return False
    print(f"   FAILED {resp.status_code}: {resp.text[:300]}", flush=True)
    return False


def register_legacy(wf: dict) -> bool:
    """Legacy engines (< 0.42.2-beta.3): POST /workflow-definition, where 409 means already registered."""
    resp = requests.post(f"{ENGINE_URL}/workflow-definition", json={"workflow": wf}, timeout=15)
    if resp.status_code in (200, 201):
        print(f"   registered via legacy route ({resp.status_code})", flush=True)
        return True
    if resp.status_code == 409 or "already exists" in resp.text.lower():
        print(f"   already registered ({resp.status_code}), skipping", flush=True)
        return True
    print(f"   FAILED {resp.status_code}: {resp.text[:300]}", flush=True)
    return False


def register_one(path: pathlib.Path) -> bool:
    print(f"-> {path.name}", flush=True)
    with path.open() as fh:
        wf = yaml.safe_load(fh)
    result = publish(wf)
    if result is None:
        print(
            "   engine has no /workflow-definition/publish (older than 0.42.2-beta.3); using legacy route", flush=True
        )
        return register_legacy(wf)
    return result


def main() -> int:
    wait_for_engine()
    yamls = sorted(WORKFLOWS_DIR.glob("*.yaml")) + sorted(WORKFLOWS_DIR.glob("*.yml"))
    if not yamls:
        print(f"no workflow files found in {WORKFLOWS_DIR}", flush=True)
        return 0
    # Register every file even if an earlier one fails (no short-circuit).
    results = [register_one(p) for p in yamls]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
