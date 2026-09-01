"""The lab's declared roles, users and workflow grants.

`cms/permissions.json` is applied by `apply_cms_config`, which reaches the CMS
over `docker compose exec` — so nothing about it is checked until a lab is
running. These assertions cover the parts that are checkable offline: the file's
shape, its internal cross-references, the two things the script has to keep
doing with it, and the point in the make targets at which it has to be applied.
"""

import json
import pathlib

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = LAB_DIR / "cms" / "permissions.json"
CONFIG = json.loads(CONFIG_PATH.read_text())
APPLY_SCRIPT = (LAB_DIR / "apply_cms_config").read_text()
MAKEFILE = (LAB_DIR / "Makefile").read_text()

# The choices `manage.py grant_workflow_permissions --profile` accepts.
PROFILES = ("author", "operator", "admin")


def _recipes():
    """Every Makefile target's commands, keyed by target name.

    Comment lines are dropped: a recipe comment that quotes a command would
    otherwise satisfy an assertion about the order commands run in. Lines naming
    several targets at once (`a b c: export ...`) declare variables rather than
    recipes and carry no body, so they are skipped.
    """
    bodies = {}
    target = None
    for line in MAKEFILE.splitlines():
        if line.startswith("\t"):
            if target is not None and not line.lstrip("\t").startswith("#"):
                bodies[target].append(line)
            continue
        target = None
        head, separator, _ = line.partition(":")
        name = head.strip()
        if separator and name and " " not in name:
            target = name
            bodies.setdefault(target, [])
    return {name: "\n".join(lines) for name, lines in bodies.items()}


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


def test_grants_are_applied_before_a_target_mints_a_token():
    """An access token carries the permissions its account holds at login and
    keeps them for its whole lifetime, so every target that mints one applies
    this file first."""
    minting = {name: body for name, body in _recipes().items() if "$(MINT_ENGINE_TOKEN)" in body}
    assert minting, "no Makefile target mints an engine token"
    for name, body in minting.items():
        assert "./apply_cms_config" in body, f"{name} mints a token without applying {CONFIG_PATH.name}"
        assert body.index("./apply_cms_config") < body.index("$(MINT_ENGINE_TOKEN)"), (
            f"{name} mints a token before applying {CONFIG_PATH.name}"
        )
