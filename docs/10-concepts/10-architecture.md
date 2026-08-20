---
title: Architecture
description: The containers, networks and ports that make up the lab — two compose files, one containerlab topology, and the bridge that joins them.
tags: [concept, architecture]
---

# Architecture

*Everything the lab runs, and how the control plane reaches the devices.*

## Two compose files, combined

The lab is declared in two files:

| File | Declares |
|---|---|
| `docker-compose.yml` | The **base stack**: CMS, workflow engine, monitor app, web client, Postgres, Elasticsearch, Redis, plus a `wait_health` helper |
| `docker-compose.worker.yml` | The **worker overlay**: the `worker`, the one-shot `lab_bootstrap`, and the `lab-net` network definition |

They are combined through docker compose's `COMPOSE_FILE` environment variable, exported only for the lab targets in the `Makefile`:

```make
LAB_COMPOSE_FILES := docker-compose.yml:docker-compose.worker.yml
local-lab-up local-lab-down local-lab-discover local-lab-logs: export COMPOSE_FILE := $(LAB_COMPOSE_FILES)
```

The scoping is deliberate: `local-env-*` targets keep using the base `docker-compose.yml` only, so you can run the control plane without the worker or the devices.

!!! warning "`docker compose` by hand needs the same environment"
    Running `docker compose logs worker` in a plain shell will not find the
    service — the base file does not declare it. Either use the make targets,
    or export the variable yourself:

    ```bash
    export COMPOSE_FILE=docker-compose.yml:docker-compose.worker.yml
    ```

## Services

| Service | Image | Published port | Notes |
|---|---|---|---|
| `cms` | `quay.io/zebbra/neops-cms-free:develop` | `8001` → 8000 | Django CMS + GraphQL. Runs `migrate`, creates the `neops` superuser, builds the ES index, then `runserver`. `REDIS_URL` points it at `redis` |
| `workflow_engine` | `quay.io/zebbra/neops-workflow-engine:develop` | `3030` | Reads the CMS token from `cms_api_key.env` |
| `workflow-engine-client` | same image as the engine | `3031` → 5173 | The **monitor app**, run in dev mode (`npm install && npm run dev`) out of `/app/rest/monitor-app` |
| `web_client` | `quay.io/zebbra/neops-web-client:develop` | `8080` | `FRONTEND_*` env vars are browser-relative, so they point at host ports |
| `worker` | `quay.io/zebbra/neops-worker-sdk:develop` | — | On **both** networks; polls the engine's blackboard and drives the devices |
| `lab_bootstrap` | `neops-lab-bootstrap:latest` (local) | — | One-shot: POSTs every `workflows/*.yaml` to the engine, then exits |
| `postgres` | `postgres:15-alpine` | — | Volume `postgres_data` |
| `elasticsearch` | `docker.elastic.co/elasticsearch/elasticsearch:8.9.2` | — | Volume `elasticsearch`; 2 CPU / 4 GB limits (2 GB heap) |
| `redis` | `redis:7-alpine` | — | The CMS's channel layer (GraphQL subscriptions), cache and Celery broker |
| `wait_health` | `busybox` | — | Depends on CMS + engine + web client being *healthy*, so `up -d` blocks until they are |

The three overridable images (`workflow_engine`/`workflow-engine-client`, `web_client`, `worker`) each read a `NEOPS_*_IMAGE` variable and set `pull_policy: missing` — see [Images](../20-operations/20-images.md).

## Networks

```mermaid
graph LR
  subgraph default["compose default network"]
    cms[cms :8000]
    engine[workflow_engine :3030]
    monitor[workflow-engine-client :5173]
    wc[web_client :8080]
    boot[lab_bootstrap]
    pg[(postgres)]
    es[(elasticsearch)]
  end
  subgraph labnet["lab-net — 172.30.0.0/24"]
    dev1["core-rtr-01 … border-rtr-01<br/>172.30.0.11–20"]
    dev2["spine-01 … leaf-03<br/>172.30.0.31–35"]
  end
  worker[worker]
  default --- worker
  worker --- labnet
  worker -- "URL_BLACKBOARD<br/>http://workflow_engine:3030" --> engine
  worker -- "SSH 22" --> dev1
  worker -- "SSH 22" --> dev2
  boot -- "POST /workflow-definition/publish" --> engine
```

`lab-net` is declared by `docker-compose.worker.yml` with an explicit IPAM subnet of `172.30.0.0/24`, and containerlab's topology sets `mgmt.network: lab-net` with the same subnet. That is the join: compose creates the bridge, containerlab attaches the devices to it at their fixed `mgmt-ipv4`, and the worker — a member of both networks — can reach the engine by service name *and* the devices by IP.

!!! note "Every project network has a fixed subnet"
    The compose `default` network is pinned to `172.30.1.0/24`
    (`docker-compose.yml`). docker hands auto-allocated networks the next free
    `/16` from its `172.16/12` pool, and on a host with many projects that can
    be `172.30.0.0/16` — which blocks `lab-net`'s fixed `/24` with "Pool
    overlaps". With every subnet pinned, the allocator never competes with the
    lab. The subnet is single-sourced in `gen_clab_topology` (`LAB_SUBNET`)
    and cross-checked by `tests/test_host_invariants.py`; `make doctor` names
    any existing network overlapping `172.30.0.0/23`.

!!! note "Ordering matters"
    `make local-lab-up` runs `docker compose up -d` **before**
    `./containerlab deploy`, because compose is what creates `lab-net`.
    Deploying containerlab first would fail to find the network.

## The devices

| Hostname | Mgmt IP | Vendor | `vendor` in `topology.json` | Login |
|---|---|---|---|---|
| `core-rtr-01` … `core-rtr-02` | 172.30.0.11–12 | FRRouting | `frr` | `frr` / `frr` |
| `edge-rtr-01` … `edge-rtr-02` | 172.30.0.13–14 | FRRouting | `frr` | `frr` / `frr` |
| `pe-rtr-01` … `pe-rtr-03` | 172.30.0.15–17 | FRRouting | `frr` | `frr` / `frr` |
| `wan-rtr-01` … `wan-rtr-02` | 172.30.0.18–19 | FRRouting | `frr` | `frr` / `frr` |
| `border-rtr-01` | 172.30.0.20 | FRRouting | `frr` | `frr` / `frr` |
| `spine-01` … `spine-02` | 172.30.0.31–32 | Nokia SR Linux | `srl` | `admin` / `NokiaSrl1!` |
| `leaf-01` … `leaf-03` | 172.30.0.33–35 | Nokia SR Linux | `srl` | `admin` / `NokiaSrl1!` |

Those credentials are lab-only: they reach throwaway containers on a local bridge and are published in this documentation on purpose.

The `vendor` value doubles as the discovery **platform** short name, which is what selects the SDK connection plugin: `frr` → `FRRNetmikoPlugin`, `srl` → `SRLinuxNetmikoPlugin`. Both ship in `neops-worker-sdk-py` under `neops_worker_sdk/connection/plugins/` and auto-register at worker startup.

## The wiring

The devices are cabled to each other with containerlab `veth` links — a Nokia SR Linux spine-leaf fabric plus an FRR WAN/core/edge domain:

```mermaid
graph TD
  subgraph fabric["SR Linux fabric"]
    sp1[spine-01] --- lf1[leaf-01]
    sp1 --- lf2[leaf-02]
    sp1 --- lf3[leaf-03]
    sp2[spine-02] --- lf1
    sp2 --- lf2
    sp2 --- lf3
  end
  subgraph wan["FRR WAN / core / edge"]
    c1[core-rtr-01] --- c2[core-rtr-02]
    c1 --- e1[edge-rtr-01]
    c1 --- e2[edge-rtr-02]
    c2 --- e1
    c2 --- e2
    e1 --- p1[pe-rtr-01]
    e1 --- p2[pe-rtr-02]
    e2 --- p3[pe-rtr-03]
    c1 --- w1[wan-rtr-01]
    c2 --- w2[wan-rtr-02]
    w1 --- b1[border-rtr-01]
    w2 --- b1
  end
```

Ports that face something outside the lab — leaf→server, pe→customer CE, border→ISP — have no peer device, so they become containerlab **`dummy` links**: a real stub interface with a description and no neighbour.

Because the links are real, interface state is real: connected ports come up **UP** and LLDP neighbours resolve (`spine-01` sees `leaf-01/02/03`). That is what makes the lab a usable substrate for neighbour- and topology-aware work.

!!! note "The two fabrics are not interconnected"
    The FRR domain and the SR Linux fabric are separate islands in the data
    plane; they meet only on the shared `lab-net` management network. Nothing
    in the lab routes between them today.

## What is authored vs generated

| Tracked in git | Generated (git-ignored) |
|---|---|
| `topology.json`, `gen_clab_topology`, `gen_device_configs` | `generated/neops-lab.clab.json` |
| `devices/frr/` (Dockerfile, `frr.conf`, `daemons`, `entrypoint.sh`, `set-aliases.sh`) | `generated/frr/<host>.iface` |
| `workflows/`, `function_blocks/`, `bootstrap/`, `scope/Global/`, `cms/oidc-config.json` | `generated/srl/<host>.cli` |
| `workflow-execution-parameters/*.json` | `generated/clab-neops-lab/` (containerlab runtime, incl. minted TLS keys) |
| the compose files, the `Makefile`, the host scripts | `cms/jwt/`, `cms_api_key.env` |

Everything under `generated/` is rebuilt from `topology.json` on every `make local-lab-up`. Never commit it — containerlab mints TLS private keys in there.
