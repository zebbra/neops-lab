"""Repo-level invariants no other gate covers."""

import ast
import pathlib
import re
import sys

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]


def _generator_constant(name):
    tree = ast.parse((LAB_DIR / "gen_clab_topology").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == name for x in node.targets):
            assert isinstance(node.value, ast.Constant)
            return str(node.value.value)
    raise AssertionError(f"{name} not found in gen_clab_topology")


def test_compose_subnets_match_generator():
    """Every project network carries a fixed subnet agreeing with the generator.

    docker auto-allocates subnet-less networks from its 172.16/12 pool, which
    can collide with lab-net's fixed /24 on a busy host; pinning every subnet
    removes the allocator from the picture.
    """
    lab_subnet = _generator_constant("LAB_SUBNET")
    worker = (LAB_DIR / "docker-compose.worker.yml").read_text()
    assert f"subnet: {lab_subnet}" in worker
    base = (LAB_DIR / "docker-compose.yml").read_text()
    assert "subnet: 172.30.1.0/24" in base


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
    import labscripts

    mod = labscripts.load("gen_compose_env")
    dotenv = tmp_path / ".env"
    dotenv.write_text("LAB_HOST=lab.example.com\nCOMPOSE_FILE=old.yml\n")
    monkeypatch.setattr(mod, "DOTENV", dotenv)
    files = "docker-compose.yml:docker-compose.traefik.yml:docker-compose.host-data.yml"
    monkeypatch.setattr(sys, "argv", ["gen_compose_env", files])
    assert mod.main() == 0
    text = dotenv.read_text()
    assert f"COMPOSE_FILE={files}" in text
    assert text.count("COMPOSE_FILE=") == 1
    assert "COMPOSE_PATH_SEPARATOR=:" in text
    assert "LAB_HOST=lab.example.com" in text


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
