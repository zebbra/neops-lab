---
title: The /app/lab mount
description: The repo is bind-mounted read-only at /app/lab inside the worker, which is why in-container paths keep a lab/ prefix while host paths never do.
tags: [concept, gotcha]
---

# The `/app/lab` mount

*The single most confusing thing about this repo. Read this once and the stray `lab/` prefixes stop looking like typos.*

## The rule

**The whole repo is bind-mounted read-only into the worker container at `/app/lab`.**

```yaml title="docker-compose.worker.yml (excerpt)"
volumes:
  - .:/app/lab:ro
```

The worker SDK image's WORKDIR is `/app`. So a path that the *worker* resolves is relative to `/app` and needs a `lab/` prefix to reach into this repo; a path that the *host* resolves is relative to the repo root and must not have one.

| Context | Path | Correct? |
|---|---|---|
| `Makefile` recipe, host shell | `./gen_clab_topology` | ✅ |
| `Makefile` recipe, host shell | `./lab/gen_clab_topology` | ❌ |
| `docker compose exec worker python3 …` | `lab/wait_devices` | ✅ |
| `docker compose exec worker python3 …` | `wait_devices` | ❌ |
| env var read **by the container** | `DIR_FUNCTION_BLOCKS: lab/function_blocks,neops/fb` | ✅ |
| env var read by the host | anything with `lab/` | ❌ |

Put plainly: **a `lab/` inside a `docker compose exec` or a container-read env var is correct; a `lab/` in a Makefile recipe or a host script is a bug.**

## Why it exists

This repo was extracted from `neops-worker-sdk-py/lab/`. In the SDK repo the lab genuinely *was* a subdirectory called `lab/`, and the mount reproduced that path inside the container. When the directory became its own repository, its contents were flattened to the repo root — **there is no `lab/` subdirectory here any more** — but the mount point stayed `/app/lab`, because the in-container layout is what `DIR_FUNCTION_BLOCKS` and every `exec` line depend on.

The result is an asymmetry that looks like an inconsistency and is not.

## Where you meet it

**`DIR_FUNCTION_BLOCKS`** — the worker's function-block search path, `lab/function_blocks,neops/fb`. The first entry is this repo's `function_blocks/` through the mount; the second is `/app/neops/fb`, baked into the image. See [Discovery](30-discovery.md).

**Device readiness** — `make local-lab-up` and `make local-lab-discover` both run:

```bash
docker compose exec -T worker python3 lab/wait_devices
```

That is *this repo's* `wait_devices` script, executed inside the worker container. It runs there rather than on the host for a network reason, not a path reason — see [Troubleshooting](../20-operations/40-troubleshooting.md#devices-never-become-reachable).

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
    docker compose exec worker ls /app/neops/fb
    docker compose exec worker ls /app/lab
    ```

    The first lists what the image ships; the second should show this repo's
    root — `topology.json`, `function_blocks/`, `wait_devices`, and so on.
