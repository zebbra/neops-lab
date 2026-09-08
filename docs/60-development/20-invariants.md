---
title: Invariants
description: The load-bearing constraints that are not obvious from the code — break one and something fails in a way that is hard to trace back.
tags: [contributing, gotcha]
---

# Invariants

*Each of these was learned the hard way. They are listed here so the next person does not have to relearn them.*

## 1. The extension-less scripts must keep their names

`tests/*` load them by path via `SourceFileLoader`, `gen_clab_topology` loads `gen_device_configs` the same way (and that one loads `resolve_scenario`), and the `Makefile` invokes them as `./gen_clab_topology`. Because they have no `.py`, ruff and pyrefly see them only through the explicit `extend-include` / `project-includes` lists in `pyproject.toml` — **add any new script to both lists, and to `tools/import_host_scripts.py`, or it is silently never checked.** The current set is `resolve_scenario`, `gen_clab_topology`, `gen_device_configs`, `gen_kind_manifests`, `gen_kind_discover_params`, `run_workflow`, `wait_ready` and `wait_devices`. See [Dev setup](10-dev-setup.md#the-extension-less-script-rule).

## 2. The repo is bind-mounted read-only at `/app/lab`

That is why in-container paths keep a `lab/` prefix (`DIR_FUNCTION_BLOCKS: lab/generated/<scenario>/scenario/function_blocks,neops/fb`, `docker compose exec worker python3 lab/wait_devices`) while host-side paths never do. **A `lab/` in a Makefile recipe or a host script is a bug; a `lab/` inside a `docker compose exec` or a container-read env var is correct.** Full explanation: [The `/app/lab` mount](../10-concepts/40-container-paths.md).

## 3. `neops/fb` ships inside the published worker image

It is not mounted from here. If discovery fails with `Function block … not found`, check that the `NEOPS_WORKER_SDK_IMAGE` you pinned actually carries `/app/neops/fb`.

## 4. `gen_clab_topology` emits `"../scenario/devices/frr/…"` on purpose

Every FRR node binds three files out of the resolved scenario tree:

```text
../scenario/devices/frr/set-aliases.sh:/lab/set-aliases.sh:ro
../scenario/devices/frr/frr.conf:/lab/frr.conf:ro
../scenario/devices/frr/daemons:/lab/daemons:ro
```

Those paths are relative to `generated/<scenario>/clab/`, where the topology file it writes lives, because containerlab resolves binds relative to the topology file — **not** to the repo root. **Do not "fix" them to `devices/…` or `scenarios/…`.**

## 5. The generator tests are the real guard on this repo

They assert that regenerating from a scenario's `topology.json` reproduces its committed `workflow-execution-parameters/*.json` byte-for-byte — `_dump_discover_params` hand-rolls a layout `json.dumps` cannot produce. The tests are **parametrised over `scenarios/*`**, so adding a scenario extends the guard automatically. Change a `topology.json` → `make generate SCENARIO=<name>` → commit the regenerated JSON, or `make test` fails.

Corollary: **`discover-params-mixed.json` has no generator and no test coverage.** It is hand-maintained and nothing will tell you it went stale. Only `wan-and-fabric` carries one.

## 6. Images are local-tag only

`neops-lab-frr:latest` and `neops-lab-bootstrap:latest` are built by `make build-docker` on whatever host runs the lab; nothing is pushed to a registry. `docker-compose.worker.yml` pins `lab_bootstrap` to that exact tag so the compose build and `build-docker` cannot diverge. Everything else — CMS, engine, web client, worker — comes from `quay.io/zebbra`.

## 7. The FRR image needs both `NET_ADMIN` and `SYS_ADMIN`

The FRR binary refuses to start without `cap_sys_admin`, even with no VRFs configured.

## 8. The FRR image bakes no config, and refuses to boot without `/lab`

`frr.conf` and `daemons` are scenario data, not image layers: `devices/frr/entrypoint.sh` copies them from `/lab` into `/etc/frr` before `docker-start` and exits non-zero if either is absent. That is deliberate — a silently wrong routing config costs far more to debug than a container that will not start. One image therefore serves every scenario, and a scenario needing a different baseline ships a `devices/frr/daemons` delta instead of a second image tag. Both flavours mount all three `/lab` files: containerlab binds them (invariant 4), the Kubernetes flavour carries them in its ConfigMap.

## 9. `scenarios/_base/cms/oidc-config.json` must have one well-formed entry with inline endpoints

At least one `OpenIdConfiguration` with inline `authWellknownEndpoints` — no network discovery. The web client's Angular bootstrap calls `OidcSecurityService.checkAuth()` in an `APP_INITIALIZER`; `null` or `[]` here makes `<app-root>` render empty. **A failure mode `curl` cannot see.**

## 10. `cms/jwt/` has no committed content and the CMS will not start without it

`make lab-jwt` mints it idempotently, and `local-env-init` depends on that target. The keypair is git-ignored on purpose: it is a throwaway lab credential, not a secret.

## 11. `apply_cms_config` uses `manage.py shell`, not GraphQL — and its ordering matters

`roleUpsert` / `scopesUpsert` / `roleScopeUpsert` all gate on permissions the freshly-bootstrapped `neops` user does not have (chicken-and-egg). It also has a documented ordering constraint: the CMS's `init_scopes` runs on *every* `manage.py` invocation and rewrites the seeded `Global` scope's columns and filters, so the columns are applied via GraphQL **last**, after all shell blocks. Re-read the script's header comment before reordering anything in it.

It also requires `SCENARIO` and reads the scope JSON from `generated/$SCENARIO/scenario/scope/$SCOPE_NAME`, so `make scenario-resolve` must have run first — the target depends on it.

Related: **the scope is `Global`, capital G.** The CMS image seeds a scope by that exact name, and Postgres name uniqueness is case-sensitive — a lowercase `global` creates a silent duplicate.

## 12. The race ordering in `local-lab-up` is deliberate

```text
make scenario-resolve                # materialise the overlay the mounts read
docker compose wait lab_bootstrap    # workflow registration
./containerlab deploy --reconfigure  # SR Linux boots slowly — start it early
./wait_ready <fb>                    # the worker registers FBs asynchronously
wait_devices, from inside the worker # the host has no route to lab-net on macOS
```

Each wait exists because of a real, reproduced failure, and each has a distinctive symptom listed in [Troubleshooting](../20-operations/40-troubleshooting.md). **Do not replace one with a `sleep`.**

## 13. Everything generated goes under `generated/`, and it is git-ignored

Never commit it — containerlab mints TLS private keys in there. The one exception to "generated output is ignored" is each scenario's `scenarios/<name>/workflow-execution-parameters/*.json` files, which *are* tracked precisely so the tests can diff against them (invariant 5). They live beside the topology that produced them, not under `generated/`.

## 14. containerlab is only ever called as `./containerlab`

In the Makefile (`$(CONTAINERLAB)`) and in every doc. The launcher runs `ghcr.io/srl-labs/clab` privileged through the docker socket on both hosts (`CLAB_NATIVE=/path` selects a host binary). The repo is mounted at the **same absolute path** inside that container: containerlab resolves the topology's relative binds (invariant 4) to absolute host paths for the daemon, so the path inside must equal the daemon's — mounting the repo at `/work` would give every FRR node a silently empty bind (and now, an FRR that refuses to boot — invariant 8). **Do not "tidy" it.**

## 15. Every project network has a fixed subnet

`lab-net` carries `172.30.0.0/24` and the compose `default` network is pinned to `172.30.1.0/24` — docker auto-allocates subnet-less networks from its `172.16/12` pool, which on a busy host collides with the lab's fixed `/24` ("Pool overlaps"). The subnet is single-sourced in `gen_clab_topology` (`LAB_SUBNET`) and cross-checked by `tests/test_host_invariants.py`. A new network in either compose file needs a fixed subnet too.

## 16. `SCENARIO` has exactly one default, and it lives in the `Makefile`

`SCENARIO ?= wan-and-fabric` plus `export SCENARIO`. Every other consumer — the four generators, `resolve_scenario`, `apply_cms_config` and both compose files — **fails when it is unset** rather than falling back. A second default is how a scenario gets applied half from one lab and half from another, which stays invisible until discovery produces a confusing result. `tests/test_host_invariants.py` asserts no consumer grows one.

## 17. Compose uses `${SCENARIO:?…}`, never a bare `${SCENARIO}`

A bare reference only makes compose *warn* on an unset variable; it then interpolates a blank path, and docker helpfully creates the missing bind source as an empty directory. The lab comes up having registered no workflows at all. The `:?` form aborts instead. Same test enforces it.

## 18. `topology.json` is never inherited from `_base`

A scenario *is* its topology, so there is no meaningful base to fall back to, and inheriting it would make the write-back target for the generated parameter files ambiguous. `resolve_scenario.source_dir` rejects a scenario missing `topology.json` or `scenario.json`. Everything else in `scenarios/_base/` is overlaid **per file** — overriding one `scope/Global/*.json` keeps the other five.

## 19. The overlay is resolved once, into `generated/<scenario>/scenario/`

`docker compose` cannot express a fallback in a bind mount, so `resolve_scenario` materialises `_base` + the scenario into one flat tree and every consumer reads that. **No consumer implements the fallback itself** — the rule exists in one place instead of being reimplemented in Python, bash and YAML. The resolve prunes what an earlier run left behind, so removing an override takes effect on the next run. Full picture: [Scenarios](../30-scenarios/index.md).

## 20. Host scripts import under Python 3.9

A stock macOS ships `/usr/bin/python3` 3.9, where a PEP 604 `X | None` annotation is evaluated at import time and raises. Every host script therefore starts with `from __future__ import annotations`. `make py39-check` (in `make check` and CI) proves it at runtime; ruff at `target-version = "py312"` will **not** warn you.
