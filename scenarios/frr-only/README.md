# FRR network only

`wan-and-fabric` with the five Nokia SR Linux nodes removed: two core routers,
two edge routers, three PEs, two WAN routers and a border router. Reached over
SSH as `frr` / `frr`.

The two vendor groups are separate islands in the full topology — no FRR
interface points at a spine or a leaf — so nothing had to be rewired to produce
this.

## Why it exists

The SR Linux nodes want several GB of RAM and boot slowly. This scenario brings
the lab up in a fraction of the time, and it is what the Kubernetes flavour
renders anyway, so `make local-lab-up SCENARIO=frr-only` and
`make kind-lab-up SCENARIO=frr-only` cover the same devices.

It also demonstrates the overlay: this directory holds a topology, a manifest
and this README, and nothing else. The workflows, the `Global` scope
configuration, the FRR device config and the example function blocks all come
from `scenarios/_base/`.

## Discovery parameters

The three generated files only. There is no `discover-params-mixed.json` here —
mixing per-subnet platforms and credentials has nothing to express when every
device runs the same NOS.
