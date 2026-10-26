---
title: Troubleshooting
description: Failure modes indexed by symptom — the three boot-order races, the CMS startup requirements, and the blank web client that curl cannot see.
tags: [operations, debugging]
---

# Troubleshooting

*Indexed by what you actually see. Most of these are boot-order races that already have a wait guarding them — if you hit one, the usual cause is a hand-run command that skipped the wait.*

## Start here

```bash
make doctor                       # host preflight: RAM, subnets, mount, images
make scenario                     # which lab the next target acts on
export SCENARIO=wan-and-fabric    # compose refuses to interpolate without it
docker compose ps                 # what is running, what exited
make local-env-logs               # every control-plane service, followed
make worker-logs                  # the worker alone (works with the profile off)
docker compose logs cms           # CMS startup crashes land here
make local-lab-status             # the deployed devices
```

Which half is broken decides where to look: `local-env-*` owns the control plane
and `local-lab-*` owns the devices, and neither touches the other. A failure in
`make discover` is one of the two, plus the path between them.

---

## `Pool overlaps with other one on this address space`

**Where:** `docker compose up`, creating `lab-net` or the project `default` network.

**Cause:** another docker network overlaps `172.30.0.0/23`. On a host with many compose projects docker's auto-assigned `/16` blocks run out and some other project's `default` network landed on `172.30.0.0/16` before the lab's networks existed. (The lab's own networks all carry fixed subnets, so they never compete with each other.)

**Fix:** `make doctor` names the overlapping network. If it is an unused leftover (`docker network inspect <name>` shows no containers): `docker network rm <name>` — the owning project's next `up` recreates it. If it is genuinely in use, stop that stack first.

---

## `Workflow with ID null not found`

**Where:** the engine, when you trigger discovery.

**Cause:** the workflow definition has not been registered yet. `docker compose up -d` returns once containers are *Started*, not *Completed*, and `lab_bootstrap` is a one-shot container that POSTs the definitions and exits.

**The guard:** `make local-env-up` runs `docker compose wait lab_bootstrap`, which blocks until that container exits and propagates its exit code — so a failed registration fails the target instead of silently producing this error later.

**Fix:** let `make local-env-up` finish before running discovery. If the container exited non-zero, read its log:

```bash
docker compose logs lab_bootstrap
```

`200 unchanged` is the idempotent re-run. A `409` means the version in the YAML already exists with different content — bump `patchVersion`/`minorVersion` (the log prints the engine's `suggestedVersion`); a `404` on `/workflow-definition/publish` means an engine older than `0.42.2-beta.3`.

---

## Discovery stays `running`, the worker log says `413 Payload Too Large`

**Where:** `make discover` after the worker discovered every device (`Generated 448 db update(s)`) and then `Failed to push job result … (413)`.

**Cause:** an engine image without the raised per-route body limits (older than `0.42.2-beta.3`). Discovery returns a few hundred `Interface` rows in one job result; the engine rejects the push and re-dispatches the job.

**Fix:** refresh the engine — `make local-env-up` pulls with `--policy always`, and the default `develop` tag is rebuilt on every merge to the engine's develop branch.

---

## `Function block … not found`

**Where:** the execution's terminal state, as `failed_safe_ack — Function block with id fb.base.neops.io/global_discover_network:0.1.0 not found`.

**Two different causes, in order of likelihood:**

1. **You raced the worker.** The worker registers its function blocks with the engine *asynchronously* after its container starts. `make local-env-up` (when the worker profile is on) and `make discover` both run `./wait_ready fb.base.neops.io/global_discover_network:0.1.0` first, which polls the engine's per-function-block worker registry until an online worker exists. Run the make target rather than `run_workflow` directly.

2. **The image does not carry the block.** `neops/fb` ships *inside* the `neops-worker-sdk` image; it is not mounted from this repo. Check what you are running:

    ```bash
    docker compose exec worker ls /app/neops/fb/base/global/discover_network.py
    ```

    ⚠️ The published `quay.io/zebbra/neops-worker-sdk:develop` tag **does not carry it** — see the next entry.

See [Discovery](../10-concepts/30-discovery.md) and [The `/app/lab` mount](../10-concepts/40-container-paths.md).

---

## `no online worker` at `wait_ready`

**Where:** `make local-env-up` or `make discover` burns its full `wait_ready` budget and gives up with

```
timeout: no online worker for fb.base.neops.io/global_discover_network:0.1.0 within 180s
```

**Cause:** the worker image you pinned does not carry
`global_discover_network` — the published `develop` tag is one such image. The
block ships *inside* the image rather than being bind-mounted from here, so the
worker starts, registers the blocks it has, and never announces this one;
`wait_ready` waits for it until the budget runs out.

**Fix:** check what the image actually holds, and fall back to a prerelease
`0.2.0-beta.*` tag (the published `develop` lacks the block) or a fresh build of
an SDK checkout that has it:

```bash
docker run --rm --entrypoint sh "$NEOPS_WORKER_SDK_IMAGE" -c 'ls neops/fb/base/global/discover_network.py'
make -C ../neops-worker-sdk-py build-docker          # -> neops-worker-sdk:latest
echo 'NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest' >> .env
make local-env-up
```

---

## `wait_ready` times out and `docker compose ps` shows no worker at all

**Where:** `make discover`, or `make local-env-up` on an environment that used to
start a worker and now does not.

**Cause:** the worker lives behind the `worker` compose profile, switched by
`COMPOSE_PROFILES` in `.env`. **`make lab-env` never overwrites an existing
`.env`**, so an environment created before the profile existed has no such line,
compose never starts a worker, and nothing announces the function block.
`docker compose ps` shows no `worker` row — not an exited one, no row at all —
which is the tell that distinguishes this from a crashed worker.

The same reading is what you get from a worker that *is* running: with no
service named, `docker compose ps` and `logs` cover the **active profile set**,
so a worker you started by hand with `make worker-up` is absent from both even
though its container is up. `docker compose ps worker` names it and shows it.

`make local-env-up` prints `worker: enabled (COMPOSE_PROFILES)` or `worker:
disabled …` on every run, so the line above the failure already says which.

**Fix:** add the line, or start one by hand:

```bash
echo 'COMPOSE_PROFILES=worker' >> .env   # the shipped .env.example has this
make worker-up                           # naming the service enables the profile
```

Re-pinning a newer `0.2.0-beta.*` the same way? Run the `discover_network.py`
check against it before `make local-lab-up`.

---

## Worker exits ~2 min after start; discovery hangs after `wait_ready`

**Known issue until [engine #402](https://github.com/zebbra/neops-workflow-engine/pull/402) is in the engine's
published `develop` image.**

**Where:** `make local-lab-up` succeeds and `wait_ready` reports an online
worker, but `make local-lab-discover` sits in `running` and never finishes. The
worker log shows `Registration failed: (500)` for one function block (e.g.
`network_device_apply_configuration`), retries for about two minutes, then the
container exits with code 1. The engine log shows `value too long for type
character varying(255)`.

**Cause:** the engine stores a function block's description and help text in
`varchar(255)` columns, and the `0.2.0-beta.*` worker ships a block whose help
text is longer. That insert fails, the worker gives up and exits. The discovery
block registers before the failing one, so `wait_ready` passes — and the engine
keeps listing the dead worker as online.

**Fix:** once #402 is merged and the engine's `develop` image is republished,
re-pull the engine and restart the stack. The worker pin does **not** need to
move.

```bash
make local-env-up          # pulls with --policy always
make local-lab-up
```

---

## `bootstrap` fails with `404` or `409` on the workflow definition

**Where:** `docker compose wait lab_bootstrap` returns non-zero and
`docker compose logs lab_bootstrap` shows a `FAILED` line.

- **`409`** — the version already exists with *different* content. Published
  workflow definitions are **immutable**; editing a `scenarios/_base/workflows/` document in place and
  re-running is exactly what triggers this. Bump
  `majorVersion`/`minorVersion`/`patchVersion` in the YAML, and update the
  matching `wf.lab.neops.io/simple_lab_discovery:<version>` in the `Makefile`'s
  `DISCOVER_WORKFLOW` variable, which both `discover` and
  `kind-discover` read.
- **`422`** — the document is publishable but the engine computed a higher
  version floor than the document declares. Raise the version.
- **A `404` handled silently** — the engine predates
  [`068753a0`](https://github.com/zebbra/neops-workflow-engine/commit/068753a0)
  and has no `/workflow-definition/publish`; `register.py` falls back to the
  legacy `POST /workflow-definition`. Nothing to fix, but you are on an old
  engine image.

---

## `401 Unauthorized` from the engine

**Where:** `wait_ready`, `run_workflow` or `lab_bootstrap` stops with `401` or `403` and a line naming `NEOPS_ENGINE_TOKEN`.

**Cause:** the engine is running `NEOPS_AUTHZ_MODE=enforce` or `permissive`, so every call to a gated route carries a bearer token. The make targets mint one per run; a hand-run script needs one in the environment. A `403` means the token is valid and its account lacks the route's permission.

**Fix:**

```bash
export NEOPS_ENGINE_TOKEN=$(./lab_token)
./wait_ready fb.base.neops.io/global_discover_network:0.1.0
```

A token lasts 15 minutes, so a long session needs a fresh one. If the account is short of a permission, widen its role:

```bash
make lab-grant ROLE=workflow-operator PROFILE=admin
```

See [Authorization](../10-concepts/50-authorization.md).

---

## Devices never become reachable

**Where:** `wait_devices` times out — `timeout: 172.30.0.31:22, … not reachable within 240s`.

**Cause:** devices boot slower than `containerlab deploy` returns. FRR is up in a second or two; Nokia SR Linux takes tens of seconds to bring up its management stack. Running discovery before then makes those hosts fail with a connection error and drop out of the 15-device count.

**The guard:** `make local-lab-up` polls TCP 22 on every mgmt IP after the deploy returns, and `make discover` polls again before it executes anything.

!!! important "The poll runs from *inside* the lab network, on purpose"
    ```bash
    docker run --rm --network lab-net -v "$PWD:/lab:ro" -w /lab \
      -e SCENARIO=$SCENARIO python:3.12-slim python3 wait_devices
    ```

    Not from the host. On macOS and Docker Desktop the host has **no route** to
    the `lab-net` bridge IPs (`172.30.0.0/24`), so a host-side poll hangs until
    timeout even when every device is perfectly healthy. A container on
    `lab-net` reaches them the same way discovery does, on every platform.

    It is a throwaway `PROBE_IMAGE` container and **not** the worker: waiting for
    devices must not require a running control plane. The worker did no part of
    this check; it was borrowed for its network attachment alone.

**Fix:** give it more time (`make local-lab-up WAIT_DEVICES_TIMEOUT=600`), or check the device itself:

```bash
docker logs spine-01
./containerlab inspect -t generated/wan-and-fabric/clab/neops-lab.clab.json
```

!!! warning "Never replace a wait with a `sleep`"
    Each wait exists because of a real, reproduced failure. A fixed sleep is
    both slower on a fast machine and still racy on a slow one.

---

## The CMS crashes at startup

**Symptom:** the `cms` container exits or never becomes healthy; the log mentions `token_service check_keys`.

**Cause:** missing `cms/jwt/{private,public}.pem`. Newer `neops-cms-free` images require an RSA keypair for RS256 JWT issuance, and `docker-compose.yml` mounts `cms/jwt` read-only into the container.

**Fix:**

```bash
make lab-jwt
```

Idempotent, and a prerequisite of `local-env-init` / `local-env-up` — so this only bites when the stack is started by hand.

---

## The web client renders an empty page

**Symptom:** <http://localhost:8080/> returns HTTP 200 and a blank `<app-root>`. **curl cannot see this failure** — the HTML is fine; the Angular bootstrap is what fails.

**Cause:** `scenarios/_base/cms/oidc-config.json` must contain at least one well-formed `OpenIdConfiguration` entry with **inline** `authWellknownEndpoints` (no network discovery). The web client calls `OidcSecurityService.checkAuth()` in an `APP_INITIALIZER`; a `null` or `[]` config makes it fail before anything renders. The CMS serves the file through its `appSettings.oidcConfig` GraphQL resolver, so a missing `OIDC_CONFIG_PATH` produces the same result.

**Fix:** check the file is present and non-empty, and that `OIDC_CONFIG_PATH=/etc/neops/oidc-config.json` is still set on the `cms` service.

!!! tip "Verify UI behaviour with a browser, not curl"
    Drive a real browser (the Playwright MCP, or just open the page) when
    checking lab or UI behaviour. This failure mode is invisible to `curl`.

---

## The `Global` scope lost its columns

**Symptom:** the web client's device table is back to default columns after a CMS restart.

**Cause:** the CMS image seeds a scope named `Global` on every startup with `always_update_on_restart=True`, and `init_scopes` runs on *every* `manage.py` invocation — rewriting the seeded scope's columns, filters and drill-down. `dashboard_configuration` is not affected; `init_scopes` never writes it.

**Fix:**

```bash
make apply-cms-config
```

!!! note "The scope is `Global`, capital G"
    Postgres name uniqueness is case-sensitive, so a lowercase `global` creates
    a silent *duplicate* scope rather than updating the seeded one.

---

## `docker compose pull` fails on an image that exists

**Symptom:** `pull access denied for neops-worker-sdk, repository does not exist`.

**Cause:** you set `NEOPS_*_IMAGE` to a local tag with no registry host, so docker resolves it as `docker.io/library/…`.

**Fix:** run the pull with `--ignore-pull-failures`, or skip it — `pull_policy: missing` means `docker compose up -d` uses the present local image without contacting a registry.

---

## `containerlab deploy` fails to start or cannot reach docker

**Cause:** `./containerlab` runs containerlab in a container through the docker socket; it needs a rootful docker daemon and, on Docker Desktop, the repo under a shared path. `make doctor` checks both.

With `CLAB_NATIVE` (a host binary) the classic failure is *"This containerlab command requires root privileges or root via SUID to run"* — usually after a **containerlab upgrade**: the new binary is installed without the SUID bit while your `clab_admins` membership survives, so `id` still looks right and only `ls -l "$(command -v containerlab)"` shows the missing `s`. `make clab-suid` restores it (idempotent).

**Fix:** `make doctor`, or `make clab-suid` for the native path; details in [Prerequisites](../getting-started/10-prerequisites.md#containerlab-one-command-both-hosts-no-install). Then confirm with the two-node probe:

```bash
./containerlab deploy  -t clab/probe.clab.yml
./containerlab destroy -t clab/probe.clab.yml --cleanup
```

---

## Duplicate interface rows after re-running discovery

**Cause:** devices are keyed by IP so they are skipped on a second run, but **interfaces are always recorded**.

**Fix:** run discovery against a fresh CMS.

```bash
make local-lab-down local-env-prune
make local-env-init && make local-lab-up && make discover
```

---

## Nothing works and you want to start over

```bash
make local-lab-down local-env-prune
make local-env-init && make local-lab-up && make discover
```

`local-lab-down` treats "nothing is deployed" as an answer, not a failure: with no generated topology it says so and exits 0. A destroy that genuinely *fails*, though, **fails the target**, so the two commands stop there rather than pruning the control plane while fifteen devices are still running — and the deployed-scenario marker survives, which is what keeps the next `local-lab-up SCENARIO=other` from getting past its guard.

`local-env-prune` drops the Elasticsearch and Postgres volumes — leftover volume state across down/up cycles has previously made `elastic_index --create` fail and stale CMS data confuse re-inits. It leaves `cms_api_key.env` on disk, which is why the second line is `local-env-init` (mints a fresh key) and not `local-env-up` (which would boot the engine on the old one).
