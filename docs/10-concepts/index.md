---
title: Concepts
description: The mental model — what containers exist, how topology.json drives everything generated, how discovery works, and why in-container paths carry a lab/ prefix.
tags: [concept]
---

# Concepts

*Four pages that explain why the lab is shaped the way it is. Read [Architecture](10-architecture.md) first; the rest can be read in any order.*

## In this section

<div class="grid cards" markdown>

-   :material-sitemap:{ .lg .middle } &nbsp; **[Architecture](10-architecture.md)**

    ---

    Every container, which compose file declares it, which network it is on, which port it publishes. Why the lab uses two compose files combined through `COMPOSE_FILE`, and how the devices end up on the same bridge as the worker.

-   :material-file-tree:{ .lg .middle } &nbsp; **[Topology as source of truth](20-topology.md)**

    ---

    `topology.json` holds every device, management IP, vendor, loopback and interface. `gen_clab_topology` renders the containerlab topology, the per-device configs and three of the four discovery parameter files from it. Nothing else is authored by hand.

-   :material-radar:{ .lg .middle } &nbsp; **[Discovery](30-discovery.md)**

    ---

    The workflow, the function block it dispatches to, and the parameter contract: subnets, platforms, and how credentials are scoped. Also: the function block lives in the *worker image*, not in this repo.

-   :material-folder-swap:{ .lg .middle } &nbsp; **[The `/app/lab` mount](40-container-paths.md)**

    ---

    The repo is bind-mounted read-only at `/app/lab` inside the worker, which is why in-container paths keep a `lab/` prefix while host paths never do. The single most confusing thing about this repo, explained once.

</div>

## The one-paragraph version

`topology.json` describes 15 devices. `gen_clab_topology` turns that into a containerlab topology plus per-device configs plus discovery parameters. containerlab deploys the devices onto the `lab-net` bridge at fixed management IPs. Docker compose runs the NeOps control plane, with the worker attached to *both* the default network (to reach the engine) and `lab-net` (to reach the devices). A one-shot bootstrap container registers the workflow definitions with the engine. Running the discovery workflow dispatches a function block onto the worker, which SSHes to every management IP and writes `Device` and `Interface` rows into the CMS.
