"""Repo-level invariants no other gate covers."""

import ast
import pathlib

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
