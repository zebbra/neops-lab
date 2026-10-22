"""The lab's engine callers when a connection breaks mid-request.

urllib wraps only the send step in `URLError`; a reset while the status line
or the body is read reaches the caller raw, as `ConnectionResetError` or
`http.client.IncompleteRead`. An engine restart produces exactly that, and the
execution it was asked about keeps running.
"""

import argparse
import http.client
import io
import json

import pytest

import engine_http
import labscripts

run_workflow = labscripts.load("run_workflow")
wait_ready = labscripts.load("wait_ready")

FB_ID = "fb.base.neops.io/global_discover_network:0.1.0"
COMPLETED = {"status": "completed_ack"}

# Each failure a round trip can raise past urllib's URLError wrapper.
BROKEN_ROUND_TRIPS = [
    pytest.param(ConnectionResetError(104, "Connection reset by peer"), id="reset"),
    pytest.param(http.client.RemoteDisconnected("Remote end closed connection without response"), id="disconnected"),
    pytest.param(http.client.IncompleteRead(b'{"sta', 40), id="incomplete-read"),
    pytest.param(TimeoutError("timed out"), id="read-timeout"),
    pytest.param(json.JSONDecodeError("Expecting value", "<html>", 0), id="not-json"),
]


class _TruncatedBody(io.BytesIO):
    """A response whose body is cut short after the status line arrived."""

    def read(self, *_args):
        raise http.client.IncompleteRead(b'{"sta', 40)


def _answers(*outcomes):
    """A stand-in for one round trip that raises or returns each outcome in turn."""
    remaining = list(outcomes)

    def answer(*_args, **_kwargs):
        outcome = remaining.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return answer


@pytest.mark.parametrize("failure", BROKEN_ROUND_TRIPS)
def test_poll_retries_past_a_broken_round_trip(failure, monkeypatch, capsys):
    """The execution outlives the connection, so polling must too."""
    monkeypatch.setattr(run_workflow, "http_json", _answers(failure, COMPLETED))
    assert run_workflow.poll_until_terminal("http://engine", "uuid-1", timeout=5, interval=0.01) == 0
    assert "poll failed, retrying" in capsys.readouterr().err


def test_poll_retries_past_a_body_cut_short(monkeypatch):
    """IncompleteRead is an HTTPException, not an OSError, and it is raised by
    `json.load` inside `http_json`, after `urlopen` already returned."""
    bodies = _answers(_TruncatedBody(), io.BytesIO(json.dumps(COMPLETED).encode()))
    monkeypatch.setattr(run_workflow.request, "urlopen", bodies)
    assert run_workflow.poll_until_terminal("http://engine", "uuid-1", timeout=5, interval=0.01) == 0


def test_poll_gives_up_at_the_deadline_while_the_engine_keeps_resetting(monkeypatch):
    def reset(*_args, **_kwargs):
        raise ConnectionResetError(104, "Connection reset by peer")

    monkeypatch.setattr(run_workflow, "http_json", reset)
    assert run_workflow.poll_until_terminal("http://engine", "uuid-1", timeout=0.05, interval=0.01) == 2


def test_poll_bounds_each_request_by_the_remaining_budget(monkeypatch):
    """A half-open connection must not hold a poll past `--timeout`."""
    timeouts = []

    def http_json(*_args, timeout=None, **_kwargs):
        timeouts.append(timeout)
        return COMPLETED

    monkeypatch.setattr(run_workflow, "http_json", http_json)
    run_workflow.poll_until_terminal("http://engine", "uuid-1", timeout=1, interval=0.01)
    assert len(timeouts) == 1
    assert timeouts[0] is not None
    assert 0 < timeouts[0] <= 1


def test_http_json_never_waits_without_a_timeout(monkeypatch):
    seen = []

    def urlopen(_req, *_args, timeout=None, **_kwargs):
        seen.append(timeout)
        return io.BytesIO(b"{}")

    monkeypatch.setattr(run_workflow.request, "urlopen", urlopen)
    run_workflow.http_json(run_workflow.build_request("http://engine/x"))
    assert seen == [run_workflow.REQUEST_TIMEOUT]


@pytest.mark.parametrize("failure", BROKEN_ROUND_TRIPS)
def test_start_reports_that_the_execution_may_exist(failure, monkeypatch, capsys):
    """The POST reached the engine, so the execution may have started; retrying
    it could start a second one. Exit 2: no terminal state was seen."""
    calls = []

    def urlopen(*_args, **_kwargs):
        calls.append(1)
        raise failure

    monkeypatch.setattr(run_workflow.request, "urlopen", urlopen)
    with pytest.raises(SystemExit) as excinfo:
        run_workflow.start_execution("http://engine", "wf.lab.neops.io/x:1.0.0", {}, [])
    assert excinfo.value.code == 2
    assert calls == [1], "a start request is not idempotent and must not be retried"
    message = capsys.readouterr().err
    assert "may have started" in message
    assert run_workflow.MONITOR_URL in message


def test_start_exits_2_when_the_engine_is_unreachable(monkeypatch, capsys):
    refused = run_workflow.error.URLError(ConnectionRefusedError(111, "Connection refused"))
    monkeypatch.setattr(run_workflow.request, "urlopen", _answers(refused))
    with pytest.raises(SystemExit) as excinfo:
        run_workflow.start_execution("http://engine", "wf.lab.neops.io/x:1.0.0", {}, [])
    assert excinfo.value.code == 2
    assert "failed to reach engine at http://engine" in capsys.readouterr().err


def test_start_exits_2_when_the_engine_refuses_the_workflow(monkeypatch, capsys):
    rejected = run_workflow.error.HTTPError("http://engine/x", 400, "Bad Request", {}, io.BytesIO(b"unknown workflow"))
    monkeypatch.setattr(run_workflow.request, "urlopen", _answers(rejected))
    with pytest.raises(SystemExit) as excinfo:
        run_workflow.start_execution("http://engine", "wf.lab.neops.io/x:1.0.0", {}, [])
    assert excinfo.value.code == 2
    assert "unknown workflow" in capsys.readouterr().err


def test_start_builds_the_request_before_anything_can_be_sent(monkeypatch):
    """A URL urllib cannot parse raises before the send, so it never reaches
    the branch that says the execution may have started."""
    calls = []
    monkeypatch.setattr(run_workflow.request, "urlopen", lambda *_a, **_k: calls.append(1))
    with pytest.raises(ValueError, match="unknown url type"):
        run_workflow.start_execution("engine.neops.local", "wf.lab.neops.io/x:1.0.0", {}, [])
    assert calls == []


def test_start_reports_a_bad_port_as_a_bad_url(capsys):
    """urllib raises InvalidURL from inside `urlopen`, before it connects."""
    with pytest.raises(SystemExit) as excinfo:
        run_workflow.start_execution("http://engine:abc", "wf.lab.neops.io/x:1.0.0", {}, [])
    assert excinfo.value.code == 2
    message = capsys.readouterr().err
    assert "invalid engine URL" in message
    assert "may have started" not in message


@pytest.mark.parametrize(
    "url",
    ["engine.neops.local", "localhost:3030", "ftp://engine", "http://engine:abc", "http://engine:99999", "http://"],
)
def test_engine_url_rejects_what_urllib_cannot_send_to(url):
    with pytest.raises(argparse.ArgumentTypeError):
        engine_http.engine_url(url)


@pytest.mark.parametrize("url", ["http://localhost:3030", "http://engine.neops.local", "https://engine:443/api"])
def test_engine_url_accepts_an_http_base_url(url):
    assert engine_http.engine_url(url) == url


def test_run_workflow_rejects_a_malformed_engine_url_before_starting(capsys):
    with pytest.raises(SystemExit) as excinfo:
        run_workflow.build_arg_parser().parse_args(["wf.lab.neops.io/x:1.0.0", "--engine-url", "engine.neops.local"])
    assert excinfo.value.code == 2
    assert "--engine-url" in capsys.readouterr().err


def test_wait_ready_rejects_a_malformed_engine_url_before_waiting(monkeypatch):
    """Otherwise every poll fails the same way and the wait burns its budget."""
    monkeypatch.setattr(wait_ready.sys, "argv", ["wait_ready", FB_ID, "--engine-url", "http://engine:abc"])
    with pytest.raises(SystemExit) as excinfo:
        wait_ready.main()
    assert excinfo.value.code == 2


@pytest.mark.parametrize("failure", BROKEN_ROUND_TRIPS)
def test_wait_ready_keeps_polling_past_a_broken_round_trip(failure, monkeypatch):
    """None keeps the wait polling until its own deadline."""
    monkeypatch.setattr(wait_ready.request, "urlopen", _answers(failure))
    assert wait_ready.worker_states("http://engine", FB_ID) is None


def test_wait_ready_keeps_polling_past_a_body_cut_short(monkeypatch):
    monkeypatch.setattr(wait_ready.request, "urlopen", _answers(_TruncatedBody()))
    assert wait_ready.worker_states("http://engine", FB_ID) is None
