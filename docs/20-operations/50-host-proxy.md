---
title: Host mode (Traefik)
description: Run the lab on a shared host behind a bundled Traefik reverse proxy — one hostname, path prefixes, same key setup as the laptop targets.
tags: [operations, host, traefik]
---

# Host mode (Traefik)

*Same control plane and devices as the laptop lab, published on a single hostname through a Traefik that ships with the stack. The `local-*` make targets are unchanged.*

## When to use this

Use **host mode** when the lab runs on a Linux box that should be reached by name (colleagues, a jump host, a demo VM) without wiring an external proxy. Use **laptop mode** (`make local-lab-up`) on a developer machine with published ports `8080` / `8001` / `3030` / `3031`.

Do not mix the two compose file sets in one shell — export `COMPOSE_FILE` only through the matching make targets.

## Path map

Routing uses Traefik's **file provider** (`traefik/dynamic.*.yml`) with fixed
compose service URLs — not the Docker provider — so modern Docker daemons that
reject API 1.24 do not break host mode.

| Public path | Backend | Notes |
|---|---|---|
| `/` | web client `:8080` | Catch-all (lowest priority) |
| `/cms` | CMS `:8000` | StripPrefix; Django `FORCE_SCRIPT_NAME=/cms` |
| `/engine` | workflow engine `:3030` | StripPrefix |
| `/monitor` | monitor app `:5173` | No strip; Vite `--base /monitor/` |
| `/traefik` | Traefik dashboard | StripPrefix → `api@internal`; open `/traefik/dashboard/` |

Static assets of the CMS (`/cms/static/…`) and of the web client (`/assets/…`) do not collide. The file API is the CMS root, so `FRONTEND_FILEAPI_ENDPOINT` is `${LAB_SCHEME}://${LAB_HOST}/cms/`.

OIDC noop endpoints (`/auth`, `/token`, `/jwks`, …) stay on the web client origin — they are not under `/cms`.

Loopback ports remain for host-side scripts:

- `127.0.0.1:8001` → CMS (used by `apply_cms_config`)
- `127.0.0.1:3030` → engine (used by `wait_ready` / `run_workflow`)

Worker and bootstrap still talk to `http://workflow_engine:3030` on the compose network.

## HTTP vs HTTPS

| `LAB_SCHEME` | Ports | Behaviour |
|---|---|---|
| `http` | **:80 only** | No TLS, no redirect, no `:443` |
| `https` (default if unset) | :80 + **:443** | HTTP→HTTPS redirect; TLS (self-signed unless ACME) |

The base overlay [`docker-compose.traefik.yml`](../../docker-compose.traefik.yml) is always HTTP. Make appends [`docker-compose.traefik-https.yml`](../../docker-compose.traefik-https.yml) unless `LAB_SCHEME=http`.

## `.env`

```bash
make lab-env          # copies .env.example → .env once
# edit .env:
LAB_HOST=lab.example.com
LAB_SCHEME=http       # or https (default)
```

Optional Let's Encrypt (**HTTPS only**, public DNS + port 80 reachable):

```bash
TRAEFIK_CERTRESOLVER=letsencrypt
TRAEFIK_ACME_EMAIL=ops@example.com
```

When `TRAEFIK_CERTRESOLVER` is set (and scheme is not `http`), make also loads [`docker-compose.traefik-acme.yml`](../../docker-compose.traefik-acme.yml). Otherwise HTTPS uses Traefik's **default self-signed** certificate — browsers will warn; that is expected for a private lab host.

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

Compose files for host lab (HTTP example):

```text
docker-compose.yml:docker-compose.worker.yml:docker-compose.traefik.yml
```

HTTPS adds `:docker-compose.traefik-https.yml` (+ `:docker-compose.traefik-acme.yml` when ACME is set).

`host-env-init` performs the **same key setup** as `local-env-init`: `make lab-jwt` → CMS starts with `cms/jwt` → `generate_api_key` → `cms_api_key.env` → `./apply_cms_config` (GraphQL via `http://localhost:8001`) → recreate `workflow_engine` so it picks up `NEOPS_CMS_TOKEN`.

`./gen_host_oidc` writes git-ignored `cms/oidc-config.host.json` and `monitor/config.host.js` from `LAB_HOST` / `LAB_SCHEME` before every host `up`.

## First bring-up

```bash
# /etc/hosts or DNS → this host
cat >> .env <<'EOF'
LAB_HOST=lab.example.com
LAB_SCHEME=http
EOF

make host-env-init
make host-lab-up
make host-lab-discover
```

Then open (with `LAB_SCHEME=http`):

- `http://lab.example.com/` — web client
- `http://lab.example.com/cms/admin/` — CMS (`neops` / `neops`)
- `http://lab.example.com/monitor/` — monitor app
- `http://lab.example.com/traefik/dashboard/` — Traefik dashboard

After changing `LAB_SCHEME`, recreate Traefik so ports/labels apply:

```bash
make host-env-up
# or: docker compose up -d --force-recreate traefik
```

If the monitor still talks to `http://localhost:3030`, open its Settings page and set the engine URL to `${LAB_SCHEME}://${LAB_HOST}/engine`.

## Ports

- **`LAB_SCHEME=http`**: only **80**. Nothing binds 443.
- **`LAB_SCHEME=https`**: **80** (redirect) and **443**. Anything else already on those ports will conflict.

This overlay does not attach to an external Traefik network.

## Elasticsearch volume

The CMS Elasticsearch data volume is named `elasticsearch_lab` (not `elasticsearch`) so it does not collide with another Elastic stack on the same Docker host. The compose **service** name stays `elasticsearch`; only the volume name changed.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `docker compose logs traefik` → `no such service` | Bare compose only sees `docker-compose.yml`. Use `make host-logs` / `make host-ps`, or `docker logs neops-lab-traefik-1` |
| Traefik 404 on every path | Stale container — `make host-env-up` after pulling; confirm file provider mount (`./traefik/dynamic.*.yml`) |
| `client version 1.24 is too old` | Old setup used the Docker provider. Current compose uses the **file** provider (no socket). Pull latest, recreate Traefik. |
| Browser jumps to HTTPS / 404 on HTTPS | `LAB_SCHEME=http` but old Traefik still has the HTTPS overlay — recreate Traefik; clear HSTS if the browser cached HTTPS |
| Blank `<app-root>` | Missing/stale `cms/oidc-config.host.json` — run `make host-oidc`; `LAB_HOST` must match the URL you type in the browser |
| `LAB_HOST is required` | Set it in `.env` or the environment before `host-*` |
| ACME challenge fails | Host not publicly reachable on :80, or DNS not pointing here, or `LAB_SCHEME=http` |
| `apply_cms_config` / `wait_ready` fail | Loopback `8001`/`3030` not published — confirm the traefik overlay is in `COMPOSE_FILE` |
