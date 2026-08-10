---
title: Discovery
description: The workflow, the function block it dispatches to, and the parameter contract — subnets, platforms, and how credentials are scoped.
tags: [concept, workflow]
---

# Discovery

*One workflow, one step, one function block. The interesting part is the parameter contract and where the function block actually lives.*

## The workflow

`workflows/simple-lab-discovery.workflow.yaml` is registered with the engine by the `lab_bootstrap` container on every `make local-lab-up`. It is a single-step workflow whose entire job is to pass parameters through to a function block:

```yaml title="workflows/simple-lab-discovery.workflow.yaml"
--8<-- "../workflows/simple-lab-discovery.workflow.yaml"
```

Its identifier is `wf.lab.neops.io/simple_lab_discovery:1.2.0` — package `wf.lab.neops.io`, name `simple_lab_discovery`, and the version assembled from `majorVersion`/`minorVersion`/`patchVersion`. That string is what `make local-lab-discover` passes to `run_workflow`, so bumping a version field in the YAML means bumping it in the `Makefile` too.

`seedEntity: global` and `runOn: global` mean the step is not scoped to an entity — it runs once, globally, which is why `run_workflow` is called with no `--ids`.

### How registration works

`bootstrap/register.py` waits for `GET /health` on the engine (60s budget, then tries anyway), then POSTs each `workflows/*.yaml` to `/workflow-definition` as `{"workflow": <parsed yaml>}`. It is **idempotent**: a `409`, or any response whose body mentions "already exists", counts as success. A real failure exits non-zero, and `docker compose wait lab_bootstrap` propagates that so `make local-lab-up` fails rather than continuing into a broken discovery.

## The function block

```text
fb.base.neops.io/global_discover_network:0.1.0
```

!!! danger "The function block is not in this repo"
    `global_discover_network` lives in **`neops-worker-sdk-py`** and ships
    *inside* the published `quay.io/zebbra/neops-worker-sdk` image, under
    `/app/neops/fb`. This repo only *names* it — in the workflow YAML and in
    the `Makefile`'s `DISCOVER_FB` variable. Renaming it upstream breaks both,
    with **no compile-time check anywhere**.

    Symptom when the pinned image does not carry it:

    ```text
    failed_safe_ack — Function block with id fb.base.neops.io/global_discover_network:0.1.0 not found
    ```

The worker is told where to look with a two-entry search path:

```yaml
DIR_FUNCTION_BLOCKS: lab/function_blocks,neops/fb
```

Both are relative to the worker image's WORKDIR, `/app`:

- **`lab/function_blocks`** → this repo's `function_blocks/`, bind-mounted at `/app/lab`. See [The `/app/lab` mount](40-container-paths.md).
- **`neops/fb`** → the base function blocks baked into the image.

`function_blocks/` currently holds only an empty `__init__.py`: it is the **extension point** for lab-local blocks (package `fb.lab.neops.io`), wired up and discovered but not yet used. Drop a block in there and the worker picks it up on restart — no image rebuild, because the directory is mounted.

## Parameters

The workflow's `parameterSchema` declares two top-level arrays.

### `subnets`

CIDRs to expand; a single host is a `/32`. Each entry may carry:

`cidr`
:   Required. The prefix to expand.

`platform`
:   Optional. The device platform (`frr`, `srl`). Omitting it makes discovery detect the platform, at the cost of an extra SSH probe per host.

`credentials`
:   Optional. Logins scoped to this subnet, tried before the global list.

**For overlapping ranges the most specific prefix wins** (longest prefix match) — that is what makes `discover-params-mixed.json` meaningful: a `/24` with FRR credentials, plus `/32` overrides carrying the SR Linux login for the five switches.

### `credentials`

The global fallback list, tried in order against hosts whose subnet carries none. Each entry is `{username, password}` plus an optional `platform`:

- an entry **scoped to a platform** is tried *first* for hosts of that platform, and **skipped** for hosts declared as another one;
- an unscoped entry is tried for anything.

So credential resolution is: **subnet credentials → global credentials**, and within a list, **platform-matched → unscoped**.

### The four parameter files

| File | Shape | Generated? |
|---|---|---|
| `discover-params.json` | 15 `/32`s with `platform`, platform-scoped credentials | yes |
| `discover-params-autodetect.json` | the same `/32`s, no `platform` | yes |
| `discover-params-subnet.json` | one `/24`, subnet-scoped credentials | yes |
| `discover-params-mixed.json` | `/24` + `/32` overrides for the SR Linux nodes | **no — hand-maintained** |

See [Your first discovery](../getting-started/30-first-discovery.md) for the contents of each and the `DISCOVER_PARAMS` override that selects them.

## What discovery writes

The function block connects to every host through the connection plugin its platform selects (`frr` → `FRRNetmikoPlugin`, `srl` → `SRLinuxNetmikoPlugin`), reads facts *and* interfaces, then writes both `Device` and `Interface` rows to the CMS in one pass.

- **Devices are keyed by IP.** Re-running discovery skips devices that already exist.
- **Interfaces are always recorded.** Re-running against the same CMS therefore duplicates interface rows.

Discovery emits a few hundred `Interface` rows in a single job result, which is why the lab wants a workflow-engine image carrying the large-payload and reference-resolution fixes. If you see the run fail on result size, pin a newer engine with `NEOPS_WORKFLOW_ENGINE_IMAGE`.

## Related

- [The `/app/lab` mount](40-container-paths.md) — why `DIR_FUNCTION_BLOCKS` has a `lab/` prefix.
- [Troubleshooting](../20-operations/40-troubleshooting.md) — the three race conditions between registration, worker readiness and device boot.
- [NeOps ecosystem](../99-appendix/neops-ecosystem.md) — the contracts this repo depends on and cannot verify locally.
