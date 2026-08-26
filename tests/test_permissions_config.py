"""The lab's declared roles, users and workflow grants.

`cms/permissions.json` is applied by `apply_cms_config`, which reaches the CMS
over `docker compose exec` — so nothing about it is checked until a lab is
running. These assertions cover the parts that are checkable offline: the file's
shape, its internal cross-references, and the two things the script has to keep
doing with it.
"""

import json
import pathlib

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = LAB_DIR / "cms" / "permissions.json"
CONFIG = json.loads(CONFIG_PATH.read_text())
APPLY_SCRIPT = (LAB_DIR / "apply_cms_config").read_text()

# The choices `manage.py grant_workflow_permissions --profile` accepts.
PROFILES = ("author", "operator", "admin")


def test_every_role_names_a_profile_the_grant_command_accepts():
    for role, profile in CONFIG["roles"].items():
        assert profile in PROFILES, f"role {role} asks for profile {profile!r}"


def test_every_role_a_user_holds_is_declared():
    """A user naming an undeclared role would receive no grant at all."""
    declared = set(CONFIG["roles"])
    for username, roles in CONFIG["users"].items():
        assert roles, f"user {username} holds no role"
        for role in roles:
            assert role in declared, f"user {username} holds undeclared role {role!r}"


def test_apply_cms_config_reads_the_declared_path():
    relative = CONFIG_PATH.relative_to(LAB_DIR).as_posix()
    assert relative in APPLY_SCRIPT, f"apply_cms_config reads no {relative}"


def test_the_grant_call_is_guarded_by_a_capability_check():
    """CMS images predating the grant command must still complete the script,
    which `make local-env-init` runs on every fresh environment."""
    assert '"grant_workflow_permissions" in get_commands()' in APPLY_SCRIPT
