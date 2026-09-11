"""Unit tests for the scenario overlay resolver.

`resolve_scenario` is an executable script (no `.py` extension) living at the
repo root, so we load it through `labscripts` (same pattern as
`test_gen_device_configs.py`).

Every test redirects the script's module-level directories at a tmp_path, so
nothing here reads or writes the real `scenarios/` or `generated/` trees.
"""

import json
import pathlib

import pytest

import labscripts

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
gen = labscripts.load("resolve_scenario")


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """A miniature repo: `_base` plus a `demo` scenario, both redirected."""
    scenarios = tmp_path / "scenarios"
    base = scenarios / "_base"
    demo = scenarios / "demo"

    _write(base / "workflows" / "discovery.yaml", "base discovery\n")
    _write(base / "scope" / "Global" / "devicecolumns.json", '{"from": "base"}\n')
    _write(base / "devices" / "frr" / "frr.conf", "base frr.conf\n")

    _write(demo / "scenario.json", json.dumps({"name": "demo", "title": "Demo", "summary": "s", "flavours": ["clab"]}))
    _write(demo / "topology.json", '{"devices": {}}\n')

    monkeypatch.setattr(gen, "SCENARIOS_DIR", scenarios)
    monkeypatch.setattr(gen, "BASE_DIR", base)
    monkeypatch.setattr(gen, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.delenv("SCENARIO", raising=False)
    return tmp_path


def test_base_only_file_comes_from_base(lab):
    gen.resolve("demo")
    resolved = lab / "generated" / "demo" / "scenario"
    assert (resolved / "workflows" / "discovery.yaml").read_text() == "base discovery\n"


def test_scenario_file_wins_over_base(lab):
    _write(lab / "scenarios" / "demo" / "devices" / "frr" / "frr.conf", "demo frr.conf\n")
    gen.resolve("demo")
    resolved = lab / "generated" / "demo" / "scenario"
    assert (resolved / "devices" / "frr" / "frr.conf").read_text() == "demo frr.conf\n"


def test_override_is_per_file_not_per_directory(lab):
    """Overriding one file in a directory keeps the base's siblings."""
    _write(lab / "scenarios" / "demo" / "scope" / "Global" / "devicecolumns.json", '{"from": "demo"}\n')
    _write(lab / "scenarios" / "_base" / "scope" / "Global" / "groupcolumns.json", '{"from": "base"}\n')
    gen.resolve("demo")
    scope = lab / "generated" / "demo" / "scenario" / "scope" / "Global"
    assert scope.joinpath("devicecolumns.json").read_text() == '{"from": "demo"}\n'
    assert scope.joinpath("groupcolumns.json").read_text() == '{"from": "base"}\n'


def test_scenario_only_file_is_added_alongside_base(lab):
    _write(lab / "scenarios" / "demo" / "workflows" / "extra.yaml", "demo extra\n")
    gen.resolve("demo")
    workflows = lab / "generated" / "demo" / "scenario" / "workflows"
    assert {p.name for p in workflows.iterdir()} == {"discovery.yaml", "extra.yaml"}


def test_removed_override_is_pruned_on_the_next_resolve(lab):
    extra = lab / "scenarios" / "demo" / "workflows" / "extra.yaml"
    _write(extra, "demo extra\n")
    gen.resolve("demo")
    extra.unlink()
    gen.resolve("demo")
    workflows = lab / "generated" / "demo" / "scenario" / "workflows"
    assert {p.name for p in workflows.iterdir()} == {"discovery.yaml"}


def test_pruning_removes_the_directory_an_override_left_empty(lab):
    _write(lab / "scenarios" / "demo" / "extras" / "only.yaml", "demo only\n")
    gen.resolve("demo")
    (lab / "scenarios" / "demo" / "extras" / "only.yaml").unlink()
    gen.resolve("demo")
    assert not (lab / "generated" / "demo" / "scenario" / "extras").exists()


def test_executable_bit_survives_the_copy(lab):
    script = lab / "scenarios" / "_base" / "devices" / "frr" / "set-aliases.sh"
    _write(script, "#!/bin/sh\n")
    script.chmod(0o755)
    gen.resolve("demo")
    copied = lab / "generated" / "demo" / "scenario" / "devices" / "frr" / "set-aliases.sh"
    assert copied.stat().st_mode & 0o111


def test_plan_reports_where_each_file_came_from(lab):
    _write(lab / "scenarios" / "demo" / "devices" / "frr" / "frr.conf", "demo frr.conf\n")
    resolved = gen.plan("demo")
    base = lab / "scenarios" / "_base"
    assert resolved[pathlib.Path("workflows/discovery.yaml")].is_relative_to(base)
    assert not resolved[pathlib.Path("devices/frr/frr.conf")].is_relative_to(base)


@pytest.mark.usefixtures("lab")
def test_unknown_scenario_lists_the_available_ones():
    with pytest.raises(SystemExit, match=r"unknown scenario 'nope'.*demo"):
        gen.source_dir("nope")


def test_missing_topology_is_an_error(lab):
    (lab / "scenarios" / "demo" / "topology.json").unlink()
    with pytest.raises(SystemExit, match=r"missing topology\.json"):
        gen.source_dir("demo")


def test_missing_manifest_is_an_error(lab):
    (lab / "scenarios" / "demo" / "scenario.json").unlink()
    with pytest.raises(SystemExit, match=r"missing scenario\.json"):
        gen.source_dir("demo")


@pytest.mark.usefixtures("lab")
def test_no_scenario_name_anywhere_is_an_error():
    with pytest.raises(SystemExit, match="no scenario"):
        gen.scenario_name(None)


@pytest.mark.usefixtures("lab")
def test_scenario_name_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("SCENARIO", "demo")
    assert gen.scenario_name(None) == "demo"
    assert gen.scenario_name("other") == "other"


@pytest.mark.usefixtures("lab")
def test_base_is_never_listed_as_a_scenario():
    assert gen.available() == ["demo"]
