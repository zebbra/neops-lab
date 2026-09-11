---
title: Topology as source of truth
description: Each scenario's topology.json describes every device and link; gen_clab_topology renders the containerlab topology, the per-device configs and three discovery parameter files from it.
tags: [concept, topology]
---

# Topology as source of truth

*One JSON file describes the network. Everything else about the network is generated from it — and a test enforces that.*

Each [scenario](../30-scenarios/index.md) owns one. `scenarios/wan-and-fabric/topology.json` is the default; `scenarios/frr-only/topology.json` is the same WAN domain without the SR Linux fabric. A topology is never inherited from `scenarios/_base/` — a scenario *is* its topology.

## `scenarios/<scenario>/topology.json`

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

`make generate` (which resolves the scenario, then runs the stdlib-only host script `gen_clab_topology`) reads the selected scenario's `topology.json` and writes, for `SCENARIO=wan-and-fabric`:

| Output | Tracked? | Contents |
|---|---|---|
| `generated/wan-and-fabric/clab/neops-lab.clab.json` | no | The containerlab topology: nodes, kinds, images, `veth` links, `dummy` links |
| `generated/wan-and-fabric/clab/frr/<host>.iface` | no | `name|description` per line, loopback first |
| `generated/wan-and-fabric/clab/srl/<host>.cli` | no | `set / interface … admin-state enable` + `… description "…"` per interface |
| `scenarios/wan-and-fabric/workflow-execution-parameters/discover-params.json` | **yes** | one `/32` per device with `platform` + platform-scoped credentials |
| `scenarios/wan-and-fabric/workflow-execution-parameters/discover-params-autodetect.json` | **yes** | the same `/32`s without `platform` |
| `scenarios/wan-and-fabric/workflow-execution-parameters/discover-params-subnet.json` | **yes** | the management `/24` with subnet-scoped credentials |

The generated parameter files are written back beside the topology that produced them, so each scenario carries its own committed set.

It also prunes stale `*.iface` and `*.cli` files for hostnames no longer in the topology, and prints a summary:

```text
scenario 'wan-and-fabric': 15 nodes, 18 veth links, 8 dummy links
generated 10 FRR + 5 SRL device configs
generated discover-params.json, discover-params-autodetect.json, discover-params-subnet.json
```

`gen_device_configs` is the sibling module holding the per-device renderers (`render_frr`, `render_srl`) and the topology loader; `gen_clab_topology` loads it by path and reuses them. It is also runnable on its own if you only want the device configs.

!!! warning "`discover-params-mixed.json` is hand-maintained"
    Three of the four parameter files are generated. **`discover-params-mixed.json`
    is not** — no generator emits it and no test covers it. It is a hand-written
    case (the `/24` plus `/32` overrides for the SR Linux nodes, exercising
    longest-prefix-match credential selection) and it exists only for
    `wan-and-fabric`, because mixing per-subnet platforms has nothing to express
    when every device runs the same NOS. If you change that topology, the other
    three files regenerate; this one you must update yourself, and nothing will
    tell you that you forgot.

## How each vendor is configured

=== "FRRouting"

    containerlab runs the local image `neops-lab-frr:latest` as `kind: linux`
    and binds four files into the node:

    - `frr/<host>.iface` → `/etc/frr/lab-interfaces/<host>.iface`
    - `../scenario/devices/frr/set-aliases.sh` → `/lab/set-aliases.sh`
    - `../scenario/devices/frr/frr.conf` → `/lab/frr.conf`
    - `../scenario/devices/frr/daemons` → `/lab/daemons`

    The last two are the scenario's FRR configuration. The image does **not**
    bake them: `devices/frr/entrypoint.sh` installs them from `/lab` before
    `docker-start` and refuses to boot if they are absent, so one
    `neops-lab-frr:latest` serves every scenario and a scenario wanting a
    different routing baseline ships a `devices/frr/daemons` delta instead of a
    second image.

    containerlab creates the `swpN` veths itself. A containerlab `exec` then
    runs `set-aliases.sh` **after wiring**, which sets each interface's Linux
    *alias* — that is what the SDK's FRR plugin reads as the interface
    description:

    ```sh title="scenarios/_base/devices/frr/set-aliases.sh"
    --8<-- "../scenarios/_base/devices/frr/set-aliases.sh"
    ```

=== "Nokia SR Linux"

    containerlab runs the public image `ghcr.io/nokia/srlinux:26.3` as
    `kind: nokia_srlinux` and applies `srl/<host>.cli` as the node's
    `startup-config` at boot, so descriptions and admin-state are set by the
    NOS itself.

    The default containerlab variant is the `7220 IXR-D2L`, so the node has
    many more ports than the topology wires. The wired ones carry descriptions;
    the rest show admin-disabled — which is realistic for a switch.

!!! warning "The `../scenario/…` bind paths are relative to the topology file"
    The generator emits those binds with a leading `../` because the topology
    file it writes lives in `generated/<scenario>/clab/`, and containerlab
    resolves binds relative to the topology file's own directory — not the repo
    root — before handing absolute host paths to the daemon. `../scenario/…`
    therefore reaches `generated/<scenario>/scenario/`, the resolved overlay.
    They are correct as written; do not "fix" them to `devices/…`.

## The generator tests are the guard

`tests/test_gen_clab_topology.py` and `tests/test_gen_device_configs.py` load the extension-less scripts by path and assert, among other things, that regenerating from a scenario's `topology.json` reproduces its **committed** `workflow-execution-parameters/*.json` byte-for-byte. `_dump_discover_params` hand-rolls a compact per-entry layout that `json.dumps` cannot produce, so the check is exact.

The guard is **parametrised over `scenarios/*`**, so adding a scenario extends it automatically rather than leaving it covering only the first one. `tests/test_scenario_manifests.py` adds the structural checks: every manifest is complete, and every device-to-device link is symmetric — which is what catches a scenario derived by deleting devices and leaving a survivor pointing at something that is gone.

The consequence for you: **change a `topology.json` → run `make generate SCENARIO=<name>` → commit the regenerated JSON**, or `make test` fails. See [Adding a device](../20-operations/30-adding-a-device.md) for the full loop.
