---
title: Images
description: The two local-only images this repo builds, the four published images it consumes, and how to swap any of them for a local build.
tags: [operations, docker]
---

# Images

*This repo builds two images and publishes neither. Everything else is pulled.*

## Built here — local tags only

```bash
make build-docker
```

| Image | Built from | Used by |
|---|---|---|
| `neops-lab-frr:latest` | `devices/frr/` | containerlab, as the image for every `kind: linux` node |
| `neops-lab-bootstrap:latest` | `bootstrap/` | the `lab_bootstrap` compose service |

!!! warning "Nothing is pushed to a registry"
    Both images are **local tags only**. Every machine that runs the lab builds
    them itself. There is no `quay.io/zebbra/neops-lab-*`, and there is no
    publish pipeline in this repo.

    `docker-compose.worker.yml` pins `lab_bootstrap` to the exact tag
    `neops-lab-bootstrap:latest` *and* declares `build: ./bootstrap`, so the
    compose build and `make build-docker` cannot drift apart.

`make build-docker` is a prerequisite of `make local-lab-up`, so in normal use you never call it directly. CI runs it as a separate job (on the `hetzner` runner) purely so a broken Dockerfile fails in CI instead of on a developer's first lab bring-up.

### `neops-lab-frr`

`frrouting/frr:v8.4.1` plus an SSH server and an `frr` / `frr` login, because discovery reaches devices over SSH:

- `openssh` with `PasswordAuthentication yes` and `PermitRootLogin no`
- the `frr` user gets a home directory, a shell, and membership in `frrvty`
- `frr.conf` and `daemons` are baked in (`zebra`, `ospfd` and `vtysh` enabled; everything else off)
- the entrypoint rewrites the hostname into `frr.conf`, seeds `/etc/machine-id`, starts `sshd`, then hands off to FRR's own `docker-start`

!!! danger "The FRR image needs `NET_ADMIN` **and** `SYS_ADMIN`"
    The FRR binary refuses to start without `cap_sys_admin`, even with no VRFs
    configured. containerlab grants both capabilities to `kind: linux` nodes,
    which is why this works under `containerlab deploy` — if you ever run the
    image by hand with plain `docker run`, you must add them yourself.

Interface *descriptions* are not baked into the image: containerlab `exec`s `devices/frr/set-aliases.sh` after the links are wired, which sets each interface's Linux alias from the generated `.iface` file. See [Topology as source of truth](../10-concepts/20-topology.md).

### `neops-lab-bootstrap`

A `python:3.12-slim` image with `pyyaml` and `requests`, whose entrypoint is `register.py`. It runs once per `docker compose up`, publishes every `workflows/*.yaml` to the engine through `POST /workflow-definition/publish`, and exits. `docker compose wait lab_bootstrap` in `local-lab-up` blocks on that exit and propagates the code.

!!! info "Publish semantics — 200 is idempotent, 409 is a real conflict"
    Under the engine's publish API a `200 unchanged` means this exact document
    is already published at the version it declares — the idempotent re-run.
    A **409** means that version already exists *with different content*:
    someone edited the YAML without bumping its version. `register.py` treats
    that as a hard failure and prints the engine's `suggestedVersion`, because
    skipping it would silently run the old definition. A **422** means the
    bump is smaller than the change warrants. Engines older than
    `0.42.2-beta.3` answer 404 for the publish route; `register.py` then falls
    back to the legacy `POST /workflow-definition`, where 409 *is* the
    idempotent case.

## Pulled — the NeOps control plane

| Service | Default image | Override with |
|---|---|---|
| `cms` | `quay.io/zebbra/neops-cms-free:develop` | `NEOPS_CMS_IMAGE` |
| `workflow_engine`, `workflow-engine-client` | `quay.io/zebbra/neops-workflow-engine:0.42.2-beta.3` (**pinned**) | `NEOPS_WORKFLOW_ENGINE_IMAGE` |
| `web_client` | `quay.io/zebbra/neops-web-client:develop` | `NEOPS_WEB_CLIENT_IMAGE` |
| `worker` | `quay.io/zebbra/neops-worker-sdk:develop` (**does not run the lab today** — see below) | `NEOPS_WORKER_SDK_IMAGE` |

Plus third-party images that need no credentials: `postgres:15-alpine`, `redis:7-alpine`, `docker.elastic.co/elasticsearch/elasticsearch:8.9.2`, `busybox`, `ghcr.io/nokia/srlinux:26.3` for the SR Linux devices, and `ghcr.io/srl-labs/clab` for container-mode containerlab on macOS.

`quay.io/zebbra` is private — `docker login quay.io` first. All four `quay.io/zebbra` images are amd64-only; on Apple Silicon they run under Rosetta.

## Image compatibility

The lab needs specific features from two of the published images. **`make images-check`** verifies the images you are configured to run — without deploying anything — and the defaults are chosen accordingly:

| Image | Needs | Default |
|---|---|---|
| **Workflow engine** | the raised per-route body limits — discovery emits a few hundred `Interface` rows in one job result and older engines reject it with **413**; and `POST /workflow-definition/publish` (the legacy `POST /workflow-definition` was removed from the engine on 2026-07-30 — `register.py` still falls back to it on 404) | `0.42.2-beta.3`, the first published tag with both. Quay's `develop` tag has lagged the branch by weeks, which is why the lab does not float on it. |
| **Worker** | `/app/neops/fb` with `fb.base.neops.io/global_discover_network:0.1.0`, and an image that can start | **No published tag qualifies as of August 2026.** The discovery block is only on unmerged `neops-worker-sdk-py` branches and the current `develop` image cannot start (`uv run` at container start rebuilds the project and fails on a missing `README.md`). Build one from a checkout that has it: `make build-worker-image SDK_DIR=../neops-worker-sdk-py`, then `NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest`. |
| CMS, web client | — | `develop` works as published. |

!!! warning "The worker image is refreshed by `local-lab-up`, not by `local-env-init`"
    `local-env-init` / `local-env-up` pull with the *base* compose file, which
    does not know the worker. `local-lab-up` runs `docker compose pull worker`
    (with `--ignore-pull-failures`, so a local tag is a warning) before `up`.

## Running a locally-built image

Copy `.env.example` to `.env` (docker compose reads `.env` automatically) or export the variable:

```bash
export NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest
make local-lab-up
```

Each overridable service also sets `pull_policy: ${NEOPS_*_PULL_POLICY:-missing}`. `missing` means an image already present locally is used as-is, with no registry call — which is exactly what makes a local tag work.

!!! note "`docker compose pull` warns on a local tag"
    A tag with no registry host resolves as `docker.io/library/…`, which does
    not exist. The explicit `docker compose pull` steps inside
    `local-env-init`, `local-env-up` and `local-lab-up` all run with
    `--ignore-pull-failures`, so an override like this is a warning, not an
    error; `up -d` uses the local image (`pull_policy: missing`).

### Why you would

- **Worker SDK** — required today (see above), and the usual way to exercise a function-block change before it is released. `make build-worker-image` builds it from a local checkout.
- **Workflow engine** — to try an engine change before it is tagged; the pinned default already has the large-payload fix and the publish API.
- **CMS / web client** — to preview backend or UI changes against a populated CMS.

## Verifying what you are running

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.worker.yml
docker compose images                       # image + tag per service
docker compose exec worker ls /app/neops/fb # base function blocks in the image
docker compose exec worker ls /app/lab      # this repo, through the read-only mount
```
