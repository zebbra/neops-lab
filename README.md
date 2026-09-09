# neops-lab — Simple Lab

A turn-key local, multi-vendor lab: **10 FRRouting routers + 5 Nokia SR Linux
switches** (15 devices) with **real point-to-point wiring**, provisioned by
[containerlab](https://containerlab.dev). The control plane — CMS + workflow
engine + a worker that runs the `global_discover_network` function block +
a one-shot bootstrap container — runs on docker-compose; the devices attach to
the same `lab-net` bridge (172.30.0.0/24) at fixed management IPs, so the worker
reaches them at those IPs.

The control plane runs from **published images** on `quay.io/zebbra` (CMS,
workflow engine, web client) — except the **worker**, whose published `develop`
tag is currently unusable and must be built locally; see
[Prerequisites](#prerequisites). This repo owns the lab itself: the topology,
the device configs, the workflow, the bootstrap sequencing and the two small
helper images.

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
- **A locally-built worker image — the published `develop` tag does not work.**
  `quay.io/zebbra/neops-worker-sdk:develop` is built from `neops-worker-sdk-py`'s
  `develop`, which carries no `neops/fb` and no `README.md` in the image, so the
  container dies at start with `OSError: Readme file does not exist: README.md`
  and would register no function blocks even if it started. The discovery block
  `fb.base.neops.io/global_discover_network:0.1.0` and the `COPY ./neops` that
  ships it live on the SDK's `feature/technopark` branch (open PR
  [zebbra/neops-worker-sdk-py#127](https://github.com/zebbra/neops-worker-sdk-py/pull/127)).
  Until that merges and CI republishes the tag, build it yourself:

  ```bash
  git -C ../neops-worker-sdk-py switch feature/technopark
  make -C ../neops-worker-sdk-py build-docker      # -> neops-worker-sdk:latest
  echo 'NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest' >> .env
  ```

  Check what you got before bringing the lab up — the image must carry the
  block, not just build:

  ```bash
  docker run --rm --entrypoint sh neops-worker-sdk:latest -c 'ls neops/fb/base/global'
  ```

  Without this the worker container exits, `local-lab-up` burns its full
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
- **Host resources**: the 5 SR Linux nodes want ≈1.5–2 GB each; with
  Elasticsearch and the control plane the lab needs roughly **14–16 GB** for
  containers. On macOS that is the Docker Desktop **VM** budget (Settings →
  Resources → Memory; the 8 GB default is too small). On Apple Silicon enable
  *Use Rosetta for x86_64/amd64 emulation* — the `quay.io/zebbra` images are
  amd64-only. The first `make local-lab-up` takes a couple of minutes; on a
  slow host raise the wait budgets
  (`make local-lab-up WAIT_READY_TIMEOUT=600 WAIT_DEVICES_TIMEOUT=600`).

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
cms/                    # oidc-config.json + permissions.json + the git-ignored jwt/ keypair (make lab-jwt)
monitor/config.js       # runtime config for the monitor app (webclientOrigin), bind-mounted into it
scope/Global/           # table columns, drill-down and dashboard applied by apply_cms_config
workflows/              # workflow YAMLs registered by the bootstrap container
function_blocks/        # lab-local function blocks, auto-discovered by the worker
bootstrap/              # one-shot container that POSTs every workflow YAML
containerlab            # containerlab launcher (runs ghcr.io/srl-labs/clab via the docker socket)
doctor                  # host preflight (docker, RAM, mount round-trip, subnets, images)
apply_cms_config        # applies cms/permissions.json + the Global scope in the CMS
lab_token               # prints a Neops access token for the engine (NEOPS_ENGINE_TOKEN)
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
| `make clab-suid` | Sets the SUID bit on the `containerlab` binary so the lab targets can deploy without sudo. Run once after installing containerlab and again after every upgrade (an upgrade drops the bit). Idempotent; needs sudo only when the bit is missing. Not chained into `local-lab-up`, which must never prompt for a password mid-run. |
| `make lab-jwt` | Mints the dev RSA keypair the CMS needs (`cms/jwt/`). Idempotent; chained into `local-env-init`. |
| `make local-env-init` | Pull + start the base stack, mint the CMS API key, force-recreate the engine to load it, then chain `apply-cms-config`. One-time per env. |
| `make build-docker` | Builds the two local-only images: `neops-lab-frr:latest` and `neops-lab-bootstrap:latest`. A prerequisite of `local-lab-up`. |
| `make local-lab-up` | Generates the containerlab topology + configs from `topology.json`, builds the lab images, brings up the base stack + worker + bootstrap (creating `lab-net`), then `containerlab deploy`s the 15 devices with real links. Waits for workflow registration, the worker's function blocks, and every device's SSH. |
| `make apply-cms-config` | Applies `cms/permissions.json` (roles, users and their workflow grant profiles) + creates the `Global` scope so the web client can see all entities. Idempotent. Chained into `local-env-init`. |
| `make lab-grant` | `make lab-grant ROLE=<role> [PROFILE=operator]` — one ad-hoc workflow grant, the same command `apply_cms_config` runs per role. Additive. |
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

The engine runs `NEOPS_AUTHZ_MODE=enforce`, so every call to it carries a token.
Besides `neops`, the lab declares three personas in `cms/permissions.json`
(password = username), which differ only in workflow authority:

| Login | Role | Can |
|---|---|---|
| `author` | `workflow-author` | read and write workflow definitions |
| `operator` | `workflow-operator` | read definitions, run and abort executions |
| `admin` | `workflow-admin` | the above, plus delete definitions and roll back |

Full model, including how the monitor app is handed a token:
[`docs/10-concepts/50-authorization.md`](./docs/10-concepts/50-authorization.md).

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
