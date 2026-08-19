---
title: Prerequisites
description: What your host needs before the first make target — Docker, containerlab (native on Linux, container mode on macOS), openssl, python3, RAM, and Quay pull access — and the preflight that checks it all.
tags: [tutorial, setup]
---

# Prerequisites

*Check these first. Every one of them fails late and confusingly if you skip it — which is exactly why `make doctor` exists.*

## Run the preflight

```bash
make doctor
```

Read-only. It checks everything on this page the way the make targets will use it and prints the fix next to each failure: docker and compose versions, the RAM/CPUs docker actually has, amd64 emulation on Apple Silicon, whether the repo path bind-mounts cleanly, which containerlab mode will be used, `python3`/`openssl`, free ports, docker networks overlapping `lab-net`, and Quay access.

## Supported hosts

| Host | containerlab | Notes |
|---|---|---|
| **Linux** | native binary, sudo-less (below) | The reference environment |
| **macOS** (Apple Silicon or Intel) | container mode via `./containerlab` — nothing to install | Docker Desktop is the tested runtime; OrbStack should behave the same. See [macOS notes](#macos-notes) |

## Host requirements

| Requirement | Why | Used by |
|---|---|---|
| **Docker** + `docker compose` **≥ 2.20** | The whole control plane and every device container; `docker compose wait` needs 2.20 | everything |
| **containerlab** through `./containerlab` | Wires real veth links via network namespaces | `make local-lab-up`, the probe, `inspect` |
| **`openssl`** | Mints the dev RSA keypair the CMS needs for RS256 JWTs (OpenSSL 3 or the LibreSSL a stock macOS ships) | `make lab-jwt` |
| **`python3` ≥ 3.9** | The host scripts are stdlib-only and import under a stock macOS `/usr/bin/python3` | `gen_clab_topology`, `run_workflow`, `wait_ready` |
| **`uv`** | Runs ruff / pyrefly / pytest and the MkDocs tooling | `make check`, `make doc-*` |
| **Quay pull access** | The CMS, engine, web client and worker images are private | `make local-env-init` |
| **RAM/CPU** | 5 SR Linux nodes (≈1.5–2 GB each) + Elasticsearch + control plane ≈ **14–16 GB** for containers | `make local-lab-up` |
| **Images that can run the lab** | The engine is pinned; the worker currently needs a local build | see [Images](../20-operations/20-images.md#image-compatibility) |

!!! note "The lab scripts themselves need nothing but `python3`"
    `gen_clab_topology`, `gen_device_configs`, `run_workflow`, `wait_ready` and
    `wait_devices` are **stdlib-only** on purpose: they run on a bare host
    before any virtualenv exists — and they carry `from __future__ import
    annotations` so that a stock macOS Python 3.9 imports them. `uv` is only
    needed for the dev tooling, not to run the lab.

## containerlab: one command on both hosts

Every make target and every command in these docs calls **`./containerlab`**, a small launcher committed at the repo root:

- If a native `containerlab` is on `PATH`, it is `exec`'d unchanged — on Linux the launcher adds nothing.
- On macOS (or anywhere with `CLAB_IN_DOCKER=1`) it runs the official `ghcr.io/srl-labs/clab` image **in container mode**: privileged, in the docker daemon's network and PID namespaces, with the repo mounted at the same absolute path. There is no containerlab binary for macOS and never will be — it needs Linux netlink and network namespaces — and on Docker Desktop / OrbStack the daemon lives in a Linux VM, so this is how containerlab documents running there. Pin a version with `CLAB_IMAGE=ghcr.io/srl-labs/clab:<version>`.
- On Linux **without** a native install it fails exactly like a missing binary would, plus a hint. Container mode is deliberately not the silent default there: it swaps the SUID model for docker-socket root, needs `:z` binds under SELinux, and leaves root-owned files under `generated/`.

### Linux: sudo-less operation

containerlab creates network namespaces and veth pairs, so it needs privileges. The make targets call it with no `sudo`, so it must work password-free:

```bash
sudo usermod -aG clab_admins $USER          # then re-login for the group to apply
sudo chown root:root "$(command -v containerlab)"
sudo chmod 4755 "$(command -v containerlab)" # SUID -> -rwsr-xr-x
```

Verify the SUID bit is set:

```bash
ls -l "$(command -v containerlab)"   # expect -rwsr-xr-x
```

### Prove it works before the 15-node deploy

The repo ships a two-node probe so you can confirm privileges (Linux) or container mode (macOS) *and* that a `linux`-kind FRR node accepts a `swpN` interface over a real veth link — without pulling the whole stack:

```yaml title="clab/probe.clab.yml"
--8<-- "../clab/probe.clab.yml"
```

```bash
./containerlab deploy  -t clab/probe.clab.yml
./containerlab destroy -t clab/probe.clab.yml --cleanup
```

A successful deploy means containerlab is ready. The failure you are checking for on Linux is `... requires root privileges`.

## macOS notes

- **Docker Desktop VM sizing.** The lab runs inside Docker Desktop's Linux VM, and the VM's memory is the whole budget: Settings → Resources → Memory ≥ **16 GB** (the 8 GB default cannot hold 5 SR Linux nodes plus Elasticsearch), then *Apply & restart*. `make doctor` reads what docker actually has.
- **Apple Silicon.** The four `quay.io/zebbra` images are amd64-only and run under emulation. Turn on *Use Rosetta for x86_64/amd64 emulation* (Settings → General) — without it they run under QEMU and the worker in particular gets very slow. containerlab, FRR and SR Linux are native arm64.
- **File sharing.** The checkout must live under a shared path (`/Users`, `/Volumes`, `/private`, `/tmp` by default) and its path must not contain spaces: container-mode containerlab bind-mounts the repo at the same absolute path, and a path outside the shared list mounts as an *empty* directory. `make doctor` round-trips the mount to check.
- **No route from the Mac to `lab-net`.** The host cannot reach `172.30.0.0/24`; the make targets poll device readiness from inside the worker for this reason, and nothing in these docs asks you to reach a device from the host. Use `docker exec <node>` / `docker logs <node>` (bare names — the topology sets `prefix: ""`). The `/etc/hosts` and `ssh_config.d` entries containerlab normally writes stay inside the ephemeral clab container.
- **A slow first run** should raise the wait budgets, not remove the waits: `make local-lab-up WAIT_READY_TIMEOUT=600 WAIT_DEVICES_TIMEOUT=600`.
- `make doc-fix-symlinks` needs `brew install symlinks`; nothing else in the docs workflow differs.

## Registry access

The lab is a **consumer of published images**. Four of the services pull from `quay.io/zebbra`, which is a **private** organisation — an anonymous pull is rejected with `401`:

```bash
docker login quay.io
```

| Image | Service |
|---|---|
| `quay.io/zebbra/neops-cms-free:develop` | `cms` |
| `quay.io/zebbra/neops-workflow-engine:0.42.2-beta.3` | `workflow_engine`, `workflow-engine-client` |
| `quay.io/zebbra/neops-web-client:develop` | `web_client` |
| `quay.io/zebbra/neops-worker-sdk:develop` | `worker` — see the note below |

`ghcr.io/nokia/srlinux:26.3` (the SR Linux devices) and `ghcr.io/srl-labs/clab` (container-mode containerlab) are public and need no login.

!!! warning "The worker needs a local build today"
    As of August 2026 **no published `neops-worker-sdk` tag runs the lab**:
    the discovery function block is not yet in a released image, and the
    current `develop` image cannot start. `make build-worker-image
    SDK_DIR=../neops-worker-sdk-py` builds one from a checkout that has it;
    run the lab with `NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest`.
    `make images-check` tells you whether the configured image can run the
    lab. Details: [Images → Image compatibility](../20-operations/20-images.md#image-compatibility).

!!! tip "`NPM_TOKEN` is **not** needed here"
    Most NeOps repos require an `NPM_TOKEN` with `read:packages` to install
    `@zebbra/*` npm packages. This repo installs no npm packages and publishes
    nothing — Quay credentials are the only registry access it needs.

## Running locally-built images instead

Every published image can be swapped for a local tag through an environment variable — this is how you exercise an unreleased engine or worker against the lab. Copy `.env.example` to `.env` (it lists the current defaults) or export the variable:

| Variable | Default |
|---|---|
| `NEOPS_CMS_IMAGE` | `quay.io/zebbra/neops-cms-free:develop` |
| `NEOPS_WORKFLOW_ENGINE_IMAGE` | `quay.io/zebbra/neops-workflow-engine:0.42.2-beta.3` |
| `NEOPS_WEB_CLIENT_IMAGE` | `quay.io/zebbra/neops-web-client:develop` |
| `NEOPS_WORKER_SDK_IMAGE` | `quay.io/zebbra/neops-worker-sdk:develop` |

```bash
export NEOPS_WORKER_SDK_IMAGE=neops-worker-sdk:latest
```

Every overridable service sets `pull_policy: missing` (itself overridable via `NEOPS_*_PULL_POLICY`), so a local image that is already present is used without contacting any registry. A tag with no registry host is not pullable — the `docker compose pull` steps in `local-env-init`, `local-env-up` and `local-lab-up` run with `--ignore-pull-failures`, so that is a warning, not an error.

## Files the lab needs but does not ship

Two things are git-ignored and created for you on first run. If either is missing the stack does not start:

- **`cms/jwt/{private,public}.pem`** — dev-only RSA keypair minted by `make lab-jwt` (`openssl genpkey`, so OpenSSL and LibreSSL emit the same PKCS#8 PEM). Newer `neops-cms-free` images require it for RS256 JWT issuance and crash at startup (`token_service check_keys`) without it. Idempotent, so re-running never invalidates issued tokens. These are throwaway lab credentials, never secrets.
- **`cms_api_key.env`** — the CMS API key the workflow engine authenticates with, minted by `make local-env-init`.

`make local-env-init` depends on `lab-jwt` (and on `lab-net`, which creates the lab network), so in practice you only run the quickstart commands.

## Next

[Quickstart :material-arrow-right:](20-quickstart.md)
