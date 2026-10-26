# neops-lab — Simple Lab

A turn-key local, multi-vendor lab with **real point-to-point wiring**,
provisioned by [containerlab](https://containerlab.dev). The control plane — CMS
+ workflow engine + a worker that runs the `global_discover_network` function
block + a one-shot bootstrap container — runs on docker-compose; the devices
attach to the same `lab-net` bridge (172.30.0.0/24) at fixed management IPs, so
the worker reaches them at those IPs.

Which network you get is a **scenario**. The default, `wan-and-fabric`, is 10
FRRouting routers + 5 Nokia SR Linux switches (15 devices); `frr-only` is the
same FRR half without the SR Linux fabric (10 devices). `make scenarios` lists
them — see [Scenarios](#scenarios).

The control plane runs from **published images** on `quay.io/zebbra`: the CMS,
the workflow engine, the web client and the worker. This repo owns the lab
itself: the scenarios,
the device configs, the workflow, the bootstrap sequencing and the two small
helper images.

The environment and the devices are **separate lifecycles**, brought up in
either order, and discovery is the step that joins them:

```bash
make local-env-init   # the control plane — one-time per environment
make local-lab-up     # the scenario's devices
make discover         # populate the CMS from them
```

End state: one `Device` row per device in the scenario (FRR `vendor=FRRouting`,
Nokia `vendor=Nokia`) in the CMS — each with its interfaces recorded. The
discovery function block records each device **and its interfaces** in one pass:
it connects to every host via the matching connection plugin, reads facts +
interfaces, and writes both `Device` and `Interface` rows to the CMS. Clicking
Run in the engine UI does the same thing.

## Documentation

Full documentation lives in [`docs/`](./docs/) and is built with the shared
Zebbra MkDocs tooling:

```bash
make doc-serve   # live preview at http://localhost:8000
make doc-build   # build into site/
```

Start at [`docs/index.md`](./docs/index.md). This README stays the quick
operator reference; the site covers the topology model, the discovery
contract, the `/app/lab` mount rule, troubleshooting by symptom, and the
repo's invariants.

> ⚠️ Not to be confused with **`neops-remote-lab`** — a completely separate
> repo, a *remote* FastAPI service brokering queued access to real Netlab
> topologies for automated tests. It shares no code with this one. See
> [`docs/99-appendix/neops-ecosystem.md`](./docs/99-appendix/neops-ecosystem.md).

## Prerequisites

Supported hosts: **Linux and macOS** (Docker Desktop or OrbStack). Run the
preflight first — it checks everything below and prints the fix next to each
failure:

```bash
make doctor
```

- **Docker** + `docker compose` ≥ 2.20. No registry login needed: the CMS, the
  web client and the default **developer preview** engine all pull anonymously.
  `docker login quay.io` is only for swapping in the full licensed engine.
- **containerlab** needs no install: every make target and documented command
  uses `./containerlab`, which runs the official `ghcr.io/srl-labs/clab` image
  through the docker socket — the same command and the same pinned containerlab
  version on both hosts. `CLAB_IMAGE` overrides the version;
  `CLAB_NATIVE=/path/to/containerlab` selects a host binary instead. Verify
  with the 2-node probe:
  ```bash
  ./containerlab deploy  -t clab/probe.clab.yml
  ./containerlab destroy -t clab/probe.clab.yml --cleanup
  ```
  Prefer a native binary instead? Set
  `CLAB_NATIVE=$(command -v containerlab)`. On Linux that path needs the SUID
  setup — `make clab-suid` does it (idempotent; re-run after a containerlab
  upgrade, which replaces the binary and drops the SUID bit).
- **`openssl`** — `make lab-jwt` mints the dev RSA keypair under `cms/jwt/`
  that the CMS requires for RS256 JWT issuance (chained into
  `make local-env-init`, idempotent; OpenSSL 3 and the LibreSSL a stock macOS
  ships both work). The keypair is git-ignored: a throwaway lab credential.
- **`python3` ≥ 3.9** — the lab itself needs nothing else; all host scripts are
  stdlib-only and import under the `/usr/bin/python3` a stock macOS ships.
- **`uv`** — only for `make test` / `make lint` / `make check` and the docs.
- **`cms_api_key.env`** exists (produced by `make local-env-init` — needed once).
- **A worker image carrying the base function blocks.**
  `fb.base.neops.io/global_discover_network:0.1.0` ships *inside* the image, and
  `quay.io/zebbra/neops-worker-sdk:develop` does not currently carry it — which
  is why `.env.example` pins a tag that does. That pin is a prerelease and
  expires; read its note before a fresh clone, and build the checkout once it
  has expired. Building it is also how you try SDK changes before they are
  released:

  ```bash
  make -C ../neops-worker-sdk-py build-docker      # -> neops-worker-sdk:latest
  echo 'NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest' >> .env
  ```

  Check what you got before bringing the lab up — the image must carry the
  block, not just build:

  ```bash
  docker run --rm --entrypoint sh neops-worker-sdk:latest -c 'ls neops/fb/base/global'
  ```

  Without this the worker container exits, `local-env-up` burns its full
  `wait_ready` budget and gives up with `timeout: no online worker for
  fb.base.neops.io/global_discover_network:0.1.0`.
- **A workflow-engine image with the publish route and the large-payload +
  reference-resolution fixes.** Discovery emits a few hundred `Interface` rows in
  one job result, and `bootstrap/register.py` writes definitions through
  `POST /workflow-definition/publish`. The default is the **developer preview**,
  `quay.io/zebbra/neops-workflow-engine-preview:develop`, which has both
  and is public — nothing to log into. `NEOPS_WORKFLOW_ENGINE_IMAGE` replaces
  the whole reference, which is how you swap in the full licensed engine
  (`docker login quay.io` first, then
  `export NEOPS_WORKFLOW_ENGINE_IMAGE=quay.io/zebbra/neops-workflow-engine:develop`)
  or run a local build (`neops-workflow-engine:latest`); `NEOPS_ENGINE_TAG=<tag>`
  in `.env` pins just the tag on the preview.
  `NEOPS_WEB_CLIENT_IMAGE` and `NEOPS_WORKER_SDK_IMAGE` work the same way — see
  `.env.example`.
- **Host resources**: for `wan-and-fabric` the 5 SR Linux nodes want ≈1.5–2 GB
  each; with Elasticsearch and the control plane that scenario needs roughly
  **14–16 GB** for containers. `SCENARIO=frr-only` drops the SR Linux nodes and
  fits in far less. On macOS that is the Docker Desktop **VM** budget (Settings →
  Resources → Memory; the 8 GB default is too small). On Apple Silicon enable
  *Use Rosetta for x86_64/amd64 emulation* — the `quay.io/zebbra` images are
  amd64-only. The first run takes a couple of minutes; on a slow host raise the
  wait budgets (`make local-lab-up WAIT_DEVICES_TIMEOUT=600`,
  `make local-env-up WAIT_READY_TIMEOUT=600`).

## Scenarios

A **scenario** is a directory under [`scenarios/`](./scenarios/) holding
everything that makes one lab different from another: its topology, its
workflows, its CMS scope configuration, its device configs and its OIDC
configuration. Anything a scenario does not carry comes from
[`scenarios/_base/`](./scenarios/_base/), file by file.

```bash
make scenarios                        # what is available
make scenario                         # what is selected right now
make local-lab-up                     # deploy the default scenario's devices
make local-lab-up SCENARIO=frr-only   # a different one
```

| Scenario | Devices | Flavours | What it is |
|---|---|---|---|
| `wan-and-fabric` (default) | 15 | clab, kind | FRR WAN/core/edge/PE + a Nokia SR Linux leaf-spine fabric — see [`scenarios/wan-and-fabric/README.md`](./scenarios/wan-and-fabric/README.md) |
| `frr-only` | 10 | clab, kind | The FRR half alone; carries only a topology, everything else inherited — see [`scenarios/frr-only/README.md`](./scenarios/frr-only/README.md) |

`SCENARIO` selects it. The [`Makefile`](./Makefile) holds the **only** default
and exports it; every host script, `docker-compose.yml` and
[`apply_cms_config`](./apply_cms_config) fail when it is unset rather than guess,
because a scenario applied half from one lab and half from another stays
invisible until discovery produces a confusing result. Set it on the command
line, or in `.env` — make reads that file itself, in the one place `SCENARIO` is
resolved, and exports the result, so make and docker compose can never disagree
about which lab is in play. Running `docker compose` by hand therefore needs
`SCENARIO=<name>` in front of it (or in `.env`).

**One scenario runs at a time**: they share `lab-net`, the `172.30.0.0/24`
subnet and the compose project. Switching means `make local-lab-down` first —
`make local-lab-up` refuses while a different scenario is deployed, because
`containerlab destroy` only removes the nodes the handed topology names.

`make scenario-resolve` materialises `scenarios/_base/` + `scenarios/$SCENARIO/`
into `generated/$SCENARIO/scenario/`, the one flat directory the containers mount
and the scripts read; it is a prerequisite of every target that consumes a
scenario. [`docs/30-scenarios/`](./docs/30-scenarios/) covers the mechanism, the
inheritance table and how to add one.

## Devices

The default `wan-and-fabric` scenario; `frr-only` is the FRR rows alone. Each
scenario's own device list is its
`scenarios/<name>/topology.json`.

| Hostname | Mgmt IP | Vendor | platform | login |
|---|---|---|---|---|
| core-rtr-01 … core-rtr-02 | 172.30.0.11–12 | FRRouting | `frr` | frr / frr |
| edge-rtr-01 … edge-rtr-02 | 172.30.0.13–14 | FRRouting | `frr` | frr / frr |
| pe-rtr-01 … pe-rtr-03 | 172.30.0.15–17 | FRRouting | `frr` | frr / frr |
| wan-rtr-01 … wan-rtr-02 | 172.30.0.18–19 | FRRouting | `frr` | frr / frr |
| border-rtr-01 | 172.30.0.20 | FRRouting | `frr` | frr / frr |
| spine-01 … spine-02 | 172.30.0.31–32 | Nokia SR Linux | `srl` | admin / NokiaSrl1! |
| leaf-01 … leaf-03 | 172.30.0.33–35 | Nokia SR Linux | `srl` | admin / NokiaSrl1! |

Each host's `platform` selects the SDK connection plugin used for discovery:
`frr` → `FRRNetmikoPlugin`, `srl` → `SRLinuxNetmikoPlugin` (both ship in
neops-worker-sdk-py under `neops_worker_sdk/connection/plugins/` and auto-register
at worker startup).

## Topology & interfaces

The devices are **really cabled** to each other with containerlab `veth` links —
a small DC fabric (SR Linux spine-leaf) plus an FRR WAN/core/edge — so the wiring
is live: interfaces on connected ports come up **UP**, and **LLDP neighbors are
real** (e.g. `spine-01` sees `leaf-01/02/03`). This is the foundation for
neighbor/topology-aware workflows later.

- **FRR routers** get `lo` + `swpN` ports (Cumulus-style `swp1`, `swp2`, …); `eth0`
  is the management interface. Data ports are real veths; their **descriptions**
  are stored as the Linux interface *alias* (which the FRR plugin reads).
- **SR Linux switches** get `mgmt0` + `ethernet-1/N` ports (containerlab's default
  `7220 IXR-D2L` variant, so many ports exist; the wired/configured ones carry
  descriptions, the rest show admin-disabled — realistic for a switch).
- **Host-facing / edge ports** (leaf→servers, pe→customer CE, border→ISP) have no
  peer device, so they are containerlab **`dummy` links** — a real stub interface
  with a description, no neighbor.

Interface descriptions encode the neighbor, e.g. `leaf-01:e1/1 -> spine-01:e1/1`.
Discovery records each interface into the CMS with its **up/down state and
description** for both vendors.

Mechanism — single source of truth → generated artifacts:

```mermaid
flowchart LR
    base["scenarios/_base/"]
    scen["scenarios/$SCENARIO/"]
    topo["scenarios/$SCENARIO/<br/>topology.json"]
    resolve["make scenario-resolve"]
    resolved["generated/$SCENARIO/scenario/<br/>mounted by the containers"]
    gen["make generate"]
    clab["generated/$SCENARIO/clab/"]
    params["scenarios/$SCENARIO/<br/>workflow-execution-parameters/<br/>(committed)"]

    base --> resolve
    scen --> resolve
    resolve --> resolved
    topo --> gen
    gen --> clab
    gen --> params
```

- `scenarios/<name>/topology.json` is the single source of truth for a scenario:
  per device its `mgmt_ip`, `vendor`, `loopback`, and `interfaces` (each with a
  `to` neighbor). It is the one file a scenario can never inherit from `_base`.
- [`gen_clab_topology`](./gen_clab_topology) (stdlib-only host script, run via
  `make generate`) renders from it:
  - `generated/<scenario>/clab/neops-lab.clab.json` — the containerlab topology
    (nodes, real `veth` links between devices, `dummy` links for stub ports),
  - `generated/<scenario>/clab/frr/<host>.iface` — FRR interface→description list,
  - `generated/<scenario>/clab/srl/<host>.cli` — SR Linux `set / interface …` config,
  - `scenarios/<scenario>/workflow-execution-parameters/discover-params.json` —
    one `/32` discovery target per device. Committed, and asserted byte-for-byte
    by `make test`.
- **FRR**: containerlab runs the custom image `neops-lab-frr:latest` (`kind:
  linux`, adds sshd + `frr/frr`), built by `make build-docker`. The image bakes
  **no** FRR configuration: `frr.conf`, `daemons` and `set-aliases.sh` are bound
  from the resolved scenario into `/lab/`, and
  [`devices/frr/entrypoint.sh`](./devices/frr/entrypoint.sh) installs the first
  two into `/etc/frr/` before FRR starts — refusing to boot if they are absent.
  One image therefore serves every scenario, and a scenario that wants `bgpd`
  ships a `daemons` delta. containerlab creates the `swpN` veths, then a
  containerlab `exec` runs `/lab/set-aliases.sh` **after wiring** to set each
  interface's alias (description); the Kubernetes flavour mounts the same three
  files at the same path from a ConfigMap.
- **SR Linux**: containerlab runs `ghcr.io/nokia/srlinux:26.3` (`kind:
  nokia_srlinux`) and applies the `.cli` as its `startup-config` at boot.

Everything generated lives under `generated/<scenario>/` (git-ignored, including
the containerlab runtime `generated/<scenario>/clab/clab-neops-lab` and the TLS
material containerlab mints there); only the scenario sources, the generators,
and the committed discovery parameter files are tracked.

## Layout

```
scenarios/_base/        # every asset a scenario may override
  workflows/            #   workflow documents (.yaml/.yml/.json) registered by the bootstrap container
  scope/Global/         #   table columns, drill-down and dashboard for apply_cms_config
  devices/frr/          #   frr.conf, daemons, set-aliases.sh — mounted at /lab, not baked
  function_blocks/      #   lab-local function blocks, auto-discovered by the worker
  cms/                  #   oidc-config.json (the web client's OIDC configuration)
                        #   + permissions.json (roles, users and workflow grants)
scenarios/<name>/       # one lab: topology.json + scenario.json + README.md (+ any override)
  workflow-execution-parameters/   # committed discovery inputs, generated from topology.json
resolve_scenario        # materialises _base + <name> -> generated/<name>/scenario
gen_clab_topology       # renders the scenario topology -> generated/<name>/clab/ + params
gen_device_configs      # per-device renderers + topology loading, reused by the others
gen_kind_manifests      # renders the FRR devices -> generated/<name>/kind/lab.yaml
gen_kind_discover_params # discovery targets for the pods: one /32 per Service ClusterIP
generated/<name>/       # git-ignored: scenario/ (resolved), clab/, kind/, clab runtime
clab/probe.clab.yml     # 2-node probe to re-check containerlab deploy works
devices/frr/            # Dockerfile (adds sshd to frrouting/frr) + entrypoint; no FRR config
cms/jwt/                # git-ignored dev RSA keypair (make lab-jwt)
monitor/config.js       # runtime config for the monitor app (webclientOrigin), bind-mounted into it
bootstrap/              # one-shot container that POSTs every workflow document
containerlab            # containerlab launcher (runs ghcr.io/srl-labs/clab via the docker socket)
doctor                  # host preflight (docker, RAM, mount round-trip, subnets, images)
apply_cms_config        # applies the scenario's cms/permissions.json + the Global scope in the CMS
lab_token               # prints a Neops access token for the engine (NEOPS_ENGINE_TOKEN)
run_workflow            # triggers a workflow execution and waits for a terminal state
wait_ready              # blocks until the worker's function block has an online worker
wait_devices            # blocks until every device in the scenario accepts SSH
docker-compose.yml               # every service: control plane + lab_bootstrap + worker (profile)
tests/                  # unit tests for the generators and the scenario overlay
```

One compose file holds the whole control plane; the worker sits behind the
`worker` profile, switched by `COMPOSE_PROFILES` in `.env`. `lab-net` is
`external` to compose — `make lab-net` creates it, containerlab attaches the
devices to it, and the worker joins it to reach them.

The whole repo is bind-mounted **read-only into the worker at `/app/lab`**, which
is why in-container paths keep a `lab/` prefix — `DIR_FUNCTION_BLOCKS:
lab/generated/${SCENARIO}/scenario/function_blocks,neops/fb` resolves inside the
container, and there is no such path on the host. Host-side paths never have one.

## Discovery inputs

`global_discover_network` accepts `subnets`; a single host is a `/32`. For
overlapping ranges the most specific prefix wins (longest prefix match).
Credentials are scoped from most to least specific: the owning subnet's
credentials, then the global list — where an entry may itself be scoped to a
platform, in which case it is tried first for hosts of that platform and
skipped for hosts declared as another one.

Each scenario carries its own set under
`scenarios/<name>/workflow-execution-parameters/`; the first three are generated
by `make generate` and must be committed.

- `discover-params.json`: one `/32` per device with known platforms and platform-scoped credentials.
- `discover-params-autodetect.json`: the same `/32`s without platforms.
- `discover-params-subnet.json`: the management `/24` with subnet-scoped credentials.
- `discover-params-mixed.json`: the `/24` plus `/32` overrides for the SR Linux
  nodes. Hand-written, so it exists only for `wan-and-fabric` — there is nothing
  to mix when every device runs the same NOS.

Override with `DISCOVER_PARAMS`, e.g.
`make discover DISCOVER_PARAMS=scenarios/wan-and-fabric/workflow-execution-parameters/discover-params-autodetect.json`.

## Make targets

The targets come in **three families**, split by what they own. The environment
is the NeOps control plane and is driven by `docker compose` alone; the device
families are driven by `containerlab` or `kubectl` alone and touch no compose
project, no CMS, no engine and no token. A handful of un-prefixed targets are
the operations that need both. `tests/test_target_families.py` enforces that
direction — a device recipe reaching for `docker compose`, `apply_cms_config`,
`lab_token`, `wait_ready` or an engine token is a test failure. The reverse is
convention: nothing stops a `local-env-*` target calling `./containerlab`.

Every target below takes `SCENARIO=<name>` to run against a different scenario;
without it they use `SCENARIO` from `.env`, else the `Makefile`'s default,
`wan-and-fabric`. `make scenario` prints which one is selected and where it came
from.

### Environment — the control plane (`docker compose` only)

| Target | What it does |
|---|---|
| `make local-env-init` | **One-time per environment.** Pulls every image, brings up *only* the CMS (the engine would refuse to start on the placeholder token and fail the whole `up`), mints the CMS API key into `cms_api_key.env`, runs `apply_cms_config`, force-recreates the engine so it loads the key, mints an engine token, brings up the rest of the stack and waits for `lab_bootstrap` to publish the workflow definitions. Chains `lab-env`, `lab-jwt`, `lab-net` and `scenario-resolve`. |
| `make local-env-up` | Start the control plane again later. Prints whether the worker profile is on, then `apply_cms_config` → mint an engine token → `up -d` → wait for `lab_bootstrap` → and, only with the worker profile active, `wait_ready` on the discovery function block. Fails clearly if `cms_api_key.env` is missing. |
| `make local-env-down` | `docker compose down` — keeps the volumes. The devices keep running. |
| `make local-env-prune` | `docker compose down -v` — the true reset, drops the ES + Postgres volumes. It leaves `cms_api_key.env` on disk, and that key is invalid against the new database, so **always follow a prune with `local-env-init`**, never `local-env-up`. |
| `make local-env-logs` | `docker compose logs -f` — every service compose has enabled. |
| `make worker-up` / `worker-down` / `worker-logs` | Run the worker by hand. Naming the service enables its profile, so these work with `COMPOSE_PROFILES` unset. |

The worker is optional and lives behind the `worker` compose profile, switched by
`COMPOSE_PROFILES` in `.env` (the shipped `.env.example` sets it to `worker`).
`make lab-env` never overwrites an existing `.env`, so **an environment created
before the profile existed has no such line and its worker silently stops coming
up** — add it, or use `make worker-up`. `local-env-up` prints `worker: enabled`
or `worker: disabled` on every run.

### Devices — containerlab (`./containerlab` only)

| Target | What it does |
|---|---|
| `make local-lab-up` | Generates the containerlab topology + configs from the scenario's `topology.json`, then `containerlab deploy --reconfigure`s the devices with real links and waits for every device's SSH. Refuses to run while a *different* scenario is deployed. Chains `build-docker-frr`, `lab-net` and `scenario-resolve` — one image built, nothing pulled. |
| `make local-lab-down` | `containerlab destroy --cleanup --keep-mgmt-net` on the scenario the deployed-scenario marker names, then removes the marker. The control plane is untouched; `lab-net` survives, because the worker sits on it. A failed destroy fails the target and keeps the marker. |
| `make local-lab-status` | `containerlab inspect` against the deployed scenario. |

### Devices — Kubernetes (`kubectl` only)

| Target | What it does |
|---|---|
| `make kind-lab-up` | Renders the scenario's **FRR** devices into `generated/$(SCENARIO)/kind/lab.yaml` and runs them as pods in a local KIND cluster, reachable over SSH at `<device>.neops-lab.svc.cluster.local`. Needs no containerlab, no compose stack and no control plane. |
| `make kind-lab-status` / `make kind-lab-down` | Pods and services; the latter deletes the namespace, never the cluster. |

### Operations — across both

| Target | What it does |
|---|---|
| `make discover` | POSTs an execution of the discovery workflow; every device in the scenario **and its interfaces** appears in the CMS. Override `DISCOVER_PARAMS` to exercise explicit hosts, autodetection, or subnet expansion. Devices are keyed by IP (re-running skips existing devices); interfaces are always recorded, so run discovery against a **fresh** CMS to avoid duplicate interface rows. |
| `make apply-cms-config` | Applies the scenario's `cms/permissions.json` (roles, users and their workflow grant profiles), grants the `neops` user the full-permission `lab-admin` role + creates the `Global` scope so the web client can see all entities. Idempotent. Chained into `local-env-init`, `local-env-up` and `discover`. |
| `make lab-grant` | `make lab-grant ROLE=<role> [PROFILE=operator]` — one ad-hoc workflow grant, the same command `apply_cms_config` runs per role. Additive. |
| `make kind-apply-cms-config` | Points the existing `apply_cms_config` at a Kubernetes-deployed CMS through `CMS_EXEC` (reused, not reimplemented). Idempotent. Getting devices into the CMS stays discovery's job. |
| `make kind-discover` | Discovery against the pods, through the same scripts the containerlab flavour uses: publishes the workflow definition with `bootstrap/register.py`, generates one `/32` per device from the Service ClusterIPs with `./gen_kind_discover_params`, waits with `./wait_ready`, executes with `./run_workflow`. Needs a worker image that carries the base function blocks, and the engine reachable at `KIND_ENGINE_URL` — the offline ingress name `http://engine.neops.local` by default, so run `make -C neops-helm config-hosts` once. |

### Scenarios, setup and gates

| Target | What it does |
|---|---|
| `make scenarios` | Lists every scenario with its device count, flavours and summary, read from each `scenarios/<name>/scenario.json`. |
| `make scenario` | Prints the scenario the next target will act on, and says when it came from `.env`. |
| `make scenario-resolve` | Materialises `scenarios/_base/` + `scenarios/$(SCENARIO)/` into `generated/$(SCENARIO)/scenario/` — the flat directory the containers mount and `apply_cms_config` reads. A prerequisite of every target that consumes a scenario, so it is rarely run by hand. |
| `make generate` | Resolves the scenario, then regenerates the containerlab topology, the per-device configs and the committed `scenarios/$(SCENARIO)/workflow-execution-parameters/*.json`. Commit those — `make test` asserts they reproduce byte-for-byte. |
| `make lab-env` | Copies `.env.example` to `.env` if absent, so compose has one. Never overwrites an existing `.env`. |
| `make lab-jwt` | Mints the dev RSA keypair the CMS needs (`cms/jwt/`, created by the target). Idempotent. |
| `make lab-net` | Creates the `lab-net` bridge from `gen_clab_topology.LAB_SUBNET` if it does not exist. It is `external` to compose, which aborts on a missing external network rather than creating one. Chained into `local-env-init`, `local-env-up`, `local-lab-up` and `worker-up`. |
| `make clab-suid` | Sets the SUID bit on the `containerlab` binary so the device targets can deploy without sudo — only for the `CLAB_NATIVE` path. Run once after installing containerlab and again after every upgrade (an upgrade drops the bit). Idempotent; needs sudo only when the bit is missing. Not chained into `local-lab-up`, which must never prompt for a password mid-run. |
| `make build-docker` | Builds the two local-only images: `neops-lab-frr:latest` (scenario-independent — it bakes no FRR config) and `neops-lab-bootstrap:latest`. `build-docker-frr` is the device image and a prerequisite of `local-lab-up` and `kind-lab-up`; `build-docker-bootstrap` is the environment one. `DOCKER_BUILD_FLAGS=--network=host` covers a host whose docker bridge has no DNS. |
| `make test` | `pytest tests` — unit tests for the generators and the scenario overlay, incl. that every scenario still reproduces its committed `workflow-execution-parameters/*.json` byte-for-byte, and that no target strays out of its family. |
| `make lint` / `make format` / `make typeCheck` | ruff / pyrefly over the repo, including the extension-less host scripts. |
| `make py39-check` / `make shell-syntax` | The host scripts import under Python 3.9 (the stock macOS interpreter), and the bash entry points parse. |
| `make check` | All five gates together: lint, typeCheck, test, py39-check, shell-syntax. |

Full reset from scratch:
`make local-lab-down local-env-prune && make local-env-init && make local-lab-up && make discover`.
The first command stops before the prune if the devices did not go down — that
is deliberate, so the deployed-scenario marker survives a failed teardown.

## URLs

- Web client: <http://localhost:8080/>
- Engine UI: <http://localhost:3031>
- CMS admin: <http://localhost:8001/admin/> (login `neops` / `neops`)
- Engine REST: <http://localhost:3030>

Every lab caller carries an engine token (`./lab_token` mints one); how much the
engine gates is `NEOPS_AUTHZ_MODE` on the `workflow_engine` service. Besides
`neops`, the lab declares three personas in the scenario's `cms/permissions.json`
(password = username), which differ only in workflow authority:

| Login | Role | Can |
|---|---|---|
| `author` | `workflow-author` | read and write workflow definitions |
| `operator` | `workflow-operator` | read definitions, run and abort executions |
| `admin` | `workflow-admin` | the above, plus delete definitions and roll back |

Full model, including how the monitor app is handed a token:
[`docs/10-concepts/50-authorization.md`](./docs/10-concepts/50-authorization.md).

## Adding a device

1. Add the device to `scenarios/<name>/topology.json`: a `mgmt_ip` (free IP in
   `172.30.0.0/24`), `vendor` (`frr` or `srl`), `loopback` (`lo` for FRR, `null`
   for SR Linux), and its `interfaces` (each `{ "name", "to" }`; `name` is `swpN`
   for FRR or `ethernet-1/N` for SR Linux; `to` is `"<peer-host>:<peer-iface>"`
   for a real link, or a plain label like `"server web-01"` for a host-facing
   stub port). Add the matching interface on the peer — `make test` asserts
   device-to-device links are symmetric.
2. `make generate SCENARIO=<name>` — rebuilds the containerlab topology (real
   link or `dummy` stub) and the discovery parameter files.
3. `make local-lab-up SCENARIO=<name> && make discover SCENARIO=<name>`.
4. `make test` — the generator tests assert the regenerated parameter files match
   what is committed, so they fail until you commit the regenerated JSON.

## Adding a scenario

1. `mkdir scenarios/<name>`, then write `topology.json`, `scenario.json` (copy
   the shape from an existing one) and `README.md`.
2. Override anything from [`scenarios/_base/`](./scenarios/_base/) by placing a
   file at the same relative path; leave out what you want inherited.
3. `make generate SCENARIO=<name>`, then commit the generated
   `workflow-execution-parameters/*.json`.
4. `make test` — the generator and manifest guards run against every scenario, so
   a new one is covered without writing a new assertion.
