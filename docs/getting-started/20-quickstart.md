---
title: Quickstart
description: The three commands that take a clean checkout to a populated CMS, what each one does, and what it blocks on.
tags: [tutorial]
---

# Quickstart

*Three commands. The first brings up the control plane, the second builds the network, the third populates the CMS. The first two are independent of each other and can run in either order.*

!!! warning "Do not run this casually"
    `make local-env-init` pulls the whole NeOps stack; `make local-lab-up`
    builds the FRR image and deploys the scenario's device containers — 15 of
    them by default. The SR Linux nodes alone want several GB of RAM, and the
    first run takes a couple of minutes. Make sure you have been through
    [Prerequisites](10-prerequisites.md) — `make doctor` checks the host first.

!!! tip "Which network am I bringing up?"
    The default scenario, `wan-and-fabric`. Every command on this page accepts
    `SCENARIO=<name>` to run a different one, and a checkout that always runs
    one lab can put `SCENARIO=frr-only` in `.env` instead — make reads that file
    too, so the generators and the containers cannot disagree. `make scenarios`
    lists what is available, `make scenario` says which is selected, and
    [Scenarios](../30-scenarios/index.md) explains the mechanism. Only one
    scenario runs at a time; they share `lab-net` and the compose project.

!!! info "Two lifecycles, not one"
    `local-env-*` owns the control plane and drives `docker compose` alone.
    `local-lab-*` owns the devices and drives `containerlab` alone. Neither
    touches the other, so they come up in either order and either can be torn
    down on its own. `make discover` is the step that joins them.

## 1. Bring up the control plane

```bash
make local-env-init
```

This is the one-time-per-environment step. It chains `lab-env` (copy
`.env.example` if there is no `.env`), `lab-jwt` (mint the RSA keypair the CMS
refuses to start without), `lab-net` (create the external bridge) and
`scenario-resolve`. Then, in order:

1. `touch cms_api_key.env` — the engine's `env_file` must exist before compose reads it.
2. `docker compose pull --policy always --ignore-pull-failures` — refresh every published image. The ignore flag is what lets a locally-built `NEOPS_*_IMAGE` override, which has no registry to pull from, warn instead of aborting.
3. `docker compose up -d --wait cms` — **only** the CMS and the datastores it depends on. The engine reads `NEOPS_CMS_TOKEN` from `cms_api_key.env`, which at this point is either empty (first run) or holds the previous key (a re-init — `touch` does not truncate). Started now it would boot on the built-in `unsafe` placeholder or on a key the new database never issued, refuse to start, and fail the whole `up` before the fresh key it was waiting for could be minted.
4. Resolves the `neops` user's pk, mints a CMS API key via `manage.py generate_api_key` and writes it into `cms_api_key.env` (an empty key fails here, not later).
5. Runs `./apply_cms_config` — grants the `neops` user a full-permission role (`lab-admin`, `default_permission=7`), applies the scenario's `cms/permissions.json`, and configures the `Global` scope's columns, drill-down and dashboard.
6. `docker compose up -d --force-recreate workflow_engine` — `env_file` changes do not trigger a recreate on their own, so the engine is restarted to pick up the new token.
7. Mints an engine token, `docker compose up -d` for the rest of the stack, then `docker compose wait lab_bootstrap` — which blocks until the one-shot container that publishes every workflow in the resolved scenario has *exited*, and propagates its exit code.

!!! info "Why the CMS config is applied *before* the engine restart"
    The CMS caches each user's accessible scopes in memory for 10 minutes. If
    the engine queries the CMS as `neops` before the grant lands, that stale
    (empty) cache hides the `Global` scope from the web client for up to ten
    minutes — the classic "scope not available when first used" report.
    Granting first means the first `neops` query caches the grant.

Later sessions use `make local-env-up`, which skips the key minting and adds a
`wait_ready` on the discovery function block when the worker profile is on.

!!! warning "The worker is optional, and an old `.env` leaves it off"
    The worker sits behind the `worker` compose profile, switched by
    `COMPOSE_PROFILES` in `.env`. The shipped `.env.example` sets it, but
    **`make lab-env` never overwrites an existing `.env`** — so an environment
    created before the profile existed has no such line and its worker silently
    stops coming up. `make local-env-up` prints `worker: enabled` or `worker:
    disabled` on every run; `make worker-up` starts one regardless.

!!! note "Expect one stale line on a fresh clone"
    There was no `.env` when make parsed the Makefile, so on this first run make
    believes `COMPOSE_PROFILES` is unset while compose — which reads the file
    `lab-env` just wrote — starts the worker anyway. The `worker: disabled` line
    is therefore wrong, and the `wait_ready` guard is skipped. `lab-env` prints a
    notice saying so. Everything is fine; the next `make local-env-up` reports
    correctly.

## 2. Build the network

```bash
make local-lab-up
```

Devices and nothing else: no `docker compose`, no CMS, no engine, no token. It
chains `build-docker-frr`, `lab-net` and `scenario-resolve`, then:

1. **Refuses to run** if `generated/.deployed-scenario-clab` records a *different* scenario — see [Switching scenarios](#switching-scenarios).
2. **`./gen_clab_topology`** — renders `generated/$SCENARIO/clab/neops-lab.clab.json`, the per-device FRR/SR&nbsp;Linux configs, and three of the four discovery parameter files from the scenario's [`topology.json`](../10-concepts/20-topology.md).
3. **`./containerlab deploy --reconfigure`** — the scenario's devices with real point-to-point links, attached to `lab-net` (`172.30.0.0/24`) at their fixed management IPs. `--reconfigure` redeploys an existing lab, so re-running the target against the **same** scenario is safe. It does nothing for switching *between* scenarios — it destroys only the nodes the handed topology names — which is what step 1 refuses on.
4. **`wait_devices` in a throwaway container on `lab-net`** — polls TCP 22 on every device's management IP (`WAIT_DEVICES_TIMEOUT`, default 240 s). `containerlab deploy` returns once containers are started, not once SSH is listening, and Nokia SR Linux takes tens of seconds longer. It runs in a container rather than on the host because on macOS/Docker Desktop the host has no route to `172.30.0.0/24`.
5. Writes the deployed-scenario marker.

Each of those waits exists because of a real, reproduced failure. See [Troubleshooting](../20-operations/40-troubleshooting.md) for the symptom each one prevents.

When it finishes you get a banner:

```text
Devices are up (scenario: wan-and-fabric, real links).
  SSH:   docker exec -it <node> vtysh      (FRR, login frr / frr)
  List:  make local-lab-status
```

## 3. Populate the CMS

```bash
make discover
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

## Switching scenarios

```bash
make local-lab-down
make local-lab-up SCENARIO=frr-only
make local-env-up SCENARIO=frr-only
```

**Tear the running scenario down first.** `containerlab destroy` acts on the
nodes named in the topology it is handed, not on every container carrying the
lab's label, so deploying a scenario with fewer devices would strand the rest
and leave the lab registered. `make local-lab-up` refuses rather than let that
happen, and `make local-lab-down` reads the deployed scenario from
`generated/.deployed-scenario-clab`, so it tears down the right one whatever you
pass on the command line.

The control plane needs the new scenario too, which is what the third command is
for — the worker's `DIR_FUNCTION_BLOCKS` and `lab_bootstrap`'s workflow mount
both point into the resolved tree, so a `SCENARIO` change recreates the worker
and re-publishes the new scenario's workflow documents.

Two more things you do not see:

- **`generated/<old-scenario>/` is never pruned**. It is harmless and it is what
  makes switching back cheap, but it does grow.
- The CMS keeps the rows discovery already wrote — devices from the previous
  scenario stay in the entity browser until you reset with
  `make local-env-prune` followed by `make local-env-init`.

## Shutting down

Each half goes down on its own:

```bash
make local-lab-down     # destroy the devices; the control plane keeps running
make local-env-down     # stop the control plane; KEEPS the volumes
make local-env-prune    # docker compose down -v — the true reset, drops ES + Postgres
```

After `local-lab-down` the worker is still up and still registered with the
engine — `wait_ready` passes while `make discover` fails against devices that
are no longer there. That is the intended end state, not a broken one.

Full reset from scratch:

```bash
make local-lab-down local-env-prune
make local-env-init && make local-lab-up && make discover
```

`local-env-init` and not `local-env-up`: the prune invalidates the key in
`cms_api_key.env` without deleting the file, and only `init` mints a new one.
The first line deliberately stops before the prune if the devices did not go
down.

## Next

[Your first discovery :material-arrow-right:](30-first-discovery.md)
