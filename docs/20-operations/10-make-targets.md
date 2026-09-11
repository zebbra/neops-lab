---
title: Make targets
description: Every target in the Makefile — lab lifecycle, environment lifecycle, quality gates, and the ones contributed by the vendored tooling repos.
tags: [operations, reference]
---

# Make targets

*The `Makefile` is the operator contract. Everything below exists in it today.*

## Scenarios

The lab holds more than one network. `SCENARIO` selects which one every target below acts on — see [Scenarios](../30-scenarios/index.md) for the mechanism.

| Target | What it does |
|---|---|
| `make scenarios` | Lists every scenario from its `scenario.json`: name, device count, supported flavours, title and summary. |
| `make scenario-resolve` | Materialises `scenarios/_base` + `scenarios/$(SCENARIO)` into `generated/$(SCENARIO)/scenario/`, the one flat directory the containers mount and the scripts read. A prerequisite of `local-env-init`, `local-env-up`, `local-lab-up`, `local-lab-discover`, `apply-cms-config`, `kind-lab-up`, `kind-lab-discover` and `kind-lab-cms-config`, so you rarely call it directly. |
| `make generate` | `scenario-resolve`, then `./gen_clab_topology` — rebuilds the containerlab topology and the **committed** `scenarios/$(SCENARIO)/workflow-execution-parameters/*.json`. |

| Variable | Default | Purpose |
|---|---|---|
| `SCENARIO` | `wan-and-fabric` | Which lab to act on. The Makefile holds the **only** default and exports it |
| `SCENARIO_SRC` | `scenarios/$(SCENARIO)` | The scenario's source assets |
| `SCENARIO_DIR` | `generated/$(SCENARIO)/scenario` | The resolved overlay |
| `GEN_DIR` | `generated/$(SCENARIO)` | Where the generators write |

```bash
make scenarios
make local-lab-up SCENARIO=frr-only
```

!!! warning "Every other consumer fails on an unset `SCENARIO`"
    The four generators, `resolve_scenario`, `apply_cms_config` and both
    compose files read `SCENARIO` and refuse to run without it. A second
    default is how a scenario gets applied half from one lab and half from
    another — invisible until discovery produces a confusing result. Drive
    `docker compose` through `make`, or set `SCENARIO` yourself.

Only one scenario runs at a time: they share `lab-net`, the `172.30.0.0/24` subnet and the compose project. The containerlab lab name stays constant across scenarios on purpose, so `containerlab deploy --reconfigure` *replaces* the running one.

## Lab lifecycle

| Target | What it does |
|---|---|
| `make local-lab-up` | Depends on `build-docker`, `lab-jwt`, `lab-env` and `scenario-resolve`. Generates the containerlab topology + device configs from the scenario's `topology.json`, refreshes the worker image, starts the CMS and waits for it to be healthy, runs `apply_cms_config`, mints an engine token, brings up the base stack **plus** the worker and `lab_bootstrap` (creating `lab-net`), waits for workflow registration, `./containerlab deploy --reconfigure`s the scenario's devices (re-runnable), mints a fresh token, waits for the worker's function blocks, then waits for every device's SSH. Refuses to run without `cms_api_key.env`. |
| `make local-lab-discover` | Runs `apply_cms_config`, mints one engine token, waits for the discovery function block and for device SSH, then POSTs a workflow execution and polls to a terminal state (15-minute ceiling). Override `DISCOVER_PARAMS` to change targeting. |
| `make local-lab-logs` | `docker compose logs -f worker lab_bootstrap`. |
| `make local-lab-down` | `./containerlab destroy --cleanup` (removes the devices and `generated/$(SCENARIO)/clab/clab-neops-lab/`), then `docker compose down`. Volumes survive. |
| `make clab-suid` | For the `CLAB_NATIVE` (host binary) path: sets the SUID bit on the `containerlab` binary so the lab targets can deploy without `sudo`. Idempotent — it only prompts for a password when the bit is missing — and warns if you are not in `clab_admins`. Re-run after every containerlab upgrade. See [Prerequisites](../getting-started/10-prerequisites.md#native-binary-optional). |

The first four export `COMPOSE_FILE=docker-compose.yml:docker-compose.worker.yml`, so they see the worker overlay; `clab-suid` touches no containers, and the `local-env-*` targets do not get the overlay either.

### Variables

| Variable | Default | Purpose |
|---|---|---|
| `DISCOVER_PARAMS` | `$(SCENARIO_SRC)/workflow-execution-parameters/discover-params.json` | Which parameter file `local-lab-discover` sends |
| `PROFILE` | `operator` | Grant profile `lab-grant` applies: `author`, `operator` or `admin` |
| `NEOPS_ENGINE_TOKEN` (env) | *(minted per target)* | Engine access token; export one to reuse it across targets. `local-lab-up` mints a fresh one after the containerlab deploy |
| `DISCOVER_FB` | `fb.base.neops.io/global_discover_network:0.1.0` | The function block `wait_ready` blocks on. Shared with the Kubernetes flavour |
| `DISCOVER_WORKFLOW` | `wf.lab.neops.io/simple_lab_discovery:1.2.0` | The definition that is executed; must match the version in the workflow YAML. Shared with the Kubernetes flavour |
| `CLAB_TOPO` | `$(GEN_DIR)/clab/neops-lab.clab.json` | The generated containerlab topology |
| `CONTAINERLAB` | `./containerlab` | The containerlab launcher |
| `CLAB_IMAGE` (env) | `ghcr.io/srl-labs/clab:0.78.2` | containerlab version the launcher runs |
| `WAIT_READY_TIMEOUT` | `180` | Seconds `wait_ready` waits for an online worker |
| `WAIT_DEVICES_TIMEOUT` | `240` | Seconds `wait_devices` waits for device SSH |

These are make/environment variables (`make local-lab-up WAIT_READY_TIMEOUT=600`); the Makefile does not read `.env` — only docker compose does.

```bash
make local-lab-discover \
  DISCOVER_PARAMS=scenarios/wan-and-fabric/workflow-execution-parameters/discover-params-autodetect.json
```

## Kubernetes lab lifecycle

A separate flavour that runs the FRR devices as pods in a local KIND cluster. It needs neither containerlab nor the compose stack — see [Kubernetes lab](50-kubernetes-lab.md) for the full picture.

| Target | What it does |
|---|---|
| `make kind-lab-up` | Depends on `build-docker-frr` and `scenario-resolve`. `kind load`s the image onto the cluster nodes, generates `generated/$(SCENARIO)/kind/lab.yaml` from the scenario's `topology.json`, applies it, waits for every Deployment to become Available, then prints each device's in-cluster DNS name. Renders `vendor: "frr"` devices only, so the scenario must declare the `kind` flavour. |
| `make kind-lab-status` | `kubectl get pods,svc` in the lab namespace. |
| `make kind-lab-down` | Deletes the namespace. The cluster itself is never touched. |
| `make kind-lab-cms-config` | Runs `apply_cms_config` against a Kubernetes-deployed CMS: grants the `neops` user the `lab-admin` role and seeds the `Global` scope, without which the web client shows no scope at all. Idempotent. |
| `make kind-lab-discover` | Publishes the workflow definition with `bootstrap/register.py`, generates the per-device targets with `./gen_kind_discover_params`, waits for the discovery function block with `./wait_ready`, then executes it with `./run_workflow`. Depends on `build-docker-bootstrap`, and on the engine being reachable at `KIND_ENGINE_URL`. |

`kind-lab-cms-config` opens a short-lived `kubectl port-forward` to the CMS and reads the API key from a cluster Secret; it touches nothing else in the product namespace. Getting the *devices* into the CMS is discovery's job, and `kind-lab-discover` does it by driving the same workflow, the same function block and the same four scripts the containerlab flavour uses — it needs a worker image that actually carries the base function blocks. See [Kubernetes lab](50-kubernetes-lab.md).

| Variable | Default | Purpose |
|---|---|---|
| `KIND_CLUSTER` | `kind` | Cluster the image is loaded into |
| `KIND_LAB_NAMESPACE` | `neops-lab` | Namespace the devices live in |
| `KIND_LAB_TIMEOUT` | `180` | Seconds `kubectl wait` allows for the pods |
| `KIND_MANIFEST` | `$(GEN_DIR)/kind/lab.yaml` | The generated manifest |
| `KIND_ENGINE_URL` | `http://engine.neops.local` | How the host and the bootstrap container reach the workflow engine. The offline ingress name, so run `make -C neops-helm config-hosts` once |
| `KIND_DISCOVER_PARAMS` | `$(GEN_DIR)/kind/discover-params.json` | The generated discovery parameters |
| `KIND_DISCOVER_TIMEOUT` | `600` | Seconds `run_workflow` polls for a terminal state |
| `NEOPS_NAMESPACE` | `neops` | Namespace the product stack runs in |
| `NEOPS_CMS_DEPLOYMENT` | `neops-neops-core` | Deployment `apply_cms_config` runs `manage.py` in |
| `NEOPS_CMS_SERVICE` / `NEOPS_CMS_PORT` | `neops-neops-core` / `8000` | What the port-forward targets |
| `NEOPS_CMS_TOKEN_SECRET` | `neops-neops-workflow-engine` | Secret the CMS API key is read from |
| `CMS_PORT` | `18000` | Local end of the port-forward |
| `CMS_EXEC` | the `kubectl exec` form | How `apply_cms_config` runs `manage.py`; the script's own default is the compose lab |

## Environment lifecycle

| Target | What it does |
|---|---|
| `make doctor` | Host preflight (`./doctor`): docker + RAM, amd64 emulation on Apple Silicon, mount round-trip, subnet overlaps, the clab image, python3. Read-only apart from pulling two images; the fix is printed per failure. |
| `make lab-jwt` | Mints `cms/jwt/{private,public}.pem` with `openssl genpkey` if absent. Idempotent. A prerequisite of `local-env-init`, `local-env-up` and `local-lab-up`. |
| `make lab-env` | Copies `.env.example` to `.env` if there is no `.env` yet, so a fresh clone has one to edit. Never overwrites an existing file. Every value in the example is commented out, so it changes no behaviour on its own. A prerequisite of `local-lab-up`. |
| `make local-env-init` | One-time per environment: pull (`--policy always`) + start the base stack, resolve the `neops` user and mint the CMS API key into `cms_api_key.env` (fails on an empty key), run `apply_cms_config`, then force-recreate the engine so it picks up the token. |
| `make local-env-up` | Start the base stack again later. Fails with a clear message if `cms_api_key.env` is missing. |
| `make local-env-down` | `docker compose down` — stops the base stack, keeps the volumes. |
| `make local-env-prune` | `docker compose down -v` — the true reset; drops the Elasticsearch and Postgres volumes. |
| `make apply-cms-config` | Runs `./apply_cms_config` on its own. Idempotent, and worth re-running after a CMS restart (see below). |
| `make lab-grant` | `make lab-grant ROLE=<role> [PROFILE=operator]` — applies one workflow grant profile to one role, the same `manage.py grant_workflow_permissions` call `apply_cms_config` makes per role in the scenario's `cms/permissions.json`. Grants only widen — see [Authorization](../10-concepts/50-authorization.md). |

!!! warning "Re-run `apply-cms-config` after a CMS restart"
    The CMS image seeds a scope named `Global` on every startup with
    `always_update_on_restart=True`, so a restart resets its columns and
    filters to the image defaults. `dashboard_configuration` is *not* reset —
    `init_scopes` never writes it. Re-run `make apply-cms-config` to reapply
    the lab's columns and drill-down.

### What `apply_cms_config` does

It grants the `neops` user a full-permission role (`lab-admin`, `default_permission=7`) and applies the scenario's `cms/permissions.json` — every declared role gets `default_permission=7` and a `RoleScope` on `Global`, every declared user gets its roles and a password equal to its username, and each role's workflow grant profile is applied through the CMS's own `manage.py grant_workflow_permissions`. See [Authorization](../10-concepts/50-authorization.md).

It also configures the `Global` scope from the JSON files under `generated/$(SCENARIO)/scenario/scope/Global/` — table columns for devices, interfaces, clients and groups, a location drill-down schema, and a dashboard configuration. Those files, and `cms/permissions.json`, come from `scenarios/_base/` unless the scenario overrides one; edit them there, not in `generated/`.

It is **bash, not Python**, and it uses `manage.py shell` rather than GraphQL for the seeding steps: `roleUpsert` / `scopesUpsert` / `roleScopeUpsert` all gate on permissions the freshly-bootstrapped `neops` user does not yet have. Table columns and drill-down *are* written through GraphQL, deliberately **last**, because the CMS's `init_scopes` runs on every `manage.py` invocation and would otherwise overwrite a shell write.

If you reorder anything in that script, read its header comment first.

## Images

| Target | What it does |
|---|---|
| `make build-docker` | Builds both local-only images — `neops-lab-frr:latest` and `neops-lab-bootstrap:latest`. Nothing is pushed. A prerequisite of `local-lab-up`. |
| `make build-docker-frr` | Just `neops-lab-frr:latest` from `devices/frr/`. A prerequisite of `kind-lab-up`, which needs no bootstrap image. |
| `make build-docker-bootstrap` | Just `neops-lab-bootstrap:latest` from `bootstrap/`. |

`DOCKER_BUILD_FLAGS` is passed to every `docker build`; set it to `--network=host` on a host whose docker bridge cannot resolve DNS. See [Images](20-images.md).

## Quality gates

| Target | What it runs |
|---|---|
| `make lint` | `ruff format --check .` then `ruff check .` |
| `make format` | `ruff format .` then `ruff check --fix .` |
| `make typeCheck` | `pyrefly check` |
| `make test` | `pytest tests` — the generator unit tests (parametrised over every scenario), the scenario-manifest checks, and the repo invariants (subnets, the one-`SCENARIO`-default rule) |
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
