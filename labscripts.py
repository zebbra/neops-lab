"""Load the extension-less host scripts as modules (stdlib-only).

The host scripts have no `.py` suffix on purpose (see AGENTS.md): they are
commands, run as `./gen_clab_topology`. That is also why `import` cannot find
them and why `spec_from_file_location` returns `None` for them, so every caller
that wants to reuse one has to go through an explicit `SourceFileLoader`.

This module is the one place that knows how. It carries a `.py` suffix because
it is a module rather than a command, and it sits beside the scripts so a script
run directly finds it on `sys.path[0]`; the root `conftest.py` puts the same
directory on the path for the tests.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import pathlib
import types

ROOT = pathlib.Path(__file__).resolve().parent


def load(name: str) -> types.ModuleType:
    """Return the host script `name` imported as a module."""
    path = ROOT / name
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    if spec is None:  # never happens with an explicit loader; keeps the types honest
        raise SystemExit(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
