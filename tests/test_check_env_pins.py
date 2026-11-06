"""Unit tests for `check_env_pins`, which warns an existing checkout whose `.env`
pins other images than `.env.example` (`make lab-env` copies the example only
into a fresh clone)."""

import labscripts

check = labscripts.load("check_env_pins")

EXAMPLE = """\
# Override the CMS image.
# NEOPS_CMS_IMAGE=neops-cms-free:latest
NEOPS_CMS_IMAGE=quay.io/zebbra/neops-cms-free:2.4.0
NEOPS_ENGINE_TAG=0.46.0
NEOPS_WORKER_SDK_IMAGE=quay.io/zebbra/neops-worker-sdk:0.5.0
"""


def _lab(tmp_path, monkeypatch, env=None):
    (tmp_path / ".env.example").write_text(EXAMPLE)
    if env is not None:
        (tmp_path / ".env").write_text(env)
    monkeypatch.setattr(check, "ROOT", tmp_path)


def test_pins_are_the_active_assignments_only():
    assert check.pins(EXAMPLE) == {
        "NEOPS_CMS_IMAGE": "quay.io/zebbra/neops-cms-free:2.4.0",
        "NEOPS_ENGINE_TAG": "0.46.0",
        "NEOPS_WORKER_SDK_IMAGE": "quay.io/zebbra/neops-worker-sdk:0.5.0",
    }


def test_an_export_or_a_quoted_value_is_the_same_pin():
    assert check.pins("export NEOPS_ENGINE_TAG=\"0.46.0\"\nNEOPS_CMS_IMAGE = 'cms:2.4.0'\n") == {
        "NEOPS_ENGINE_TAG": "0.46.0",
        "NEOPS_CMS_IMAGE": "cms:2.4.0",
    }


def test_an_env_on_the_examples_pins_says_nothing(tmp_path, monkeypatch, capsys):
    _lab(tmp_path, monkeypatch, env=EXAMPLE + "LAB_SUBNET=172.31.0.0/23\n")
    assert check.main() == 0
    assert capsys.readouterr().out == ""


def test_an_older_worker_pin_is_named_with_the_examples(tmp_path, monkeypatch, capsys):
    _lab(tmp_path, monkeypatch, env=EXAMPLE.replace("neops-worker-sdk:0.5.0", "neops-worker-sdk:0.3.0"))
    assert check.main() == 0
    out = capsys.readouterr().out
    assert "NEOPS_WORKER_SDK_IMAGE=quay.io/zebbra/neops-worker-sdk:0.3.0" in out
    assert ".env.example pins quay.io/zebbra/neops-worker-sdk:0.5.0" in out
    assert "NEOPS_ENGINE_TAG" not in out


def test_a_pin_the_env_leaves_unset_is_named(tmp_path, monkeypatch, capsys):
    _lab(tmp_path, monkeypatch, env="NEOPS_CMS_IMAGE=quay.io/zebbra/neops-cms-free:2.4.0\n")
    check.main()
    out = capsys.readouterr().out
    assert ".env leaves NEOPS_ENGINE_TAG unset; .env.example pins 0.46.0" in out
    assert ".env leaves NEOPS_WORKER_SDK_IMAGE unset" in out


def test_a_fresh_clone_has_no_env_to_check(tmp_path, monkeypatch, capsys):
    _lab(tmp_path, monkeypatch)
    assert check.main() == 0
    assert capsys.readouterr().out == ""
