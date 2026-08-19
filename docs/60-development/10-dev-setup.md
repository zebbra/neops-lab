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
make check     # lint + typeCheck + test
```

| Target | Command |
|---|---|
| `make lint` | `uv run ruff format --check .` then `uv run ruff check .` |
| `make format` | `uv run ruff format .` then `uv run ruff check --fix .` |
| `make typeCheck` | `uv run pyrefly check` |
| `make test` | `uv run pytest tests` |
| `make shellcheck-syntax` | `bash -n` over the bash entry points (`apply_cms_config`, `containerlab`, `doctor`) |
| `make py39-check` | imports the five host scripts under Python 3.9 (`uv run --python 3.9`) |

Ruff is configured with line length 120, target `py312`, and a broad rule selection (`F E W I B UP N S A C4 SIM RET PIE ARG PTH PERF PT PL RUF`) with `E501` delegated to the formatter. **`py312` is the floor for the dev tooling only** — the host scripts must keep importing under Python 3.9 (a stock macOS), which ruff will not check for you; `make py39-check` and `tests/test_host_invariants.py` do.

## What CI runs

`.github/workflows/ci.yml`, on pushes to `main`/`develop` and on every PR:

1. **`lint-test`** on `ubuntu-latest` — `uv sync --group dev --frozen`, then ruff format check, ruff lint, pyrefly, pytest, `make py39-check`, `make shellcheck-syntax`. Exactly `make check`.
2. **`macos`** on `macos-latest` — pytest, the host scripts imported by the *stock* `/usr/bin/python3` (3.9), the bash entry points parsed by `/bin/bash` 3.2, and `gen_clab_topology` reproducing the committed parameter files with BSD userland. macOS is a supported host; this job is what makes that promise CI-owned rather than best-effort. It stands up no containers.
3. **`docker`** on the self-hosted `hetzner` runner, gated on `lint-test` — `make build-docker`. The images are local-only, so this job exists purely to make a broken Dockerfile fail in CI rather than on a developer's first `make local-lab-up`.

There is no job that stands the lab up: 15 device containers and a few GB of SR Linux RAM do not belong in CI.

## The extension-less script rule

!!! danger "Add a new host script to **both** include lists or it is never checked"
    The host scripts are executables with **no `.py` extension**:

    ```text
    gen_clab_topology  gen_device_configs  run_workflow  wait_ready  wait_devices
    ```

    Ruff and pyrefly both discover files by extension, so each script has to be
    named explicitly in `pyproject.toml` — in **two** places:

    ```toml
    [tool.ruff]
    extend-include = ["gen_clab_topology", "gen_device_configs", "run_workflow", "wait_devices", "wait_ready"]

    [tool.pyrefly]
    project-includes = ["tests/**/*.py", "function_blocks/**/*.py", "gen_clab_topology", …]
    ```

    Miss one and the script is **silently** never linted or type-checked. There
    is no warning; the gate just passes.

### Why they have no extension

Three callers depend on the bare names:

- `tests/*` load them by path via `importlib.machinery.SourceFileLoader` — `spec_from_file_location` returns `None` for an unrecognised extension, which is why the tests use the explicit-loader form;
- `gen_clab_topology` loads `gen_device_configs` the same way;
- the `Makefile` and the docs invoke them as `./gen_clab_topology`.

Renaming them to `*.py` is not an option — it would break every caller.

!!! note "`apply_cms_config`, `containerlab` and `doctor` are bash, not Python"
    They are deliberately absent from both include lists. Do not "fix" that by
    adding them — ruff would try to parse shell as Python. Keep them bash-3.2
    and BSD-userland compatible (no arrays under `set -u`, no `grep -P`, no
    `base64 FILE`, no `sed -i` without a suffix); `make shellcheck-syntax`
    parses them, and the CI macOS job parses them with the real `/bin/bash`.

    Note also that CI lints `.` (a directory walk) rather than an explicit file
    list, because `extend-include` only applies to discovery.

## Tests

```bash
uv run pytest tests
```

Three modules:

- `tests/test_gen_device_configs.py` — the per-device renderers: FRR `.iface` lines, the loopback-first rule, SR Linux `set /` lines, and the `ethernet-1/N` → `e1/N` description conversion.
- `tests/test_gen_clab_topology.py` — interface-name mapping, veth-link deduplication, dummy-link generation, and **the byte-for-byte reproduction of the committed `workflow-execution-parameters/*.json`**.
- `tests/test_host_invariants.py` — the constants that live in more than one place (`LAB_SUBNET`/`LAB_NET` in the Makefile vs `gen_clab_topology`; `lab-net` external in compose) and the Python-3.9 rule for the host scripts.

That last one is the repo's real guard. `_dump_discover_params` hand-rolls a compact layout `json.dumps` cannot produce, so the assertion is exact: change `topology.json`, rerun `./gen_clab_topology`, and commit the regenerated JSON — or `make test` fails.

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

`docs/` contains symlinks to the repo's source directories (`workflows/`, `devices/`, `clab/`, `workflow-execution-parameters/`, …) created by the setup script. That is what makes `--8<--` snippet includes work without referencing paths outside `docs/`:

```markdown
--8<-- "../workflows/simple-lab-discovery.workflow.yaml"
```

Snippets are configured with `check_paths: true`, so a broken include fails `make doc-build` rather than rendering an empty block. Keep code blocks longer than a few lines as includes from real files — that is what stops the docs drifting from the source.

## Before you push

```bash
make check
make doc-build   # if you touched docs/ or mkdocs_custom.yml
```
