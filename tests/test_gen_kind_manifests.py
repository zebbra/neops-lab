"""Unit tests for the Kubernetes manifest generator.

`gen_kind_manifests` is an executable script (no `.py` extension) living at the repo
root, so we load it through `labscripts` (same pattern as
`test_gen_clab_topology.py`).
"""

import json
import pathlib

import labscripts

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
gen = labscripts.load("gen_kind_manifests")

SCENARIO = "wan-and-fabric"
TOPOLOGY = json.loads((LAB_DIR / "scenarios" / SCENARIO / "topology.json").read_text())
LAB_FILES = {
    name: (LAB_DIR / "scenarios" / "_base" / "devices" / "frr" / name).read_text()
    for name in ("set-aliases.sh", "frr.conf", "daemons")
}


def _manifests(namespace="neops-lab", image="neops-lab-frr:latest"):
    return gen.render_manifests(gen.frr_devices(TOPOLOGY["devices"]), namespace, image, LAB_FILES)


def _by_kind(docs, kind):
    return [doc for doc in docs if doc["kind"] == kind]


def test_only_frr_devices_are_rendered():
    devices = gen.frr_devices(TOPOLOGY["devices"])
    assert len(devices) == 10
    assert all(dev["vendor"] == "frr" for dev in devices.values())
    assert not any(name.startswith(("spine-", "leaf-")) for name in devices)


def test_frr_devices_keep_declaration_order():
    assert list(gen.frr_devices(TOPOLOGY["devices"])) == [
        name for name, dev in TOPOLOGY["devices"].items() if dev["vendor"] == "frr"
    ]


def test_one_deployment_and_one_service_per_device():
    docs = _manifests()
    devices = list(gen.frr_devices(TOPOLOGY["devices"]))

    assert [d["metadata"]["name"] for d in _by_kind(docs, "Deployment")] == devices
    assert [d["metadata"]["name"] for d in _by_kind(docs, "Service")] == devices
    assert len(_by_kind(docs, "Namespace")) == 1
    assert len(_by_kind(docs, "ConfigMap")) == 1


def test_namespace_document_comes_first():
    """kubectl applies in file order, so nothing may precede the namespace."""
    docs = _manifests()
    assert docs[0]["kind"] == "Namespace"
    assert docs[1]["kind"] == "ConfigMap"


def test_namespace_is_applied_to_every_namespaced_document():
    docs = _manifests(namespace="other-ns")
    assert docs[0]["metadata"]["name"] == "other-ns"
    assert all(doc["metadata"]["namespace"] == "other-ns" for doc in docs[1:])


def test_config_map_carries_the_alias_script_and_every_iface_file():
    config_map = _by_kind(_manifests(), "ConfigMap")[0]
    data = config_map["data"]

    assert data["set-aliases.sh"] == LAB_FILES["set-aliases.sh"]
    assert set(data) == set(LAB_FILES) | {f"{name}.iface" for name in gen.frr_devices(TOPOLOGY["devices"])}


def test_iface_file_matches_the_shared_frr_renderer():
    """The descriptions come from gen_device_configs, not from a second copy."""
    devices = gen.frr_devices(TOPOLOGY["devices"])
    data = _by_kind(_manifests(), "ConfigMap")[0]["data"]

    expected = gen.render_frr("core-rtr-01", devices["core-rtr-01"])
    assert data["core-rtr-01.iface"] == expected
    assert "swp1|core-rtr-01:swp1 -> core-rtr-02:swp1" in expected


def test_service_selects_its_own_deployment_pods():
    docs = _manifests()
    deployments = {d["metadata"]["name"]: d for d in _by_kind(docs, "Deployment")}

    for service in _by_kind(docs, "Service"):
        name = service["metadata"]["name"]
        assert service["spec"]["selector"] == {"neops.io/device": name}
        assert service["spec"]["ports"] == [{"name": "ssh", "port": 22, "targetPort": 22, "protocol": "TCP"}]
        assert service["spec"]["type"] == "ClusterIP"

        pod_labels = deployments[name]["spec"]["template"]["metadata"]["labels"]
        assert pod_labels["neops.io/device"] == name
        assert pod_labels["app.kubernetes.io/name"] == "neops-lab-frr"


def test_pod_creates_its_interfaces_before_frr_starts():
    """The dummy links must exist by the time zebra reads the interface list."""
    spec = _by_kind(_manifests(), "Deployment")[0]["spec"]["template"]["spec"]
    init = spec["initContainers"][0]

    assert init["command"] == ["/bin/sh", "/lab/set-aliases.sh"]
    assert init["securityContext"]["capabilities"]["add"] == ["NET_ADMIN"]
    assert spec["containers"][0]["securityContext"]["capabilities"]["add"] == ["NET_ADMIN", "SYS_ADMIN"]


def test_pod_hostname_matches_the_iface_file_name():
    """set-aliases.sh resolves its file as `$(hostname).iface`."""
    for deployment in _by_kind(_manifests(), "Deployment"):
        name = deployment["metadata"]["name"]
        spec = deployment["spec"]["template"]["spec"]
        assert spec["hostname"] == name
        mounts = spec["containers"][0]["volumeMounts"]
        assert {
            "name": "device-config",
            "mountPath": f"/etc/frr/lab-interfaces/{name}.iface",
            "subPath": f"{name}.iface",
        } in mounts


def test_image_is_used_by_both_containers():
    spec = _by_kind(_manifests(image="neops-lab-frr:probe"), "Deployment")[0]["spec"]["template"]["spec"]
    assert spec["initContainers"][0]["image"] == "neops-lab-frr:probe"
    assert spec["containers"][0]["image"] == "neops-lab-frr:probe"
    assert spec["containers"][0]["imagePullPolicy"] == "IfNotPresent"


def test_lab_hostname_env_drives_the_frr_hostname():
    for deployment in _by_kind(_manifests(), "Deployment"):
        name = deployment["metadata"]["name"]
        env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        assert env == [{"name": "LAB_HOSTNAME", "value": name}]


def test_every_device_pod_reports_ready_on_tcp_22():
    """The probe is why `kind-lab-up` may wait on Deployment availability.

    It is the same TCP-22 check `wait_devices` does, run from inside the cluster.
    """
    for deployment in _by_kind(_manifests(), "Deployment"):
        probe = deployment["spec"]["template"]["spec"]["containers"][0]["readinessProbe"]
        assert probe["tcpSocket"] == {"port": 22}


def test_dump_is_deterministic():
    """Re-rendering the same topology must be byte-identical."""
    assert gen.dump_documents(_manifests()) == gen.dump_documents(_manifests())


def test_dump_emits_one_yaml_document_per_manifest():
    rendered = gen.dump_documents(_manifests())
    assert rendered.startswith("---\n")
    assert len([chunk for chunk in rendered.split("---\n") if chunk]) == len(_manifests())
    assert rendered.endswith("\n")


def test_dump_quotes_strings_and_leaves_numbers_bare():
    rendered = gen.dump_documents([{"apiVersion": "v1", "kind": "X", "spec": {"replicas": 1, "on": True}}])
    assert 'apiVersion: "v1"' in rendered
    assert "replicas: 1" in rendered
    assert "on: true" in rendered


def test_dump_writes_multi_line_values_as_literal_blocks():
    rendered = gen.dump_documents([{"data": {"script": "line one\nline two\n"}}])
    assert rendered == "---\ndata:\n  script: |\n    line one\n    line two\n"


def test_dump_indents_nested_sequences_of_mappings():
    rendered = gen.dump_documents([{"spec": {"containers": [{"name": "frr", "ports": [{"containerPort": 22}]}]}}])
    assert rendered == ('---\nspec:\n  containers:\n    - name: "frr"\n      ports:\n        - containerPort: 22\n')


def test_config_map_carries_the_frr_config_the_image_no_longer_bakes():
    data = _by_kind(_manifests(), "ConfigMap")[0]["data"]
    assert data["frr.conf"] == LAB_FILES["frr.conf"]
    assert data["daemons"] == LAB_FILES["daemons"]


def test_both_containers_mount_every_lab_file():
    """The init container runs set-aliases.sh; the device container's entrypoint
    installs frr.conf and daemons before FRR starts. Both need /lab."""
    spec = _by_kind(_manifests(), "Deployment")[0]["spec"]["template"]["spec"]
    for container in (spec["initContainers"][0], spec["containers"][0]):
        paths = {mount["mountPath"] for mount in container["volumeMounts"]}
        assert {"/lab/set-aliases.sh", "/lab/frr.conf", "/lab/daemons"} <= paths
