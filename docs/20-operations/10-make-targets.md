---
title: Make targets
description: Every target in the Makefile — lab lifecycle, environment lifecycle, quality gates, and the ones contributed by the vendored tooling repos.
tags: [operations, reference]
---

# Make targets

*The `Makefile` is the operator contract. Everything below exists in it today.*

## Lab lifecycle

| Target | What it does |
|---|---|
| `make local-lab-up` | Depends on `build-docker` and `lab-env`. Generates the containerlab topology + device configs from `topology.json`, refreshes the worker image, brings up the base stack **plus** the worker and `lab_bootstrap` (creating `lab-net`), waits for workflow registration, `./containerlab deploy --reconfigure`s the 15 devices (re-runnable), waits for the worker's function blocks, then waits for every device's SSH. Refuses to run without `cms_api_key.env`. |
| `make local-lab-discover` | Waits for the discovery function block and for device SSH, then POSTs a workflow execution and polls to a terminal state (15-minute ceiling). Override `DISCOVER_PARAMS` to change targeting. |
| `make local-lab-logs` | `docker compose logs -f worker lab_bootstrap`. |
| `make local-lab-down` | `./containerlab destroy --cleanup` (removes the devices and `generated/clab-neops-lab/`), then `docker compose down`. Volumes survive. |
| `make clab-suid` | For the `CLAB_NATIVE` (host binary) path: sets the SUID bit on the `containerlab` binary so the lab targets can deploy without `sudo`. Idempotent — it only prompts for a password when the bit is missing — and warns if you are not in `clab_admins`. Re-run after every containerlab upgrade. See [Prerequisites](../getting-started/10-prerequisites.md#native-binary-optional). |

The first four export `COMPOSE_FILE=docker-compose.yml:docker-compose.worker.yml`, so they see the worker overlay; `clab-suid` touches no containers, and the `local-env-*` targets do not get the overlay either.

### Variables

| Variable | Default | Purpose |
|---|---|---|
| `DISCOVER_PARAMS` | `workflow-execution-parameters/discover-params.json` | Which parameter file `local-lab-discover` sends |
| `DISCOVER_FB` | `fb.base.neops.io/global_discover_network:0.1.0` | The function block `wait_ready` blocks on |
| `CLAB_TOPO` | `generated/neops-lab.clab.json` | The generated containerlab topology |
| `CONTAINERLAB` | `./containerlab` | The containerlab launcher |
| `CLAB_IMAGE` (env) | `ghcr.io/srl-labs/clab:0.78.2` | containerlab version the launcher runs |
| `WAIT_READY_TIMEOUT` | `180` | Seconds `wait_ready` waits for an online worker |
| `WAIT_DEVICES_TIMEOUT` | `240` | Seconds `wait_devices` waits for device SSH |

These are make/environment variables (`make local-lab-up WAIT_READY_TIMEOUT=600`); the Makefile does not read `.env` — only docker compose does.

```bash
make local-lab-discover \
  DISCOVER_PARAMS=workflow-execution-parameters/discover-params-autodetect.json
```

## Environment lifecycle

| Target | What it does |
|---|---|
| `make doctor` | Host preflight (`./doctor`): docker + RAM, amd64 emulation on Apple Silicon, mount round-trip, subnet overlaps, the clab image, python3. Read-only apart from pulling two images; the fix is printed per failure. |
| `make lab-jwt` | Mints `cms/jwt/{private,public}.pem` with `openssl genpkey` if absent. Idempotent. A prerequisite of both `local-env-init` and `local-env-up`. |
| `make lab-env` | Copies `.env.example` to `.env` if there is no `.env` yet, so a fresh clone has one to edit. Never overwrites an existing file. Every value in the example is commented out, so it changes no behaviour on its own. A prerequisite of `local-lab-up`. |
| `make local-env-init` | One-time per environment: pull (`--policy always`) + start the base stack, resolve the `neops` user and mint the CMS API key into `cms_api_key.env` (fails on an empty key), run `apply_cms_config`, then force-recreate the engine so it picks up the token. |
| `make local-env-up` | Start the base stack again later. Fails with a clear message if `cms_api_key.env` is missing. |
| `make local-env-down` | `docker compose down` — stops the base stack, keeps the volumes. |
| `make local-env-prune` | `docker compose down -v` — the true reset; drops the Elasticsearch and Postgres volumes. |
| `make apply-cms-config` | Runs `./apply_cms_config` on its own. Idempotent, and worth re-running after a CMS restart (see below). |

!!! warning "Re-run `apply-cms-config` after a CMS restart"
    The CMS image seeds a scope named `Global` on every startup with
    `always_update_on_restart=True`, so a restart resets its columns and
    filters to the image defaults. `dashboard_configuration` is *not* reset —
    `init_scopes` never writes it. Re-run `make apply-cms-config` to reapply
    the lab's columns and drill-down.

### What `apply_cms_config` does

It grants the `neops` user a full-permission role (`lab-admin`, `default_permission=7`) and configures the `Global` scope from the JSON files under `scope/Global/` — table columns for devices, interfaces, clients and groups, a location drill-down schema, and a dashboard configuration.

It is **bash, not Python**, and it uses `manage.py shell` rather than GraphQL for the seeding steps: `roleUpsert` / `scopesUpsert` / `roleScopeUpsert` all gate on permissions the freshly-bootstrapped `neops` user does not yet have. Table columns and drill-down *are* written through GraphQL, deliberately **last**, because the CMS's `init_scopes` runs on every `manage.py` invocation and would otherwise overwrite a shell write.

If you reorder anything in that script, read its header comment first.

## Images

| Target | What it does |
|---|---|
| `make build-docker` | Builds `neops-lab-frr:latest` from `devices/frr/` and `neops-lab-bootstrap:latest` from `bootstrap/`. Local tags only — nothing is pushed. A prerequisite of `local-lab-up`. |

See [Images](20-images.md).

## Quality gates

| Target | What it runs |
|---|---|
| `make lint` | `ruff format --check .` then `ruff check .` |
| `make format` | `ruff format .` then `ruff check --fix .` |
| `make typeCheck` | `pyrefly check` |
| `make test` | `pytest tests` — the generator unit tests + repo invariants (subnets, the Python-3.9 rule) |
| `make py39-check` | Imports the host scripts under Python 3.9 (the stock macOS python3) |
| `make shell-syntax` | `bash -n` over `apply_cms_config`, `containerlab`, `doctor` |
| `make check` | `lint typeCheck test py39-check shell-syntax` — the one to run before pushing |

## Documentation

Contributed by the vendored `mkdocs-documentation` tooling in `.make_scripts/mkdocs-documentation/`:

| Target | What it does |
|---|---|
| `make doc-serve` | Live-preview server; regenerates `mkdocs.yml` when `mkdocs_custom.yml` or `mkdocs_base.yml` change |
| `make doc-build` | Regenerate `mkdocs.yml`, `mkdocs build`, then clean the site dir |
| `make doc-build-docker` / `make doc-run-docker` | Build and run the docs as an NGINX image |
| `make doc-create-mkdocs` | Regenerate `mkdocs.yml` and refresh the docs CI workflow |
| `make doc-update-assets` | Pull the latest tooling release into `.make_scripts/` |

!!! danger "`mkdocs.yml` is autogenerated — never edit it"
    It is produced by `setup_documentation.py` from this repo's
    `mkdocs_custom.yml` deep-merged over the shared `mkdocs_base.yml`. Edit
    `mkdocs_custom.yml`. Note that **dicts merge but lists concatenate**, so
    re-declaring `hooks:` or `plugins:` entries that the base already has
    registers them twice.

## Release and infrastructure

Contributed by the vendored `release-management` and `project-infrastructure` tooling:

| Target | What it does |
|---|---|
| `make tag-patch` / `tag-minor` / `tag-major` (+ `-beta`) | Create a local annotated SemVer tag |
| `make tag-latest-beta`, `make check-for-releases`, `make hard-reset-tags`, `make tag-major-minor-ruleset` | Tag helpers |
| `make sync-release-assets`, `make sync-infrastructure-assets` | Re-vendor the tooling scripts (destructive by design — they `rm -rf` the vendored dir first) |
| `make github-set-branch-protections`, `make github-set-default-branch`, `make github-autodelete-merged-branches` | Repository settings |

!!! note "Tagging this repo publishes nothing"
    `neops-lab` is not a distributable package — no wheel, no npm package, no
    registry image. `make tag-*` creates a **local** annotated tag; the
    separate `git push --tags` is what triggers downstream pipelines in repos
    that have them. This one has none.

## Full reset

```bash
make local-lab-down local-env-prune
make local-env-init && make local-lab-up && make local-lab-discover
```
