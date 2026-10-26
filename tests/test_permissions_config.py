"""The lab's declared roles, users and workflow grants.

`scenarios/_base/cms/permissions.json` is applied by `apply_cms_config`, which
reaches the CMS over `$CMS_EXEC` — so nothing about it is checked until a lab is
running. These assertions cover the parts that are checkable offline: the file's
shape, its internal cross-references, the two things the script has to keep
doing with it, and the points in the make targets at which it has to be applied
and the token carrying its grants minted.

Every scenario carrying the file is checked, since a scenario may override it.
"""

import json
import pathlib

import pytest

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
CONFIG_NAME = "permissions.json"
# The resolved tree the script reads is built from these, `_base` included.
CONFIG_PATHS = sorted((LAB_DIR / "scenarios").glob(f"*/cms/{CONFIG_NAME}"))
APPLY_SCRIPT = (LAB_DIR / "apply_cms_config").read_text()

# The choices `manage.py grant_workflow_permissions --profile` accepts.
PROFILES = ("author", "operator", "admin")


@pytest.fixture(params=CONFIG_PATHS, ids=lambda path: path.relative_to(LAB_DIR).as_posix())
def config(request):
    return json.loads(request.param.read_text())


def test_every_role_names_a_profile_the_grant_command_accepts(config):
    for role, profile in config["roles"].items():
        assert profile in PROFILES, f"role {role} asks for profile {profile!r}"


def test_every_role_a_user_holds_is_declared(config):
    """A user naming an undeclared role would receive no grant at all."""
    declared = set(config["roles"])
    for username, roles in config["users"].items():
        assert roles, f"user {username} holds no role"
        for role in roles:
            assert role in declared, f"user {username} holds undeclared role {role!r}"


def test_the_base_scenario_declares_the_file():
    """Nothing else guarantees the resolved tree has one to read."""
    assert (LAB_DIR / "scenarios" / "_base" / "cms" / CONFIG_NAME).is_file()


def test_apply_cms_config_reads_it_out_of_the_resolved_tree():
    """The overlay is resolved exactly once; no consumer reads `scenarios/`."""
    assert f'"${{SCENARIO_DIR}}/cms/{CONFIG_NAME}"' in APPLY_SCRIPT
    assert 'SCENARIO_DIR="generated/${SCENARIO}/scenario"' in APPLY_SCRIPT


def test_the_grant_call_is_guarded_by_a_capability_check():
    """CMS images predating the grant command must still complete the script,
    which `make local-env-init` runs on every fresh environment."""
    assert '"grant_workflow_permissions" in get_commands()' in APPLY_SCRIPT


def test_grants_are_applied_before_a_target_mints_a_token(recipes):
    """An access token carries the permissions its account holds at login and
    keeps them for its whole lifetime, so every target that mints one applies
    this file first."""
    minting = {name: body for name, body in recipes.items() if "$(MINT_ENGINE_TOKEN)" in body}
    assert minting, "no Makefile target mints an engine token"
    for name, body in minting.items():
        assert "./apply_cms_config" in body, f"{name} mints a token without applying {CONFIG_NAME}"
        assert body.index("./apply_cms_config") < body.index("$(MINT_ENGINE_TOKEN)"), (
            f"{name} mints a token before applying {CONFIG_NAME}"
        )
