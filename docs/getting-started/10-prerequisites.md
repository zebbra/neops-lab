---
title: Prerequisites
description: What your host needs before the first make target — Docker, the containerlab launcher, openssl, python3, RAM, Quay access — and the preflight that checks it all.
tags: [tutorial, setup]
---

# Prerequisites

*Check these first. Every one of them fails late and confusingly if you skip it — which is why `make doctor` exists.*

## Run the preflight

```bash
make doctor
```

Read-only apart from pulling two small images. It checks the docker daemon and the RAM it has, amd64 emulation on Apple Silicon, that the repo bind-mounts at its own path, docker networks overlapping the lab's subnets, the containerlab image, and that `python3` imports the host scripts — and prints the fix next to each failure.

## Host requirements

| Requirement | Why | Used by |
|---|---|---|
| **Docker** + `docker compose` ≥ 2.20 | The whole control plane, the devices, and containerlab itself | everything |
| **`openssl`** | Mints the dev RSA keypair the CMS needs for RS256 JWTs (OpenSSL 3 or macOS LibreSSL) | `make lab-jwt` |
| **`python3` ≥ 3.9** | The host scripts are stdlib-only and import under a stock macOS `/usr/bin/python3` | `gen_clab_topology`, `run_workflow`, `wait_ready` |
| **`uv`** | ruff / pyrefly / pytest and the MkDocs tooling | `make check`, `make doc-*` |
| **Quay pull access** | The CMS, engine, web client and worker images are private | `make local-env-init` |
| **RAM** | 5 SR Linux nodes (≈1.5–2 GB each) + Elasticsearch + control plane ≈ **14–16 GB** for containers | `make local-lab-up` |
| **A worker image with the discovery block** | Published with [neops-worker-sdk-py#127](https://github.com/zebbra/neops-worker-sdk-py/pull/127); until then build it from a checkout | [Images](../20-operations/20-images.md) |

## containerlab — one command, both hosts, no install

Every make target and every command in these docs calls **`./containerlab`**, a small launcher committed at the repo root. It runs the official `ghcr.io/srl-labs/clab` image privileged through the docker socket — on Linux exactly as on macOS — so the containerlab version is pinned (`CLAB_IMAGE`) and the host needs nothing but docker. This is containerlab's documented container mode; it needs a rootful docker daemon (podman is not supported by clab's container mode — set `CLAB_NATIVE=/path/to/containerlab` to use a host binary there).

Three things follow from the container mode:

- The repo is mounted at the **same absolute path** inside the clab container, because containerlab hands the topology's bind paths to the docker daemon as absolute host paths. On Docker Desktop the checkout must therefore live under a shared path (`/Users`, `/Volumes`, `/private`, `/tmp` by default) and must not contain spaces — `make doctor` checks the mount round-trips.
- containerlab's convenience entries (`/etc/hosts`, `ssh_config.d`) land inside the ephemeral container, on both hosts. Reach devices with `docker exec <node>` / `docker logs <node>` — the topology sets `prefix: ""`, so node names are container names.
- On plain Linux the lab runtime dir (`generated/clab-neops-lab/`) is written as root; the launcher chowns it back to you after each run.

Verify with the two-node probe — it confirms the whole chain (docker socket, privileged mode, veth wiring) without pulling the NeOps stack:

```yaml title="clab/probe.clab.yml"
--8<-- "../clab/probe.clab.yml"
```

```bash
./containerlab deploy  -t clab/probe.clab.yml
./containerlab destroy -t clab/probe.clab.yml --cleanup
```

### Native binary (optional)

`CLAB_NATIVE=$(command -v containerlab)` makes the launcher exec a host
binary instead. On Linux that path needs sudo-less operation — membership in
`clab_admins` plus the SUID bit; `make clab-suid` does the SUID half for you:
idempotent, it prompts for sudo only when the bit is actually missing, and
warns if you are not in `clab_admins`.

!!! warning "Re-run `make clab-suid` after every containerlab upgrade"
    A package upgrade replaces the binary and silently drops the SUID bit.
    The next `make local-lab-up` then fails with *"This containerlab command
    requires root privileges or root via SUID to run"* — group membership
    survives the upgrade, so `id` looks fine and only the file mode gives it
    away.

## macOS notes

- **Docker Desktop VM sizing.** The VM's memory is the whole budget: Settings → Resources → Memory ≥ **16 GB** (the 8 GB default cannot hold 5 SR Linux nodes plus Elasticsearch), then *Apply & restart*.
- **Apple Silicon.** The four `quay.io/zebbra` images are amd64-only; enable *Use Rosetta for x86_64/amd64 emulation* (Settings → General) or they run under QEMU, much slower. containerlab, FRR and SR Linux are native arm64.
- **No route from the Mac to `lab-net`** (`172.30.0.0/24`): the make targets poll device readiness from inside the worker, and nothing in these docs reaches a device from the host.
- A slow first run wants larger wait budgets, not fewer waits: `make local-lab-up WAIT_READY_TIMEOUT=600 WAIT_DEVICES_TIMEOUT=600`.
- `make doc-fix-symlinks` needs `brew install symlinks`; nothing else in the docs workflow differs.

## Registry access

Four services pull from `quay.io/zebbra`, a **private** organisation — an anonymous pull is rejected with `401`:

```bash
docker login quay.io
```

| Image | Service |
|---|---|
| `quay.io/zebbra/neops-cms-free:develop` | `cms` |
| `quay.io/zebbra/neops-workflow-engine:develop` | `workflow_engine`, `workflow-engine-client` |
| `quay.io/zebbra/neops-web-client:develop` | `web_client` |
| `quay.io/zebbra/neops-worker-sdk:develop` | `worker` — see [Images](../20-operations/20-images.md) |

`ghcr.io/nokia/srlinux:26.3` (the SR Linux devices) and `ghcr.io/srl-labs/clab` (containerlab) are public and need no login.

!!! tip "`NPM_TOKEN` is **not** needed here"
    Most NeOps repos require an `NPM_TOKEN` to install `@zebbra/*` npm
    packages. This repo installs no npm packages and publishes nothing — Quay
    credentials are the only registry access it needs.

## Running locally-built images instead

Every published image can be swapped for a local tag through an environment variable; copy `.env.example` to `.env` (docker compose reads it automatically) or export the variable:

| Variable | Default |
|---|---|
| `NEOPS_WORKFLOW_ENGINE_IMAGE` | `quay.io/zebbra/neops-workflow-engine:${NEOPS_ENGINE_TAG:-develop}` |
| `NEOPS_WEB_CLIENT_IMAGE` | `quay.io/zebbra/neops-web-client:develop` |
| `NEOPS_WORKER_SDK_IMAGE` | `quay.io/zebbra/neops-worker-sdk:develop` |

Every overridable service sets `pull_policy: missing`, so a local image already present is used without a registry call; the make targets pull the published tags with `--policy always --ignore-pull-failures`, so a local override tag is a warning, not an error.

## Files the lab needs but does not ship

Two things are git-ignored and created on first run; without them the stack does not start:

- **`cms/jwt/{private,public}.pem`** — dev-only RSA keypair minted by `make lab-jwt` (`openssl genpkey`, so OpenSSL and LibreSSL emit the same PKCS#8 PEM). Idempotent; a throwaway lab credential.
- **`cms_api_key.env`** — the CMS API key the engine authenticates with, minted by `make local-env-init`.

## Next

[Quickstart :material-arrow-right:](20-quickstart.md)
