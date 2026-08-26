---
title: Authorization
description: The lab runs the engine in enforce mode — what the three modes are, which identities exist, where their grants are declared, and how the monitor app gets a token.
tags: [concept, security]
---

# Authorization

*The lab is the reference deployment for NeOps authorization: the engine enforces, every caller carries a token, and the whole model is declared in one committed file.*

## The three modes

The engine reads `NEOPS_AUTHZ_MODE`, and rejects anything outside these three values at startup:

| Mode | What the engine does |
|---|---|
| `enforce` | Verifies the bearer token on every gated route; answers `401` without one and `403` without the route's permission. |
| `permissive` | Verifies a token when one is present and lets the request through either way. |
| `disabled` | Treats every caller as anonymous and gates nothing. |

`docker-compose.yml` sets `enforce`. A lab that gates nothing would prove nothing about the deployments it stands in for, and the failure modes that matter — a missing grant, an expired token, a CORS origin nobody enumerated — only appear under enforcement.

Two more variables travel with it on the `workflow_engine` service:

- `NEOPS_JWT_PUBLIC_KEY_PATH` — the SPKI PEM the engine verifies RS256 signatures against. `make lab-jwt` mints `cms/jwt/{private,public}.pem` for the CMS; the public half is mounted into the engine at `/etc/neops/jwt/public.pem`.
- `NEOPS_CORS_ORIGINS` — the exact browser origins allowed to call the engine: the web client on `:8080` and the monitor app on `:3031`.

## Two identities

**The automation identity** is `neops`, holding the role `lab-admin`. Every host script and the `lab_bootstrap` container acts as it, and so does the engine: `make local-env-init` mints a CMS API key for `neops` into `cms_api_key.env`, which the engine reads as `NEOPS_CMS_TOKEN`.

!!! note "`lab-admin` holds the `admin` profile for two reasons"
    The host scripts publish definitions and start executions, and the engine's
    `unlockResources` mutation verifies that the `NEOPS_CMS_TOKEN` caller holds
    `workflow-execution:write`. That second coupling is tracked as
    [neops-workflow-engine#234](https://github.com/zebbra/neops-workflow-engine/issues/234).

**The three personas** exist to make the model visible in the UI. Each holds one role, and each password equals the username:

| Login | Role | Profile | Can |
|---|---|---|---|
| `author` / `author` | `workflow-author` | `author` | read and write workflow definitions |
| `operator` / `operator` | `workflow-operator` | `operator` | read definitions, run and abort executions |
| `admin` / `admin` | `workflow-admin` | `admin` | everything above, plus delete definitions and roll executions back |

All four roles carry the same CMS visibility (`default_permission` 7 and a `RoleScope` on `Global`), so the only difference between the personas is their workflow authority. Each profile's contents come from the CMS: `apply_cms_config` prints the exact flags per element as `grant_workflow_permissions` applies them.

`author` and `operator` are partial profiles, so those two personas meet a `403` in the monitor app. The monitor answers one at the request that met it: the panel or the affordance reports the permission it wanted, and the rest of the page keeps working. Signing a persona out takes a request with no valid token, so even the narrowest profile reaches a usable app.

## Where the grants are declared

`cms/permissions.json`:

```json
--8<-- "../cms/permissions.json"
```

`apply_cms_config` reads it, creates each role and user, and then runs the CMS's own `manage.py grant_workflow_permissions --role <role> --profile <profile> --yes` once per role, printing the diff it applies. That command is the single mechanism: the script writes no grant row itself.

To change the model, edit the file and re-apply:

```bash
make apply-cms-config
```

`make local-lab-up` and `make local-lab-discover` apply it too, before they mint their token, so an edit reaches the engine on the next lab target.

For a one-off grant outside the file:

```bash
make lab-grant ROLE=workflow-operator PROFILE=admin
```

!!! warning "Grants only widen"
    `grant_workflow_permissions` ORs a profile's flags into whatever the role
    already holds. Moving a role from `admin` to `operator` in the file and
    re-applying reports "Nothing to change" and leaves the `admin` flags in
    place. To take a flag away, clear the checkbox in the web client's rights
    management screen or delete the `RolePermissionElement` row in the CMS
    admin; the lab has no command for it.

!!! warning "The published CMS image has no `grant_workflow_permissions`"
    `apply_cms_config` checks for the command and prints a one-line message when
    it is absent, so `make local-env-init` completes against
    `quay.io/zebbra/neops-cms-free:develop`. The lab then runs with roles, users
    and scopes but no workflow grants — see [Running branch images](#running-branch-images).

## How the monitor app gets a token

The monitor app at <http://localhost:3031> holds no session of its own. The web client embeds it in an iframe (`FRONTEND_WORKFLOW_MANAGER_URL`) and relays its access token over `postMessage`; the monitor keeps it in memory only.

The relay's trust anchor is `window.__NEOPS_CONFIG__.webclientOrigin`, which the lab supplies through `monitor/config.js`, bind-mounted over `rest/monitor-app/static/config.js`. Setting `WEBCLIENT_ORIGIN` on the service has no effect here: that variable is read by an nginx entrypoint, and this service runs the engine image with `npm run dev`. See [invariant 16](../60-development/20-invariants.md).

Opening `http://localhost:3031` directly gives an unauthenticated monitor, because no web client is there to relay from. Reach it through the web client's workflow-monitor page.

## Tokens expire, and logins are rate-limited

Access tokens last 15 minutes (`NEOPS_JWT_ACCESS_LIFETIME_MINUTES`, a CMS default this lab keeps). A token carries the grants its account held at the moment it was issued, and the engine reads them from the token alone, so a grant added or withdrawn afterwards reaches the engine at the next login and no sooner. `make local-lab-discover` polls to a 900-second ceiling, so a discovery minted at the start and still running at the end outlives its token; `run_workflow` reports that and stops polling. The execution itself continues — watch it in the monitor.

The CMS rate-limits local logins to 5 per minute per client IP (`NEOPS_LOCAL_LOGIN_RATE_LIMIT`), and every lab call leaves the host from the same address. Each make target mints one token and passes it to every caller in that target, which keeps a full `local-lab-up` plus `local-lab-discover` cycle at two logins. Re-running a target several times inside a minute is what reaches the limit; `./lab_token` names the setting when it does.

Mint a token by hand with:

```bash
export NEOPS_ENGINE_TOKEN=$(./lab_token)                  # as neops
export NEOPS_ENGINE_TOKEN=$(./lab_token --username operator)
curl -H "Authorization: Bearer $NEOPS_ENGINE_TOKEN" http://localhost:3030/workflow-execution
```

## Running branch images

Enforcement needs a CMS carrying `grant_workflow_permissions`, an engine carrying the auth module, and a web client carrying the token broker. Until those merge and CI republishes, build each from its authorization branch and point the lab at it:

```bash
export NEOPS_CMS_IMAGE=neops-cms-free:latest
export NEOPS_WORKFLOW_ENGINE_IMAGE=neops-workflow-engine:latest
export NEOPS_WEB_CLIENT_IMAGE=neops-web-client:latest
make local-env-prune && make local-env-init
```

Against the published images the lab still comes up: the engine ignores the three authorization variables, the public-key mount goes unread, a bearer header on an ungated route is harmless, and `apply_cms_config` skips the grant step. See [Images](../20-operations/20-images.md).
