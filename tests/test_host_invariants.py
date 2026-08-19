"""Repo-level invariants that no other gate would catch.

These guard the load-bearing constants that live in more than one place, and the
one portability rule for the host scripts. See docs/60-development/20-invariants.md.
"""

import ast
import pathlib

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
HOST_SCRIPTS = ("gen_clab_topology", "gen_device_configs", "run_workflow", "wait_ready", "wait_devices")


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
