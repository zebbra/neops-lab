---
title: Kubernetes lab
description: The FRR devices as pods in a local KIND cluster — generated manifests, in-cluster DNS, and what it deliberately leaves out.
tags: [operations, kubernetes]
---

# Kubernetes lab

*The same devices, as pods. No containerlab, no docker-compose, no control plane.*

`make kind-lab-up` renders the FRR devices of the selected scenario's `topology.json` into Kubernetes manifests and applies them to a local [KIND](https://kind.sigs.k8s.io/) cluster. It is a second flavour of the lab, not a replacement: it exists so a discovery tool has real, SSH-reachable FRR devices to talk to without the full containerlab bring-up.

Only `vendor: "frr"` devices are rendered, so a scenario declares whether it supports this flavour in its `scenario.json`:

```json
"flavours": ["clab", "kind"]
```

Both shipped scenarios do. `make kind-lab-up SCENARIO=frr-only` brings up the same ten devices as the containerlab flavour of that scenario, since `frr-only` has no SR Linux nodes to leave out.

## Targets

| Target | What it does |
|---|---|
| `make kind-lab-up` | Builds `neops-lab-frr:latest`, `kind load`s it onto the cluster nodes, resolves the scenario, runs `./gen_kind_manifests`, applies the result, waits for every Deployment to become Available, then prints each device's DNS name. |
| `make kind-lab-status` | `kubectl get pods,svc` in the lab namespace. |
| `make kind-lab-down` | Deletes the namespace, and nothing else. |
| `make kind-lab-discover` | Publishes the workflow definition, generates the per-device targets, waits for the discovery function block, then runs it — see [Discovery](#discovery). |

| Variable | Default | Purpose |
|---|---|---|
| `KIND_CLUSTER` | `kind` | Cluster `kind load docker-image` pushes the image to |
| `KIND_LAB_NAMESPACE` | `neops-lab` | Namespace the devices live in |
| `KIND_LAB_TIMEOUT` | `180` | Seconds `kubectl wait` allows for the pods |
| `SCENARIO` | `wan-and-fabric` | Which scenario's FRR devices to render |
| `KIND_MANIFEST` | `generated/$(SCENARIO)/kind/lab.yaml` | The generated manifest |
| `DOCKER_BUILD_FLAGS` | *(empty)* | Extra flags for every `docker build`, e.g. `--network=host` when the docker bridge has no DNS |

```bash
make kind-lab-up DOCKER_BUILD_FLAGS=--network=host
```

!!! warning "The cluster is shared"
    `kind-lab-down` deletes the **namespace**, never the cluster. Nothing in
    this repo creates or destroys a KIND cluster.


!!! warning "Switching scenarios needs a teardown here"

    `kubectl apply` adds and updates but never removes, so bringing up a
    scenario whose devices differ from the deployed one would leave the
    previous Deployments running and answering discovery. `make kind-lab-up`
    refuses in that case; run `make kind-lab-down` (which deletes the
    namespace) first.

    The containerlab flavour needs the same teardown, for a different reason:
    `containerlab destroy` acts on the nodes the handed topology names, not on
    every container carrying the lab's label, so a scenario with fewer devices
    would strand the rest. `make local-lab-up` refuses too; run
    `make local-lab-down` first.

## Reaching a device

Every device gets a ClusterIP Service named after it, so from any pod in the cluster:

```bash
ssh frr@core-rtr-01.neops-lab.svc.cluster.local   # password: frr
```

There are no management IPs here. The topology's `mgmt_ip` values belong to the containerlab `lab-net` bridge and are unused by this flavour — in-cluster DNS is the address.

That holds for reaching a device by hand, not for discovery. Discovery scans CIDRs and cannot be pointed at a name: the CMS keeps a device's address in a Postgres `inet` column, so a `*.svc.cluster.local` hostname is rejected outright rather than resolved. The addresses that do work here are the Service ClusterIPs, which `kubectl -n neops-lab get svc` prints — and the cluster assigns a fresh set every time the namespace is recreated, so nothing may hardcode them. `make kind-lab-discover` reads them per run for exactly that reason.

## Making the CMS usable

Bringing the pods up needs no product stack. Wiring them to one is a separate target, the same way `local-lab-up` and `local-lab-discover` are separate:

```bash
make kind-lab-cms-config   # grant the CMS role and seed the Global scope
```

That runs `apply_cms_config`, the compose lab's own script, reused rather than copied: it drives `manage.py` through a `CMS_EXEC` prefix, which this flavour sets to `kubectl exec` instead of `docker compose exec`. Without it a freshly installed CMS gives the `neops` user no role, and the web client shows *You don't have access to any scope*.

The host reaches the CMS through a short-lived `kubectl port-forward` that the target opens and tears down, so no ingress, public DNS or TLS is involved.

| Variable | Default | Purpose |
|---|---|---|
| `NEOPS_NAMESPACE` | `neops` | Namespace the product stack runs in |
| `NEOPS_CMS_DEPLOYMENT` | `neops-neops-core` | Deployment `manage.py` runs in |
| `NEOPS_CMS_SERVICE` / `NEOPS_CMS_PORT` | `neops-neops-core` / `8000` | What the port-forward targets |
| `NEOPS_CMS_TOKEN_SECRET` | `neops-neops-workflow-engine` | Secret the CMS API key is read from |
| `CMS_PORT` | `18000` | Local end of the port-forward |

!!! note "Getting the devices *into* the CMS is discovery's job"
    Registering devices is what `fb.base.neops.io/global_discover_network` does,
    driven from this repo by `bootstrap/register.py`, `run_workflow` and
    `scenarios/_base/workflows/simple-lab-discovery.workflow.yaml`. This
    flavour deliberately adds no second path for it — it runs the same one,
    against the pods.

## Discovery

```bash
make kind-lab-discover
```

Four steps, each one of the repo's existing scripts, so nothing about publishing, waiting or executing exists twice:

1. **Publish** the resolved scenario's workflow documents (`generated/<scenario>/scenario/workflows/`) by running `bootstrap/register.py` in the `neops-lab-bootstrap` image. The compose flavour does this from its `lab_bootstrap` service during `local-lab-up`; `kind-lab-up` has no equivalent step, so the definition is published here instead. Re-publishing unchanged content is a no-op (`200`); publishing a *changed* definition under a version that already exists fails with `409`, because published versions are immutable.
2. **Generate the targets** with `./gen_kind_discover_params`, which writes `generated/<scenario>/kind/discover-params.json`.
3. **Wait** for an online worker registering the discovery block, with `./wait_ready`. The worker registers its blocks asynchronously; without the wait the execution fails with *Function block not found*.
4. **Execute** with `./run_workflow`, polling to a terminal state. Ten devices take roughly two minutes.

There is no `./wait_devices` step. Each pod's `tcpSocket: 22` readiness probe already is that poll, and the host could not reach a ClusterIP to run it anyway.

### The parameters, and why they are generated

`./gen_kind_discover_params` reads the Service ClusterIPs live from `kubectl -n <namespace> get svc -o json` and emits one target per device, in the scenario's `topology.json` declaration order:

```json
{
  "subnets": [
    { "cidr": "10.96.49.169/32", "platform": "frr" }
  ],
  "credentials": [
    { "username": "frr", "password": "frr", "platform": "frr" }
  ]
}
```

The device set comes from `gen_kind_manifests` and the credentials from `gen_clab_topology`, so the file can only ever target devices that were rendered, with the logins the image was built with. Two properties are load-bearing:

- **One `/32` per device; a summarising CIDR is forbidden.** The ClusterIPs are scattered across the cluster's service range, so the only prefix covering all ten would be the whole range. Discovery expands a CIDR into one SSH probe per address and the block's target guard is disabled, so a `/16` would launch 65534 of them.
- **No hostname.** `<device>.<namespace>.svc.cluster.local` is how a human reaches a device; the CMS rejects it, as above.

The output is git-ignored and regenerated on every run, because a `kind-lab-down` / `kind-lab-up` cycle hands out a fresh set of addresses.

### The worker image has to carry the base blocks

Discovery runs the `fb.base.neops.io/global_discover_network:0.1.0` block, which ships **inside the worker image** rather than being mounted from here. Which image you deployed decides whether this works at all:

| Worker image built from | Function blocks | Discovery |
|---|---|---|
| `quay.io/zebbra/neops-worker-sdk:develop`, the default | 25, including `global_discover_network` | Works |
| the `neops-worker-sdk-py` checkout, `make build-docker` | 25, plus whatever you are editing | Works |
| any image built without `neops/fb` | none | *Function block not found* |

The KIND release deployed against this lab runs a worker built from that checkout and loaded into the cluster as `neops-worker-sdk:cutting-edge`, like every other service — the workspace-root `make deploy-cutting-edge` does both — which is why discovery works here today. `make kind-lab-discover` fails at step 3 with a `wait_ready` timeout if you point it at a release whose image lacks the block.

### Variables

| Variable | Default | Purpose |
|---|---|---|
| `KIND_ENGINE_URL` | `http://engine.neops.local` | How the host **and** the bootstrap container reach the workflow engine |
| `KIND_DISCOVER_PARAMS` | `generated/$(SCENARIO)/kind/discover-params.json` | The generated parameter file |
| `KIND_DISCOVER_TIMEOUT` | `600` | Seconds `run_workflow` polls for a terminal state |
| `DISCOVER_FB` | `fb.base.neops.io/global_discover_network:0.1.0` | The block `wait_ready` blocks on — shared with the containerlab flavour |
| `DISCOVER_WORKFLOW` | `wf.lab.neops.io/simple_lab_discovery:1.2.0` | The definition that is published and executed — shared with the containerlab flavour |
| `DOCKER_RUN_FLAGS` | *(empty)* | Extra flags for the `docker run`, e.g. `--network=host` |

### Why one URL, and where it comes from

The engine is the one thing here that is *not* reached through a `kubectl port-forward`, unlike the CMS in `kind-lab-cms-config`. It has to be reachable from two places — the host scripts and the bootstrap container that publishes the definition — and a port-forward is bound on the host only. One address serving both sides is what keeps this to a single variable.

The default is the umbrella's **offline ingress name**. Every service is published twice, under a public name and a `*.neops.local` twin, and the twins are mapped to `127.0.0.1` by:

```bash
make -C neops-helm config-hosts   # writes the *.neops.local lines into /etc/hosts, once
```

Run that once and `http://engine.neops.local` works with no further configuration, on anyone's deployment of the stack.

A container does not share the host's `/etc/hosts`, so the bootstrap container is handed the mapping explicitly as `--add-host engine.neops.local:host-gateway` — the ingress listens on the host's port 80, and `host-gateway` is the address a container reaches the host at. The Makefile derives both the hostname and that flag from `KIND_ENGINE_URL`, so overriding the URL is enough:

```bash
# A remote engine reachable through real DNS: no --add-host is added, because a
# public name resolves the same on both sides. This is the URL of *one*
# deployment; substitute your own.
make kind-lab-discover KIND_ENGINE_URL=https://engine.neops.lerena.cloud

# Your own port-forward instead: 127.0.0.1 means the host, so the container
# needs the host's network namespace rather than a name mapping.
kubectl -n neops port-forward svc/neops-neops-workflow-engine 13030:3030 &
make kind-lab-discover KIND_ENGINE_URL=http://127.0.0.1:13030 DOCKER_RUN_FLAGS=--network=host
```

!!! note "Re-running is safe here"
    Devices are keyed by address, so a second run skips the ones already in the
    CMS. Against this lab a re-run also left the interface counts untouched
    (10 devices / 48 interfaces before and after), so the containerlab
    flavour's "discover against a fresh CMS" caution did not apply. Check the
    counts rather than assuming, on either flavour.

## What the pods look like

`./gen_kind_manifests` writes one multi-document YAML file containing a `Namespace`, a single `ConfigMap`, and a `Deployment` + `Service` per device. Re-running it is byte-identical, exactly like `./gen_clab_topology`.

The ConfigMap carries every device's rendered `.iface` file **plus the three `/lab` files** the containerlab flavour binds — `set-aliases.sh`, `frr.conf` and `daemons` — taken from the resolved scenario. Both the init container and the FRR container mount all three at `/lab`: the init container runs `set-aliases.sh`, and the FRR container's entrypoint installs `frr.conf` and `daemons` into `/etc/frr` before FRR starts. The image bakes neither, so a scenario's FRR config reaches the pods the same way it reaches the containerlab nodes. See [Images](20-images.md).

A pod has only `eth0`, so the topology's `swpN` ports are created as **dummy links** by an init container running `/lab/set-aliases.sh` — the same script at the same path containerlab `exec`s, applying the same descriptions from the same [`render_frr`](../10-concepts/20-topology.md) renderer. Init containers share the pod's network namespace, so the links and their aliases are already in place when zebra reads the interface list:

```
Interface       Status  Protocol  Description
lo              up      up        loopback
                                  core-rtr-01 loopback
swp1            up      up        core-rtr-01:swp1 -> core-rtr-02:swp1
swp2            up      up        core-rtr-01:swp2 -> edge-rtr-01:swp1
```

The init container needs `NET_ADMIN` to create the links; the FRR container needs `NET_ADMIN` **and** `SYS_ADMIN`, because the FRR binary refuses to start without `cap_sys_admin` — the same constraint containerlab satisfies for `kind: linux` nodes. Neither container is privileged.

Each pod carries a `tcpSocket: 22` readiness probe, so a Deployment reports Available exactly when its device accepts SSH. That is why `kind-lab-up` waits with `kubectl wait` and not with `./wait_devices`: the probe already *is* that TCP-22 poll, run per pod from inside the cluster. A host-side poll could not do it — neither a ClusterIP nor a `*.svc.cluster.local` name is reachable or resolvable from the host.

## What it deliberately leaves out

- **Any non-FRR device.** Each SR Linux node wants several GB of RAM and a slow management-stack boot; only `vendor: "frr"` devices are rendered, whatever the scenario contains. A scenario with no FRR device cannot use this flavour and must not declare `kind` in its `flavours`.
- **Deploying the control plane.** Nothing here installs a CMS, engine, worker or web client; `make local-env-*` and `make local-lab-up` still do that for the compose flavour. `kind-lab-cms-config` and `kind-lab-discover` *use* a control plane someone else deployed — they configure and drive it, and they never install, upgrade or delete it.
- **Real links.** The `swpN` ports are dummy interfaces with the right names and descriptions, not point-to-point wiring. Discovery sees a realistic device; packets do not cross between devices.
