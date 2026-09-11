---
title: Host-direct mode (ports)
description: Run the lab on a shared host with published ports and LAB_HOST URLs — no Traefik, no path prefixes.
tags: [operations, host, ports]
---

# Host-direct mode (ports)

*Laptop-style ports on a shared host: web `:8080`, CMS `:8001`, engine `:3030`, monitor `:3031`. OIDC and CORS use `LAB_HOST` instead of `localhost`. No reverse proxy.*

Use this when Traefik path prefixes (`/cms`, Vite `--base /monitor/`) get in the way of debugging, or when you want direct container endpoints without redirect rewriting.

## When to use this

| Mode | Reach the stack via | Make prefix |
|---|---|---|
| Laptop | `localhost:8080` … | `local-*` |
| Host (Traefik) | `https://LAB_HOST/…` path prefixes | `host-*` |
| **Host-direct** | `http://LAB_HOST:8080` … | `host-direct-*` |

Do **not** run Traefik host mode and host-direct at the same time. Tear down first:

```bash
make host-env-down          # or host-lab-down
make host-direct-env-init
```

## Port map

| Port | Service | Notes |
|---|---|---|
| `8080` | web client | OIDC origin |
| `8001` | CMS | Admin `/admin/`, GraphQL `/graphql`, static `/djstatic/` |
| `3030` | workflow engine | REST |
| `3031` | monitor app | Vite **root** base (no `/monitor` prefix) |

All ports bind on all interfaces. Traffic is plain HTTP; terminate TLS at another layer if required.

## `.env`

```bash
LAB_HOST=lab.example.com
# LAB_SCHEME is ignored for URL generation in this mode (ports are HTTP).
```

`make host-direct-oidc` runs `./gen_host_oidc` with `LAB_ACCESS=direct`, which writes:

- web client origin `http://LAB_HOST:8080`
- monitor `apiBaseUrl` `http://LAB_HOST:3030`

## Make targets

| Target | What it does |
|---|---|
| `make host-direct-env-init` | JWT, direct OIDC, pull/up, API key, `apply_cms_config`, recreate engine |
| `make host-direct-env-up` / `down` / `prune` | Base stack lifecycle |
| `make host-direct-lab-up` / `down` / `discover` / `logs` | Worker + devices |
| `make host-direct-ps` / `logs` / `compose` | Compose helpers |

Compose files:

```text
docker-compose.yml:docker-compose.host-direct.yml
# + docker-compose.worker.yml for lab targets
```

## First bring-up

```bash
# DNS or /etc/hosts → this host
echo 'LAB_HOST=lab.example.com' >> .env

make host-direct-env-init
make host-direct-lab-up
make host-direct-lab-discover
```

Then open:

- `http://lab.example.com:8080/` — web client
- `http://lab.example.com:8001/admin/` — CMS (`neops` / `neops`)
- `http://lab.example.com:3031/` — monitor
- `http://lab.example.com:3030/health` — engine

## Firewall

Open TCP `8080`, `8001`, `3030`, `3031` to clients that should reach the lab. Prefer a VPN or jump host over exposing these on the public internet.
