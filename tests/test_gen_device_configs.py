"""Unit tests for the lab device-config generator.

`gen_device_configs` is an executable script (no `.py` extension) living at the
repo root, so we load it by path via `importlib.util`.
"""

import importlib.machinery
import importlib.util
import pathlib

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = LAB_DIR / "gen_device_configs"

# The script has no `.py` suffix, so an explicit SourceFileLoader is needed;
# `spec_from_file_location` alone returns None for an unrecognised extension.
_loader = importlib.machinery.SourceFileLoader("gen_device_configs", str(SCRIPT_PATH))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
assert _spec is not None
gen = importlib.util.module_from_spec(_spec)
_loader.exec_module(gen)


def test_render_frr_with_loopback():
    dev = {
        "vendor": "frr",
        "loopback": "lo",
        "interfaces": [
            {"name": "swp1", "to": "core-rtr-02:swp1"},
            {"name": "swp2", "to": "edge-rtr-01:swp1"},
        ],
    }
    out = gen.render_frr("core-rtr-01", dev)
    lines = out.splitlines()

    # Loopback line comes first.
    assert lines[0] == "lo|core-rtr-01 loopback"
    # Interface lines use `name|description` with the exact description format.
    assert lines[1] == "swp1|core-rtr-01:swp1 -> core-rtr-02:swp1"
    assert lines[2] == "swp2|core-rtr-01:swp2 -> edge-rtr-01:swp1"
    assert out.endswith("\n")


def test_render_frr_without_loopback_has_no_lo_line():
    dev = {
        "vendor": "frr",
        "loopback": None,
        "interfaces": [{"name": "swp1", "to": "x:swp1"}],
    }
    out = gen.render_frr("r1", dev)
    assert out == "swp1|r1:swp1 -> x:swp1\n"


def test_render_srl_lines_and_short_conversion():
    dev = {
        "vendor": "srl",
        "loopback": None,
        "interfaces": [
            {"name": "ethernet-1/1", "to": "spine-01:e1/1"},
            {"name": "ethernet-1/3", "to": "server web-01"},
        ],
    }
    out = gen.render_srl("leaf-01", dev)
    lines = out.splitlines()

    # Two lines per interface.
    assert lines[0] == "set / interface ethernet-1/1 admin-state enable"
    assert lines[1] == 'set / interface ethernet-1/1 description "leaf-01:e1/1 -> spine-01:e1/1"'
    assert lines[2] == "set / interface ethernet-1/3 admin-state enable"
    assert lines[3] == 'set / interface ethernet-1/3 description "leaf-01:e1/3 -> server web-01"'
    # ethernet-1/N -> e1/N conversion happened in the description.
    assert "leaf-01:e1/1" in lines[1]
    assert "ethernet-1/1" not in gen.description("leaf-01", dev["interfaces"][0])
    assert out.endswith("\n")


def test_short_name_conversion():
    assert gen.short_name("ethernet-1/4") == "e1/4"
    assert gen.short_name("swp1") == "swp1"
