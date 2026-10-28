"""Which documents `bootstrap/register.py` publishes, and in what order.

The script runs in the `neops-lab-bootstrap` image, whose `requests` and `yaml`
are absent from this repo's dev environment — so they are stubbed here and the
module is loaded by path. Nothing in it touches either at import time.
"""

import pathlib
import sys
import types

import pytest

import labscripts

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]


class _AnyAttribute(types.ModuleType):
    """A stand-in module every attribute access succeeds on.

    `register.py` annotates `requests.Response` at def time, so an empty
    `ModuleType` is not enough to import it.
    """

    def __getattr__(self, name):
        return object


def _load_register():
    """Import `bootstrap/register.py` with its image-only dependencies stubbed."""
    stubbed = {name: _AnyAttribute(name) for name in ("requests", "yaml") if name not in sys.modules}
    sys.modules.update(stubbed)
    try:
        return labscripts.load("bootstrap/register.py")
    finally:
        for name in stubbed:
            del sys.modules[name]


register = _load_register()


@pytest.fixture
def workflows(tmp_path):
    """A workflows directory holding one document of every shape the lab has."""
    for name in (
        "simple-lab-discovery.workflow.yaml",
        "original_spie_deploy_vlans.workflow.json",
        "legacy.yml",
        "README.md",
    ):
        (tmp_path / name).write_text("{}\n")
    (tmp_path / "nested").mkdir()
    return tmp_path


def test_json_documents_are_published_alongside_yaml(workflows):
    """A workflow authored as JSON is a workflow. `yaml.safe_load` reads both,
    and the engine is handed the same parsed document either way."""
    found = [path.name for path in register.workflow_files(workflows)]
    assert "original_spie_deploy_vlans.workflow.json" in found
    assert "simple-lab-discovery.workflow.yaml" in found
    assert "legacy.yml" in found


def test_nothing_but_a_workflow_document_is_published(workflows):
    """A scenario's `workflows/` may carry a README; publishing it would 4xx."""
    found = [path.name for path in register.workflow_files(workflows)]
    assert "README.md" not in found
    assert "nested" not in found


def test_the_order_is_stable(workflows):
    """The engine reports per-document failures, so a run has to be comparable
    with the one before it."""
    assert register.workflow_files(workflows) == sorted(register.workflow_files(workflows))


def test_the_base_scenario_ships_a_json_workflow():
    """The file this behaviour exists for. Without it the assertions above pass
    against a shape the repo no longer has."""
    base = LAB_DIR / "scenarios" / "_base" / "workflows"
    assert [path.name for path in register.workflow_files(base) if path.suffix == ".json"]


def test_one_unpublishable_document_does_not_hide_the_rest(workflows, monkeypatch):
    """`all()` short-circuits, which would keep every later document off the
    engine — including the discovery workflow `local-lab-up` waits for."""
    seen = []

    def register_one(path):
        seen.append(path.name)
        return path.suffix != ".json"

    monkeypatch.setattr(register, "WORKFLOWS_DIR", workflows)
    # `make test` exports the Makefile's DISCOVER_WORKFLOW; ordering is tested below.
    monkeypatch.setattr(register, "DISCOVER_WORKFLOW", "")
    monkeypatch.setattr(register, "register_one", register_one)
    monkeypatch.setattr(register, "wait_for_engine", lambda: None)

    assert register.main() == 1, "a refused document must fail the bootstrap container"
    assert len(seen) == 3, f"registration stopped after {seen}"


DISCOVERY = "wf.lab.neops.io/simple_lab_discovery:1.3.0"


@pytest.fixture
def documents(workflows, monkeypatch):
    """Stand in for `yaml.safe_load`: each file parses to a document named after it,
    and the discovery file to the id the Makefile's DISCOVER_WORKFLOW names."""

    def load_document(path):
        if path.name == "simple-lab-discovery.workflow.yaml":
            return {
                "package": "wf.lab.neops.io",
                "name": "simple_lab_discovery",
                "majorVersion": 1,
                "minorVersion": 3,
                "patchVersion": 0,
            }
        return {
            "package": "wf.lab.neops.io",
            "name": path.stem,
            "majorVersion": 1,
            "minorVersion": 0,
            "patchVersion": 0,
        }

    monkeypatch.setattr(register, "load_document", load_document)
    return register.workflow_files(workflows)


def test_discovery_is_published_before_the_rest(documents):
    """The engine caps how many definitions it holds. When a scenario's
    workflows exceed the cap, the one refused must not be discovery, which
    `local-lab-up` waits on and `local-lab-discover` runs."""
    ordered = register.publish_order(documents, DISCOVERY)
    assert ordered[0].name == "simple-lab-discovery.workflow.yaml"
    assert sorted(ordered) == documents, "reordering must neither drop nor duplicate a document"


def test_the_rest_keep_their_file_order(documents):
    ordered = register.publish_order(documents, DISCOVERY)
    rest = [p for p in documents if p.name != "simple-lab-discovery.workflow.yaml"]
    assert ordered[1:] == rest


@pytest.mark.parametrize("first", ["", "wf.lab.neops.io/simple_lab_discovery:9.9.9"])
def test_an_unset_or_unmatched_discovery_id_keeps_file_order(documents, first):
    """Unset outside make; unmatched when the Makefile and the YAML disagree on
    a version. Neither may stop the documents from being published."""
    assert register.publish_order(documents, first) == documents


def test_the_makefile_names_the_discovery_workflow_the_base_scenario_ships():
    """The id is matched exactly, version included, so the two must move together."""
    makefile = (LAB_DIR / "Makefile").read_text()
    assert f"DISCOVER_WORKFLOW := {DISCOVERY}\n" in makefile
    text = (LAB_DIR / "scenarios" / "_base" / "workflows" / "simple-lab-discovery.workflow.yaml").read_text()
    for line in (
        "package: wf.lab.neops.io",
        "name: simple_lab_discovery",
        "majorVersion: 1",
        "minorVersion: 3",
        "patchVersion: 0",
    ):
        assert f"\n{line}\n" in text, line
