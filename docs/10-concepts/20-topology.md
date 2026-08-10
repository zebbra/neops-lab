---
title: Topology as source of truth
description: topology.json describes every device and link; gen_clab_topology renders the containerlab topology, the per-device configs and three discovery parameter files from it.
tags: [concept, topology]
---

# Topology as source of truth

*One JSON file describes the network. Everything else about the network is generated from it — and a test enforces that.*

## `topology.json`

A single object, `devices`, keyed by hostname. Each device carries four fields:

```json
"leaf-01": {
  "mgmt_ip": "172.30.0.33",
  "vendor": "srl",
  "loopback": null,
  "interfaces": [
    { "name": "ethernet-1/1", "to": "spine-01:e1/1" },
    { "name": "ethernet-1/3", "to": "server web-01" }
  ]
}
```

| Field | Meaning |
|---|---|
| `mgmt_ip` | A free address in `172.30.0.0/24`. Becomes containerlab's `mgmt-ipv4` and the discovery target. |
| `vendor` | `frr` or `srl`. Selects the node kind, the image, the credentials and the discovery platform. |
| `loopback` | `"lo"` for FRR, `null` for SR Linux. FRR gets an extra `lo` line with description `<host> loopback`. |
| `interfaces` | List of `{ "name", "to" }`. `name` is `swpN` (FRR) or `ethernet-1/N` (SR Linux). |

### The `to` field decides link type

`to` is parsed by `parse_endpoint`:

- **`"<peer-host>:<peer-iface>"` where `<peer-host>` is a device in the file** → a real `veth` link between the two nodes.
- **anything else** → a `dummy` link: a real stub interface on the owning node, with a description, and no neighbour. That covers a plain label (`"isp-upstream"`, `"server web-01"`) *and* a `host:iface` pair whose host is not a device (`"cust-a-ce:ge0/0"`).

Real links are deduplicated: a physical cable is listed on both devices, and `build_links` keys them by the unordered endpoint pair so it appears once in the topology.

### Interface-name mapping

Three name spellings coexist and the generator converts between them:

| Where | FRR | SR Linux |
|---|---|---|
| `topology.json` `name` | `swp1` | `ethernet-1/1` |
| `topology.json` `to` (short form) | `swp1` | `e1/1` |
| containerlab netdev | `swp1` | `e1-1` |
| Interface description | `swp1` | `e1/1` |

`clab_iface` maps a `name` to the containerlab netdev, `_peer_iface_to_clab` handles both spellings on the peer side, and `short_name` produces the description form. SR Linux itself aliases `e1-1` back to `ethernet-1/1`, so the NOS config and the containerlab wiring agree.

## What the generator produces

`./gen_clab_topology` (stdlib-only, runs on the host) reads `topology.json` and writes:

| Output | Tracked? | Contents |
|---|---|---|
| `generated/neops-lab.clab.json` | no | The containerlab topology: nodes, kinds, images, `veth` links, `dummy` links |
| `generated/frr/<host>.iface` | no | `name|description` per line, loopback first |
| `generated/srl/<host>.cli` | no | `set / interface … admin-state enable` + `… description "…"` per interface |
| `workflow-execution-parameters/discover-params.json` | **yes** | 15 `/32`s with `platform` + platform-scoped credentials |
| `workflow-execution-parameters/discover-params-autodetect.json` | **yes** | the same `/32`s without `platform` |
| `workflow-execution-parameters/discover-params-subnet.json` | **yes** | the management `/24` with subnet-scoped credentials |

It also prunes stale `generated/frr/*.iface` and `generated/srl/*.cli` files for hostnames no longer in the topology, and prints a summary:

```text
generated clab topology: 15 nodes, 18 veth links, 8 dummy links
generated 10 FRR + 5 SRL device configs
generated discover-params.json + discover-params-autodetect.json + discover-params-subnet.json
```

`gen_device_configs` is the sibling module holding the per-device renderers (`render_frr`, `render_srl`); `gen_clab_topology` loads it by path and reuses them. It is also runnable on its own if you only want the device configs.

!!! warning "`discover-params-mixed.json` is hand-maintained"
    Three of the four parameter files are generated. **`discover-params-mixed.json`
    is not** — no generator emits it and no test covers it. It is a hand-written
    scenario (the `/24` plus `/32` overrides for the SR Linux nodes, exercising
    longest-prefix-match credential selection). If you change `topology.json`,
    the other three files regenerate; this one you must update yourself, and
    nothing will tell you that you forgot.

## How each vendor is configured

=== "FRRouting"

    containerlab runs the local image `neops-lab-frr:latest` as `kind: linux`
    and binds two files into the node:

    - `frr/<host>.iface` → `/etc/frr/lab-interfaces/<host>.iface`
    - `../devices/frr/set-aliases.sh` → `/etc/frr/set-aliases.sh`

    containerlab creates the `swpN` veths itself. A containerlab `exec` then
    runs `set-aliases.sh` **after wiring**, which sets each interface's Linux
    *alias* — that is what the SDK's FRR plugin reads as the interface
    description:

    ```sh title="devices/frr/set-aliases.sh"
    --8<-- "../devices/frr/set-aliases.sh"
    ```

=== "Nokia SR Linux"

    containerlab runs the public image `ghcr.io/nokia/srlinux:26.3` as
    `kind: nokia_srlinux` and applies `srl/<host>.cli` as the node's
    `startup-config` at boot, so descriptions and admin-state are set by the
    NOS itself.

    The default containerlab variant is the `7220 IXR-D2L`, so the node has
    many more ports than the topology wires. The wired ones carry descriptions;
    the rest show admin-disabled — which is realistic for a switch.

!!! warning "`../devices/frr/set-aliases.sh` is relative to `generated/`"
    The generator emits that bind path with a leading `../` because the
    topology file it writes lives in `generated/`, and containerlab resolves
    binds relative to the topology file. It is correct as written — do not
    "fix" it to `devices/…`.

## The generator tests are the guard

`tests/test_gen_clab_topology.py` and `tests/test_gen_device_configs.py` load the extension-less scripts by path and assert, among other things, that regenerating from `topology.json` reproduces the **committed** `workflow-execution-parameters/*.json` byte-for-byte. `_dump_discover_params` hand-rolls a compact per-entry layout that `json.dumps` cannot produce, so the check is exact.

The consequence for you: **change `topology.json` → run `./gen_clab_topology` → commit the regenerated JSON**, or `make test` fails. See [Adding a device](../20-operations/30-adding-a-device.md) for the full loop.
