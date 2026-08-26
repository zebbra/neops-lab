"""Authorization wiring in the compose file.

The engine verifies tokens against a key the lab mounts, runs in a named
authorization mode and answers only enumerated browser origins. Each of the
three is a value on one service that has to agree with something else in the
same file, which is what these assertions pin.
"""

import pathlib
import re

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = (LAB_DIR / "docker-compose.yml").read_text()

# src/config.ts rejects anything else at load, naming the accepted values.
AUTHZ_MODES = ("enforce", "permissive", "disabled")


def _service(name):
    """Return the lines of one compose service, its `<name>:` header excluded."""
    lines = COMPOSE.splitlines()
    start = lines.index(f"  {name}:")
    block = []
    for line in lines[start + 1 :]:
        if line.strip() and not line.startswith("    "):
            break
        block.append(line)
    assert block, f"service {name} is empty"
    return block


def _env(block, key):
    """Return an environment value, from either the list or the mapping form."""
    for line in block:
        match = re.match(rf"\s*-?\s*{re.escape(key)}\s*[:=]\s*(.*)", line)
        if match:
            return match.group(1).strip().strip('"')
    raise AssertionError(f"{key} is not set on this service")


def _published_ports():
    return {int(port) for port in re.findall(r'^\s*- "(\d+):\d+"', COMPOSE, re.MULTILINE)}


def test_engine_mounts_the_key_it_verifies_against():
    """NEOPS_JWT_PUBLIC_KEY_PATH names a path the engine service mounts."""
    engine = _service("workflow_engine")
    key_path = _env(engine, "NEOPS_JWT_PUBLIC_KEY_PATH")
    mounts = [line for line in engine if line.strip().endswith(f":{key_path}:ro")]
    assert mounts, f"no read-only mount targets {key_path}"


def test_engine_authz_mode_is_one_the_engine_accepts():
    assert _env(_service("workflow_engine"), "NEOPS_AUTHZ_MODE") in AUTHZ_MODES


def test_cors_origins_name_published_ports():
    """Each allowed origin points at a port this compose file publishes.

    The browser reaches the engine from the web client and the monitor app, so
    an origin naming a port no service publishes can never be an origin the
    engine is called from.
    """
    published = _published_ports()
    origins = _env(_service("workflow_engine"), "NEOPS_CORS_ORIGINS").split(",")
    assert origins
    for origin in origins:
        port = int(origin.rsplit(":", 1)[1])
        assert port in published, f"{origin} names port {port}, which no service publishes"
