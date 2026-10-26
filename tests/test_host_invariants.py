"""Repo-level invariants no other gate covers."""

import ast
import os
import pathlib
import re
import subprocess

import pytest

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]


def _generator_constant(name):
    tree = ast.parse((LAB_DIR / "gen_clab_topology").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id == name for x in node.targets):
            assert isinstance(node.value, ast.Constant)
            return str(node.value.value)
    raise AssertionError(f"{name} not found in gen_clab_topology")


def test_the_generator_owns_the_lab_subnet():
    """lab-net's subnet is written once, in the generator's mgmt block.

    Compose joins lab-net as `external` and so states no subnet for it; the
    project network it does own is pinned, because docker auto-allocates
    subnet-less networks from its 172.16/12 pool and that can collide with
    lab-net's fixed /24 on a busy host.
    """
    base = (LAB_DIR / "docker-compose.yml").read_text()
    assert "subnet: 172.30.1.0/24" in base

    generator = (LAB_DIR / "gen_clab_topology").read_text()
    assert '"ipv4-subnet": LAB_SUBNET' in generator, "the mgmt block must use the constant, not a literal"
    assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+/\d+", _generator_constant("LAB_SUBNET"))


def test_lab_net_is_external_to_compose():
    """`local-env-down` must never remove the network the devices sit on, and
    `local-lab-up` must work with no compose project in sight. Both follow from
    compose declaring lab-net external rather than owning it."""
    base = (LAB_DIR / "docker-compose.yml").read_text()
    assert re.search(r"^  lab-net:\n    external: true$", base, re.MULTILINE), "lab-net is not declared external"
    lab_net_block = base.split("  lab-net:", 1)[1].split("\n\n", 1)[0]
    assert "subnet:" not in lab_net_block, "an external network must not restate the subnet"


def test_compose_holds_every_service_in_one_file():
    """One compose file, one project — otherwise `local-env-down` cannot see the
    worker it has to tear down, which is how it used to orphan it."""
    assert not (LAB_DIR / "docker-compose.worker.yml").exists(), "the worker overlay must be gone"
    base = (LAB_DIR / "docker-compose.yml").read_text()
    for service in ("  cms:", "  workflow_engine:", "  worker:", "  lab_bootstrap:"):
        assert service in base, f"{service.strip()} is missing from docker-compose.yml"


def test_the_worker_is_the_only_profiled_service():
    """`lab_bootstrap` publishes workflow definitions and is control plane, so it
    is never optional; the worker is the one thing you turn off to debug."""
    base = (LAB_DIR / "docker-compose.yml").read_text()
    assert len(re.findall(r"^    profiles:", base, re.M)) == 1, "exactly one service carries a profile"
    # Slice to the next service header, whatever it is: hard-coding the service
    # that follows makes a reorder silently stop proving anything.
    worker = re.split(r"\n  \w[\w-]*:", base.split("\n  worker:", 1)[1], maxsplit=1)[0]
    assert 'profiles: ["worker"]' in worker


def test_compose_mounts_the_resolved_scenario_tree():
    """The three scenario assets containers consume are interpolated per
    scenario, so `SCENARIO=x docker compose up` mounts x's copies."""
    base = (LAB_DIR / "docker-compose.yml").read_text()

    assert "/scenario/workflows:/workflows:ro" in base
    assert "/scenario/function_blocks,neops/fb" in base
    assert "/scenario/cms/oidc-config.json:/etc/neops/oidc-config.json:ro" in base

    # `:?` and not `:-`: compose must abort on an unset SCENARIO. Left to warn,
    # it interpolates a blank and docker creates the missing bind source as an
    # empty directory — a lab that comes up with no workflows registered.
    assert base.count("${SCENARIO:?") == base.count("${SCENARIO"), "every SCENARIO reference must use :?"


def test_the_lab_net_name_matches_the_generator():
    """The Makefile and the topology must name the same network or the devices
    and the worker end up on different ones."""
    makefile = (LAB_DIR / "Makefile").read_text()
    assert f"LAB_NET_NAME := {_generator_constant('LAB_NET_NAME')}" in makefile


def test_every_target_that_starts_compose_creates_lab_net_first():
    """compose ABORTS on a missing external network and creates nothing, and the
    control-plane targets never deploy devices — so on a fresh clone nothing
    else would ever create it."""
    makefile = (LAB_DIR / "Makefile").read_text()
    for target in ("local-env-init", "local-env-up", "local-lab-up"):
        match = re.search(rf"^{re.escape(target)}:(.*)$", makefile, re.MULTILINE)
        assert match, f"no {target} target"
        assert "lab-net" in match.group(1).split(), f"{target} can start compose without lab-net"


def test_the_makefile_holds_the_only_scenario_default():
    """A second default is how a scenario gets half-applied — some assets from
    the new one, some from the old — which stays invisible until discovery
    produces a confusing result. Everything but the Makefile must fail on an
    unset SCENARIO rather than guess one."""
    makefile = (LAB_DIR / "Makefile").read_text()
    assert makefile.count("wan-and-fabric") == 1, "the default is written more than once"
    # Pin the whole expression, not just its spelling: `count == 1` is satisfied
    # just as well by a different default with `wan-and-fabric` left behind in a
    # comment. The literal lives here, so the Makefile's own count is unaffected.
    assert "SCENARIO ?= $(if $(DOTENV_SCENARIO),$(DOTENV_SCENARIO),wan-and-fabric)" in makefile
    assert "export SCENARIO" in makefile

    for name in ("docker-compose.yml", "apply_cms_config", "resolve_scenario"):
        text = (LAB_DIR / name).read_text()
        assert "SCENARIO:-" not in text, f"{name} carries a fallback SCENARIO default"


def test_make_reads_scenario_from_dotenv_because_compose_does():
    """Left to compose alone, SCENARIO in `.env` would reach the containers and
    not the generators — a scenario applied half from each of two labs."""
    makefile = (LAB_DIR / "Makefile").read_text()
    assert "DOTENV_SCENARIO := $(call dotenv,SCENARIO)" in makefile, "make never reads .env for SCENARIO"
    assert ".env" in _dotenv_command("SCENARIO")


def _dotenv_command(key):
    """The Makefile's own `.env` extraction for one key, lifted out so the tests
    run the real expression rather than a second copy of it that is free to
    drift."""
    makefile = (LAB_DIR / "Makefile").read_text()
    line = next(ln for ln in makefile.splitlines() if ln.startswith("dotenv = "))
    return line.split("$(shell ", 1)[1].rsplit(")", 2)[0].replace("$(1)", key)


# `$(dotenv)` is ONE rule with two callers, so every property below is asserted
# for both keys: a break that only shows up for the key the tests skipped is
# exactly what a shared rule tested through one caller lets through.
DOTENV_VALUES = {"SCENARIO": "frr-only", "COMPOSE_PROFILES": "worker"}
# Both keys, together, as `.env.example` writes them, among the neighbours a real
# file has — so each key is also shown not to read the other's line.
SAMPLE_DOTENV = "".join(
    ["# a comment\n", "NEOPS_CMS_IMAGE=neops-cms-free:latest\n", *(f"{k}={v}\n" for k, v in DOTENV_VALUES.items())]
)


@pytest.fixture(params=sorted(DOTENV_VALUES))
def dotenv_key(request):
    return request.param


def _value_from_dotenv(tmp_path, key, dotenv_text):
    (tmp_path / ".env").write_text(dotenv_text)
    result = subprocess.run(  # noqa: S602
        _dotenv_command(key), shell=True, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_the_dotenv_expression_parses_the_documented_form(tmp_path, dotenv_key):
    """Run the Makefile's own extraction against a sample `.env`. The expression
    is the risky part — a silent mismatch here is the failure this task exists
    to prevent."""
    assert _value_from_dotenv(tmp_path, dotenv_key, SAMPLE_DOTENV) == DOTENV_VALUES[dotenv_key]


def test_the_dotenv_expression_accepts_an_export_prefix(tmp_path, dotenv_key):
    """compose honours `export SCENARIO=x`, so make must too. Read by only one of
    them, it is the one form that diverges SILENTLY: make would fall through to
    its default and generate that scenario's tree while the containers mounted
    the other's, and `resolve_scenario` cannot object because both names are
    valid. Every other unsupported form fails loudly instead."""
    value = DOTENV_VALUES[dotenv_key]
    assert _value_from_dotenv(tmp_path, dotenv_key, f"export {dotenv_key}={value}\n") == value
    assert _value_from_dotenv(tmp_path, dotenv_key, f"  export   {dotenv_key} = {value}\n") == value


def test_the_dotenv_expression_matches_only_its_own_key(tmp_path, dotenv_key):
    """The `export` alternation must not widen the key it recognises — a prefix,
    a suffix or a run-on word is a different variable and means nothing here."""
    noise = f"MY_{dotenv_key}=nope\nEXPORT{dotenv_key}=nope\n{dotenv_key}_X=nope\n"
    assert _value_from_dotenv(tmp_path, dotenv_key, noise) == ""
    assert _value_from_dotenv(tmp_path, dotenv_key, f"# {dotenv_key}=nope\n") == ""


def test_the_last_definition_in_dotenv_wins(tmp_path, dotenv_key):
    """compose takes the last definition of a key, which is what `tail -n 1` is
    for; reading the first would hand make a value the containers never see."""
    assert _value_from_dotenv(tmp_path, dotenv_key, f"{dotenv_key}=first\n{dotenv_key}=last\n") == "last"


def test_an_absent_dotenv_is_not_an_error(tmp_path, dotenv_key):
    """A fresh clone has no `.env`; the default has to survive that, and so does
    a `.env` that simply does not mention this key."""
    result = subprocess.run(  # noqa: S602
        _dotenv_command(dotenv_key), shell=True, cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert result.stdout.strip() == ""
    assert _value_from_dotenv(tmp_path, dotenv_key, "NEOPS_CMS_IMAGE=neops-cms-free:latest\n") == ""


def test_every_dotenv_caller_memoizes_the_shell_call():
    """`$(call dotenv,…)` forks a `sed`, and make re-expands a recursive (`=`)
    variable on every reference — so a caller that left the call in one would
    re-read `.env` once per mention, twice in `local-env-up` alone, and could
    answer differently within a single recipe if the file changed underneath.
    `:=` expands it once, while the file is being parsed.

    Read from make's own variable database rather than from the source: a
    simply-expanded variable is recorded there as its VALUE, so a `$(call
    dotenv,…)` still visible is precisely one that stayed recursive.
    """
    database = subprocess.run(
        ["make", "-p", "-n", "--no-print-directory", "scenario"],  # noqa: S607
        cwd=LAB_DIR,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "DOTENV_COMPOSE_PROFILES := " in database, "make printed no variable database to inspect"
    unmemoized = [line for line in database.splitlines() if "$(call dotenv," in line]
    assert not unmemoized, f"a $(dotenv) call left in a recursive variable: {unmemoized}"


def test_the_environment_beats_dotenv(tmp_path):
    """`make local-lab-up SCENARIO=x` must win over the file, or an operator
    cannot override a checkout that pins one scenario.

    Run from a tmpdir carrying a `.env` of its own: `$(shell)` and `test -f .env`
    resolve against make's cwd, so this pits a real file against a real
    environment variable. Run in the repo it would prove nothing — the committed
    `.env` has no SCENARIO line, leaving the environment nothing to beat.

    The expected value is neither the file's nor the Makefile's default, so the
    assertion fails whichever of the three won by mistake. `-I` because the
    Makefile's `include` lines are repo-relative and make resolves them against
    the cwd rather than against the makefile.
    """
    (tmp_path / ".env").write_text("SCENARIO=frr-only\n")
    env = {**os.environ, "SCENARIO": "sentinel-from-the-environment"}
    result = subprocess.run(  # noqa: S603
        ["make", "-I", str(LAB_DIR), "-f", str(LAB_DIR / "Makefile"), "--no-print-directory", "scenario"],  # noqa: S607
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "sentinel-from-the-environment", "the environment did not override .env"


def test_env_example_documents_the_form_the_expression_parses():
    """A quoted or inline-commented entry would parse to the wrong value, and the
    example is where an operator copies the form from."""
    example = (LAB_DIR / ".env.example").read_text()
    assert "\n# SCENARIO=frr-only" in example, "the .env.example entry must be a plain, unquoted assignment"


def test_env_example_does_not_restate_the_default():
    """`wan-and-fabric` lives in the Makefile. An example naming it again is a
    second written-down default, free to drift from the real one."""
    example = (LAB_DIR / ".env.example").read_text()
    assert "wan-and-fabric" not in example


def test_env_example_documents_each_override_once():
    """The same override documented twice is two things to keep in step.
    Collapsed in Task 1; this keeps it collapsed."""
    example = (LAB_DIR / ".env.example").read_text()
    for key in ("NEOPS_CMS_IMAGE=", "NEOPS_WORKER_SDK_IMAGE=", "NEOPS_WEB_CLIENT_IMAGE="):
        assert example.count(key) == 1, f"{key} is documented more than once"


@pytest.mark.parametrize("target", ["local-env-init", "local-env-up"])
def test_the_stack_targets_mint_the_jwt_keypair_first(target):
    """The engine service bind-mounts `cms/jwt/public.pem` as a file. Docker
    creates a directory under that name when the file is absent, which the
    engine cannot read as a key and which `make lab-jwt` cannot write over.

    Every target that brings the compose project up therefore needs `lab-jwt`
    ahead of it. `local-lab-up` no longer does: it deploys devices only.
    """
    compose = (LAB_DIR / "docker-compose.yml").read_text()
    assert "./cms/jwt/public.pem:" in compose, "the engine service mounts no key file"
    makefile = (LAB_DIR / "Makefile").read_text()
    match = re.search(rf"^{target}:(.*)$", makefile, re.MULTILINE)
    assert match, f"the Makefile declares no {target} target"
    assert "lab-jwt" in match.group(1).split(), f"{target} starts the stack without lab-jwt"
