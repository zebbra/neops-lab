"""Unit tests for the Kubernetes discovery-parameter generator.

`gen_kind_discover_params` is an executable script (no `.py` extension) living at
the repo root, so we load it through `labscripts` (same pattern as
`test_gen_kind_manifests.py`).

`kubectl` is stubbed throughout: these tests must never touch a cluster, and the
addresses they assert on are the ones the stub hands out.
"""

import json
import pathlib
import re
import subprocess

import pytest

import labscripts

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
gen = labscripts.load("gen_kind_discover_params")

SCENARIO = "wan-and-fabric"
TOPOLOGY = json.loads((LAB_DIR / "scenarios" / SCENARIO / "topology.json").read_text())
FRR_DEVICES = gen.frr_devices(TOPOLOGY["devices"])

CIDR_32 = re.compile(r"^(\d{1,3}\.){3}\d{1,3}/32$")


def _fake_service(name, cluster_ip):
    return {"metadata": {"name": name}, "spec": {"clusterIP": cluster_ip}}


def _stub_kubectl(monkeypatch, services, recorder=None):
    """Replace the kubectl call with a canned `get svc -o json` payload."""

    def fake_run(argv, **kwargs):  # noqa: ARG001 — the stub ignores capture/text/check
        if recorder is not None:
            recorder.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps({"items": services}), stderr="")

    monkeypatch.setattr(gen.subprocess, "run", fake_run)


def _lab_services():
    """One ClusterIP per FRR device, deliberately not in declaration order."""
    services = [_fake_service(name, f"10.96.{i}.{i + 7}") for i, name in enumerate(FRR_DEVICES, start=1)]
    return list(reversed(services))


def _params(monkeypatch, services=None, recorder=None):
    _stub_kubectl(monkeypatch, _lab_services() if services is None else services, recorder)
    return gen.render_discover_params(FRR_DEVICES, gen.cluster_ips("neops-lab"))


def test_kubectl_is_asked_for_the_requested_namespace(monkeypatch):
    calls = []
    _stub_kubectl(monkeypatch, _lab_services(), calls)
    gen.cluster_ips("other-ns")
    assert calls == [["kubectl", "-n", "other-ns", "get", "svc", "-o", "json"]]


def test_one_slash_32_target_per_frr_device(monkeypatch):
    subnets = _params(monkeypatch)["subnets"]
    assert len(subnets) == len(FRR_DEVICES) == 10
    assert all(subnet["cidr"].endswith("/32") for subnet in subnets)


def test_no_sr_linux_device_is_targeted(monkeypatch):
    """Only `vendor: "frr"` is rendered, exactly as the manifests are."""
    subnets = _params(monkeypatch)["subnets"]
    assert all(subnet["platform"] == "frr" for subnet in subnets)
    assert not any(name.startswith(("spine-", "leaf-")) for name in FRR_DEVICES)
    assert len(FRR_DEVICES) < len(TOPOLOGY["devices"])


def test_targets_follow_topology_declaration_order(monkeypatch):
    """kubectl lists Services alphabetically; the output must not inherit that."""
    services = _lab_services()
    addresses = {service["metadata"]["name"]: service["spec"]["clusterIP"] for service in services}

    subnets = _params(monkeypatch, services)["subnets"]
    assert [subnet["cidr"] for subnet in subnets] == [f"{addresses[name]}/32" for name in FRR_DEVICES]


def test_output_is_deterministic_for_a_fixed_cluster_state(monkeypatch):
    first = gen._dump_discover_params(_params(monkeypatch))
    second = gen._dump_discover_params(_params(monkeypatch))
    assert first == second


def test_credentials_are_the_lab_login_scoped_to_the_platform(monkeypatch):
    """One entry per vendor present — here only FRR, so only the frr login."""
    assert _params(monkeypatch)["credentials"] == [{"username": "frr", "password": "frr", "platform": "frr"}]


def test_subnets_carry_no_credentials_of_their_own(monkeypatch):
    assert all(set(subnet) == {"cidr", "platform"} for subnet in _params(monkeypatch)["subnets"])


def test_a_hostname_never_appears_as_a_target(monkeypatch):
    """The CMS keeps a device address in a Postgres `inet` column, which rejects
    a `*.svc.cluster.local` name rather than resolving it."""
    for subnet in _params(monkeypatch)["subnets"]:
        assert CIDR_32.match(subnet["cidr"]), subnet["cidr"]


def test_a_device_without_a_service_is_a_hard_error(monkeypatch):
    services = _lab_services()[:-1]
    _stub_kubectl(monkeypatch, services)
    with pytest.raises(SystemExit, match="no Service ClusterIP for"):
        gen.render_discover_params(FRR_DEVICES, gen.cluster_ips("neops-lab"))


def test_a_headless_service_counts_as_no_address(monkeypatch):
    services = [_fake_service(name, "None") for name in FRR_DEVICES]
    _stub_kubectl(monkeypatch, services)
    assert gen.cluster_ips("neops-lab") == {}


def test_unrelated_services_in_the_namespace_are_ignored(monkeypatch):
    services = [*_lab_services(), _fake_service("kubernetes", "10.96.0.1")]
    subnets = _params(monkeypatch, services)["subnets"]
    assert len(subnets) == len(FRR_DEVICES)
    assert "10.96.0.1/32" not in [subnet["cidr"] for subnet in subnets]


def test_kubectl_failure_surfaces_its_stderr(monkeypatch):
    def failing_run(argv, **kwargs):  # noqa: ARG001 — the stub ignores capture/text/check
        raise subprocess.CalledProcessError(1, argv, stderr='Error from server: namespace "nope" not found')

    monkeypatch.setattr(gen.subprocess, "run", failing_run)
    with pytest.raises(SystemExit, match="namespace"):
        gen.cluster_ips("nope")
