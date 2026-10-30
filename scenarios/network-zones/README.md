# Network zones

Six FRR routers in three network zones. Two sit on the lab network in
`default`, as every other scenario's devices do; `zone-a` and `zone-b` each hold
two on a subnet of their own, with a worker attached to that subnet alone.
Reached over SSH as `frr` / `frr`.

| Zone | Subnet | Devices | Worker |
| --- | --- | --- | --- |
| `default` | `172.30.0.0/24` (`LAB_SUBNET`) | `core-rtr-01`, `core-rtr-02` | `worker`, the central one |
| `zone-a` | `172.30.10.0/24` | `site-a-rtr-01`, `site-a-rtr-02` | `worker-zone-a` |
| `zone-b` | `172.30.20.0/24` | `site-b-rtr-01`, `site-b-rtr-02` | `worker-zone-b` |

## Why it exists

It shows network zones on real devices. Each zone's worker is the only one that
can reach that zone's routers, so a discovery job that ran on the wrong worker
would find nothing:

- **Routing.** `make local-lab-discover` discovers `default` as every scenario
  does, then runs `wf.lab.neops.io/zone_discovery` once per zone. That
  workflow's step declares `networkZone: "{{ parameters.zone }}"`, so the
  engine hands each run's job only to a worker serving that zone.
- **Stamping.** The discovery block records each device in the zone its job ran
  in. The web client's device list shows the zone, and the CMS filters by it:
  `devices(networkZone_Name: "zone-a")`.

No two zones share an address here, because one Docker daemon refuses
overlapping subnets. Two devices answering on the same address in two zones is
covered by the workflow engine's end-to-end playbook, not by this lab.

## What it needs

The zones are recent on every side, so the published pins in `.env.example`
predate them. Point the lab at images that carry network zones (`.env.example`
lists the tags, commented out):

- a CMS from neops-core 2.4.0 or later (`NEOPS_CMS_IMAGE`): `apply_cms_config`
  stops with a message naming it otherwise;
- a workflow engine 0.45.0 or later (`NEOPS_ENGINE_TAG`);
- a worker from neops-worker-sdk 0.4.0 or later (`NEOPS_WORKER_SDK_IMAGE`),
  which carries `global_discover_network:0.2.0`;
- `docker compose` 2.24.4 or later, for the `!override` that keeps each zone's
  worker off the other networks.

It runs on containerlab only: the Kubernetes flavour puts every FRR device in
one namespace and knows no zones.

## How the lab carries it

The zones are declared in `topology.json` under `zones`, each with its subnet
and a description, and each device names its zone with `"zone"`; a device
without one is in `default`. From that one declaration:

- `apply_cms_config` creates the zones in the CMS before any worker starts. A
  zone's worker is refused while its zone does not exist.
- `make generate` writes one containerlab topology per zone
  (`generated/network-zones/clab/neops-lab-<zone>.clab.json`, on network
  `${LAB_NET}-<zone>`), a compose overlay with one worker per zone
  (`generated/network-zones/compose/zones.yml`), and the per-zone discovery
  parameters under `workflow-execution-parameters/zones/`.
- `make local-lab-up` waits until `default` and each zone have an online worker
  holding the discovery block, then for each zone's devices from inside that
  zone's worker.

The central worker serves `default` in every scenario
(`NEOPS_WORKER_NETWORK_ZONES: default` in `docker-compose.worker.yml`). The zones
stay in the CMS volume after `make local-lab-down`, and once a zone exists the
engine refuses a worker that lists none.

The zone subnets are fixed in `topology.json`. `LAB_SUBNET` moves only the
`default` devices, so a second lab beside this one needs other zone subnets
in its topology.

## Discovery parameters

The three generated files cover the `default` devices only. Each zone has one
generated file, `zones/<zone>.json`, which carries the zone's name beside its
`/32` targets and credentials.
