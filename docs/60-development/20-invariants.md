---
title: Invariants
description: The load-bearing constraints that are not obvious from the code — break one and something fails in a way that is hard to trace back.
tags: [contributing, gotcha]
---

# Invariants

*Each of these was learned the hard way. They are listed here so the next person does not have to relearn them.*

## 1. The extension-less scripts must keep their names

`tests/*` load them by path via `SourceFileLoader`, `gen_clab_topology` loads `gen_device_configs` the same way, and the `Makefile` invokes them as `./gen_clab_topology`. Because they have no `.py`, ruff and pyrefly see them only through the explicit `extend-include` / `project-includes` lists in `pyproject.toml` — **add any new script to both lists or it is silently never checked.** See [Dev setup](10-dev-setup.md#the-extension-less-script-rule).

## 2. The repo is bind-mounted read-only at `/app/lab`

That is why in-container paths keep a `lab/` prefix (`DIR_FUNCTION_BLOCKS: lab/function_blocks,neops/fb`, `docker compose exec worker python3 lab/wait_devices`) while host-side paths never do. **A `lab/` in a Makefile recipe or a host script is a bug; a `lab/` inside a `docker compose exec` or a container-read env var is correct.** Full explanation: [The `/app/lab` mount](../10-concepts/40-container-paths.md).

## 3. `neops/fb` ships inside the published worker image

It is not mounted from here. If discovery fails with `Function block … not found`, check that the `NEOPS_WORKER_SDK_IMAGE` you pinned actually carries `/app/neops/fb`.

## 4. `gen_clab_topology` emits `"../devices/frr/set-aliases.sh:…"` on purpose

That bind path is relative to `generated/`, where the topology file it writes lives, and containerlab resolves binds relative to the topology file. **Do not "fix" it to `devices/…`.**

## 5. The generator tests are the real guard on this repo

They assert that regenerating from `topology.json` reproduces the committed `workflow-execution-parameters/*.json` byte-for-byte — `_dump_discover_params` hand-rolls a layout `json.dumps` cannot produce. Change `topology.json` → rerun `./gen_clab_topology` → commit the regenerated JSON, or `make test` fails.

Corollary: **`discover-params-mixed.json` has no generator and no test coverage.** It is hand-maintained and nothing will tell you it went stale.

## 6. Images are local-tag only

`neops-lab-frr:latest` and `neops-lab-bootstrap:latest` are built by `make build-docker` on whatever host runs the lab; nothing is pushed to a registry. `docker-compose.worker.yml` pins `lab_bootstrap` to that exact tag so the compose build and `build-docker` cannot diverge. Everything else — CMS, engine, web client, worker — comes from `quay.io/zebbra`.

## 7. The FRR image needs both `NET_ADMIN` and `SYS_ADMIN`

The FRR binary refuses to start without `cap_sys_admin`, even with no VRFs configured.

## 8. `cms/oidc-config.json` must have one well-formed entry with inline endpoints

At least one `OpenIdConfiguration` with inline `authWellknownEndpoints` — no network discovery. The web client's Angular bootstrap calls `OidcSecurityService.checkAuth()` in an `APP_INITIALIZER`; `null` or `[]` here makes `<app-root>` render empty. **A failure mode `curl` cannot see.**

## 9. `cms/jwt/` has no committed content and the CMS will not start without it

`make lab-jwt` mints it idempotently, and `local-env-init` depends on that target. The keypair is git-ignored on purpose: it is a throwaway lab credential, not a secret.

## 10. `apply_cms_config` uses `manage.py shell`, not GraphQL — and its ordering matters

`roleUpsert` / `scopesUpsert` / `roleScopeUpsert` all gate on permissions the freshly-bootstrapped `neops` user does not have (chicken-and-egg). It also has a documented ordering constraint: the CMS's `init_scopes` runs on *every* `manage.py` invocation and rewrites the seeded `Global` scope's columns and filters, so the columns are applied via GraphQL **last**, after all shell blocks. Re-read the script's header comment before reordering anything in it.

Related: **the scope is `Global`, capital G.** The CMS image seeds a scope by that exact name, and Postgres name uniqueness is case-sensitive — a lowercase `global` creates a silent duplicate.

## 11. The race ordering in `local-lab-up` is deliberate

```text
docker compose wait lab_bootstrap         # workflow registration
./containerlab deploy --reconfigure       # SR Linux boots slowly — start it early
./wait_ready <fb>                         # the worker registers FBs asynchronously
wait_devices, from inside the worker      # the host has no route to lab-net on macOS
```

Each wait exists because of a real, reproduced failure, and each has a distinctive symptom listed in [Troubleshooting](../20-operations/40-troubleshooting.md). **Do not replace one with a `sleep`.** Their budgets are `WAIT_READY_TIMEOUT` / `WAIT_DEVICES_TIMEOUT` — raise those, never remove a wait.

## 12. Everything generated goes under `generated/`, and it is git-ignored

Never commit it — containerlab mints TLS private keys in there. The one exception to "generated output is ignored" is the three `workflow-execution-parameters/*.json` files, which *are* tracked precisely so the tests can diff against them (invariant 5).

## 13. containerlab is only ever called as `./containerlab`

In the Makefile (`$(CONTAINERLAB)`) and in every doc. The launcher exec's a native binary when one is on `PATH` (Linux: byte-identical to calling it directly) and otherwise — on Darwin, or with `CLAB_IN_DOCKER=1` — runs `ghcr.io/srl-labs/clab` privileged through the docker socket. **A bare `containerlab …` in a recipe or a doc breaks every Mac.** Container mode is deliberately not the silent fallback on Linux: SELinux `:z` binds, rootless socket paths, root-owned files under `generated/`.

## 14. In container mode the repo is mounted at the *same* absolute path

`-v "$ROOT:$ROOT" -w "$PWD"`. containerlab turns the topology's relative binds (`frr/<host>.iface`, `../devices/frr/set-aliases.sh` — invariant 4) into absolute host paths and hands them to the docker daemon; that only resolves if the path inside the clab container equals the daemon's. Mounting the repo at `/work` would give every FRR node a silently empty bind. On Docker Desktop this is also why the checkout must live under a shared path. **Do not "tidy" it.**

## 15. `lab-net` is created by the Makefile, not by compose

`make lab-net` (prerequisite of every `*-up` target) creates it with `LAB_SUBNET` *before* the first `docker compose up` and refuses one with a different subnet; `docker-compose.worker.yml` declares it `external: true` — with no `ipam` block, on purpose, since compose ignores everything but `name` on an external network. The reason is docker's concurrent auto-subnet allocation colliding with the fixed `/24` on busy hosts ([Architecture → Networks](../10-concepts/10-architecture.md#networks)). The subnet is single-sourced in `gen_clab_topology` (`LAB_SUBNET`) and cross-checked against the Makefile by `tests/test_host_invariants.py`. `local-lab-down` and `local-env-prune` remove the network again.

## 16. Host scripts import under Python 3.9

A stock macOS ships `/usr/bin/python3` 3.9, where a PEP 604 `X | None` annotation is evaluated at import time and raises. Every host script therefore starts with `from __future__ import annotations`. `make py39-check` (in `make check` and CI) proves it at runtime; `tests/test_host_invariants.py` keeps the rule visible; ruff at `target-version = "py312"` will **not** warn you.

## 17. Redis is wired, and the engine is pinned

The CMS gets `REDIS_URL=redis://redis:6379` (channel layer, cache, Celery broker — as in production; without it neops-core configures no channel layer at all). The engine defaults to `quay.io/zebbra/neops-workflow-engine:0.42.2-beta.3`, the first published tag with the raised body limits *and* the publish API, and `bootstrap/register.py` implements the publish semantics (200 unchanged = idempotent, **409 = hard failure**, 422 = bump too small, 404 → legacy route). See [Images → Image compatibility](../20-operations/20-images.md#image-compatibility).
