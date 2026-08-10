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

- **Docker** + docker compose.
- **containerlab** (Linux host — it wires real veths via network namespaces).
  Sudo-less operation is required so the make targets can `containerlab deploy`
  without a password:
  ```bash
  sudo usermod -aG clab_admins $USER          # then re-login for the group to apply
  sudo chown root:root "$(command -v containerlab)"
  sudo chmod 4755 "$(command -v containerlab)" # SUID -> -rwsr-xr-x
  ```
  Verify: `ls -l $(command -v containerlab)` shows the `s` bit, and
  `containerlab deploy -t clab/probe.clab.yml` (a 2-node probe) stands up
  without the "requires root privileges" error (`containerlab destroy -t
  clab/probe.clab.yml` to clean up).
- **`openssl`** — `make lab-jwt` mints the dev RSA keypair under `cms/jwt/` that
  the CMS image requires for RS256 JWT issuance. Without it the CMS crashes at
  startup (`token_service check_keys`) and nothing else comes up. It is chained
  into `make local-env-init`, and is idempotent, so you rarely run it directly.
  The keypair is git-ignored: it is a throwaway lab credential, not a secret.
- **`uv`** — only for `make test` / `make lint`; the lab itself needs nothing
  but `python3` (all host scripts are stdlib-only).
- **`cms_api_key.env`** exists (produced by `make local-env-init` — needed once).
- **A workflow-engine image with the large-payload + reference-resolution fixes.**
  Discovery emits a few hundred `Interface` rows in one job result. To run a
  locally-built engine instead of the published `develop` image, set
  `NEOPS_WORKFLOW_ENGINE_IMAGE` (e.g. `export NEOPS_WORKFLOW_ENGINE_IMAGE=neops-workflow-engine:latest`)
  before `make local-lab-up`. Unset, it defaults to the published engine.
  `NEOPS_WEB_CLIENT_IMAGE` and `NEOPS_WORKER_SDK_IMAGE` work the same way — see
  `.env.example`.
- Host resources: the 5 SR Linux nodes are RAM/CPU-hungry (budget a few GB) and
  boot slower than FRR, so the first `make local-lab-up` takes a couple of minutes.

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
apply_cms_config        # seeds the neops role + Global scope in the CMS
run_workflow            # triggers a workflow execution and waits for a terminal state
wait_ready              # blocks until the worker's function block has an online worker
wait_devices            # blocks until every lab device (topology.json) accepts SSH
workflow-execution-parameters/   # generated discovery inputs
docker-compose.yml               # base stack (CMS, engine, monitor app, web client, postgres, ES, redis)
docker-compose.worker.yml        # worker + lab_bootstrap + the lab-net network definition
tests/                  # unit tests for the two generators
```

The base stack + worker compose files are combined via docker compose's
`COMPOSE_FILE` (target-scoped in the `Makefile`); containerlab provisions the
devices onto the `lab-net` that the worker compose defines.

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
| `make lab-jwt` | Mints the dev RSA keypair the CMS needs (`cms/jwt/`). Idempotent; chained into `local-env-init`. |
| `make local-env-init` | Pull + start the base stack, mint the CMS API key, force-recreate the engine to load it, then chain `apply-cms-config`. One-time per env. |
| `make build-docker` | Builds the two local-only images: `neops-lab-frr:latest` and `neops-lab-bootstrap:latest`. A prerequisite of `local-lab-up`. |
| `make local-lab-up` | Generates the containerlab topology + configs from `topology.json`, builds the lab images, brings up the base stack + worker + bootstrap (creating `lab-net`), then `containerlab deploy`s the 15 devices with real links. Waits for workflow registration, the worker's function blocks, and every device's SSH. |
| `make apply-cms-config` | Grants the `neops` user a full-permission role (`lab-admin`, default_permission=7) + creates the `Global` scope so the web client can see all entities. Idempotent. Chained into `local-env-init`. |
| `make local-lab-discover` | POSTs an execution of the discovery workflow; all 15 devices **and their interfaces** appear in the CMS. Override `DISCOVER_PARAMS` to exercise explicit hosts, autodetection, or subnet expansion. Devices are keyed by IP (re-running skips existing devices); interfaces are always recorded, so run discovery against a **fresh** CMS to avoid duplicate interface rows. |
| `make local-lab-logs` | Tails worker + bootstrap logs. |
| `make local-lab-down` | `containerlab destroy --cleanup` (removes devices + runtime dir) then `docker compose down` (preserves volumes). |
| `make local-env-prune` | `docker compose down -v` — the true reset, drops the ES + postgres volumes. |
| `make test` | `pytest tests` — unit tests for the two generators, incl. that they still reproduce the committed `workflow-execution-parameters/*.json`. |
| `make lint` / `make format` / `make typeCheck` / `make check` | ruff / pyrefly over the repo, including the extension-less host scripts. |

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
