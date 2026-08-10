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

A `python:3.12-slim` image with `pyyaml` and `requests`, whose entrypoint is `register.py`. It runs once per `docker compose up`, POSTs every `workflows/*.yaml` to the engine's `/workflow-definition`, and exits. `docker compose wait lab_bootstrap` in `local-lab-up` blocks on that exit and propagates the code.

## Pulled — the NeOps control plane

| Service | Default image | Override with |
|---|---|---|
| `cms` | `quay.io/zebbra/neops-cms-free:develop` | — (not overridable) |
| `workflow_engine`, `workflow-engine-client` | `quay.io/zebbra/neops-workflow-engine:develop` | `NEOPS_WORKFLOW_ENGINE_IMAGE` |
| `web_client` | `quay.io/zebbra/neops-web-client:develop` | `NEOPS_WEB_CLIENT_IMAGE` |
| `worker` | `quay.io/zebbra/neops-worker-sdk:develop` | `NEOPS_WORKER_SDK_IMAGE` |

Plus third-party images that need no credentials: `postgres:15-alpine`, `redis:5-alpine`, `docker.elastic.co/elasticsearch/elasticsearch:8.9.2`, `busybox`, and `ghcr.io/nokia/srlinux:26.3` for the SR Linux devices.

`quay.io/zebbra` is private — `docker login quay.io` first.

## Running a locally-built image

Copy `.env.example` to `.env` (docker compose reads `.env` automatically) or export the variable:

```bash
export NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest
make local-lab-up
```

Each overridable service also sets `pull_policy: ${NEOPS_*_PULL_POLICY:-missing}`. `missing` means an image already present locally is used as-is, with no registry call — which is exactly what makes a local tag work.

!!! warning "`docker compose pull` fails on a local tag"
    A tag with no registry host resolves as `docker.io/library/…`, which does
    not exist. The explicit `docker compose pull` inside `make local-env-init`
    and `make local-env-up` therefore fails. Run that step yourself with
    `--ignore-pull-failures` when you override an image this way; `up -d` is
    unaffected.

### Why you would

- **Worker SDK** — the most common case. The lab depends on `fb.base.neops.io/global_discover_network:0.1.0` shipping inside the worker image; point `NEOPS_WORKER_SDK_IMAGE` at a local build to exercise a function-block change before it is released.
- **Workflow engine** — discovery emits a few hundred `Interface` rows in one job result, so it needs an engine with the large-payload and reference-resolution fixes. If the published `develop` tag lags, run a local build.
- **Web client** — to preview UI changes against a populated CMS.

## Verifying what you are running

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.worker.yml
docker compose images                       # image + tag per service
docker compose exec worker ls /app/neops/fb # base function blocks in the image
docker compose exec worker ls /app/lab      # this repo, through the read-only mount
```
