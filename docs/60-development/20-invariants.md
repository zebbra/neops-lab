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
docker compose wait lab_bootstrap    # workflow registration
./containerlab deploy --reconfigure  # SR Linux boots slowly — start it early
./wait_ready <fb>                    # the worker registers FBs asynchronously
wait_devices, from inside the worker # the host has no route to lab-net on macOS
```

Each wait exists because of a real, reproduced failure, and each has a distinctive symptom listed in [Troubleshooting](../20-operations/40-troubleshooting.md). **Do not replace one with a `sleep`.**

## 12. Everything generated goes under `generated/`, and it is git-ignored

Never commit it — containerlab mints TLS private keys in there. The one exception to "generated output is ignored" is the three `workflow-execution-parameters/*.json` files, which *are* tracked precisely so the tests can diff against them (invariant 5).

## 13. containerlab is only ever called as `./containerlab`

In the Makefile (`$(CONTAINERLAB)`) and in every doc. The launcher runs `ghcr.io/srl-labs/clab` privileged through the docker socket on both hosts (`CLAB_NATIVE=/path` selects a host binary). The repo is mounted at the **same absolute path** inside that container: containerlab resolves the topology's relative binds (invariant 4) to absolute host paths for the daemon, so the path inside must equal the daemon's — mounting the repo at `/work` would give every FRR node a silently empty bind. **Do not "tidy" it.**

## 14. Every project network has a fixed subnet

`lab-net` carries `172.30.0.0/24` and the compose `default` network is pinned to `172.30.1.0/24` — docker auto-allocates subnet-less networks from its `172.16/12` pool, which on a busy host collides with the lab's fixed `/24` ("Pool overlaps"). The subnet is single-sourced in `gen_clab_topology` (`LAB_SUBNET`) and cross-checked by `tests/test_host_invariants.py`. A new network in either compose file needs a fixed subnet too.

## 15. Host scripts import under Python 3.9

A stock macOS ships `/usr/bin/python3` 3.9, where a PEP 604 `X | None` annotation is evaluated at import time and raises. Every host script therefore starts with `from __future__ import annotations`. `make py39-check` (in `make check` and CI) proves it at runtime; ruff at `target-version = "py312"` will **not** warn you.
