---
title: Get started
description: From a clean checkout to 15 discovered devices — prerequisites, the four-command quickstart, and your first discovery run.
tags: [tutorial]
---

# Get started

*Three pages, in order. Budget about 20 minutes of wall-clock time, most of it waiting for images to pull and SR Linux to boot.*

## The short version

```bash
make lab-jwt          # dev RSA keypair for the CMS (idempotent)
make local-env-init   # pull + start the base stack, mint the CMS API key, seed CMS config
make local-lab-up     # generate topology, build lab images, deploy 15 devices
make local-lab-discover
```

If any of those four words mean nothing to you yet, read on — each page below explains one step and the failure modes it protects you from.

## In this section

<div class="grid cards" markdown>

-   :material-clipboard-check:{ .lg .middle } &nbsp; **[Prerequisites](10-prerequisites.md)**

    ---

    Docker, containerlab (with sudo-less operation — the part people get wrong), `openssl`, `uv`, and Quay pull access for the `@zebbra` images. Includes a two-node probe that proves containerlab works before you commit to a 15-node deploy.

-   :material-rocket-launch:{ .lg .middle } &nbsp; **[Quickstart](20-quickstart.md)**

    ---

    The four commands in order, what each one actually does, what it waits for, and the URLs you get at the end.

-   :material-radar:{ .lg .middle } &nbsp; **[Your first discovery](30-first-discovery.md)**

    ---

    Trigger the discovery workflow, watch it in the monitor app, and see the 15 devices and their interfaces land in the web client. Then swap the parameter file to exercise autodetection and subnet expansion.

</div>

## What to read next

- **[Architecture](../10-concepts/10-architecture.md)** — the container/network layout you just started.
- **[Make targets](../20-operations/10-make-targets.md)** — the complete target list, including the ones the quickstart does not use.
- **[Troubleshooting](../20-operations/40-troubleshooting.md)** — read this the moment something hangs; nearly every failure here is a known boot-order race with a distinctive error string.
