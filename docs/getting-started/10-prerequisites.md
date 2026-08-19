---
title: Prerequisites
description: What your host needs before the first make target — Docker, containerlab with sudo-less operation, openssl, uv, and Quay pull access.
tags: [tutorial, setup]
---

# Prerequisites

*Check these first. Every one of them fails late and confusingly if you skip it.*

## Host requirements

| Requirement | Why | Used by |
|---|---|---|
| **Docker** + `docker compose` | The whole control plane and every device container | everything |
| **containerlab** | Wires real veth links via network namespaces — Linux only | `make local-lab-up` |
| **`openssl`** | Mints the dev RSA keypair the CMS needs for RS256 JWTs | `make lab-jwt` |
| **`uv`** | Runs ruff / pyrefly / pytest and the MkDocs tooling | `make check`, `make doc-*` |
| **Quay pull access** | The CMS, engine, web client and worker images are private | `make local-env-init` |
| **RAM/CPU** | The 5 SR Linux nodes are hungry — budget a few GB | `make local-lab-up` |

!!! note "The lab scripts themselves need nothing but `python3`"
    `gen_clab_topology`, `gen_device_configs`, `run_workflow`, `wait_ready` and
    `wait_devices` are **stdlib-only** on purpose: they run on a bare host
    before any virtualenv exists. `uv` is only needed for the dev tooling, not
    to run the lab.

## containerlab and sudo-less operation

containerlab creates network namespaces and veth pairs, so it needs privileges. The make targets call `containerlab deploy` directly, with no `sudo`, so it must work password-free:

```bash
sudo usermod -aG clab_admins $USER          # then re-login for the group to apply
sudo chown root:root "$(command -v containerlab)"
sudo chmod 4755 "$(command -v containerlab)" # SUID -> -rwsr-xr-x
```

`make clab-suid` does the SUID half for you: idempotent, it prompts for sudo
only when the bit is actually missing, and warns if you are not in
`clab_admins`.

!!! warning "Re-run `make clab-suid` after every containerlab upgrade"
    A package upgrade replaces the binary and silently drops the SUID bit.
    The next `make local-lab-up` then fails with *"This containerlab command
    requires root privileges or root via SUID to run"* — group membership
    survives the upgrade, so `id` looks fine and only the file mode gives it
    away.

Verify the SUID bit is set:

```bash
ls -l "$(command -v containerlab)"   # expect -rwsr-xr-x
```

### Prove it works before the 15-node deploy

The repo ships a two-node probe so you can confirm privileges *and* that a `linux`-kind FRR node accepts a `swpN` interface over a real veth link — without pulling the whole stack:

```yaml title="clab/probe.clab.yml"
--8<-- "../clab/probe.clab.yml"
```

```bash
containerlab deploy  -t clab/probe.clab.yml
containerlab destroy -t clab/probe.clab.yml
```

A successful deploy means containerlab is ready. The failure you are checking for is `... requires root privileges`.

!!! warning "Linux only"
    containerlab wires veths through Linux network namespaces. The lab's
    control plane runs anywhere Docker does, but the 15 devices do not come up
    on macOS or Windows. Where macOS *does* still matter is the
    [device-readiness poll](../20-operations/40-troubleshooting.md#devices-never-become-reachable),
    which deliberately runs from inside the lab network for exactly this
    class of reason.

## Registry access

The lab is a **consumer of published images**. Four of the services pull from `quay.io/zebbra`, which is a **private** organisation — an anonymous pull is rejected with `401`:

```bash
docker login quay.io
```

| Image | Service |
|---|---|
| `quay.io/zebbra/neops-cms-free:develop` | `cms` |
| `quay.io/zebbra/neops-workflow-engine:develop` | `workflow_engine`, `workflow-engine-client` |
| `quay.io/zebbra/neops-web-client:develop` | `web_client` |
| `quay.io/zebbra/neops-worker-sdk:develop` | `worker` |

`ghcr.io/nokia/srlinux:26.3` (the SR Linux devices) is public and needs no login.

!!! tip "`NPM_TOKEN` is **not** needed here"
    Most NeOps repos require an `NPM_TOKEN` with `read:packages` to install
    `@zebbra/*` npm packages. This repo installs no npm packages and publishes
    nothing — Quay credentials are the only registry access it needs. (In the
    shared dev environment `NPM_TOKEN` and `PYPI_TOKEN` are exported anyway;
    they are simply unused by this lab.)

## Running locally-built images instead

Every published image can be swapped for a local tag through an environment variable — this is how you exercise an unreleased engine or worker against the lab. Copy `.env.example` to `.env` and uncomment what you need:

| Variable | Default |
|---|---|
| `NEOPS_WORKFLOW_ENGINE_IMAGE` | `quay.io/zebbra/neops-workflow-engine:develop` |
| `NEOPS_WEB_CLIENT_IMAGE` | `quay.io/zebbra/neops-web-client:develop` |
| `NEOPS_WORKER_SDK_IMAGE` | `quay.io/zebbra/neops-worker-sdk:develop` |

```bash
export NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest
```

!!! warning "A local tag breaks the explicit `docker compose pull` step"
    A tag with no registry host (`neops-worker-sdk:latest`) resolves as
    `docker.io/library/neops-worker-sdk:latest`, which does not exist, so the
    `docker compose pull` inside `make local-env-init` / `make local-env-up`
    **fails**. Run that step yourself with `--ignore-pull-failures` when you
    override an image this way.

    `docker compose up -d` is unaffected: every overridable service sets
    `pull_policy: missing` (itself overridable via `NEOPS_*_PULL_POLICY`), so a
    local image that is already present is used without contacting any
    registry.

## Files the lab needs but does not ship

Two things are git-ignored and created for you on first run. If either is missing the stack does not start:

- **`cms/jwt/{private,public}.pem`** — dev-only RSA keypair minted by `make lab-jwt`. Newer `neops-cms-free` images require it for RS256 JWT issuance and crash at startup (`token_service check_keys`) without it. Idempotent, so re-running never invalidates issued tokens. These are throwaway lab credentials, never secrets.
- **`cms_api_key.env`** — the CMS API key the workflow engine authenticates with, minted by `make local-env-init`.

`make local-env-init` depends on `lab-jwt`, so in practice you only run the four quickstart commands.

## Next

[Quickstart :material-arrow-right:](20-quickstart.md)
