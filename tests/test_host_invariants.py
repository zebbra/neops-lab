"""Repo-level invariants no other gate covers."""

import ast
import pathlib
import re

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
