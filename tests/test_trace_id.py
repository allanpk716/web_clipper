"""Tests for trace_id envelope field and FlightContext integration."""

from __future__ import annotations

import json
import os
import signal
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from web_clip_helper.crash import (
    FlightContext,
    _exception_handler,
    _signal_handler,
    flight_context,
    write_crash_dump,
)
from web_clip_helper.output import (
    get_trace_id,
    jsonl_emit,
    jsonl_emit_error,
    jsonl_emit_help,
    jsonl_emit_progress,
    jsonl_emit_result,
    jsonl_emit_warning,
    set_trace_id,
)


# ── set_trace_id / get_trace_id ─────────────────────────────────────


class TestSetGetTraceId:
    """Verify module-level trace_id state management."""

    def setup_method(self) -> None:
        """Reset trace_id before each test."""
        import web_clip_helper.output as _out
        _out._current_trace_id = None

    def test_initially_none(self) -> None:
        """trace_id is None before set_trace_id is called."""
        assert get_trace_id() is None

    def test_set_and_get(self) -> None:
        """set_trace_id stores the value; get_trace_id returns it."""
        set_trace_id("abc123")
        assert get_trace_id() == "abc123"

    def test_overwrite(self) -> None:
        """Calling set_trace_id again replaces the previous value."""
        set_trace_id("first")
        set_trace_id("second")
        assert get_trace_id() == "second"

    def test_empty_string_is_valid(self) -> None:
        """Empty string is a valid trace_id (truthy check is for None only)."""
        set_trace_id("")
        assert get_trace_id() == ""


# ── trace_id in JSONL envelope ──────────────────────────────────────


class TestTraceIdInEnvelope:
    """Verify trace_id appears in JSONL output when set, absent when None."""

    def setup_method(self) -> None:
        import web_clip_helper.output as _out
        _out._current_trace_id = None

    def _parse_line(self, capsys) -> dict:
        lines = capsys.readouterr().out.strip().split("\n")
        return json.loads(lines[0])

    def test_absent_when_none(self, capsys) -> None:
        """trace_id field is omitted when not set."""
        jsonl_emit("progress", message="test")
        obj = self._parse_line(capsys)
        assert "trace_id" not in obj

    def test_present_when_set(self, capsys) -> None:
        """trace_id appears alongside version/tool/timestamp when set."""
        set_trace_id("my-trace-42")
        jsonl_emit("progress", message="test")
        obj = self._parse_line(capsys)
        assert obj["trace_id"] == "my-trace-42"

    def test_present_on_all_message_types(self, capsys) -> None:
        """trace_id appears on progress, result, error, warning, help."""
        set_trace_id("universal")
        jsonl_emit_progress(message="step")
        jsonl_emit_result(done=True)
        jsonl_emit_error(stage="x", detail="y")
        jsonl_emit_warning(message="careful")
        jsonl_emit_help(commands=[{"name": "clip", "help": "Clip"}])

        lines = capsys.readouterr().out.strip().split("\n")
        for line in lines:
            obj = json.loads(line)
            assert obj["trace_id"] == "universal", f"Missing trace_id in {obj['type']} message"

    def test_trace_id_position_in_envelope(self, capsys) -> None:
        """trace_id is a top-level field alongside version/tool/timestamp."""
        set_trace_id("env-test")
        jsonl_emit("result", data="payload")
        obj = self._parse_line(capsys)
        # All envelope fields present
        assert "version" in obj
        assert "tool" in obj
        assert "timestamp" in obj
        assert "trace_id" in obj
        assert obj["trace_id"] == "env-test"

    def test_trace_id_not_overridden_by_kwargs(self, capsys) -> None:
        """User-supplied trace_id kwarg is silently ignored (envelope wins)."""
        set_trace_id("canonical")
        # Pass trace_id as a kwarg — should be ignored because envelope
        # trace_id is injected after kwargs merge
        jsonl_emit("result", trace_id="evil")
        obj = self._parse_line(capsys)
        # The kwargs trace_id="evil" is in the payload first, but our
        # post-merge injection only adds trace_id when _current_trace_id
        # is not None — and since kwargs already has trace_id="evil",
        # the payload will have trace_id="evil" from kwargs. We need to
        # verify the actual behavior.
        # Actually: payload = {"type":..., **kwargs, "version":..., "tool":..., "timestamp":...}
        # kwargs contains trace_id="evil", but the code only sets payload["trace_id"]
        # if _current_trace_id is not None — which it IS, so it will overwrite
        # the kwargs value with "canonical".
        assert obj["trace_id"] == "canonical"

    def test_none_trace_id_does_not_shadow_kwargs(self, capsys) -> None:
        """When trace_id is None, user-supplied trace_id kwarg passes through."""
        # _current_trace_id is None (default)
        jsonl_emit("result", trace_id="user-supplied")
        obj = self._parse_line(capsys)
        # The code only injects trace_id when _current_trace_id is not None,
        # so the kwargs value passes through
        assert obj["trace_id"] == "user-supplied"

    def test_multiple_emits_share_trace_id(self, capsys) -> None:
        """All lines in one invocation carry the same trace_id."""
        set_trace_id("consistent")
        jsonl_emit_progress(message="step1")
        jsonl_emit_progress(message="step2")
        jsonl_emit_result(final=True)

        lines = capsys.readouterr().out.strip().split("\n")
        for line in lines:
            obj = json.loads(line)
            assert obj["trace_id"] == "consistent"

    def test_uuid_format_trace_id(self, capsys) -> None:
        """A UUID-style trace_id works correctly."""
        tid = uuid.uuid4().hex[:16]
        set_trace_id(tid)
        jsonl_emit("result", ok=True)
        obj = self._parse_line(capsys)
        assert obj["trace_id"] == tid
        assert len(tid) == 16


# ── CLI integration: trace_id set from AGENT_TRACE_ID env var ───────


class TestCliTraceId:
    """Verify trace_id is set during CLI startup from env var or auto-generated."""

    def setup_method(self) -> None:
        import web_clip_helper.output as _out
        _out._current_trace_id = None

    def test_env_var_propagated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AGENT_TRACE_ID env var is used as trace_id."""
        monkeypatch.setenv("AGENT_TRACE_ID", "from-env-123")
        from web_clip_helper.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        # Parse the JSONL output
        obj = json.loads(result.output.strip())
        assert obj["trace_id"] == "from-env-123"

    def test_auto_generated_when_no_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When AGENT_TRACE_ID is unset, a 16-char hex ID is auto-generated."""
        monkeypatch.delenv("AGENT_TRACE_ID", raising=False)
        from web_clip_helper.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        obj = json.loads(result.output.strip())
        # trace_id should be a 16-char hex string
        tid = obj["trace_id"]
        assert tid is not None
        assert len(tid) == 16
        # Verify it's valid hex
        int(tid, 16)

    def test_consistent_across_commands(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Same env var is used across the entire invocation."""
        monkeypatch.setenv("AGENT_TRACE_ID", "stable-id")
        from web_clip_helper.cli import app
        runner = CliRunner()
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        lines = [l for l in result.output.strip().split("\n") if l.strip()]
        for line in lines:
            obj = json.loads(line)
            assert obj.get("trace_id") == "stable-id"


# ── Crash dump integration ─────────────────────────────────────────


class TestCrashDumpTraceId:
    """Verify trace_id appears in crash dump data."""

    def setup_method(self) -> None:
        import web_clip_helper.output as _out
        _out._current_trace_id = None

    def test_signal_handler_includes_trace_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Signal handler crash dump includes trace_id when set."""
        set_trace_id("crash-trace-sig")

        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        import web_clip_helper.crash as crash_mod
        monkeypatch.setattr(crash_mod, "_in_handler", False)

        with pytest.raises(SystemExit):
            _signal_handler(signal.SIGINT, None)

        assert dump_file.exists()
        data = json.loads(dump_file.read_text(encoding="utf-8"))
        assert data["trace_id"] == "crash-trace-sig"
        assert data["AGENT_ABORTED"] is True

    def test_exception_handler_includes_trace_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exception handler crash dump includes trace_id when set."""
        set_trace_id("crash-trace-exc")

        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        import web_clip_helper.crash as crash_mod
        monkeypatch.setattr(crash_mod, "_in_handler", False)

        try:
            raise RuntimeError("test")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        with pytest.raises(SystemExit):
            _exception_handler(exc_type, exc_value, exc_tb)

        assert dump_file.exists()
        data = json.loads(dump_file.read_text(encoding="utf-8"))
        assert data["trace_id"] == "crash-trace-exc"
        assert data["exception_type"] == "RuntimeError"

    def test_signal_handler_no_trace_id_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Crash dump omits trace_id when not set (backward compat)."""
        # _current_trace_id is None (reset in setup_method)

        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        import web_clip_helper.crash as crash_mod
        monkeypatch.setattr(crash_mod, "_in_handler", False)

        with pytest.raises(SystemExit):
            _signal_handler(signal.SIGINT, None)

        data = json.loads(dump_file.read_text(encoding="utf-8"))
        assert "trace_id" not in data

    def test_exception_handler_no_trace_id_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Crash dump omits trace_id when not set (backward compat)."""
        # _current_trace_id is None (reset in setup_method)

        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        import web_clip_helper.crash as crash_mod
        monkeypatch.setattr(crash_mod, "_in_handler", False)

        try:
            raise ValueError("no-trace")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        with pytest.raises(SystemExit):
            _exception_handler(exc_type, exc_value, exc_tb)

        data = json.loads(dump_file.read_text(encoding="utf-8"))
        assert "trace_id" not in data
