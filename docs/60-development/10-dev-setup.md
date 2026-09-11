---
title: Dev setup
description: Quality gates, what CI runs, and the extension-less script rule that silently skips linting if you forget it.
tags: [contributing, setup]
---

# Dev setup

*Fast, hermetic, and entirely local — no lab needs to be running to work on this repo.*

## Install

```bash
uv sync --group dev
```

That gets `pytest`, `ruff` and `pyrefly`. Nothing else is needed: the repo declares **no runtime dependencies**, because the host scripts are stdlib-only by design.

## The gates

```bash
make check     # lint + typeCheck + test + py39-check + shell-syntax
```

| Target | Command |
|---|---|
| `make lint` | `uv run ruff format --check .` then `uv run ruff check .` |
| `make format` | `uv run ruff format .` then `uv run ruff check --fix .` |
| `make typeCheck` | `uv run pyrefly check` |
| `make test` | `uv run pytest tests` |
| `make py39-check` | imports the host scripts under Python 3.9 (`uv run --python 3.9`) |
| `make shell-syntax` | `bash -n` over the bash entry points |

Ruff is configured with line length 120, target `py312`, and a broad rule selection (`F E W I B UP N S A C4 SIM RET PIE ARG PTH PERF PT PL RUF`) with `E501` delegated to the formatter.

## What CI runs

`.github/workflows/ci.yml`, on pushes to `main`/`develop` and on every PR:

1. **`lint-test`** on `ubuntu-latest` — `uv sync --group dev --frozen`, then ruff format check, ruff lint, pyrefly, `pytest tests`, `make py39-check`, and a parse of the bash entry points with a real bash 3.2 (the `bash:3.2` image — the shell macOS ships) in place of `make shell-syntax`. The parameter-file reproduction is not a separate step: it is one of the pytest assertions.
2. **`docker`** on the self-hosted `hetzner` runner, gated on `lint-test` — `make build-docker`. The images are local-only, so this job exists purely to make a broken Dockerfile fail in CI rather than on a developer's first `make local-lab-up`.

There is no job that stands the lab up: 15 device containers and a few GB of SR Linux RAM do not belong in CI.

## The extension-less script rule

!!! danger "Add a new host script to **both** include lists or it is never checked"
    The host scripts are executables with **no `.py` extension**:

    ```text
    resolve_scenario  gen_clab_topology  gen_device_configs
    gen_kind_manifests  gen_kind_discover_params
    run_workflow  wait_ready  wait_devices
    ```

    Ruff and pyrefly both discover files by extension, so each script has to be
    named explicitly in `pyproject.toml` — in **two** places:

    ```toml
    [tool.ruff]
    extend-include = ["gen_clab_topology", "gen_device_configs", …, "resolve_scenario", "run_workflow", …]

    [tool.pyrefly]
    project-includes = ["tests/**/*.py", "gen_clab_topology", …, "resolve_scenario", …]
    ```

    Miss one and the script is **silently** never linted or type-checked. There
    is no warning; the gate just passes.

### Why they have no extension

Three callers depend on the bare names:

- `tests/*` load them by path via `importlib.machinery.SourceFileLoader` — `spec_from_file_location` returns `None` for an unrecognised extension, which is why the tests use the explicit-loader form;
- `gen_clab_topology` loads `gen_device_configs` the same way, which loads `resolve_scenario` in turn;
- the `Makefile` invokes them as `./gen_clab_topology`.

A third place needs updating too: `tools/import_host_scripts.py` enumerates them for `make py39-check`.

Renaming them to `*.py` is not an option — it would break every caller.

!!! note "`apply_cms_config`, `containerlab` and `doctor` are bash, not Python"
    They are deliberately absent from both include lists. Do not "fix" that by
    adding them — ruff would try to parse shell as Python. Keep them bash-3.2
    and BSD-userland compatible; `make shell-syntax` parses them.

    Note also that CI lints `.` (a directory walk) rather than an explicit file
    list, because `extend-include` only applies to discovery.

## Tests

```bash
uv run pytest tests
```

Eight modules, each loading the script under test through `labscripts`:

- `tests/test_gen_device_configs.py` — the per-device renderers: FRR `.iface` lines, the loopback-first rule, SR Linux `set /` lines, and the `ethernet-1/N` → `e1/N` description conversion.
- `tests/test_gen_clab_topology.py` — interface-name mapping, veth-link deduplication, dummy-link generation, the FRR nodes' `/lab` binds, and **the byte-for-byte reproduction of each scenario's committed `workflow-execution-parameters/*.json`**.
- `tests/test_resolve_scenario.py` — the overlay itself: per-file precedence, additions, pruning of a removed override, and the error paths.
- `tests/test_scenario_manifests.py` — every `scenario.json` is complete and matches its directory, and every scenario's device-to-device links are symmetric.
- `tests/test_gen_kind_manifests.py` and `tests/test_gen_kind_discover_params.py` — the Kubernetes flavour's Deployments, Services and `/32` discovery targets, with `kubectl` stubbed so the suite never touches a cluster.
- `tests/test_wait_devices.py` — which hosts the readiness poll waits on, per scenario. The regression guard for a poller that reads one fixed topology whatever scenario is selected.
- `tests/test_host_invariants.py` — the cross-file constants the compose files and the generators must agree on.

The byte-for-byte assertion is the repo's real guard. `_dump_discover_params` hand-rolls a compact layout `json.dumps` cannot produce, so it is exact: change a scenario's `topology.json`, run `make generate SCENARIO=<name>`, and commit the regenerated JSON — or `make test` fails. It is parametrised over `scenarios/*`, so adding a scenario extends the guard rather than leaving it covering only the first one.

## Working on the docs

```bash
make doc-serve    # live preview with regeneration on config change
make doc-build    # what to run before pushing docs changes
```

!!! danger "`mkdocs.yml` is autogenerated — never edit it"
    It is produced by `setup_documentation.py` from `mkdocs_custom.yml`
    deep-merged over the shared `mkdocs_base.yml` (vendored under
    `.make_scripts/mkdocs-documentation/`). Two consequences:

    - **Dicts merge, lists concatenate.** Re-declaring a `hooks:` or `plugins:`
      entry that the base already registers loads it **twice**.
    - **`docs/assets/extra.css` and `extra.js` are overwritten on every
      `make doc-update-assets`.** Project-specific styling must go in a
      differently named file.

`docs/` contains symlinks to the repo's source directories (`scenarios/`, `devices/`, `clab/`, `tests/`, …) created by the setup script. That is what makes `--8<--` snippet includes work without referencing paths outside `docs/`:

```markdown
--8<-- "../scenarios/_base/workflows/simple-lab-discovery.workflow.yaml"
```

Snippets are configured with `check_paths: true`, so a broken include fails `make doc-build` rather than rendering an empty block. Keep code blocks longer than a few lines as includes from real files — that is what stops the docs drifting from the source.

## Before you push

```bash
make check
make doc-build   # if you touched docs/ or mkdocs_custom.yml
```
