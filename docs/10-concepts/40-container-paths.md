---
title: The /app/lab mount
description: The repo is bind-mounted read-only at /app/lab inside the worker, which is why in-container paths keep a lab/ prefix while host paths never do.
tags: [concept, gotcha]
---

# The `/app/lab` mount

*The single most confusing thing about this repo. Read this once and the stray `lab/` prefixes stop looking like typos.*

## The rule

**The whole repo is bind-mounted read-only into the worker container at `/app/lab`.**

```yaml title="docker-compose.yml — the worker service (excerpt)"
volumes:
  - .:/app/lab:ro
```

The worker SDK image's WORKDIR is `/app`. So a path that the *worker* resolves is relative to `/app` and needs a `lab/` prefix to reach into this repo; a path that the *host* resolves is relative to the repo root and must not have one.

| Context | Path | Correct? |
|---|---|---|
| `Makefile` recipe, host shell | `./gen_clab_topology` | ✅ |
| `Makefile` recipe, host shell | `./lab/gen_clab_topology` | ❌ |
| `docker compose exec worker ls …` | `lab/scenarios` | ✅ |
| `docker compose exec worker ls …` | `scenarios` | ❌ |
| env var read **by the container** | `DIR_FUNCTION_BLOCKS: lab/generated/${SCENARIO}/scenario/function_blocks,neops/fb` | ✅ |
| env var read by the host | anything with `lab/` | ❌ |
| compose bind **source** (host side) | `./generated/${SCENARIO}/scenario/workflows` | ✅ |

Put plainly: **a `lab/` inside a `docker compose exec` into the worker, or in a container-read env var, is correct; a `lab/` in a Makefile recipe or a host script is a bug.**

!!! note "The rule is about *this* mount, not about containers in general"
    `/app/lab` is the worker's mount point, and nothing else in the lab uses it.
    The throwaway container `wait_devices` runs in mounts the repo at `/lab`
    with `-w /lab`, so it is invoked as plain `python3 wait_devices`; the
    containerlab device binds land at `/lab` too. A `lab/` prefix outside the
    worker is as wrong as one on the host.

## Why it exists

This repo was extracted from `neops-worker-sdk-py/lab/`. In the SDK repo the lab genuinely *was* a subdirectory called `lab/`, and the mount reproduced that path inside the container. When the directory became its own repository, its contents were flattened to the repo root — **there is no `lab/` subdirectory here any more** — but the mount point stayed `/app/lab`, because the in-container layout is what `DIR_FUNCTION_BLOCKS` and every `exec` line depend on.

The result is an asymmetry that looks like an inconsistency and is not.

## Where you meet it

**`DIR_FUNCTION_BLOCKS`** — the worker's function-block search path, `lab/generated/${SCENARIO}/scenario/function_blocks,neops/fb`. The first entry is the resolved [scenario](../30-scenarios/index.md) tree through the mount; the second is `/app/neops/fb`, baked into the image. See [Discovery](30-discovery.md).

!!! note "The resolved scenario is inside the repo, which is why this works"
    `make scenario-resolve` materialises `scenarios/_base` + `scenarios/$SCENARIO`
    into `generated/$SCENARIO/scenario/` — under the repo root, so the whole-repo
    mount carries it into the container for free. Only the prefix differs:
    `generated/…` on the host, `lab/generated/…` inside the worker. The rule is
    unchanged; the path simply got longer.

**Device readiness used to be the other example, and no longer is.** `make local-lab-up` and `make discover` both wait for device SSH, but they do it in a throwaway `python:3.12-slim` container attached to `lab-net`:

```bash
docker run --rm --network lab-net -v "$PWD:/lab:ro" -w /lab \
  -e SCENARIO=$SCENARIO python:3.12-slim python3 wait_devices
```

It runs in a container rather than on the host for a network reason — on macOS/Docker Desktop the host has no route to `172.30.0.0/24` — see [Troubleshooting](../20-operations/40-troubleshooting.md#devices-never-become-reachable). It used to run as `docker compose exec worker python3 lab/wait_devices`, which made a *device* wait require a running control plane; the worker did no part of the check and was borrowed for its network attachment alone.

## Two consequences worth knowing

!!! warning "The mount is read-only"
    `:ro`. A function block cannot write into the repo from inside the worker,
    and neither can anything else in that container. Generated output belongs
    in `generated/`, written by the **host** script.

!!! note "`neops/fb` is not mounted from here"
    The base function blocks come from the image, not from this repo. If
    discovery fails with `Function block … not found`, the question is not
    "is my mount right" but "does the `NEOPS_WORKER_SDK_IMAGE` I pinned carry
    `/app/neops/fb`".

    ```bash
    export SCENARIO=wan-and-fabric   # or run these through make
    docker compose exec worker ls /app/neops/fb
    docker compose exec worker ls /app/lab
    ```

    The first lists what the image ships; the second should show this repo's
    root — `scenarios/`, `generated/`, `wait_devices`, and so on.
