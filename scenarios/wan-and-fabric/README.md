# WAN and DC fabric

The lab's original network, and the one every make target uses unless
`SCENARIO` says otherwise.

Two independent islands on `lab-net` (`172.30.0.0/24`):

- **A 10-node FRR network** — two core routers, two edge routers, three PEs,
  two WAN routers and a border router, wired core-to-edge-to-PE with customer
  CE stubs and an ISP uplink stub. Reached over SSH as `frr` / `frr`.
- **A 5-node Nokia SR Linux fabric** — two spines and three leaves in a
  leaf-spine mesh, with server stubs on the leaves. Reached as
  `admin` / `NokiaSrl1!`.

## What it demonstrates

Discovery against two NOS families in one run, from four different parameter
shapes: declared platforms, autodetected platforms, a summarising subnet, and a
hand-written mixed file. LLDP neighbour discovery is real on the SR Linux
fabric only; the FRR nodes do not run LLDP.
