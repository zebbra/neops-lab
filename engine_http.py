"""What the host scripts that call the workflow engine share (stdlib-only).

`run_workflow` and `wait_ready` both reach the engine's REST API from the host,
so the token they send, how they read a refusal, which failures they treat as
a broken round trip and which `--engine-url` they accept are decided here once.
Like `labscripts.py`, this is a module rather than a command and sits beside the
scripts, so a script run directly finds it on `sys.path[0]`.

`bootstrap/register.py` cannot import it: it ships in the bootstrap image.
"""

from __future__ import annotations

import argparse
import http.client
import os
from urllib import error, parse

DEFAULT_ENGINE_URL = "http://localhost:3030"

# What the engine answers a caller whose token is absent, expired, or short of
# the permission the route wants.
UNAUTHORIZED = (401, 403)

AUTH_HINT = "mint a token with ./lab_token and export it as NEOPS_ENGINE_TOKEN"

# What one engine round trip raises when it breaks. urllib wraps only the send
# step in URLError, so a reset while the answer is read arrives raw:
# OSError covers URLError, HTTPError, ConnectionResetError and timeouts,
# HTTPException covers IncompleteRead, ValueError covers a body that is not JSON.
REQUEST_ERRORS = (OSError, http.client.HTTPException, ValueError)


def auth_headers() -> dict:
    """`Authorization` for the engine, from NEOPS_ENGINE_TOKEN.

    Empty while the variable is unset, which an engine in `disabled` mode and
    every `@Public` route still answer.
    """
    token = os.environ.get("NEOPS_ENGINE_TOKEN", "").strip()
    return {"Authorization": "Bearer " + token} if token else {}


def error_body(exc: error.HTTPError) -> str:
    """The body of an engine error answer; empty when the connection broke
    while it was read, since the status alone still says what happened."""
    try:
        return exc.read().decode(errors="replace")
    except REQUEST_ERRORS:
        return ""


def refusal(exc: error.HTTPError) -> str:
    """Why the engine refused a 401/403: its status, its body, then the hint."""
    return f"({exc.code} {exc.reason}): {error_body(exc)[:300]} — {AUTH_HINT}"


def is_engine_url(value: str) -> bool:
    """Whether `value` is an http(s) base URL urllib can send to."""
    try:
        parts = parse.urlsplit(value)
        port = parts.port  # raises ValueError for a port that is not a number or out of range
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname) and port != 0


def engine_url(value: str) -> str:
    """argparse type for `--engine-url`.

    urllib notices some malformed URLs only while sending, where they read as a
    broken round trip: retried until the deadline, or reported as a start that
    may have gone through. Rejecting them here exits 2 before anything is sent.
    """
    if not is_engine_url(value):
        raise argparse.ArgumentTypeError(f"expected http(s)://host[:port], got {value!r}")
    return value


def add_engine_url_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--engine-url",
        type=engine_url,
        default=DEFAULT_ENGINE_URL,
        help=f"Workflow engine REST base URL (default: {DEFAULT_ENGINE_URL})",
    )
