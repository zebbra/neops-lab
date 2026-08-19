---
title: Glossary
description: Terms used across this documentation and the wider NeOps platform.
tags: [reference]
---

# Glossary

Blackboard
:   The workflow engine's job-distribution mechanism. Workers poll it for jobs matching the function blocks they have registered; the engine posts results back. In this lab the worker reaches it at `URL_BLACKBOARD=http://workflow_engine:3030`.

CMS
:   The NeOps network content-management system — the Django monolith (`neops-core`, shipped here as `quay.io/zebbra/neops-cms-free`) that owns entities such as `Device` and `Interface` and serves the platform GraphQL API. Reachable at <http://localhost:8001>.

containerlab
:   The tool that runs the device containers and wires real `veth` links between them via Linux network namespaces. Driven by the generated `generated/neops-lab.clab.json`. Always invoked as `./containerlab` here — the repo's launcher, which exec's a native binary on Linux and runs the official `ghcr.io/srl-labs/clab` image in container mode on macOS. See [containerlab.dev](https://containerlab.dev).

Control plane
:   In this repo's vocabulary, the NeOps services on docker compose — CMS, workflow engine, monitor app, web client, worker — as opposed to the 15 device containers.

Dummy link
:   A containerlab link type that creates a real interface on one node with **no** peer. Used for ports that face something outside the lab: leaf→server, pe→customer CE, border→ISP.

Entity
:   A record in the CMS. Discovery creates `Device` and `Interface` entities.

Function block
:   The unit of work a worker executes, identified as `<package>/<name>:<major.minor.patch>` — e.g. `fb.base.neops.io/global_discover_network:0.1.0`. Workflow steps dispatch to function blocks by that identifier.

FRR / FRRouting
:   The open-source routing stack behind the 10 `frr` nodes. Run here as `kind: linux` from the locally built `neops-lab-frr:latest`. Vendor string in the CMS: `FRRouting`.

`lab-net`
:   The docker bridge network (`172.30.0.0/24`) created by the Makefile (`make lab-net`) before the first `docker compose up`, declared `external` in `docker-compose.worker.yml`, and used by containerlab as the devices' management network. The worker sits on it *and* on the compose default network, which is how it reaches both the engine and the devices.

Monitor app
:   The SvelteKit UI shipped inside the workflow-engine image (`/app/rest/monitor-app`), run here as the `workflow-engine-client` service on <http://localhost:3031>. Today the primary UI for workflow authoring and execution monitoring; explicitly temporary — the functionality is planned to move into the NeOps web client.

`neops-lab`
:   **This repo.** A *local* containerlab dev/demo environment. Not published, not imported by anything.

`neops-remote-lab`
:   A **different repo**: a shared, *remote* FastAPI service giving automated tests exclusive, FIFO-queued access to real [Netlab](https://netlab.tools/) topologies. Published to PyPI and imported by `neops-worker-sdk-py` as `remote_lab_fixture`. **It shares nothing with this repo.** See [NeOps ecosystem](neops-ecosystem.md).

Platform
:   In discovery parameters, the short vendor name that selects the SDK connection plugin: `frr` → `FRRNetmikoPlugin`, `srl` → `SRLinuxNetmikoPlugin`. Matches the `vendor` field in `topology.json`.

Scope
:   A CMS concept controlling which entities a user sees and how they are presented (table columns, filters, drill-down, dashboard). The lab configures exactly one, named `Global` — capital G.

SR Linux
:   Nokia's network OS, behind the 5 `srl` nodes. Run from the public `ghcr.io/nokia/srlinux:26.3` image as `kind: nokia_srlinux`, with the generated `.cli` applied as its startup config. Vendor string in the CMS: `Nokia`.

`veth`
:   A Linux virtual Ethernet pair — the mechanism containerlab uses to "cable" two device containers together. What makes interface state and LLDP neighbours real in this lab rather than simulated.

Worker
:   The process that polls the blackboard and executes function blocks. Here it is the published `quay.io/zebbra/neops-worker-sdk` image, with this repo mounted read-only at `/app/lab`.

Workflow
:   A declarative YAML/JSON definition of steps executed by the engine, identified as `<package>/<name>:<version>`. This lab ships one: `wf.lab.neops.io/simple_lab_discovery:1.2.0`.
