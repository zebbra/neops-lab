"""Register every workflow document in /workflows with the engine. Idempotent."""

import os
import pathlib
import sys
import time

import requests
import yaml

ENGINE_URL = os.environ.get("ENGINE_URL", "http://workflow_engine:3030")
WORKFLOWS_DIR = pathlib.Path(os.environ.get("WORKFLOWS_DIR", "/workflows"))
MAX_WAIT_SECONDS = int(os.environ.get("ENGINE_WAIT_SECONDS", "60"))

# The engine takes one parsed workflow document, however it was authored. JSON
# is a subset of YAML, so `yaml.safe_load` reads either and the engine is handed
# the same structure — a scenario exported from the web client lands as `.json`
# and is as publishable as a hand-written `.yaml`.
WORKFLOW_SUFFIXES = (".yaml", ".yml", ".json")

# Publishing a definition needs `workflow:write`. Empty while NEOPS_ENGINE_TOKEN
# is unset, which an engine in `disabled` mode still answers; `/health` is
# `@Public` and is polled without a header either way.
ENGINE_TOKEN = os.environ.get("NEOPS_ENGINE_TOKEN", "").strip()
AUTH_HEADERS = {"Authorization": "Bearer " + ENGINE_TOKEN} if ENGINE_TOKEN else {}

# What the engine answers a caller whose token is absent, expired, or short of
# `workflow:write`.
UNAUTHORIZED = (401, 403)

AUTH_HINT = "mint a token with ./lab_token and export NEOPS_ENGINE_TOKEN before `docker compose up -d`"

# The discovery workflow, as `package/name:major.minor.patch` — the Makefile's
# DISCOVER_WORKFLOW. It is published before every other document: the engine's
# license caps how many definitions it holds, and when a scenario's workflows
# exceed that cap it must be an extra workflow that is refused, never the one
# `local-lab-up` and `local-lab-discover` cannot do without. Unset, the order is
# the plain sorted one.
DISCOVER_WORKFLOW = os.environ.get("DISCOVER_WORKFLOW", "").strip()


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


def _failure_detail(resp: requests.Response) -> str:
    """What to print beside a refused status code.

    The engine's refusal body says why it refused; a 403 names the permission
    the route wanted.
    """
    if resp.status_code in UNAUTHORIZED:
        return f"{resp.text[:300]} — {AUTH_HINT}"
    return resp.text[:300]


def _status_of(resp: requests.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return ""
    return str(body.get("status") or "")


def register_legacy(wf: dict) -> bool:
    """Fallback for engines predating POST /workflow-definition/publish."""
    resp = requests.post(f"{ENGINE_URL}/workflow-definition", json={"workflow": wf}, headers=AUTH_HEADERS, timeout=15)
    if resp.status_code in (200, 201):
        print(f"   registered via legacy route ({resp.status_code})", flush=True)
        return True
    if resp.status_code == 409 or "already exists" in resp.text.lower():
        print(f"   already registered ({resp.status_code}), skipping", flush=True)
        return True
    print(f"   FAILED {resp.status_code}: {_failure_detail(resp)}", flush=True)
    return False


def load_document(path: pathlib.Path) -> dict:
    with path.open() as fh:
        return yaml.safe_load(fh)


def workflow_id(wf: dict) -> str:
    """The `package/name:major.minor.patch` the engine and `run_workflow` address a definition by."""
    version = f"{wf.get('majorVersion')}.{wf.get('minorVersion')}.{wf.get('patchVersion')}"
    return f"{wf.get('package')}/{wf.get('name')}:{version}"


def register_one(path: pathlib.Path) -> bool:
    print(f"-> {path.name}", flush=True)
    wf = load_document(path)

    resp = requests.post(
        f"{ENGINE_URL}/workflow-definition/publish",
        json={"workflow": wf},
        headers=AUTH_HEADERS,
        timeout=15,
    )

    if resp.status_code == 404:
        print("   engine has no /publish route, falling back to the legacy one", flush=True)
        return register_legacy(wf)

    if resp.status_code == 201:
        print(f"   published ({resp.status_code} {_status_of(resp)})", flush=True)
        return True

    if resp.status_code == 200:
        print(f"   already published, unchanged ({resp.status_code})", flush=True)
        return True

    if resp.status_code == 409:
        print(
            f"   FAILED {resp.status_code}: this version already exists with different content.\n"
            f"   Published versions are immutable — bump majorVersion/minorVersion/patchVersion\n"
            f"   in {path.name} (and every reference to it) instead of editing in place.\n"
            f"   {resp.text[:300]}",
            flush=True,
        )
        return False

    if resp.status_code == 422:
        print(
            f"   FAILED {resp.status_code}: the declared version does not describe the change honestly;\n"
            f"   the engine computed a higher floor. Raise the version in {path.name}.\n"
            f"   {resp.text[:300]}",
            flush=True,
        )
        return False

    print(f"   FAILED {resp.status_code}: {_failure_detail(resp)}", flush=True)
    return False


def workflow_files(directory: pathlib.Path) -> list[pathlib.Path]:
    """Every workflow document in `directory`, in a stable order.

    A scenario's `workflows/` may hold a README beside them, which the engine
    would refuse, so the suffix decides rather than the directory listing.
    """
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix in WORKFLOW_SUFFIXES)


def publish_order(paths: list[pathlib.Path], first: str) -> list[pathlib.Path]:
    """`paths` with the document whose id is `first` moved to the front.

    A `first` no document carries is reported, not fatal: it means the
    Makefile's DISCOVER_WORKFLOW and the discovery YAML disagree on a version,
    which `local-lab-discover` would otherwise only reveal as a 404.
    """
    if not first:
        return paths
    for path in paths:
        if workflow_id(load_document(path)) == first:
            return [path, *(p for p in paths if p != path)]
    print(f"warning: no workflow document is {first}; publishing in file order", flush=True)
    return paths


def main() -> int:
    wait_for_engine()
    workflows = publish_order(workflow_files(WORKFLOWS_DIR), DISCOVER_WORKFLOW)
    if not workflows:
        print(f"no workflow files found in {WORKFLOWS_DIR}", flush=True)
        return 0
    # Deliberately not `all(...)`: it short-circuits, so one unpublishable
    # document would keep every later one off the engine — including the
    # discovery workflow `local-lab-up` waits for. Register them all, then fail.
    published = [register_one(path) for path in workflows]
    return 0 if all(published) else 1


if __name__ == "__main__":
    sys.exit(main())
