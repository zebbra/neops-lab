"""Put the repo root on `sys.path` so the tests can `import labscripts`.

A host script run as `./gen_clab_topology` gets its own directory on
`sys.path[0]` for free; a test module collected out of `tests/` does not.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def _parse_recipes(makefile_text):
    """Every Makefile target's commands, keyed by target name.

    Comment lines are dropped: a recipe comment that quotes a command would
    otherwise satisfy an assertion about the order commands run in. Lines naming
    several targets at once (`a b c: export ...`) declare variables rather than
    recipes and carry no body, so they are skipped. So are the assignment forms
    `NAME := v`, `NAME ::= v` and `NAME :::= v`, which are not rules at all — a
    caller asking "is every target declared .PHONY" must not be handed the
    Makefile's variables as targets.
    """
    bodies = {}
    target = None
    for line in makefile_text.splitlines():
        if line.startswith("\t"):
            if target is not None and not line.lstrip("\t").startswith("#"):
                bodies[target].append(line)
            continue
        target = None
        head, separator, rest = line.partition(":")
        name = head.strip()
        if rest.lstrip(":").startswith("="):
            continue
        if separator and name and " " not in name:
            target = name
            bodies.setdefault(target, [])
    return {name: "\n".join(lines) for name, lines in bodies.items()}


@pytest.fixture
def recipes():
    """The Makefile's recipes, parsed once per test that asks for them."""
    return _parse_recipes((pathlib.Path(__file__).resolve().parent / "Makefile").read_text())


@pytest.fixture(autouse=True)
def _no_inherited_make_state(monkeypatch):
    """`make test` must not change what the tests that shell out to `make` see.

    Under the outer make they inherit MAKELEVEL, so the child prints
    `make[1]: Entering directory …` into stdout a test then runs as a script,
    and MAKEFLAGS could hand it flags such as `-j`. Scrubbed here rather than
    per call site, so a test written later cannot reintroduce the coupling.
    """
    monkeypatch.delenv("MAKELEVEL", raising=False)
    monkeypatch.delenv("MAKEFLAGS", raising=False)
