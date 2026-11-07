"""The discovery workflow every scenario inherits, and the Makefile pins that name it.

Published workflows are immutable, so the file's version and `DISCOVER_WORKFLOW`
move together, and the block the step names is the one `wait_ready` waits for.
"""

import pathlib
import re

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
MAKEFILE = (LAB_DIR / "Makefile").read_text()
DISCOVERY = LAB_DIR / "scenarios" / "_base" / "workflows" / "simple-lab-discovery.workflow.yaml"


def _make_var(name):
    match = re.search(rf"^{name} := (\S+)$", MAKEFILE, re.MULTILINE)
    assert match, f"the Makefile declares no {name}"
    return match.group(1)


def _top_level_field(text, key):
    match = re.search(rf"^{key}: (\S+)$", text, re.MULTILINE)
    assert match, f"the workflow declares no {key}"
    return match.group(1)


def workflow_identity(path):
    text = path.read_text()
    version = ".".join(_top_level_field(text, key) for key in ("majorVersion", "minorVersion", "patchVersion"))
    return f"{_top_level_field(text, 'package')}/{_top_level_field(text, 'name')}:{version}"


def test_the_discovery_pins_agree():
    assert _make_var("DISCOVER_WORKFLOW") == workflow_identity(DISCOVERY)
    assert f'functionBlock: "{_make_var("DISCOVER_FB")}"' in DISCOVERY.read_text()


def test_the_discovery_step_runs_in_the_zone_it_is_given_else_default():
    """One workflow for every scenario: a run without `zone` discovers in default."""
    text = DISCOVERY.read_text()
    assert "    networkZone: \"{{ parameters.zone || 'default' }}\"\n" in text
    required = re.search(r"^  required: \[(.*)\]$", text, re.MULTILINE)
    assert required is None or "zone" not in required.group(1)
