"""Repo-level invariants no other gate covers."""

import ast
import pathlib
import re
import sys

import labscripts

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]


def _generator_constant(name):
    tree = ast.parse((LAB_DIR / "gen_clab_topology").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == name for x in node.targets):
            assert isinstance(node.value, ast.Constant)
            return str(node.value.value)
    raise AssertionError(f"{name} not found in gen_clab_topology")


def test_compose_subnets_come_from_the_makefile():
    """Every project network carries a fixed subnet, set by the Makefile.

    docker auto-allocates subnet-less networks from its 172.16/12 pool, which
    can collide with lab-net's fixed /24 on a busy host; pinning every subnet
    removes the allocator from the picture. The default device subnet is the
    one the topologies are written in, so a default lab moves no address.
    """
    worker = (LAB_DIR / "docker-compose.worker.yml").read_text()
    assert "subnet: ${LAB_SUBNET:?" in worker
    assert "name: ${LAB_NET:?" in worker
    base = (LAB_DIR / "docker-compose.yml").read_text()
    assert "subnet: ${LAB_COMPOSE_SUBNET:?" in base
    makefile = (LAB_DIR / "Makefile").read_text()
    assert f"LAB_SUBNET ?= {_generator_constant('TOPOLOGY_SUBNET')}" in makefile
    for name in ("LAB_NAME", "LAB_NET", "LAB_SUBNET", "LAB_COMPOSE_SUBNET"):
        assert re.search(rf"^export .*\b{name}\b", makefile, re.MULTILINE), f"the Makefile does not export {name}"


def test_compose_mounts_the_resolved_scenario_tree():
    """The three scenario assets containers consume are interpolated per
    scenario, so `SCENARIO=x docker compose up` mounts x's copies."""
    worker = (LAB_DIR / "docker-compose.worker.yml").read_text()
    base = (LAB_DIR / "docker-compose.yml").read_text()

    assert "/scenario/workflows:/workflows:ro" in worker
    assert "/scenario/function_blocks,neops/fb" in worker
    assert "/scenario/cms/oidc-config.json:/etc/neops/oidc-config.json:ro" in base

    # `:?` and not `:-`: compose must abort on an unset SCENARIO. Left to warn,
    # it interpolates a blank and docker creates the missing bind source as an
    # empty directory — a lab that comes up with no workflows registered.
    for text in (worker, base):
        assert text.count("${SCENARIO:?") == text.count("${SCENARIO"), "every SCENARIO reference must use :?"


def test_the_makefile_holds_the_only_scenario_default():
    """A second default is how a scenario gets half-applied — some assets from
    the new one, some from the old — which stays invisible until discovery
    produces a confusing result. Everything but the Makefile must fail on an
    unset SCENARIO rather than guess one."""
    makefile = (LAB_DIR / "Makefile").read_text()
    assert "SCENARIO ?= wan-and-fabric" in makefile
    assert "export SCENARIO" in makefile

    for name in ("docker-compose.yml", "docker-compose.worker.yml", "apply_cms_config", "resolve_scenario"):
        text = (LAB_DIR / name).read_text()
        assert "SCENARIO:-" not in text, f"{name} carries a fallback SCENARIO default"


def test_host_traefik_routes_djstatic():
    """CMS STATIC_URL is /djstatic/; Traefik must not send it to the web client."""
    for name in ("dynamic.http.yml", "dynamic.https.yml", "dynamic.https-acme.yml"):
        text = (LAB_DIR / "traefik" / name).read_text()
        assert "PathPrefix(`/djstatic`)" in text, name
        assert "http://cms:8000" in text, name


def test_host_direct_overlay_publishes_ports():
    """host-direct mode exposes laptop ports without Traefik."""
    text = (LAB_DIR / "docker-compose.host-direct.yml").read_text()
    assert re.search(r"(?m)^  cms-proxy:", text) is None
    assert "8080:8080" in text
    assert "8001:8000" in text
    assert "3030:3030" in text
    assert "3031:5173" in text
    makefile = (LAB_DIR / "Makefile").read_text()
    assert "host-direct-env-init" in makefile
    assert "docker-compose.host-direct.yml" in makefile


def test_gen_compose_env_upserts_dotenv(tmp_path, monkeypatch):
    """Bare docker compose reads COMPOSE_FILE from .env after host-env-init."""
    mod = labscripts.load("gen_compose_env")
    dotenv = tmp_path / ".env"
    dotenv.write_text("LAB_HOST=lab.example.com\nCOMPOSE_FILE=old.yml\n")
    monkeypatch.setattr(mod, "DOTENV", dotenv)
    files = "docker-compose.yml:docker-compose.traefik.yml:docker-compose.host-data.yml"
    for name in _required_compose_vars(files):
        monkeypatch.setenv(name, "x")
    monkeypatch.setattr(sys, "argv", ["gen_compose_env", files])
    assert mod.main() == 0
    text = dotenv.read_text()
    assert f"COMPOSE_FILE={files}" in text
    assert text.count("COMPOSE_FILE=") == 1
    assert "COMPOSE_PATH_SEPARATOR=:" in text
    assert "LAB_HOST=lab.example.com" in text


HOST_COMPOSE_FILE_SETS = (
    "docker-compose.yml:docker-compose.traefik.yml:docker-compose.traefik-https.yml:docker-compose.host-data.yml",
    "docker-compose.yml:docker-compose.worker.yml:docker-compose.traefik.yml:docker-compose.traefik-https.yml"
    ":docker-compose.host-data.yml",
    "docker-compose.yml:docker-compose.worker.yml:docker-compose.host-direct.yml:docker-compose.host-data.yml",
)


def _required_compose_vars(files: str) -> set[str]:
    names: set[str] = set()
    for name in files.split(":"):
        names.update(re.findall(r"\$\{([A-Z_][A-Z0-9_]*):\?", (LAB_DIR / name).read_text()))
    return names


def _dotenv_keys(text: str) -> set[str]:
    return {line.split("=", 1)[0].strip() for line in text.splitlines() if "=" in line and not line.startswith("#")}


def test_gen_compose_env_writes_every_required_compose_variable(tmp_path, monkeypatch):
    """Bare `docker compose` in host mode reads only .env, and the compose files
    refuse to interpolate without SCENARIO and the LAB_* values make resolved."""
    mod = labscripts.load("gen_compose_env")
    for files in HOST_COMPOSE_FILE_SETS:
        required = _required_compose_vars(files)
        assert "SCENARIO" in required
        dotenv = tmp_path / ".env"
        dotenv.write_text("LAB_HOST=lab.example.com\n")
        monkeypatch.setattr(mod, "DOTENV", dotenv)
        for name in required:
            monkeypatch.setenv(name, f"value-of-{name}")
        monkeypatch.setattr(sys, "argv", ["gen_compose_env", files])
        assert mod.main() == 0
        text = dotenv.read_text()
        assert required <= _dotenv_keys(text), f"{files}: missing {sorted(required - _dotenv_keys(text))}"
        assert "SCENARIO=value-of-SCENARIO" in text
        assert "LAB_HOST=lab.example.com" in text


def test_gen_compose_env_refuses_an_unresolved_required_variable(tmp_path, monkeypatch):
    """Without make's exports there is no value to persist; writing a blank
    would only move the failure to the bare `docker compose` call."""
    mod = labscripts.load("gen_compose_env")
    dotenv = tmp_path / ".env"
    dotenv.write_text("")
    monkeypatch.setattr(mod, "DOTENV", dotenv)
    files = HOST_COMPOSE_FILE_SETS[0]
    for name in _required_compose_vars(files):
        monkeypatch.setenv(name, "x")
    monkeypatch.delenv("SCENARIO")
    monkeypatch.setattr(sys, "argv", ["gen_compose_env", files])
    assert mod.main() == 2


def test_host_data_overlay_bind_mounts():
    """Host modes persist Postgres + CMS /tmp under ./data like neops-docker-compose."""
    text = (LAB_DIR / "docker-compose.host-data.yml").read_text()
    assert "${LAB_DATA_DIR:-./data}/postgres:/var/lib/postgresql/data" in text
    assert "${LAB_DATA_DIR:-./data}/cms_tmp:/tmp" in text
    assert re.search(r"(?m)^  elasticsearch:", text) is None
    assert re.search(r"(?m)^  redis:", text) is None
    makefile = (LAB_DIR / "Makefile").read_text()
    assert "docker-compose.host-data.yml" in makefile
    assert "host-data-dirs" in makefile
    gitignore = (LAB_DIR / ".gitignore").read_text()
    assert re.search(r"(?m)^data/$", gitignore)


def test_host_https_overlay_does_not_wipe_engine_env():
    """environment: !override on workflow_engine drops JWT/CMS URL → exit 1."""
    text = (LAB_DIR / "docker-compose.traefik-https.yml").read_text()
    assert "environment: !override" not in text
    assert "NEOPS_CORS_ORIGINS:" in text


def test_host_monitor_iframe_is_cross_origin():
    """postMessage auth rejects same-origin /monitor under Traefik."""
    http = (LAB_DIR / "docker-compose.traefik.yml").read_text()
    assert "FRONTEND_WORKFLOW_MANAGER_URL: http://${LAB_HOST}:3031/" in http
    assert "npm run dev -- --host 0.0.0.0 --port 5173 --base /monitor/" not in http
    https = (LAB_DIR / "docker-compose.traefik-https.yml").read_text()
    assert "FRONTEND_WORKFLOW_MANAGER_URL: https://${LAB_HOST}:8443/" in https
    assert "8443:8443" in https
    assert "--entrypoints.monitor.address=:8443" in https
    dyn = (LAB_DIR / "traefik" / "dynamic.https.yml").read_text()
    assert "monitor-iframe:" in dyn
    assert "monitor-strip" in dyn


def test_host_traefik_uses_api_base_path():
    """Dashboard JS calls /traefik/api — needs api.basePath, not StripPrefix alone."""
    for path in (
        "docker-compose.traefik.yml",
        "docker-compose.traefik-https.yml",
    ):
        text = (LAB_DIR / path).read_text()
        assert "--api.basePath=/traefik" in text, path
    for name in ("dynamic.http.yml", "dynamic.https.yml", "dynamic.https-acme.yml"):
        text = (LAB_DIR / "traefik" / name).read_text()
        assert "dashboard-strip" not in text, name
        assert "PathPrefix(`/traefik`)" in text, name


def test_local_lab_up_mints_the_jwt_keypair_first():
    """The engine service bind-mounts `cms/jwt/public.pem` as a file. Docker
    creates a directory under that name when the file is absent, which the
    engine cannot read as a key and which `make lab-jwt` cannot write over.
    """
    compose = (LAB_DIR / "docker-compose.yml").read_text()
    assert "./cms/jwt/public.pem:" in compose, "the engine service mounts no key file"
    makefile = (LAB_DIR / "Makefile").read_text()
    match = re.search(r"^local-lab-up:(.*)$", makefile, re.MULTILINE)
    assert match, "the Makefile declares no local-lab-up target"
    assert "lab-jwt" in match.group(1).split(), "local-lab-up starts the stack without lab-jwt"
