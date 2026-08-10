---
title: Adding a device
description: The four-step loop for extending the lab — edit topology.json, regenerate, redeploy, and commit the regenerated parameter files.
tags: [operations, howto]
---

# Adding a device

*Everything about the network comes from `topology.json`, so adding a device is one edit plus one regeneration. The step people miss is committing the regenerated JSON.*

## 1. Edit `topology.json`

Add an entry under `devices`, keyed by hostname:

```json
"leaf-04": {
  "mgmt_ip": "172.30.0.36",
  "vendor": "srl",
  "loopback": null,
  "interfaces": [
    { "name": "ethernet-1/1", "to": "spine-01:e1/4" },
    { "name": "ethernet-1/2", "to": "spine-02:e1/4" },
    { "name": "ethernet-1/3", "to": "server app-03" }
  ]
}
```

| Field | Rule |
|---|---|
| `mgmt_ip` | A free address in `172.30.0.0/24`. Existing devices use `.11`–`.20` (FRR) and `.31`–`.35` (SR Linux); `.1` is the bridge gateway. |
| `vendor` | `frr` or `srl` — anything else makes the generator exit with `unknown vendor`. |
| `loopback` | `"lo"` for FRR, `null` for SR Linux. |
| `interfaces[].name` | `swpN` for FRR, `ethernet-1/N` for SR Linux. |
| `interfaces[].to` | `"<peer-host>:<peer-iface>"` for a real link, or any other label for a host-facing stub. |

!!! tip "Cable both ends"
    A real link is deduplicated by endpoint pair, so declaring it on one side
    alone still produces the veth. But the *description* on the peer interface
    comes from the peer's own entry — declare it on both sides (as the existing
    devices do) or the neighbour will have an undescribed port.

    In the example above, `spine-01` also needs an `ethernet-1/4` entry
    pointing back at `leaf-04:e1/1`.

## 2. Regenerate and redeploy

```bash
make local-lab-up
```

`local-lab-up` runs `./gen_clab_topology` for you, so this single command rebuilds the containerlab topology (real link or `dummy` stub, plus the node's image and credentials) and the three generated parameter files, then redeploys.

To regenerate without touching the running lab:

```bash
./gen_clab_topology
```

## 3. Discover it

```bash
make local-lab-discover
```

The new device is picked up automatically: `discover-params.json` now contains its `/32`, and `wait_devices` reads the mgmt IPs straight from `topology.json`.

## 4. Commit the regenerated JSON

```bash
make test
```

!!! danger "The generator tests fail until you commit the regenerated files"
    `tests/` assert that regenerating from `topology.json` reproduces the
    committed `workflow-execution-parameters/*.json` **byte-for-byte**. Adding
    a device changes three of those files, so `make test` fails until you
    stage them:

    ```bash
    ./gen_clab_topology
    git add workflow-execution-parameters/
    ```

    This is the intended guard, not an annoyance — it is what keeps the
    committed parameter files honest.

## 5. If you touched the mixed scenario

`discover-params-mixed.json` has **no generator and no test coverage**. If your new device belongs in that scenario — the `/24` plus per-host `/32` credential overrides — edit it by hand. Nothing will remind you.

## Removing a device

Delete its entry from `topology.json` and regenerate. `gen_clab_topology` prunes stale `generated/frr/*.iface` and `generated/srl/*.cli` files for hostnames that no longer exist, so nothing is left behind. Commit the regenerated parameter files as above.

Devices already discovered into the CMS are **not** removed — discovery only adds. Use `make local-env-prune` for a clean CMS.

## Adding a different vendor

Not supported today without code changes. `gen_clab_topology` hardcodes the two vendors in three places:

- `mgmt_creds()` — the per-vendor login,
- `render_clab()` — the containerlab `kind` (`linux` / `nokia_srlinux`), the image, and the per-kind bind/exec or `startup-config` wiring,
- `gen_device_configs` — `render_frr` / `render_srl`.

Discovery also needs a matching connection plugin in `neops-worker-sdk-py` for the new platform. Treat it as a cross-repo change.
