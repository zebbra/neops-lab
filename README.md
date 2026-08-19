# neops-lab — Simple Lab

A turn-key local, multi-vendor lab: **10 FRRouting routers + 5 Nokia SR Linux
switches** (15 devices) with **real point-to-point wiring**, provisioned by
[containerlab](https://containerlab.dev). The control plane — CMS + workflow
engine + a worker that runs the `global_discover_network` function block +
a one-shot bootstrap container — runs on docker-compose; the devices attach to
the same `lab-net` bridge (172.30.0.0/24) at fixed management IPs, so the worker
reaches them at those IPs.

Everything the control plane runs comes from **published images** on
`quay.io/zebbra` (CMS, workflow engine, web client, worker SDK). This repo owns
the lab itself: the topology, the device configs, the workflow, the bootstrap
sequencing and the two small helper images.

End state: run a make target, click Run in the engine UI (or use the matching
make target), and **15 `Device` rows** (FRR `vendor=FRRouting`, Nokia
`vendor=Nokia`) appear in the CMS — each with its interfaces recorded. The
discovery function block records each device **and its interfaces** in one pass:
it connects to every host via the matching connection plugin, reads facts +
interfaces, and writes both `Device` and `Interface` rows to the CMS.

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

Supported hosts: **Linux** (native containerlab) and **macOS** (Docker Desktop or
OrbStack; containerlab runs in a container). Run the preflight first — it checks
everything below and prints the fix next to each failure:

```bash
make doctor
```

- **Docker** + `docker compose` **≥ 2.20** (`docker compose wait` is used).
  `quay.io/zebbra` is private: `docker login quay.io`.
- **containerlab**, through the repo's `./containerlab` launcher — the Makefile
  and every command in the docs use it, so it is one command on both OSes:
  - **Linux:** install containerlab natively
    ([containerlab.dev/install](https://containerlab.dev/install/)); `./containerlab`
    exec's it unchanged. Sudo-less operation is required so the make targets can
    deploy without a password:
    ```bash
    sudo usermod -aG clab_admins $USER          # then re-login for the group to apply
    sudo chown root:root "$(command -v containerlab)"
    sudo chmod 4755 "$(command -v containerlab)" # SUID -> -rwsr-xr-x
    ```
  - **macOS:** nothing to install. There is no containerlab binary for macOS
    (it needs Linux netlink + network namespaces); `./containerlab` runs the
    official `ghcr.io/srl-labs/clab` image privileged inside the Docker Desktop
    / OrbStack Linux VM, which is how containerlab documents running there.
    Pin a different version with `CLAB_IMAGE=ghcr.io/srl-labs/clab:<version>`.
  - Verify either way with the 2-node probe:
    `./containerlab deploy -t clab/probe.clab.yml` stands up without a
    "requires root privileges" error; `./containerlab destroy -t clab/probe.clab.yml --cleanup`.
- **`openssl`** — `make lab-jwt` mints the dev RSA keypair under `cms/jwt/` that
  the CMS image requires for RS256 JWT issuance. Without it the CMS crashes at
  startup (`token_service check_keys`) and nothing else comes up. Chained into
  `make local-env-init`, idempotent. Both OpenSSL 3 and the LibreSSL a stock
  macOS ships work. The keypair is git-ignored: a throwaway lab credential.
- **`python3`** ≥ 3.9 — the lab itself needs nothing else (all host scripts are
  stdlib-only and import under the `/usr/bin/python3` a stock macOS ships).
- **`uv`** — only for `make test` / `make lint` / `make check` and the docs.
- **`cms_api_key.env`** exists (produced by `make local-env-init` — needed once).
- **Images that can run the lab** — see [Image compatibility](#image-compatibility)
  below; `make images-check` verifies the configured ones.
- **Host resources.** The 5 SR Linux nodes are RAM/CPU-hungry (≈1.5–2 GB
  each) and boot slower than FRR; with Elasticsearch and the control plane the
  full lab wants roughly **14–16 GB** for containers. On macOS that is the
  Docker Desktop **VM** budget (Settings → Resources → Memory — the 8 GB
  default cannot hold the lab; `make doctor` checks). The first
  `make local-lab-up` takes a couple of minutes.

### macOS notes

- **Apple Silicon:** the four `quay.io/zebbra` images are amd64-only and run
  under Rosetta — turn on *Use Rosetta for x86_64/amd64 emulation* in Docker
  Desktop (Settings → General); without it they run under QEMU and are much
  slower. containerlab, FRR and SR Linux are native arm64.
- **File sharing:** the repo must live under a Docker Desktop shared path
  (`/Users`, `/Volumes`, `/private`, `/tmp` by default) and its path must not
  contain spaces — container-mode containerlab bind-mounts the checkout at the
  same absolute path.
- **No route from the Mac to `lab-net`** (`172.30.0.0/24`): the make targets
  already poll device readiness from inside the worker, and the docs never ask
  you to reach a device from the host. Use `docker exec <node>` / `docker logs
  <node>` (bare names — the topology sets `prefix: ""`); the `/etc/hosts` and
  `ssh_config.d` entries containerlab writes stay inside the ephemeral clab
  container.
- **Slow first run?** Raise the wait budgets instead of removing the waits:
  `make local-lab-up WAIT_READY_TIMEOUT=600 WAIT_DEVICES_TIMEOUT=600`.

## Image compatibility

The lab is a consumer of published images, and it needs specific features from
two of them. `make images-check` tells you whether the images you are
configured to run carry them; the defaults are chosen accordingly.

| Image | Default | Why |
|---|---|---|
| Workflow engine | `quay.io/zebbra/neops-workflow-engine:0.42.2-beta.3` (**pinned**) | Discovery emits a few hundred `Interface` rows in one job result — the engine needs the raised per-route body limits (otherwise **413**). The lab registers workflows through `POST /workflow-definition/publish`; older engines get the legacy route as a fallback. `0.42.2-beta.3` is the first published tag with both, and quay's `develop` tag has lagged the branch by weeks. |
| Worker | `quay.io/zebbra/neops-worker-sdk:develop` | **No published tag runs the lab today** (August 2026): `fb.base.neops.io/global_discover_network` is not yet in a released image, and the current `develop` image cannot start. Build one from a checkout that has it — `make build-worker-image SDK_DIR=../neops-worker-sdk-py` — and run with `NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest`. |
| CMS, web client | `…:develop` | Work as published. |

Override any of them with `NEOPS_CMS_IMAGE`, `NEOPS_WORKFLOW_ENGINE_IMAGE`,
`NEOPS_WEB_CLIENT_IMAGE`, `NEOPS_WORKER_SDK_IMAGE` (see `.env.example`); every
service uses `pull_policy: missing`, so a local tag already present is used
without a registry call.

## Devices

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

- `topology.json` is the single source of truth: per device its `mgmt_ip`,
  `vendor`, `loopback`, and `interfaces` (each with a `to` neighbor).
- `gen_clab_topology` (stdlib-only host script) renders from it:
  - `generated/neops-lab.clab.json` — the containerlab topology (nodes, real
    `veth` links between devices, `dummy` links for stub ports),
  - `generated/frr/<host>.iface` — FRR interface→description list,
  - `generated/srl/<host>.cli` — SR Linux `set / interface …` config,
  - `workflow-execution-parameters/discover-params.json` — the 15 discovery targets (one `/32` per device).
- **FRR**: containerlab runs the custom image `neops-lab-frr:latest` (`kind:
  linux`, adds sshd + `frr/frr`), built by `make build-docker`. containerlab
  creates the `swpN` veths; a containerlab `exec` runs
  `devices/frr/set-aliases.sh` **after wiring** to set each interface's alias
  (description).
- **SR Linux**: containerlab runs `ghcr.io/nokia/srlinux:26.3` (`kind:
  nokia_srlinux`) and applies the `.cli` as its `startup-config` at boot.

Everything generated lives under `generated/` (git-ignored, including the
containerlab runtime and the TLS material containerlab mints there); only
`topology.json`, the generator, and the committed discovery parameter files are
tracked.

## Layout

```
topology.json           # single source of truth: mgmt_ip + interfaces per device
gen_clab_topology       # renders topology.json -> generated/ + discover-params.json
gen_device_configs      # per-device renderers, reused by gen_clab_topology
generated/              # git-ignored: clab.json, frr/*.iface, srl/*.cli, clab runtime
clab/probe.clab.yml     # 2-node probe to re-check containerlab deploy works
devices/frr/            # Dockerfile (adds sshd to frrouting/frr) + entrypoint + set-aliases.sh
cms/                    # oidc-config.json + the git-ignored jwt/ keypair (make lab-jwt)
scope/Global/           # table columns, drill-down and dashboard applied by apply_cms_config
workflows/              # workflow YAMLs registered by the bootstrap container
function_blocks/        # lab-local function blocks, auto-discovered by the worker
bootstrap/              # one-shot container that POSTs every workflow YAML
containerlab            # containerlab launcher: native binary on Linux, container mode on macOS
doctor                  # host preflight (docker/compose/RAM/ports/subnet/containerlab/python/quay)
apply_cms_config        # seeds the neops role + Global scope in the CMS
run_workflow            # triggers a workflow execution and waits for a terminal state
wait_ready              # blocks until the worker's function block has an online worker
wait_devices            # blocks until every lab device (topology.json) accepts SSH
workflow-execution-parameters/   # generated discovery inputs
docker-compose.yml               # base stack (CMS, engine, monitor app, web client, postgres, ES, redis)
docker-compose.worker.yml        # worker + lab_bootstrap; attaches to the (external) lab-net network
tests/                  # unit tests for the two generators
```

The base stack + worker compose files are combined via docker compose's
`COMPOSE_FILE` (target-scoped in the `Makefile`). The `lab-net` bridge
(`172.30.0.0/24`) is created by the Makefile (`make lab-net`, a prerequisite of
every `*-up` target) *before* the first `docker compose up` and is `external`
to compose — on a host with many docker networks, letting compose create it
concurrently with its auto-subnetted networks can collide ("Pool overlaps").
containerlab provisions the devices onto it.

The whole repo is bind-mounted **read-only into the worker at `/app/lab`**, which
is why in-container paths keep a `lab/` prefix (`DIR_FUNCTION_BLOCKS:
lab/function_blocks,neops/fb`, `docker compose exec worker python3
lab/wait_devices`). Host-side paths never have one.

## Discovery inputs

`global_discover_network` accepts `subnets`; a single host is a `/32`. For
overlapping ranges the most specific prefix wins (longest prefix match).
Credentials are scoped from most to least specific: the owning subnet's
credentials, then the global list — where an entry may itself be scoped to a
platform, in which case it is tried first for hosts of that platform and
skipped for hosts declared as another one.

- `discover-params.json`: 15 `/32` subnets with known platforms and platform-scoped credentials.
- `discover-params-autodetect.json`: the same `/32`s without platforms.
- `discover-params-subnet.json`: the management `/24` with subnet-scoped credentials.
- `discover-params-mixed.json`: the `/24` plus `/32` overrides for the SR Linux nodes.

## Make targets

| Target | What it does |
|---|---|
| `make doctor` | Preflight: docker/compose versions, VM RAM, amd64 emulation, repo path/mount, containerlab mode, python/openssl, free ports, `lab-net` subnet overlap, quay access. Read-only; prints the fix per failure. |
| `make images-check` | Verifies the configured worker image carries `/app/neops/fb` and can start, and the engine has the publish API + raised body limits — without deploying anything. |
| `make build-worker-image` | Builds `neops-worker-sdk:latest` from `SDK_DIR` (default `../neops-worker-sdk-py`) for `NEOPS_WORKER_SDK_IMAGE`. Native arch (arm64 on Apple Silicon). |
| `make lab-jwt` | Mints the dev RSA keypair the CMS needs (`cms/jwt/`). Idempotent; chained into `local-env-init`. |
| `make lab-net` | Creates the `lab-net` docker network (`172.30.0.0/24`) if absent, refuses one with a different subnet. Prerequisite of every `*-up` target. |
| `make local-env-init` | Pull + start the base stack, mint the CMS API key, force-recreate the engine to load it, then chain `apply-cms-config`. One-time per env. |
| `make build-docker` | Builds the two local-only images: `neops-lab-frr:latest` and `neops-lab-bootstrap:latest`. A prerequisite of `local-lab-up`. |
| `make local-lab-up` | Generates the containerlab topology + configs from `topology.json`, builds the lab images, refreshes the worker image, brings up the base stack + worker + bootstrap on `lab-net`, then `./containerlab deploy --reconfigure`s the 15 devices with real links (re-runnable). Waits for workflow registration, the worker's function blocks, and every device's SSH (`WAIT_READY_TIMEOUT`, `WAIT_DEVICES_TIMEOUT`). |
| `make apply-cms-config` | Grants the `neops` user a full-permission role (`lab-admin`, default_permission=7) + creates the `Global` scope so the web client can see all entities. Idempotent. Chained into `local-env-init`. |
| `make local-lab-discover` | POSTs an execution of the discovery workflow; all 15 devices **and their interfaces** appear in the CMS. Override `DISCOVER_PARAMS` to exercise explicit hosts, autodetection, or subnet expansion. Devices are keyed by IP (re-running skips existing devices); interfaces are always recorded, so run discovery against a **fresh** CMS to avoid duplicate interface rows. |
| `make local-lab-logs` | Tails worker + bootstrap logs. |
| `make local-lab-down` | `./containerlab destroy --cleanup` (removes devices + runtime dir), `docker compose down` (preserves volumes), removes `lab-net`. |
| `make local-env-prune` | `docker compose down -v` — the true reset, drops the ES + postgres volumes and `lab-net`. |
| `make test` | `pytest tests` — unit tests for the two generators, incl. that they still reproduce the committed `workflow-execution-parameters/*.json`. |
| `make lint` / `make format` / `make typeCheck` / `make check` | ruff / pyrefly over the repo, including the extension-less host scripts; `check` also runs `shellcheck-syntax` (bash -n) and `py39-check` (the host scripts import under Python 3.9). |

Full reset from scratch:
`make local-lab-down local-env-prune && make local-env-init && make local-lab-up && make local-lab-discover`.

## URLs

- Web client: <http://localhost:8080/>
- Engine UI: <http://localhost:3031>
- CMS admin: <http://localhost:8001/admin/> (login `neops` / `neops`)
- Engine REST: <http://localhost:3030>

## Adding a device

1. Add the device to `topology.json`: a `mgmt_ip` (free IP in `172.30.0.0/24`),
   `vendor` (`frr` or `srl`), `loopback` (`lo` for FRR, `null` for SR Linux), and
   its `interfaces` (each `{ "name", "to" }`; `name` is `swpN` for FRR or
   `ethernet-1/N` for SR Linux; `to` is `"<peer-host>:<peer-iface>"` for a real
   link, or a plain label like `"server web-01"` for a host-facing stub port).
2. `make local-lab-up && make local-lab-discover` — the generator rebuilds the
   containerlab topology (real link or `dummy` stub, credentials, and
   `discover-params.json`) from `topology.json` automatically.
3. `make test` — the generator tests assert the regenerated parameter files match
   what is committed, so they fail until you commit the regenerated JSON.
