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
MAKEFILE = (LAB_DIR / "Makefile").read_text()
PORT_VAR = r"\$\{(LAB_[A-Z]+_PORT):\?[^}]*\}"

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


def _host_ports(block):
    """The port variables a service publishes on, e.g. `LAB_WEB_PORT`."""
    return [var for line in block for var in re.findall(rf'- "{PORT_VAR}:\d+"', line)]


def _published_ports():
    return set(re.findall(rf'^\s*- "{PORT_VAR}:\d+"', COMPOSE, re.MULTILINE))


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
        match = re.fullmatch(rf"http://localhost:{PORT_VAR}", origin)
        assert match, f"{origin} names no published port variable"
        assert match.group(1) in published, f"{origin} names {match.group(1)}, which no service publishes"


def test_monitor_config_is_mounted_where_the_app_reads_it():
    """`static/config.js` is the assets path src/app.html loads at boot."""
    monitor = _service("workflow-engine-client")
    target = "./generated/monitor/config.js:/app/rest/monitor-app/static/config.js:ro"
    assert any(line.strip() == f"- {target}" for line in monitor), f"no mount of {target}"


def test_monitor_relays_from_the_origin_the_web_client_publishes():
    """webclientOrigin is the trust anchor of the token relay, so it has to be
    the origin the browser actually loaded the web client from."""
    match = re.search(r"webclientOrigin: 'http://localhost:\$\((LAB_[A-Z]+_PORT)\)'", MAKEFILE)
    assert match, "make monitor-config sets no webclientOrigin"
    assert match.group(1) in _host_ports(_service("web_client")), f"web_client publishes no {match.group(1)}"


def test_monitor_calls_the_engine_this_lab_publishes():
    """Left to its compile-time default the monitor calls :3030, which on a
    host running a second lab is the other lab's engine."""
    assert "apiBaseUrl: '$(LAB_ENGINE_URL)'" in MAKEFILE
    assert "LAB_ENGINE_URL := http://localhost:$(LAB_ENGINE_PORT)" in MAKEFILE
    assert "LAB_ENGINE_PORT" in _host_ports(_service("workflow_engine"))


def test_monitor_service_installs_its_dev_dependencies():
    """`npm run dev` resolves vite and @sveltejs/kit from rest/monitor-app's
    devDependencies, which `npm install` omits under NODE_ENV=production."""
    assert _env(_service("workflow-engine-client"), "NODE_ENV") == "development"
