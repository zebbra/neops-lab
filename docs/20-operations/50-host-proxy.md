---
title: Host mode (Traefik)
description: Run the lab on a shared host behind a bundled Traefik reverse proxy — one hostname, path prefixes, same key setup as the laptop targets.
tags: [operations, host, traefik]
---

# Host mode (Traefik)

*Same control plane and devices as the laptop lab, published on a single hostname through a Traefik that ships with the stack. The `local-*` make targets are unchanged.*

## When to use this

Use **host mode** when the lab runs on a Linux box that should be reached by name (colleagues, a jump host, a demo VM) and you want HTTPS on ports 80/443 without wiring an external proxy. Use **laptop mode** (`make local-lab-up`) on a developer machine with published ports `8080` / `8001` / `3030` / `3031`.

Do not mix the two compose file sets in one shell — export `COMPOSE_FILE` only through the matching make targets.

## Path map

Traefik listens on **80** (redirect) and **443**. Routers match `Host(${LAB_HOST})` only — opening the host by IP returns 404. Point DNS or `/etc/hosts` at the box first.

| Public path | Backend | Notes |
|---|---|---|
| `/` | web client `:8080` | Catch-all (lowest priority) |
| `/cms` | CMS `:8000` | StripPrefix; Django `FORCE_SCRIPT_NAME=/cms` so admin/static/graphql/file-API stay under `/cms` |
| `/engine` | workflow engine `:3030` | StripPrefix |
| `/monitor` | monitor app `:5173` | No strip; Vite `--base /monitor/` |

Static assets of the CMS (`/cms/static/…`) and of the web client (`/assets/…`, Angular routes) therefore do not collide. The file API is the CMS root, so `FRONTEND_FILEAPI_ENDPOINT` is `${LAB_SCHEME}://${LAB_HOST}/cms/` (not `/`).

OIDC noop endpoints (`/auth`, `/token`, `/jwks`, …) stay on the web client origin — they are not under `/cms`.

Loopback ports remain for host-side scripts:

- `127.0.0.1:8001` → CMS (used by `apply_cms_config`)
- `127.0.0.1:3030` → engine (used by `wait_ready` / `run_workflow`)

Worker and bootstrap still talk to `http://workflow_engine:3030` on the compose network.

## `.env`

```bash
make lab-env          # copies .env.example → .env once
# edit .env:
LAB_HOST=lab.example.com
LAB_SCHEME=https      # default if omitted
```

Optional Let's Encrypt (public DNS required for HTTP-01 on port 80):

```bash
TRAEFIK_CERTRESOLVER=letsencrypt
TRAEFIK_ACME_EMAIL=ops@example.com
```

When `TRAEFIK_CERTRESOLVER` is set, make appends [`docker-compose.traefik-acme.yml`](../../docker-compose.traefik-acme.yml). Otherwise Traefik serves its **default self-signed** certificate — browsers will warn; that is expected for a private lab host.

## Make targets

| Target | Laptop counterpart | What it does |
|---|---|---|
| `make host-env-init` | `local-env-init` | JWT, Traefik overlay, OIDC render, pull/up, mint `cms_api_key.env`, `apply_cms_config`, force-recreate engine |
| `make host-env-up` | `local-env-up` | Start base stack + Traefik again |
| `make host-env-down` | `local-env-down` | Stop; keep volumes |
| `make host-env-prune` | `local-env-prune` | Stop and drop volumes |
| `make host-lab-up` | `local-lab-up` | Worker + bootstrap + containerlab devices |
| `make host-lab-discover` | `local-lab-discover` | Run discovery workflow |
| `make host-lab-down` | `local-lab-down` | Destroy devices + compose down |
| `make host-lab-logs` | `local-lab-logs` | Tail worker + bootstrap |

Compose files for host lab:

```text
docker-compose.yml:docker-compose.worker.yml:docker-compose.traefik.yml
[+ docker-compose.traefik-acme.yml when TRAEFIK_CERTRESOLVER is set]
```

`host-env-init` performs the **same key setup** as `local-env-init`: `make lab-jwt` → CMS starts with `cms/jwt` → `generate_api_key` → `cms_api_key.env` → `./apply_cms_config` (GraphQL via `http://localhost:8001`) → recreate `workflow_engine` so it picks up `NEOPS_CMS_TOKEN`.

`./gen_host_oidc` writes git-ignored `cms/oidc-config.host.json` from [`cms/oidc-config.host.json.template`](../../cms/oidc-config.host.json.template) before every host `up`. The laptop [`cms/oidc-config.json`](../../cms/oidc-config.json) is left alone.

## First bring-up

```bash
# /etc/hosts or DNS → this host
echo 'LAB_HOST=lab.example.com' >> .env

make host-env-init
make host-lab-up
make host-lab-discover
```

Then open:

- `https://lab.example.com/` — web client
- `https://lab.example.com/cms/admin/` — CMS (`neops` / `neops`)
- `https://lab.example.com/monitor/` — monitor app

If the monitor still talks to `http://localhost:3030`, open its Settings page and set the engine URL to `https://lab.example.com/engine` (the overlay also exports `PUBLIC_ENGINE_URL` / `VITE_ENGINE_URL` when the image honours them).

## Ports 80 / 443

The bundled Traefik **binds host ports 80 and 443**. Anything else already listening there (another reverse proxy, systemd socket) will conflict — stop it or use laptop mode instead. This overlay does not attach to an external Traefik network.

## Elasticsearch volume

The CMS Elasticsearch data volume is named `elasticsearch_lab` (not `elasticsearch`) so it does not collide with another Elastic stack on the same Docker host. The compose **service** name stays `elasticsearch`; only the volume name changed.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Traefik 404 on the IP | Routers require `Host(${LAB_HOST})` — use the name from `.env` |
| Blank `<app-root>` | Missing/stale `cms/oidc-config.host.json` — run `make host-oidc` |
| `LAB_HOST is required` | Set it in `.env` or the environment before `host-*` |
| ACME challenge fails | Host not publicly reachable on :80, or DNS not pointing here |
| `apply_cms_config` / `wait_ready` fail | Loopback `8001`/`3030` not published — confirm the traefik overlay is in `COMPOSE_FILE` |
