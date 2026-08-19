---
title: Troubleshooting
description: Failure modes indexed by symptom — the three boot-order races, the CMS startup requirements, and the blank web client that curl cannot see.
tags: [operations, debugging]
---

# Troubleshooting

*Indexed by what you actually see. Most of these are boot-order races that already have a wait guarding them — if you hit one, the usual cause is a hand-run command that skipped the wait.*

## Start here

```bash
make doctor                       # host preflight — ports, RAM, subnet overlap, containerlab mode, quay
make images-check                 # do the configured worker/engine images carry what the lab needs?
export COMPOSE_FILE=docker-compose.yml:docker-compose.worker.yml
docker compose ps                 # what is running, what exited
make local-lab-logs               # worker + lab_bootstrap, followed
docker compose logs cms           # CMS startup crashes land here
./containerlab inspect -t generated/neops-lab.clab.json
```

Without `COMPOSE_FILE` exported, plain `docker compose` commands do not see the `worker` or `lab_bootstrap` services — the base compose file does not declare them. The make targets set it themselves. Note that a hand-run `docker compose up` also needs the `lab-net` network to exist (`make lab-net`) — it is external to compose.

---

## `network lab-net declared as external, but could not be found` / `Pool overlaps with other one on this address space`

**Where:** `docker compose up`, either from a make target or by hand.

**Cause (external, could not be found):** `lab-net` is created by the Makefile (`make lab-net`, a prerequisite of every `*-up` target), not by compose. A hand-run `docker compose up` after `local-lab-down`/`local-env-prune` removed it hits this.

**Fix:** `make lab-net`, or use the make targets.

**Cause (Pool overlaps):** another docker network already covers `172.30.0.0/24`. On a host with many compose projects docker's auto-assigned `172.x.0.0/16` blocks run out and `172.30.0.0/16` gets handed to some other project's `default` network — which is exactly why the Makefile creates `lab-net` with its fixed subnet *before* compose creates anything. If it happens anyway, `make doctor` names the overlapping network; remove it if it is unused (`docker network rm <name>` — compose recreates such networks on the next `up` of that project) or `docker network prune`.

**Cause (`lab-net exists with subnet …, expected 172.30.0.0/24`):** a stale `lab-net` from an older checkout. `make local-lab-down` (or `docker network rm lab-net`) and retry.

---

## `Workflow with ID null not found`

**Where:** the engine, when you trigger discovery.

**Cause:** the workflow definition has not been registered yet. `docker compose up -d` returns once containers are *Started*, not *Completed*, and `lab_bootstrap` is a one-shot container that POSTs the definitions and exits.

**The guard:** `make local-lab-up` runs `docker compose wait lab_bootstrap`, which blocks until that container exits and propagates its exit code — so a failed registration fails the target instead of silently producing this error later.

**Fix:** let `make local-lab-up` finish before running discovery. If the container exited non-zero, read its log:

```bash
docker compose logs lab_bootstrap
```

`register.py` publishes through `POST /workflow-definition/publish`: `200 unchanged` is the idempotent re-run, **`409` is a real conflict** — the version in the YAML already exists with *different* content, so bump `patchVersion`/`minorVersion` (the log prints the engine's `suggestedVersion`); `422` means the bump is smaller than the change warrants. A `404` on the publish route means an engine older than `0.42.2-beta.3`; `register.py` then falls back to the legacy route automatically.

---

## `Function block … not found`

**Where:** the execution's terminal state, as `failed_safe_ack — Function block with id fb.base.neops.io/global_discover_network:0.1.0 not found`.

**Two different causes, in order of likelihood:**

1. **You raced the worker.** The worker registers its function blocks with the engine *asynchronously* after its container starts. `make local-lab-up` and `make local-lab-discover` both run `./wait_ready fb.base.neops.io/global_discover_network:0.1.0` first, which polls the engine's per-function-block worker registry until an online worker exists. Run the make target rather than `run_workflow` directly.

2. **The image does not carry the block.** `neops/fb` ships *inside* the worker image; it is not mounted from this repo. As of August 2026 **no published `neops-worker-sdk` tag carries it** (and the `develop` image cannot even start — it exits during `uv run`'s project rebuild with `Readme file does not exist`). Check with `make images-check`, and build one locally: `make build-worker-image SDK_DIR=../neops-worker-sdk-py`, then `NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest make local-lab-up`.

    ```bash
    make images-check
    docker compose ps worker                    # Exited (1)? it is crash-looping
    docker compose logs --tail 30 worker
    ```

    `wait_ready` cannot tell these apart from "the worker is still starting" — the engine only learns about a function block when a worker registers it — which is why it prints this list of causes when it times out.

See [Discovery](../10-concepts/30-discovery.md), [Images → Image compatibility](20-images.md#image-compatibility) and [The `/app/lab` mount](../10-concepts/40-container-paths.md).

---

## The execution stays `running`, then times out; the worker log says `413 Payload Too Large`

**Where:** `make local-lab-discover` after a run that, in the worker log, discovered every device fine (`Generated 448 db update(s)`) and then `Failed to push job result … (413)`.

**Cause:** the engine image predates the raised per-route body limits (anything older than `0.42.2-beta.3`, including the `develop` tag on quay as of mid-2026). Discovery returns a few hundred `Interface` rows in one job result and the engine's default body limit rejects it; the engine re-dispatches the job and the same happens again.

**Fix:** run the pinned default (`quay.io/zebbra/neops-workflow-engine:0.42.2-beta.3`) — do not override `NEOPS_WORKFLOW_ENGINE_IMAGE` with an older tag. `make images-check` reports the engine's status.

---

## Devices never become reachable

**Where:** `wait_devices` times out — `timeout: 172.30.0.31:22, … not reachable within 240s`.

**Cause:** devices boot slower than `containerlab deploy` returns. FRR is up in a second or two; Nokia SR Linux takes tens of seconds to bring up its management stack. Running discovery before then makes those hosts fail with a connection error and drop out of the 15-device count.

**The guard:** `make local-lab-up` deploys containerlab *early* — before the worker-readiness wait — precisely so SR Linux boot time overlaps with something useful, then polls TCP 22 on every mgmt IP.

!!! important "The poll runs from *inside* the lab network, on purpose"
    ```bash
    docker compose exec -T worker python3 lab/wait_devices
    ```

    Not from the host. On macOS and Docker Desktop the host has **no route** to
    the `lab-net` bridge IPs (`172.30.0.0/24`), so a host-side poll hangs until
    timeout even when every device is perfectly healthy. The worker is on
    `lab-net`, so container-to-container reachability — the same path discovery
    actually uses — works on every platform.

    This is also why the command carries a `lab/` prefix: the repo is mounted
    at `/app/lab` inside the worker.

**Fix:** give it more time — `make local-lab-up WAIT_DEVICES_TIMEOUT=600` (a Docker Desktop VM booting 5 SR Linux nodes can genuinely need it) — or check the device itself:

```bash
docker logs spine-01
./containerlab inspect -t generated/neops-lab.clab.json
```

!!! warning "Never replace a wait with a `sleep`"
    Each of the three waits exists because of a real, reproduced failure. A
    fixed sleep is both slower on a fast machine and still racy on a slow one.

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

**Cause:** `cms/oidc-config.json` must contain at least one well-formed `OpenIdConfiguration` entry with **inline** `authWellknownEndpoints` (no network discovery). The web client calls `OidcSecurityService.checkAuth()` in an `APP_INITIALIZER`; a `null` or `[]` config makes it fail before anything renders. The CMS serves the file through its `appSettings.oidcConfig` GraphQL resolver, so a missing `OIDC_CONFIG_PATH` produces the same result.

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

## `containerlab deploy` says it requires root privileges (Linux)

**Cause:** the native containerlab is not set up for sudo-less operation. The make targets never call `sudo`.

**Fix:** see [Prerequisites](../getting-started/10-prerequisites.md#linux-sudo-less-operation), then confirm with the two-node probe:

```bash
./containerlab deploy  -t clab/probe.clab.yml
./containerlab destroy -t clab/probe.clab.yml --cleanup
```

---

## `containerlab: command not found` (Linux) / container mode questions (macOS)

Everything calls `./containerlab`, the repo's launcher. On **Linux** it exec's a native binary and fails like this when there is none — install containerlab natively ([Prerequisites](../getting-started/10-prerequisites.md#containerlab-one-command-on-both-hosts)); `CLAB_IN_DOCKER=1` forces container mode if you really want it (root-owned files under `generated/`, SELinux `:z` caveats). On **macOS** it always uses container mode (`ghcr.io/srl-labs/clab`, pinned via `CLAB_IMAGE`). If a deploy fails with an empty `.iface` bind or "topology file not found" on a Mac, the checkout is outside Docker Desktop's shared paths or its path contains spaces — `make doctor` catches both. Device access on a Mac is `docker exec <node>`; the host has no route to `172.30.0.0/24` and containerlab's `/etc/hosts`/ssh-config entries stay inside the ephemeral clab container.

---

## Duplicate interface rows after re-running discovery

**Cause:** devices are keyed by IP so they are skipped on a second run, but **interfaces are always recorded**.

**Fix:** run discovery against a fresh CMS.

```bash
make local-lab-down local-env-prune
make local-env-init && make local-lab-up && make local-lab-discover
```

---

## Nothing works and you want to start over

```bash
make local-lab-down local-env-prune
make local-env-init && make local-lab-up && make local-lab-discover
```

`local-lab-down` tolerates there being no deployed lab (the `./containerlab destroy` line is prefixed with `-`, so `make` continues on failure) and removes `lab-net`. `local-env-prune` drops the Elasticsearch and Postgres volumes (and `lab-net`) — leftover volume state across down/up cycles has previously made `elastic_index --create` fail and stale CMS data confuse re-inits.
