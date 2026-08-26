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
export COMPOSE_FILE=docker-compose.yml:docker-compose.worker.yml
docker compose ps                 # what is running, what exited
make local-lab-logs               # worker + lab_bootstrap, followed
docker compose logs cms           # CMS startup crashes land here
./containerlab inspect -t generated/neops-lab.clab.json
```

Without `COMPOSE_FILE` exported, plain `docker compose` commands do not see the `worker` or `lab_bootstrap` services — the base compose file does not declare them. The make targets set it themselves.

---

## `Pool overlaps with other one on this address space`

**Where:** `docker compose up`, creating `lab-net` or the project `default` network.

**Cause:** another docker network overlaps `172.30.0.0/23`. On a host with many compose projects docker's auto-assigned `/16` blocks run out and some other project's `default` network landed on `172.30.0.0/16` before the lab's networks existed. (The lab's own networks all carry fixed subnets, so they never compete with each other.)

**Fix:** `make doctor` names the overlapping network. If it is an unused leftover (`docker network inspect <name>` shows no containers): `docker network rm <name>` — the owning project's next `up` recreates it. If it is genuinely in use, stop that stack first.

---

## `Workflow with ID null not found`

**Where:** the engine, when you trigger discovery.

**Cause:** the workflow definition has not been registered yet. `docker compose up -d` returns once containers are *Started*, not *Completed*, and `lab_bootstrap` is a one-shot container that POSTs the definitions and exits.

**The guard:** `make local-lab-up` runs `docker compose wait lab_bootstrap`, which blocks until that container exits and propagates its exit code — so a failed registration fails the target instead of silently producing this error later.

**Fix:** let `make local-lab-up` finish before running discovery. If the container exited non-zero, read its log:

```bash
docker compose logs lab_bootstrap
```

`200 unchanged` is the idempotent re-run. A `409` means the version in the YAML already exists with different content — bump `patchVersion`/`minorVersion` (the log prints the engine's `suggestedVersion`); a `404` on `/workflow-definition/publish` means an engine older than `0.42.2-beta.3`.

---

## Discovery stays `running`, the worker log says `413 Payload Too Large`

**Where:** `make local-lab-discover` after the worker discovered every device (`Generated 448 db update(s)`) and then `Failed to push job result … (413)`.

**Cause:** an engine image without the raised per-route body limits (older than `0.42.2-beta.3`). Discovery returns a few hundred `Interface` rows in one job result; the engine rejects the push and re-dispatches the job.

**Fix:** refresh the engine — `make local-env-up` pulls with `--policy always`, and the default `develop` tag is rebuilt on every merge to the engine's develop branch.

---

## `Function block … not found`

**Where:** the execution's terminal state, as `failed_safe_ack — Function block with id fb.base.neops.io/global_discover_network:0.1.0 not found`.

**Two different causes, in order of likelihood:**

1. **You raced the worker.** The worker registers its function blocks with the engine *asynchronously* after its container starts. `make local-lab-up` and `make local-lab-discover` both run `./wait_ready fb.base.neops.io/global_discover_network:0.1.0` first, which polls the engine's per-function-block worker registry until an online worker exists. Run the make target rather than `run_workflow` directly.

2. **The image does not carry the block.** `neops/fb` ships *inside* the `neops-worker-sdk` image; it is not mounted from this repo. Check what you are running:

    ```bash
    docker compose exec worker ls /app/neops/fb
    ```

    ⚠️ The published `quay.io/zebbra/neops-worker-sdk:develop` tag **does not carry it** — see the next entry.

See [Discovery](../10-concepts/30-discovery.md) and [The `/app/lab` mount](../10-concepts/40-container-paths.md).

---

## The worker container exits immediately / `no online worker` at `wait_ready`

**Where:** `make local-lab-up` burns its full `wait_ready` budget and gives up with

```
timeout: no online worker for fb.base.neops.io/global_discover_network:0.1.0 within 180s
```

and `docker compose logs worker` ends in

```
OSError: Readme file does not exist: README.md
```

**Cause:** you are running the published `quay.io/zebbra/neops-worker-sdk:develop`
image. It is built from `neops-worker-sdk-py`'s `develop` branch, where `neops/`
contains only `.gitkeep` files and the Dockerfile copies neither `neops/` nor
`README.md`. `CMD ["uv", "run", "neops_worker"]` installs the project at container
start, hatchling reads `readme = "README.md"`, and the container dies before the
worker ever connects. Even if it started, it would register no function blocks.

**Fix:** build the image from the SDK branch that has the function blocks
(open PR [zebbra/neops-worker-sdk-py#127](https://github.com/zebbra/neops-worker-sdk-py/pull/127))
and point the lab at it:

```bash
git -C ../neops-worker-sdk-py switch feature/technopark
make -C ../neops-worker-sdk-py build-docker          # -> neops-worker-sdk:latest
docker run --rm --entrypoint sh neops-worker-sdk:latest -c 'ls neops/fb/base/global'
echo 'NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest' >> .env
make local-lab-up
```

This entry disappears once #127 merges and CI republishes the `develop` tag.

---

## `bootstrap` fails with `404` or `409` on the workflow definition

**Where:** `docker compose wait lab_bootstrap` returns non-zero and
`docker compose logs lab_bootstrap` shows a `FAILED` line.

- **`409`** — the version already exists with *different* content. Published
  workflow definitions are **immutable**; editing `workflows/*.yaml` in place and
  re-running is exactly what triggers this. Bump
  `majorVersion`/`minorVersion`/`patchVersion` in the YAML, and update the
  matching `wf.lab.neops.io/simple_lab_discovery:<version>` in the `Makefile`'s
  `local-lab-discover` recipe.
- **`422`** — the document is publishable but the engine computed a higher
  version floor than the document declares. Raise the version.
- **A `404` handled silently** — the engine predates
  [`068753a0`](https://github.com/zebbra/neops-workflow-engine/commit/068753a0)
  and has no `/workflow-definition/publish`; `register.py` falls back to the
  legacy `POST /workflow-definition`. Nothing to fix, but you are on an old
  engine image.

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

**Fix:** give it more time (`./wait_devices --timeout 600` from inside the worker), or check the device itself:

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

## `containerlab deploy` fails to start or cannot reach docker

**Cause:** `./containerlab` runs containerlab in a container through the docker socket; it needs a rootful docker daemon and, on Docker Desktop, the repo under a shared path. `make doctor` checks both.

With `CLAB_NATIVE` (a host binary) the classic failure is *"This containerlab command requires root privileges or root via SUID to run"* — usually after a **containerlab upgrade**: the new binary is installed without the SUID bit while your `clab_admins` membership survives, so `id` still looks right and only `ls -l "$(command -v containerlab)"` shows the missing `s`. `make clab-suid` restores it (idempotent).

**Fix:** `make doctor`, or `make clab-suid` for the native path; details in [Prerequisites](../getting-started/10-prerequisites.md#containerlab--one-command-both-hosts-no-install). Then confirm with the two-node probe:

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
make local-env-init && make local-lab-up && make local-lab-discover
```

---

## Nothing works and you want to start over

```bash
make local-lab-down local-env-prune
make local-env-init && make local-lab-up && make local-lab-discover
```

`local-lab-down` tolerates there being no deployed lab (the `./containerlab destroy` line is prefixed with `-`, so `make` continues on failure). `local-env-prune` drops the Elasticsearch and Postgres volumes — leftover volume state across down/up cycles has previously made `elastic_index --create` fail and stale CMS data confuse re-inits.
