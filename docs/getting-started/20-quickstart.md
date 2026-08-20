---
title: Quickstart
description: The four commands that take a clean checkout to a running lab, what each one does, and what it blocks on.
tags: [tutorial]
---

# Quickstart

*Four commands. The first two set up the control plane, the third builds the network, the fourth populates the CMS.*

!!! warning "Do not run this casually"
    `make local-lab-up` builds two images, pulls the whole NeOps stack and
    deploys 15 device containers. The SR Linux nodes alone want several GB of
    RAM, and the first run takes a couple of minutes. Make sure you have been
    through [Prerequisites](10-prerequisites.md) — `make doctor` checks the
    host first.

## 1. Mint the CMS keypair

```bash
make lab-jwt
```

Writes `cms/jwt/{private,public}.pem` with `openssl genpkey` if they are not already there. The CMS mounts them read-only and refuses to start without them. Idempotent — an existing keypair is left alone.

You rarely run this directly: `local-env-init` depends on it.

## 2. Bring up the control plane

```bash
make local-env-init
```

This is the one-time-per-environment step. In order, it:

1. `touch cms_api_key.env` — the engine's `env_file` must exist before compose reads it.
2. `docker compose pull --policy always` then `docker compose up -d` — the base stack (`docker-compose.yml`): CMS, workflow engine, monitor app, web client, Postgres, Elasticsearch, Redis (the CMS's channel layer and cache). A `wait_health` service makes `up -d` block until CMS, engine and web client report healthy.
3. Resolves the `neops` user's id, mints a CMS API key via `manage.py generate_api_key` and writes it into `cms_api_key.env` (an empty key fails here, not later).
4. Runs `./apply_cms_config` — grants the `neops` user a full-permission role (`lab-admin`, `default_permission=7`) and configures the `Global` scope's columns, drill-down and dashboard.
5. `docker compose up -d --force-recreate workflow_engine` — `env_file` changes do not trigger a recreate on their own, so the engine is restarted to pick up the new token.

!!! info "Why the CMS config is applied *before* the engine restart"
    The CMS caches each user's accessible scopes in memory for 10 minutes. If
    the engine queries the CMS as `neops` before the grant lands, that stale
    (empty) cache hides the `Global` scope from the web client for up to ten
    minutes — the classic "scope not available when first used" report.
    Granting first means the first `neops` query caches the grant.

## 3. Build the network

```bash
make local-lab-up
```

The long one. It depends on `build-docker`, then:

1. **`./gen_clab_topology`** — renders `generated/neops-lab.clab.json`, the per-device FRR/SR&nbsp;Linux configs, and three of the four discovery parameter files from [`topology.json`](../10-concepts/20-topology.md).
2. **`docker compose pull --policy always worker`** — refreshes the worker image (the base-stack pulls never see it).
3. **`docker compose up -d`** with the worker overlay — adds the `worker` and the one-shot `lab_bootstrap` containers and creates the `lab-net` bridge (`172.30.0.0/24`) that containerlab attaches the devices to.
4. **`docker compose wait lab_bootstrap`** — blocks until the one-shot container that publishes every `workflows/*.yaml` to the engine has *exited*, and propagates its exit code.
5. **`./containerlab deploy --reconfigure`** — the 15 devices with real point-to-point links. Deployed early on purpose: SR Linux boots slowly, so it overlaps with the waits below; `--reconfigure` redeploys an existing lab, so the target is re-runnable.
6. **`./wait_ready fb.base.neops.io/global_discover_network:0.1.0`** — the worker registers its function blocks with the engine *asynchronously* after its container starts; this polls the engine's per-function-block worker registry until an online worker exists (`WAIT_READY_TIMEOUT`, default 180 s).
7. **`docker compose exec -T worker python3 lab/wait_devices`** — polls TCP 22 on every device's management IP, **from inside the lab network** (`WAIT_DEVICES_TIMEOUT`, default 240 s).

Each of those waits exists because of a real, reproduced failure. See [Troubleshooting](../20-operations/40-troubleshooting.md) for the symptom each one prevents, and [The `/app/lab` mount](../10-concepts/40-container-paths.md) for why step 7 has a `lab/` prefix that host commands do not.

When it finishes you get a banner:

```text
Lab is up (containerlab: 10 FRR + 5 Nokia SR Linux, real links).
  Web client:   http://localhost:8080/
  Engine UI:    http://localhost:3031
  Engine API:   http://localhost:3030/
  CMS admin:    http://localhost:8001/admin/ (neops / neops)
  CMS GraphQL:  http://localhost:8001/graphql
```

## 4. Populate the CMS

```bash
make local-lab-discover
```

Runs the discovery workflow and waits for a terminal state. Covered in detail on the [next page](30-first-discovery.md).

## Where to look

| URL | What you get |
|---|---|
| <http://localhost:8080/> | Web client — entity browser; the devices land here after step 4 |
| <http://localhost:3031> | Monitor app — workflow definitions and live execution monitoring |
| <http://localhost:3030> | Workflow engine REST API |
| <http://localhost:8001/admin/> | CMS Django admin — log in as `neops` / `neops` |
| <http://localhost:8001/graphql> | CMS GraphQL API |

## Shutting down

```bash
make local-lab-down     # destroy the devices, stop the stack, KEEP the volumes
make local-env-prune    # docker compose down -v — the true reset, drops ES + Postgres
```

Full reset from scratch:

```bash
make local-lab-down local-env-prune
make local-env-init && make local-lab-up && make local-lab-discover
```

## Next

[Your first discovery :material-arrow-right:](30-first-discovery.md)
