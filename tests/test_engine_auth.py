"""The lab's three engine callers under `NEOPS_AUTHZ_MODE=enforce`.

`run_workflow`, `wait_ready` and `bootstrap/register.py` each hit a route the
engine gates, so each carries a bearer token and each stops on a 401 or 403
rather than treating it as a transient condition to retry.
"""

import io
import json
import pathlib
from urllib import error

import pytest

import labscripts
from tools import import_host_scripts

LAB_DIR = pathlib.Path(__file__).resolve().parents[1]


def _toml_list(text, header):
    """Return the body of one TOML array, from its `<key> = [` header."""
    start = text.index(header)
    return text[start : text.index("]", start)]


lab_token = labscripts.load("lab_token")
run_workflow = labscripts.load("run_workflow")
wait_ready = labscripts.load("wait_ready")

# register.py imports `requests` and `yaml`, which live in the lab_bootstrap
# image and are absent from this repo's dev environment.
REGISTER_SOURCE = (LAB_DIR / "bootstrap" / "register.py").read_text()

APPLY_SCRIPT = (LAB_DIR / "apply_cms_config").read_text()

FB_ID = "fb.base.neops.io/global_discover_network:0.1.0"

# The two shapes the engine refuses with. A 403 names the permission the route
# wanted, in `requiredPermission` and in the message; a 401 names why no identity
# could be established and carries no permission at all.
DENIED_BODY = (
    b'{"statusCode":403,"code":"PERMISSION_DENIED",'
    b'"message":"Missing permission \\"workflow-execution:read\\".",'
    b'"requiredPermission":"workflow-execution:read"}'
)
UNAUTHENTICATED_BODY = (
    b'{"statusCode":401,"code":"AUTHENTICATION_REQUIRED",'
    b'"message":"This endpoint requires a Neops access token in the Authorization header."}'
)


def _raising(status, reason, body=b""):
    """An engine answer that raises, carrying the response body it refused with."""

    def raise_http_error(*_args, **_kwargs):
        raise error.HTTPError("http://engine/x", status, reason, {}, io.BytesIO(body))

    return raise_http_error


def _capture_requests(monkeypatch, module, body):
    """Replace the module's `urlopen` with one recording every Request.

    Returns the list the recorded Requests land in; each answers `body` as JSON.
    """
    seen = []

    def urlopen(req, *_args, **_kwargs):
        seen.append(req)
        return io.BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(module.request, "urlopen", urlopen)
    return seen


# One gated call per host script, with the body the engine answers it.
GATED_CALLS = [
    pytest.param(
        wait_ready,
        [],
        lambda m: m.worker_states("http://engine", FB_ID),
        id="wait_ready",
    ),
    pytest.param(
        run_workflow,
        {"uuid": "exec-1"},
        lambda m: m.start_execution("http://engine", "wf.lab.neops.io/x:1.0.0", {}, []),
        id="run_workflow",
    ),
]


@pytest.mark.parametrize(("module", "body", "call"), GATED_CALLS)
def test_callers_send_the_token_as_a_bearer(module, body, call, monkeypatch):
    monkeypatch.setenv("NEOPS_ENGINE_TOKEN", "tok-123")
    seen = _capture_requests(monkeypatch, module, body)
    call(module)
    assert [req.get_header("Authorization") for req in seen] == ["Bearer tok-123"]


@pytest.mark.parametrize(("module", "body", "call"), GATED_CALLS)
def test_callers_send_no_header_without_a_token(module, body, call, monkeypatch):
    """An engine in `disabled` mode answers a tokenless caller, and a `Bearer`
    carrying an empty token is a credential the engine refuses."""
    monkeypatch.delenv("NEOPS_ENGINE_TOKEN", raising=False)
    seen = _capture_requests(monkeypatch, module, body)
    call(module)
    assert [req.get_header("Authorization") for req in seen] == [None]


@pytest.mark.parametrize("module", [run_workflow, wait_ready])
def test_callers_name_the_token_variable_when_refused(module):
    assert "NEOPS_ENGINE_TOKEN" in module.AUTH_HINT
    assert "./lab_token" in module.AUTH_HINT
    assert module.UNAUTHORIZED == (401, 403)


def test_register_prints_the_engines_refusal_before_the_hint():
    """Both branches of `_failure_detail` print the engine's body; the 401/403
    one adds the hint after it."""
    detail = REGISTER_SOURCE.split("def _failure_detail", 1)[1].split("\n\n\n", 1)[0]
    assert detail.count("resp.text[:300]") == 2
    assert "AUTH_HINT" in detail
    assert detail.index("resp.text[:300]") < detail.index("AUTH_HINT"), "the hint leads and the body follows it"


def test_register_reads_the_token_and_sends_it_as_a_bearer():
    assert 'os.environ.get("NEOPS_ENGINE_TOKEN"' in REGISTER_SOURCE
    assert '{"Authorization": "Bearer " + ENGINE_TOKEN}' in REGISTER_SOURCE
    # Both publish routes carry it: /workflow-definition/publish and the
    # legacy /workflow-definition fallback.
    assert REGISTER_SOURCE.count("headers=AUTH_HEADERS") == 2


def test_wait_ready_stops_on_an_unauthorized_answer(monkeypatch):
    """A 401 ends the wait at once; polling past it burns the whole budget.

    The engine's body separates a missing token from an invalid one, so it is
    printed before the hint.
    """
    monkeypatch.setattr(wait_ready.request, "urlopen", _raising(401, "Unauthorized", UNAUTHENTICATED_BODY))
    with pytest.raises(SystemExit) as excinfo:
        wait_ready.worker_states("http://engine", FB_ID)
    message = str(excinfo.value)
    assert UNAUTHENTICATED_BODY.decode() in message
    assert "NEOPS_ENGINE_TOKEN" in message
    assert message.index(UNAUTHENTICATED_BODY.decode()) < message.index("NEOPS_ENGINE_TOKEN"), (
        "the hint leads and the engine's reason follows it"
    )


def test_wait_ready_keeps_polling_past_a_not_yet_registered_block(monkeypatch):
    """A 404 means no worker has registered the block, which polling resolves."""
    monkeypatch.setattr(wait_ready.request, "urlopen", _raising(404, "Not Found"))
    assert wait_ready.worker_states("http://engine", FB_ID) is None


def test_run_workflow_stops_polling_on_an_unauthorized_answer(monkeypatch):
    """An expired token ends the poll loop, naming the engine's refusal, the
    execution that keeps running and where to follow it."""
    monkeypatch.setattr(run_workflow, "http_json", _raising(403, "Forbidden", DENIED_BODY))
    with pytest.raises(SystemExit) as excinfo:
        run_workflow.poll_until_terminal("http://engine", "uuid-1", timeout=5, interval=0.01)
    message = str(excinfo.value)
    assert DENIED_BODY.decode() in message
    assert "NEOPS_ENGINE_TOKEN" in message
    assert message.index(DENIED_BODY.decode()) < message.index("NEOPS_ENGINE_TOKEN"), (
        "the hint leads and the permission the route wanted follows it"
    )
    assert "uuid-1" in message
    assert run_workflow.MONITOR_URL in message


def test_run_workflow_reports_the_refusal_that_blocked_the_start(monkeypatch):
    """A start refused for a missing permission is only actionable with the
    engine's own message."""
    monkeypatch.setattr(run_workflow.request, "urlopen", _raising(403, "Forbidden", DENIED_BODY))
    with pytest.raises(SystemExit) as excinfo:
        run_workflow.start_execution("http://engine", "wf.lab.neops.io/x:1.0.0", {}, [])
    message = str(excinfo.value)
    assert DENIED_BODY.decode() in message
    assert "NEOPS_ENGINE_TOKEN" in message
    assert message.index(DENIED_BODY.decode()) < message.index("NEOPS_ENGINE_TOKEN"), (
        "the hint leads and the permission the route wanted follows it"
    )


def test_lab_token_login_payload_carries_the_credentials():
    payload = lab_token.login_payload("operator", "operator")
    assert payload["variables"] == {"username": "operator", "password": "operator"}
    assert "accessToken" in payload["query"]


def test_lab_token_reads_the_cms_url_apply_cms_config_reads(monkeypatch):
    """The two run back to back in one make recipe, so a lab moved off :8001
    has to reach the same CMS from both."""
    monkeypatch.setenv("CMS_URL", "http://cms.example:9000")
    assert lab_token.build_arg_parser().parse_args([]).cms_url == "http://cms.example:9000"
    monkeypatch.delenv("CMS_URL")
    fallback = lab_token.build_arg_parser().parse_args([]).cms_url
    assert f"CMS_URL=${{CMS_URL:-{fallback}}}" in APPLY_SCRIPT


def test_lab_token_names_the_rate_limit_setting():
    assert "NEOPS_LOCAL_LOGIN_RATE_LIMIT" in lab_token.RATE_LIMIT_HINT


def test_lab_token_is_in_every_list_that_sees_extension_less_scripts():
    """ruff and pyrefly discover files by extension, py39-check by name — so a
    script missing from any of the three lists goes unchecked."""
    pyproject = (LAB_DIR / "pyproject.toml").read_text()
    assert '"lab_token"' in _toml_list(pyproject, "extend-include = [")
    assert '"lab_token"' in _toml_list(pyproject, "project-includes = [")
    assert "lab_token" in import_host_scripts.SCRIPTS
