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
