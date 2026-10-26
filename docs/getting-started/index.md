---
title: Get started
description: From a clean checkout to a discovered network — prerequisites, the four-command quickstart, and your first discovery run.
tags: [tutorial]
---

# Get started

*Three pages, in order. Budget about 20 minutes of wall-clock time, most of it waiting for images to pull and SR Linux to boot.*

## The short version

```bash
make local-env-init   # the control plane: pull, start, mint the CMS API key, seed CMS config
make local-lab-up     # the devices: resolve the scenario, build the FRR image, deploy
make discover         # populate the CMS from them
```

The first two are independent — `local-env-*` drives `docker compose` alone,
`local-lab-*` drives `containerlab` alone — so they run in either order and
either can be torn down without the other. `make discover` is what joins them.

If any of that means nothing to you yet, read on — each page below explains one step and the failure modes it protects you from.

!!! tip "In a hurry, or short on RAM"
    Those commands run the default `wan-and-fabric` scenario: 15 devices, five
    of them slow-booting Nokia SR Linux nodes. `make scenarios` lists the
    alternatives, and `SCENARIO=frr-only` gives you a 10-device FRR-only lab
    that comes up in a fraction of the time:

    ```bash
    make local-lab-up SCENARIO=frr-only
    make discover SCENARIO=frr-only
    ```

    A checkout that always runs one lab can put `SCENARIO=frr-only` in `.env`
    instead; `make scenario` says which is selected and where it came from.

    See [Scenarios](../30-scenarios/index.md).

## In this section

<div class="grid cards" markdown>

-   :material-clipboard-check:{ .lg .middle } &nbsp; **[Prerequisites](10-prerequisites.md)**

    ---

    Docker, containerlab (with sudo-less operation — the part people get wrong), `openssl` and `uv`. The default `@zebbra` images are public, so no Quay login is needed. Includes a two-node probe that proves containerlab works before you commit to a full deploy.

-   :material-rocket-launch:{ .lg .middle } &nbsp; **[Quickstart](20-quickstart.md)**

    ---

    The four commands in order, what each one actually does, what it waits for, and the URLs you get at the end.

-   :material-radar:{ .lg .middle } &nbsp; **[Your first discovery](30-first-discovery.md)**

    ---

    Trigger the discovery workflow, watch it in the monitor app, and see the devices and their interfaces land in the web client. Then swap the parameter file to exercise autodetection and subnet expansion.

</div>

## What to read next

- **[Scenarios](../30-scenarios/index.md)** — running a different network, and adding one of your own.
- **[Architecture](../10-concepts/10-architecture.md)** — the container/network layout you just started.
- **[Make targets](../20-operations/10-make-targets.md)** — the complete target list, including the ones the quickstart does not use.
- **[Troubleshooting](../20-operations/40-troubleshooting.md)** — read this the moment something hangs; nearly every failure here is a known boot-order race with a distinctive error string.
