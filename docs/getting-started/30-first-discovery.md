---
title: Your first discovery
description: Run the discovery workflow, watch it execute, and see 15 devices with their interfaces appear in the CMS — then swap parameter files to change how discovery is targeted.
tags: [tutorial]
---

# Your first discovery

*One command turns 15 running containers into 15 `Device` entities with their `Interface` rows.*

## Run it

```bash
make local-lab-discover
```

The target does three things:

1. `./wait_ready fb.base.neops.io/global_discover_network:0.1.0` — confirm an online worker is registered for the discovery function block.
2. `docker compose exec -T worker python3 lab/wait_devices` — confirm every device in `topology.json` accepts SSH.
3. `./run_workflow --timeout 900 wf.lab.neops.io/simple_lab_discovery:1.2.0 @workflow-execution-parameters/discover-params.json`

`run_workflow` POSTs to `/workflow-execution`, prints the execution UUID, then polls until the execution reaches a terminal state:

```text
execution 4f2c…-…-…
  [  2s] running
  [ 41s] completed_ack
```

Its exit code is meaningful: `0` for `completed_ack`, `1` for `failed_safe_ack` / `failed_unsafe_ack`, `2` if the workflow could not be started or polling timed out.

!!! info "Why the 15-minute timeout"
    `run_workflow`'s own default is 300s. Discovering 15 devices — SSH plus
    fact and interface collection across 10 FRR and 5 slower Nokia SR Linux
    nodes — legitimately exceeds it, so the make target passes
    `--timeout 900`. Autodetection adds an SSH probe per host, and the same
    ceiling covers that too.

## Watch it happen

Open the monitor app at <http://localhost:3031> while it runs — the execution appears with its step state and any failure reason. Then open the web client at <http://localhost:8080/> and browse to the device list: 15 rows, `vendor=FRRouting` for the 10 routers and `vendor=Nokia` for the 5 switches, each with its interfaces recorded.

The discovery function block records the device **and its interfaces** in one pass: it connects via the matching connection plugin, reads facts plus interfaces, and writes both `Device` and `Interface` rows to the CMS. Interface descriptions encode the neighbour (`leaf-01:e1/1 -> spine-01:e1/1`), and connected ports come up **UP**, because the links are real veths — not simulated state.

!!! warning "Re-running discovery duplicates interfaces"
    Devices are keyed by IP, so a second run skips existing devices.
    **Interfaces are always recorded**, so a second run against the same CMS
    adds a second set of interface rows. Run discovery against a *fresh* CMS
    (`make local-env-prune` → `make local-env-init`) when the interface counts
    matter.

## Targeting discovery differently

`make local-lab-discover` takes a `DISCOVER_PARAMS` override, so the same workflow can be pointed at four different shapes of input:

=== "Explicit hosts (default)"

    15 `/32` subnets with a known `platform`, and credentials scoped to that
    platform — so no host is ever tried with the other vendor's login.

    ```bash
    make local-lab-discover
    ```

    ```json title="workflow-execution-parameters/discover-params.json"
    --8<-- "../workflow-execution-parameters/discover-params.json"
    ```

=== "Autodetect"

    The same `/32`s with `platform` left out, so discovery has to detect it —
    what a real greenfield scan looks like.

    ```bash
    make local-lab-discover \
      DISCOVER_PARAMS=workflow-execution-parameters/discover-params-autodetect.json
    ```

    ```json title="workflow-execution-parameters/discover-params-autodetect.json"
    --8<-- "../workflow-execution-parameters/discover-params-autodetect.json"
    ```

=== "Subnet expansion"

    One target for the whole management `/24`, with subnet-scoped credentials.
    Discovery expands the prefix and probes every address.

    ```bash
    make local-lab-discover \
      DISCOVER_PARAMS=workflow-execution-parameters/discover-params-subnet.json
    ```

    ```json title="workflow-execution-parameters/discover-params-subnet.json"
    --8<-- "../workflow-execution-parameters/discover-params-subnet.json"
    ```

=== "Mixed"

    The `/24` plus `/32` overrides for the SR Linux nodes — exercises
    longest-prefix-match credential selection.

    ```bash
    make local-lab-discover \
      DISCOVER_PARAMS=workflow-execution-parameters/discover-params-mixed.json
    ```

    ```json title="workflow-execution-parameters/discover-params-mixed.json"
    --8<-- "../workflow-execution-parameters/discover-params-mixed.json"
    ```

The precedence rules behind these — longest prefix wins, credentials scoped from most to least specific — are explained in [Discovery](../10-concepts/30-discovery.md).

!!! note "`wait_devices` always waits for the *known* devices"
    Even when you point discovery at the `/24`, the readiness poll uses
    `topology.json`, not the parameter file. A subnet target also contains
    unused addresses, and waiting on those would always time out.

## Running a workflow by hand

`run_workflow` is a general-purpose host script, not discovery-specific:

```bash
# Parameters from a file (curl-style "@file")
./run_workflow wf.lab.neops.io/simple_lab_discovery:1.2.0 \
  @workflow-execution-parameters/discover-params.json

# Inline JSON
./run_workflow wf.lab.neops.io/simple_lab_discovery:1.2.0 '{"subnets": []}'

# From stdin
echo '{"subnets": []}' | ./run_workflow wf.lab.neops.io/simple_lab_discovery:1.2.0 -
```

`--ids 12,34` fills `executeOnParameters.ids` for entity-scoped workflows; `--engine-url`, `--timeout` and `--interval` are also available (`./run_workflow --help`).

## Next

- [Discovery](../10-concepts/30-discovery.md) — the workflow, the function block and the parameter contract.
- [Troubleshooting](../20-operations/40-troubleshooting.md) — if the run failed, start with the error string.
