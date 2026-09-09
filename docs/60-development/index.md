---
title: Development
description: Contributor docs — the quality gates, the extension-less script rule, and the invariants that are load-bearing but invisible in the code.
tags: [contributing]
---

# Development

*Two pages. Read both before your first change — the second one is the part that is not visible from the code.*

## In this section

<div class="grid cards" markdown>

-   :material-tools:{ .lg .middle } &nbsp; **[Dev setup](10-dev-setup.md)**

    ---

    `uv sync`, `make check`, what CI runs, and the repo's one structural trap: the host scripts have **no `.py` extension**, so ruff and pyrefly only see them through explicit include lists.

-   :material-shield-lock:{ .lg .middle } &nbsp; **[Invariants](20-invariants.md)**

    ---

    The things that will break if you change them casually — script names, the read-only mount, the one `SCENARIO` default, the capital-G scope, the deliberate race ordering, and more.

</div>

## Ground rules

- **Branch from `develop`.**
- **This is not a distributable package.** No wheel, no npm package, no registry image. `pyproject.toml` exists only to configure pytest/ruff/pyrefly and is marked `[tool.uv] package = false`.
- **Host scripts are stdlib-only.** `resolve_scenario`, `gen_clab_topology`, `gen_device_configs`, `gen_kind_manifests`, `gen_kind_discover_params`, `run_workflow`, `wait_ready` and `wait_devices` run on a bare host before any virtualenv exists. Do not add a third-party import to them, and register any new one in **both** `pyproject.toml` lists (ruff `extend-include`, pyrefly `project-includes`) *and* in `tools/import_host_scripts.py`.
- **Never commit `generated/`.** It is rebuilt from the scenario on every lab bring-up, and containerlab mints TLS private keys in there.
- **`make test` is the meaningful gate for generator changes** — fast, hermetic, and it is what catches an uncommitted parameter-file regeneration.

## Package naming

| Thing | Package | Lives in |
|---|---|---|
| Lab-local function blocks | `fb.lab.neops.io` | this repo, `scenarios/_base/function_blocks/` (currently empty) |
| Lab workflows | `wf.lab.neops.io` | this repo, `scenarios/_base/workflows/` |
| The discovery function block | `fb.base.neops.io` | **`neops-worker-sdk-py`**, shipped in the worker image |
