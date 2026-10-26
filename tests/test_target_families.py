"""The boundary between the environment and the device targets.

`local-env-*` owns the compose project; `local-lab-*` and `kind-lab-*` own the
devices and may not reach into it. Nothing enforces that but this file — the
coupling it forbids is exactly what the Makefile used to do.
"""

import os
import pathlib
import re
import subprocess

import pytest

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
MAKEFILE = (LAB_DIR / "Makefile").read_text()
ENV_EXAMPLE = (LAB_DIR / ".env.example").read_text()
# The Makefile with its comments stripped. A comment that quotes a command —
# `# NOT `docker compose wait …`` — must not answer for the command itself, in
# either direction: it can neither satisfy an assertion nor break a ban.
MAKEFILE_CODE = "\n".join(ln for ln in MAKEFILE.splitlines() if not ln.lstrip("\t").startswith("#"))


def test_wait_devices_runs_in_its_own_container():
    """A TCP-22 poll is device work. It used to run as
    `docker compose exec worker`, borrowing a control-plane service purely
    because that service sat on lab-net — so a lab could not be waited on
    without an environment.
    """
    assert "docker compose exec -T -e SCENARIO=$(SCENARIO) worker python3 lab/wait_devices" not in MAKEFILE
    assert "--network $(LAB_NET_NAME)" in MAKEFILE, "no throwaway container on lab-net"
    assert "WAIT_DEVICES =" in MAKEFILE, "the invocation is not declared once"


def test_wait_devices_is_declared_once_and_reused():
    """Two copies of a container invocation is two chances to drift."""
    assert MAKEFILE.count("python3 wait_devices") == 1
    # Recipe lines start with a tab, comments do not — so a prose mention of the
    # variable cannot stand in for a call site that went missing.
    call_sites = [ln for ln in MAKEFILE.splitlines() if ln.startswith("\t") and "$(WAIT_DEVICES)" in ln]
    assert len(call_sites) == 2, f"both recipes must reuse the variable; found {call_sites}"


def test_env_up_registers_workflows_and_waits_for_them(recipes):
    """`lab_bootstrap` publishes the workflow definitions and is a control-plane
    service, so waiting on it belongs here and not in a device target."""
    body = recipes["local-env-up"]
    assert "$(WAIT_BOOTSTRAP)" in body
    assert "$(MINT_ENGINE_TOKEN)" in body, "lab_bootstrap needs a token interpolated at up -d"


def test_no_recipe_mints_a_second_token(recipes):
    """A double mint is for a recipe that runs a long job between two engine
    calls, long enough for the first token to expire. No recipe does that any
    more — each makes its engine calls back to back, so a second login would buy
    nothing and spend one of the CMS's five-a-minute. The `unset` is a PROXY for
    the rule, not the rule: it is how $(MINT_ENGINE_TOKEN) is forced to re-mint,
    because the snippet reuses an already-set NEOPS_ENGINE_TOKEN. A hand-rolled
    `NEOPS_ENGINE_TOKEN=$$(./lab_token)` would mint a second token and pass both
    assertions.

    Whole-file, deliberately: the rule is about every recipe, not this one. The
    count stays scoped — three recipes mint a first token, so a whole-file count
    would just be wrong."""
    assert "unset NEOPS_ENGINE_TOKEN" not in MAKEFILE
    assert recipes["local-env-up"].count("$(MINT_ENGINE_TOKEN)") == 1


def test_the_worker_profile_is_documented_where_it_is_set():
    """COMPOSE_PROFILES is read by compose from .env, so .env.example is the
    place an operator finds the switch."""
    assert "COMPOSE_PROFILES=worker" in ENV_EXAMPLE


def test_env_up_says_whether_the_worker_is_on(recipes):
    """A worker that is off by profile must never look like one that failed."""
    body = recipes["local-env-up"]
    assert "COMPOSE_PROFILES" in body
    assert body.count("*,worker,*") == 2, "the report and the worker wait must agree on what counts as on"


def test_worker_debug_targets_exist(recipes):
    for name in ("worker-up", "worker-down", "worker-logs"):
        assert name in recipes, f"no {name} target"
    # Naming a profiled service on the command line enables its profile, so
    # these work with COMPOSE_PROFILES unset — that is the debug loop.
    assert "worker" in recipes["worker-up"]


def test_the_worker_profile_is_read_from_dotenv_not_the_shell():
    """compose reads COMPOSE_PROFILES from `.env`, which make never reads. A
    recipe interpolating the shell's copy would therefore report "disabled" on
    the very configuration `.env.example` ships, and skip the worker wait."""
    assert "COMPOSE_PROFILES ?= $(DOTENV_COMPOSE_PROFILES)" in MAKEFILE
    assert "DOTENV_COMPOSE_PROFILES := $(call dotenv,COMPOSE_PROFILES)" in MAKEFILE
    assert "$${COMPOSE_PROFILES}" not in MAKEFILE


def _worker_profile_case(profiles, text=MAKEFILE):
    """A recipe's own profile test, lifted out and handed a value — so the
    matrices below run the real `case`, not a second copy of its pattern.

    `text` defaults to the whole Makefile, whose first such block is
    `local-env-up`'s; pass a single recipe body to reach any other.
    """
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if 'case ",$(COMPOSE_PROFILES)," in' in ln)
    end = next(i for i in range(start, len(lines)) if lines[i].strip() == "esac")
    block = "\n".join(lines[start : end + 1]).lstrip("\t@")
    return block.replace("$(COMPOSE_PROFILES)", profiles)


@pytest.mark.parametrize(
    ("profiles", "expected"),
    [
        ("worker", "enabled"),
        ("foo,worker,bar", "enabled"),
        ("worker,extras", "enabled"),
        ("extras,worker", "enabled"),
        ("workerish", "disabled"),
        ("myworker", "disabled"),
        ("foo", "disabled"),
        ("", "disabled"),
    ],
)
def test_the_worker_profile_case_matches_a_whole_list_entry(profiles, expected):
    """COMPOSE_PROFILES is a comma-separated list, so the report has to match a
    whole entry: `foo,worker,bar` is the worker and `workerish` is not. The
    commas wrapping the subject are what buy that."""
    result = subprocess.run(  # noqa: S602
        _worker_profile_case(profiles), shell=True, capture_output=True, text=True, check=True
    )
    assert result.stdout.startswith(f"worker: {expected}"), result.stdout


@pytest.mark.parametrize(
    ("profiles", "noted"),
    [("worker", False), ("foo,worker,bar", False), ("workerish", True), ("foo", True), ("", True)],
)
def test_env_logs_notes_a_worker_left_outside_the_profiles(recipes, profiles, noted):
    """`docker compose logs -f` covers the services compose has ENABLED, so a
    worker started by `make worker-up` with the profile off is running and yet
    absent from the output. The `local-lab-logs` this target replaced named
    `worker` explicitly and so always showed it; without the note the
    replacement loses that silently.

    The same `*,worker,*` pattern as `local-env-up`, run here for real: two
    recipes disagreeing about what counts as an enabled worker is exactly the
    drift a shared pattern asserted through one caller lets through."""
    body = recipes["local-env-logs"]
    assert "*,worker,*" in body, "local-env-logs has no COMPOSE_PROFILES guard"
    result = subprocess.run(  # noqa: S602
        _worker_profile_case(profiles, body), shell=True, capture_output=True, text=True, check=True
    )
    assert ("worker-logs" in result.stdout) is noted, result.stdout


# Every target in the device family, by name — not an enumerated up/down/status,
# so a future `local-lab-restart` is held to the rule the day it is written. The
# cross-cutting operations are outside the family because they are no longer
# named into it: discovery needs the engine, the worker AND the devices, so it
# belongs to neither lifecycle and cannot be held to this rule.
DEVICE_TARGET = re.compile(r"^(local-lab|kind-lab)-[a-z-]+$")

# What a device target may never do. `docker` itself is fine — the device
# targets legitimately run `docker network create` and a throwaway `docker run`
# on lab-net. Reaching into the compose PROJECT is what is forbidden.
ENV_ONLY = ("docker compose", "./apply_cms_config", "./lab_token", "./wait_ready", "MINT_ENGINE_TOKEN")


def test_device_targets_never_touch_the_environment(recipes):
    """Devices and the control plane come up in either order, independently.
    `local-lab-up` used to start the whole compose project and `local-lab-down`
    used to `docker compose down`, so tearing down the devices took the CMS."""
    for name, body in recipes.items():
        if not DEVICE_TARGET.match(name):
            continue
        for forbidden in ENV_ONLY:
            assert forbidden not in body, f"{name} reaches into the control plane with {forbidden!r}"


def test_local_lab_down_leaves_the_environment_running(recipes):
    """It used to run a bare `docker compose down` after destroying the devices,
    so tearing down a lab tore down the CMS with it."""
    body = recipes["local-lab-down"]
    assert "containerlab destroy" in body or "$(CONTAINERLAB) destroy" in body
    assert "docker compose" not in body


def test_no_compose_file_override_survives():
    """One compose file means no overlay selection, which is what stopped
    `local-env-down` from seeing the worker it had to tear down."""
    assert "COMPOSE_FILE" not in MAKEFILE
    assert "COMPOSE_PATH_SEPARATOR" not in MAKEFILE


@pytest.mark.parametrize("target", ["local-env-init", "local-env-up"])
def test_the_stack_targets_create_a_dotenv(target):
    """`.env.example` ships an uncommented `COMPOSE_PROFILES=worker`, so it is no
    longer a file of pure overrides: a fresh clone with no `.env` runs the worker
    OFF while the example says it is on. compose reads `.env` and nothing else
    writes it, so every target that brings the project up needs `lab-env`."""
    assert "\nCOMPOSE_PROFILES=worker" in ENV_EXAMPLE, "the example no longer sets a default profile"
    match = re.search(rf"^{target}:(.*)$", MAKEFILE, re.MULTILINE)
    assert match, f"the Makefile declares no {target} target"
    assert "lab-env" in match.group(1).split(), f"{target} can run without a .env"


def test_local_lab_down_keeps_the_shared_network(recipes):
    """`containerlab destroy` removes the management network by default, but
    lab-net is not containerlab's: `make lab-net` creates it, compose declares it
    `external`, and the worker attaches to it. Removing it makes the next
    `docker compose up -d` abort on a missing external network."""
    assert "--keep-mgmt-net" in recipes["local-lab-down"]
    compose = (LAB_DIR / "docker-compose.yml").read_text()
    assert "external: true" in compose, "compose no longer treats lab-net as external"
    # The flag's justification named lab_bootstrap for three tasks; it has no
    # `networks:` key and never sat here. Pinning the attachment count is what
    # keeps the reason checkable instead of folklore.
    attached = [ln for ln in compose.splitlines() if ln.strip() == "- lab-net"]
    assert len(attached) == 1, f"{len(attached)} services declare lab-net; the comments say only the worker does"


def test_the_device_targets_act_on_the_deployed_scenario(recipes):
    """$(SCENARIO) is what was asked for; the marker is what is running. A status
    run against the requested topology reports nothing deployed while a full lab
    runs, and a teardown against it strands every device the two do not share."""
    for name in ("local-lab-down", "local-lab-status"):
        assert "$(DEPLOYED_CLAB_TOPO)" in recipes[name], f"{name} ignores the deployed-scenario marker"
    assert "$(CLAB_TOPO)" not in recipes["local-lab-status"]


def _run_local_lab_down(tmp_path, destroy_exit, with_topology=True):
    """`local-lab-down` as make expands it, run against a stub containerlab.

    `make -n` does the expanding and runs nothing itself, so the real
    containerlab is never reached however the recipe changes.
    """
    stub = tmp_path / "containerlab"
    stub.write_text(f"#!/bin/sh\nexit {destroy_exit}\n")
    stub.chmod(0o755)
    marker = tmp_path / "deployed-scenario"
    marker.write_text("wan-and-fabric\n")
    if with_topology:
        topo = tmp_path / "generated/wan-and-fabric/clab/neops-lab.clab.json"
        topo.parent.mkdir(parents=True)
        topo.write_text("{}")
    script = subprocess.run(  # noqa: S603
        ["make", "-n", "local-lab-down", f"CONTAINERLAB={stub}", f"CLAB_DEPLOYED_MARKER={marker}"],  # noqa: S607
        cwd=LAB_DIR,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    result = subprocess.run(  # noqa: S602
        script, shell=True, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    return result, marker


def test_a_failed_destroy_keeps_the_marker_and_fails(tmp_path):
    """The marker is the only record of what is deployed. Dropped after a failed
    destroy, the next `local-lab-up SCENARIO=other` walks past its guard and two
    scenarios run side by side."""
    result, marker = _run_local_lab_down(tmp_path, destroy_exit=1)
    assert result.returncode != 0, "a teardown that did not tear down reported success"
    assert marker.exists(), "the deployed-scenario marker was dropped after a failed destroy"


def test_a_successful_destroy_removes_the_marker(tmp_path):
    result, marker = _run_local_lab_down(tmp_path, destroy_exit=0)
    assert result.returncode == 0, result.stderr
    assert not marker.exists()


def test_nothing_to_destroy_is_not_a_failure(tmp_path):
    """A clone that never deployed must be able to run this target."""
    result, marker = _run_local_lab_down(tmp_path, destroy_exit=1, with_topology=False)
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert "nothing to destroy" in result.stdout


def test_the_operation_targets_are_not_in_a_lifecycle_family(recipes):
    """Discovery needs the engine, the worker and the devices — it belongs to
    neither lifecycle, and naming it as one is what dragged the engine into a
    device target in the first place."""
    for name in ("discover", "kind-discover", "apply-cms-config", "kind-apply-cms-config", "lab-grant"):
        assert name in recipes, f"no {name} target"
    for gone in ("local-lab-discover", "kind-lab-discover", "kind-lab-cms-config", "local-lab-logs"):
        assert gone not in recipes, f"{gone} should have been renamed"


def _phony_names():
    """The names `.PHONY` declares.

    Built from the raw text and not from the `recipes` fixture, which keys
    `.PHONY` itself as a bodiless target. The continuations are joined FIRST:
    `.PHONY` spans many backslash-continued lines, so a line-anchored regex
    would capture only the first and pass vacuously for every name after it.
    """
    body = MAKEFILE.split(".PHONY:", 1)[1]
    body = body[: body.index("\n\n")] if "\n\n" in body else body
    return set(body.replace("\\\n", " ").split())


def test_phony_names_are_real_targets(recipes):
    """A stale `.PHONY` entry is a rename nobody finished."""
    missing = sorted(name for name in _phony_names() if name not in recipes)
    assert not missing, f".PHONY names targets that do not exist: {missing}"


def test_every_target_is_declared_phony(recipes):
    """None of these produce a file of their own name, so a stray file of that
    name would silently stop the target from running."""
    phony = _phony_names()
    undeclared = sorted(name for name in recipes if name not in phony and not name.startswith("."))
    assert not undeclared, f"targets missing from .PHONY: {undeclared}"


# The control-plane targets that have to see lab_bootstrap's workflow
# registration finish before they report success.
BOOTSTRAP_WAITERS = ("local-env-init", "local-env-up")


def test_no_recipe_waits_on_lab_bootstrap_by_running_state():
    """`docker compose wait SERVICE` blocks until that service's containers
    STOP, so a one-shot that has already exited leaves it nothing to attach to:
    it fails with "no containers for project" instead of reporting the exit code
    compose recorded. The faster registration finishes, the more reliably it
    loses — and `local-env-init` waits for a healthy engine first, so it is fast.
    """
    assert "docker compose wait lab_bootstrap" not in MAKEFILE_CODE


def test_both_control_plane_targets_wait_for_workflow_registration(recipes):
    for name in BOOTSTRAP_WAITERS:
        assert "$(WAIT_BOOTSTRAP)" in recipes[name], f"{name} does not wait for workflow registration"


def test_the_bootstrap_wait_is_declared_once_and_reused():
    """Two copies of the wait is two chances to drift, the same as WAIT_DEVICES."""
    assert MAKEFILE_CODE.count("docker wait") == 1, "the invocation is not declared once"
    call_sites = [ln for ln in MAKEFILE.splitlines() if ln.startswith("\t") and "$(WAIT_BOOTSTRAP)" in ln]
    assert len(call_sites) == len(BOOTSTRAP_WAITERS), f"both recipes must reuse the variable; found {call_sites}"


def _wait_bootstrap_snippet():
    """The Makefile's own bootstrap wait, lifted out. make collapses the
    backslash-newlines into spaces, so this is the single command the recipe
    runs — and `$$` is make's escape for a shell `$`."""
    lines = MAKEFILE.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("WAIT_BOOTSTRAP = "))
    end = start
    while lines[end].endswith("\\"):
        end += 1
    joined = " ".join(ln.rstrip("\\").strip() for ln in lines[start : end + 1])
    return joined.split("=", 1)[1].strip().replace("$$", "$")


def _run_wait_bootstrap(tmp_path, cid, exit_code):
    """Run that snippet against a stub `docker`, so the assertions below are
    about what the recipe does with an exit code rather than about a live
    project. `docker wait` prints the code and itself exits 0, which is the
    whole reason the snippet cannot just rely on its status."""
    stub = tmp_path / "docker"
    stub.write_text(
        "#!/bin/sh\n"
        'case "$1 $2" in\n'
        f'  "compose ps") printf %s "{cid}";;\n'
        '  "compose logs") echo "(stub logs)";;\n'
        f'  "wait "*) echo "{exit_code}";;\n'
        "esac\n"
        "exit 0\n"
    )
    stub.chmod(0o755)
    return subprocess.run(  # noqa: S602
        _wait_bootstrap_snippet(),
        shell=True,
        cwd=tmp_path,
        env={"PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_bootstrap_wait_passes_on_a_clean_registration(tmp_path):
    result = _run_wait_bootstrap(tmp_path, cid="abc123", exit_code=0)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_bootstrap_wait_fails_on_a_failed_registration(tmp_path):
    """A container that exited non-zero published nothing; carrying on would
    leave `make discover` to 404 on a workflow that was never registered."""
    result = _run_wait_bootstrap(tmp_path, cid="abc123", exit_code=3)
    assert result.returncode != 0, result.stdout
    assert "3" in result.stdout, result.stdout


def test_the_bootstrap_wait_fails_when_the_container_never_started(tmp_path):
    """An empty id would otherwise reach `docker wait` as no argument at all."""
    result = _run_wait_bootstrap(tmp_path, cid="", exit_code=0)
    assert result.returncode != 0, result.stdout
