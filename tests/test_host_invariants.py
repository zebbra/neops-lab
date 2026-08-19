"""Repo-level invariants that no other gate would catch.

These guard the load-bearing constants that live in more than one place, and the
one portability rule for the host scripts. See docs/60-development/20-invariants.md.
"""

import ast
import pathlib
import re

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
HOST_SCRIPTS = ("gen_clab_topology", "gen_device_configs", "run_workflow", "wait_ready", "wait_devices")


def _generator_constant(name: str) -> str:
    """Read a module-level string constant from gen_clab_topology without importing it."""
    tree = ast.parse((LAB_DIR / "gen_clab_topology").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            assert isinstance(node.value, ast.Constant)
            return str(node.value.value)
    raise AssertionError(f"{name} not found in gen_clab_topology")


def test_makefile_lab_subnet_matches_generator():
    """The Makefile pre-creates `lab-net`; containerlab's mgmt block must use the same subnet."""
    makefile = (LAB_DIR / "Makefile").read_text()
    match = re.search(r"^LAB_SUBNET\s*:=\s*(\S+)", makefile, flags=re.M)
    assert match, "LAB_SUBNET not defined in the Makefile"
    assert match.group(1) == _generator_constant("LAB_SUBNET")
    match = re.search(r"^LAB_NET\s*:=\s*(\S+)", makefile, flags=re.M)
    assert match, "LAB_NET not defined in the Makefile"
    assert match.group(1) == _generator_constant("LAB_NET_NAME")


def test_worker_compose_declares_lab_net_external():
    """compose only attaches to lab-net; creating it (with the subnet) is the Makefile's job."""
    compose = (LAB_DIR / "docker-compose.worker.yml").read_text()
    assert re.search(r"^\s+lab-net:\n(?:\s+.*\n)*?\s+external:\s*true", compose, flags=re.M)
    assert "subnet:" not in compose, "the subnet belongs to the Makefile (LAB_SUBNET), not to compose"


def test_host_scripts_are_python39_safe():
    """Every host script must start with `from __future__ import annotations`.

    Stock macOS ships /usr/bin/python3 3.9, where a PEP 604 `X | None`
    annotation is evaluated at import time and raises. The future import
    defers that. `make py39-check` proves it at runtime; this test keeps the
    rule visible in the fast suite.
    """
    for name in HOST_SCRIPTS:
        tree = ast.parse((LAB_DIR / name).read_text(), filename=name)
        body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
        first = body[0]
        msg = f"{name}: first statement after the docstring must be `from __future__ import annotations`"
        assert isinstance(first, ast.ImportFrom), msg
        assert first.module == "__future__", msg
        assert any(alias.name == "annotations" for alias in first.names), msg
