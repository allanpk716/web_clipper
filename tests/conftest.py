"""Shared test fixtures and SDK test helpers.

Provides:
- ``_reset_trace_id`` (autouse): resets SDK App singleton between tests.
- ``run_sdk_cli(tmp_path)``: factory fixture to run CLI commands via SDK
  App.run() and capture JSONL envelope output.
- ``_parse_envelopes(output)`` / ``_unwrap_data()`` / ``_unwrap_error_message()``:
  helpers for parsing and validating SDK Envelope JSONL.
- ``_capture_jsonl()``: fixture for tests that call output functions directly
  (not through the CLI) — captures the Writer's internal buffer.
"""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from typing import Sequence

import pytest


# ── Auto-use: reset SDK App singleton ────────────────────────────


@pytest.fixture(autouse=True)
def _reset_trace_id():
    """Reset SDK Writer state between tests to prevent leakage.

    NEVER null _app. SDK command closures in cli.py capture the App
    at import time and write to its Writer. If we replace the App,
    those closures break silently.
    """
    import web_clip_helper.app as _app_module
    _app_module.get_app().writer.set_quiet(False)
    yield
    _app_module.get_app().writer.set_quiet(False)


# ── Temp config fixtures ─────────────────────────────────────────


@pytest.fixture()
def tmp_config_dir(tmp_path: Path) -> Path:
    """Return a temporary directory suitable for config files."""
    d = tmp_path / "cfg"
    d.mkdir()
    return d


@pytest.fixture()
def tmp_config_path(tmp_config_dir: Path) -> Path:
    """Return a path to a temporary config.json."""
    return tmp_config_dir / "config.json"


# ── SDK CLI runner fixture ───────────────────────────────────────


@pytest.fixture()
def run_sdk_cli(tmp_path: Path):
    """Factory fixture that runs CLI commands via SDK App.run().

    Returns a callable ``run_sdk_cli(args, env=None) -> (exit_code, envelopes)``.
    The SDK Writer output is captured from the real stdout stream that
    the SDK installs during ``App.run()``.

    Pattern adapted from ``test_sdk_cli_entry.py``.
    """

    def _run(
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[int, list[dict]]:
        import web_clip_helper.app as app_mod
        from web_clip_helper.cli import app as typer_app

        # Capture output by redirecting sys.stdout and the App's _real_stdout.
        # Do NOT reset _app — SDK command closures capture it at import time.
        app = app_mod.get_app()
        app.writer.set_quiet(False)

        capture_buf = io.StringIO()
        saved_stdout = sys.stdout
        sys.stdout = capture_buf
        # Patch the App's _real_stdout so SDK Writer writes to our buffer
        saved_real_stdout = app._real_stdout
        app._real_stdout = capture_buf

        old_exit = sys.exit
        exit_codes: list[int] = []
        sys.exit = lambda code=0: exit_codes.append(code)  # type: ignore[assignment]

        old_env = os.environ.copy()
        if env:
            for k, v in env.items():
                os.environ[k] = v

        try:
            code = app.run(typer_app, args=args)
            if exit_codes:
                code = exit_codes[-1]
            output = capture_buf.getvalue()
            envelopes = _parse_envelopes(output) if output.strip() else []
            return code, envelopes
        finally:
            app._real_stdout = saved_real_stdout
            sys.stdout = saved_stdout
            sys.exit = old_exit
            for k in list(os.environ.keys()):
                if k not in old_env:
                    del os.environ[k]
                elif os.environ[k] != old_env[k]:
                    os.environ[k] = old_env[k]
            for k in set(old_env.keys()) - set(os.environ.keys()):
                os.environ[k] = old_env[k]

    return _run


# ── Shared envelope parsing helpers ──────────────────────────────


def _parse_envelopes(output: str) -> list[dict]:
    """Parse JSONL output into a list of validated envelope dicts.

    Each line is parsed as JSON and checked for required envelope fields:
    ``version``, ``tool``, ``type``, ``timestamp``.  Raises ``AssertionError``
    if any line is missing a required field — this catches format regressions
    early.
    """
    lines = [ln for ln in output.strip().split("\n") if ln.strip()]
    envelopes: list[dict] = []
    for line in lines:
        obj = json.loads(line)
        for field in ("version", "tool", "type", "timestamp"):
            assert field in obj, f"Envelope missing required field {field!r}: {line}"
        envelopes.append(obj)
    return envelopes


def _unwrap_data(envelope: dict) -> dict:
    """Return the ``data`` payload from a result-type envelope."""
    assert envelope.get("type") == "result", (
        f"Expected result envelope, got type={envelope.get('type')!r}"
    )
    return envelope["data"]


def _unwrap_error_message(envelope: dict) -> tuple[str, str]:
    """Parse ``[stage] detail`` from an error envelope's message field.

    Returns ``(stage, detail)``.  If the message doesn't follow the
    ``[stage] detail`` pattern, returns ``("", message)``.
    """
    assert envelope.get("type") == "error", (
        f"Expected error envelope, got type={envelope.get('type')!r}"
    )
    msg = envelope.get("message", "")
    if msg.startswith("[") and "]" in msg:
        bracket_end = msg.index("]")
        stage = msg[1:bracket_end]
        detail = msg[bracket_end + 1:].strip()
        return stage, detail
    return "", msg


# ── Direct Writer capture fixture ────────────────────────────────


@pytest.fixture()
def _capture_jsonl():
    """Fixture for tests that call output functions directly (not via CLI).

    Returns a callable that, when invoked, returns the parsed envelopes
    from the SDK Writer's internal buffer.

    NOTE: Does NOT reset the App singleton. SDK command closures in cli.py
    capture the App at import time. We swap the Writer on the existing App
    instead.

    Usage::

        def test_something(_capture_jsonl):
            jsonl_emit("result", ok=True)
            envelopes = _capture_jsonl()
            assert envelopes[0]["type"] == "result"
    """
    from web_clip_helper.app import get_app

    app = get_app()
    buf = io.StringIO()
    from agentsdk.writer import Writer
    test_writer = Writer(buf, tool_name="web-clip-helper")
    old_writer = app.writer
    app.set_writer(test_writer)

    def _capture() -> list[dict]:
        text = buf.getvalue()
        if not text.strip():
            return []
        return _parse_envelopes(text)

    yield _capture

    # Restore original writer
    app.set_writer(old_writer)
