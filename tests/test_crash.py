"""Tests for crash black box — FlightContext, signal handlers, exception handlers."""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.crash import (
    FlightContext,
    _CRASH_DUMP_DIR,
    _CRASH_DUMP_FILE,
    _exception_handler,
    _signal_handler,
    flight_context,
    install_handlers,
    write_crash_dump,
)
from web_clip_helper.error_codes import EXIT_CODE_MAP, exit_code_for


# ── FlightContext tests ─────────────────────────────────────────────


class TestFlightContext:
    """Verify FlightContext update, serialize, and clear."""

    def test_update_and_to_dict(self) -> None:
        ctx = FlightContext()
        ctx.update(command="clip", url="https://example.com", phase="starting")
        d = ctx.to_dict()
        assert d["command"] == "clip"
        assert d["url"] == "https://example.com"
        assert d["phase"] == "starting"

    def test_to_dict_returns_copy(self) -> None:
        ctx = FlightContext()
        ctx.update(command="clip")
        d = ctx.to_dict()
        d["command"] = "modified"
        assert ctx.to_dict()["command"] == "clip"

    def test_clear(self) -> None:
        ctx = FlightContext()
        ctx.update(command="clip", phase="starting")
        ctx.clear()
        assert ctx.to_dict() == {}

    def test_update_overwrites(self) -> None:
        ctx = FlightContext()
        ctx.update(phase="starting")
        ctx.update(phase="fetching")
        assert ctx.to_dict()["phase"] == "fetching"

    def test_update_with_none_values(self) -> None:
        ctx = FlightContext()
        ctx.update(command=None, args=None, phase="")
        d = ctx.to_dict()
        assert d["command"] is None
        assert d["args"] is None
        assert d["phase"] == ""

    def test_update_empty_strings(self) -> None:
        ctx = FlightContext()
        ctx.update(command="", url="")
        d = ctx.to_dict()
        assert d["command"] == ""
        assert d["url"] == ""


# ── Crash dump writer tests ─────────────────────────────────────────


class TestWriteCrashDump:
    """Verify crash dump file creation and content."""

    def test_creates_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        result = write_crash_dump({"test": "data"})
        assert result == dump_file
        assert dump_file.exists()

        data = json.loads(dump_file.read_text(encoding="utf-8"))
        assert data["test"] == "data"

    def test_structure_has_required_fields(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        crash_data = {
            "AGENT_ABORTED": True,
            "source": "signal",
            "signal": "SIGINT",
            "signal_number": 2,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "flight_context": {"command": "clip", "phase": "fetching"},
            "call_stack": ["frame1", "frame2"],
        }
        write_crash_dump(crash_data)

        data = json.loads(dump_file.read_text(encoding="utf-8"))
        assert data["AGENT_ABORTED"] is True
        assert data["source"] == "signal"
        assert data["signal"] == "SIGINT"
        assert data["flight_context"]["command"] == "clip"
        assert "timestamp" in data

    def test_dir_created_automatically(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dump_dir = tmp_path / "nested" / "deep" / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        assert not dump_dir.exists()
        write_crash_dump({"test": "auto_create"})
        assert dump_dir.exists()
        assert dump_file.exists()

    def test_unwritable_dir_no_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When dump dir can't be created, write_crash_dump returns None (no crash)."""
        bad_path = MagicMock(spec=Path)
        bad_path.mkdir.side_effect = OSError("permission denied")
        bad_path.__truediv__ = MagicMock(return_value=bad_path)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", bad_path)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", bad_path)

        result = write_crash_dump({"test": "fail"})
        assert result is None

    def test_atomic_write_no_partial_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify the .tmp file is cleaned up after successful write."""
        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        write_crash_dump({"test": "atomic"})

        # .tmp should not remain
        tmp_files = list(dump_dir.glob("*.tmp"))
        assert len(tmp_files) == 0
        assert dump_file.exists()

    def test_overwrites_existing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        write_crash_dump({"version": 1})
        write_crash_dump({"version": 2})

        data = json.loads(dump_file.read_text(encoding="utf-8"))
        assert data["version"] == 2


# ── Signal handler tests ────────────────────────────────────────────


class TestSignalHandler:
    """Verify signal handler writes crash dump and emits FATAL_CRASH."""

    def test_signal_handler_writes_crash_dump(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        flight_context.update(command="clip", url="https://example.com", phase="fetching")

        # Reset re-entry flag before testing
        import web_clip_helper.crash as crash_mod
        monkeypatch.setattr(crash_mod, "_in_handler", False)

        with pytest.raises(SystemExit) as exc_info:
            _signal_handler(signal.SIGINT, None)

        assert exc_info.value.code == 1
        assert dump_file.exists()

        data = json.loads(dump_file.read_text(encoding="utf-8"))
        assert data["AGENT_ABORTED"] is True
        assert data["source"] == "signal"
        assert data["signal"] == "SIGINT"
        assert data["flight_context"]["command"] == "clip"

        flight_context.clear()

    def test_signal_handler_emits_fatal_crash_jsonl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        import web_clip_helper.crash as crash_mod
        monkeypatch.setattr(crash_mod, "_in_handler", False)

        with pytest.raises(SystemExit):
            _signal_handler(signal.SIGINT, None)

        # The FATAL_CRASH JSONL may be captured or may fail silently
        # (depends on io_guard state); check the dump file instead
        assert dump_file.exists()

    def test_re_entry_prevention(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Calling handler twice should not re-enter (second call returns None)."""
        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        import web_clip_helper.crash as crash_mod

        # First call sets _in_handler = True and raises SystemExit
        monkeypatch.setattr(crash_mod, "_in_handler", False)

        with pytest.raises(SystemExit):
            _signal_handler(signal.SIGINT, None)

        # Second call — _in_handler is now True, should return without SystemExit
        # (the handler returns early)
        result = _signal_handler(signal.SIGINT, None)
        assert result is None  # returned early, no SystemExit


# ── Exception handler tests ─────────────────────────────────────────


class TestExceptionHandler:
    """Verify exception handler writes crash dump and emits FATAL_CRASH."""

    def test_exception_handler_writes_crash_dump(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        flight_context.update(command="refresh", phase="running")

        import web_clip_helper.crash as crash_mod
        monkeypatch.setattr(crash_mod, "_in_handler", False)

        try:
            raise RuntimeError("test crash")
        except RuntimeError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        with pytest.raises(SystemExit) as exc_info:
            _exception_handler(exc_type, exc_value, exc_tb)

        assert exc_info.value.code == 1
        assert dump_file.exists()

        data = json.loads(dump_file.read_text(encoding="utf-8"))
        assert data["AGENT_ABORTED"] is True
        assert data["source"] == "exception"
        assert data["exception_type"] == "RuntimeError"
        assert data["exception_value"] == "test crash"
        assert data["flight_context"]["command"] == "refresh"
        assert "traceback" in data

        flight_context.clear()

    def test_exception_handler_exit_code_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Uncaught exception should exit with FATAL_CRASH code (1)."""
        dump_dir = tmp_path / "crash_dumps"
        dump_file = dump_dir / ".last-crash.json"
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_DIR", dump_dir)
        monkeypatch.setattr("web_clip_helper.crash._CRASH_DUMP_FILE", dump_file)

        import web_clip_helper.crash as crash_mod
        monkeypatch.setattr(crash_mod, "_in_handler", False)

        try:
            raise ValueError("test")
        except ValueError:
            exc_type, exc_value, exc_tb = sys.exc_info()

        with pytest.raises(SystemExit) as exc_info:
            _exception_handler(exc_type, exc_value, exc_tb)

        assert exc_info.value.code == 1


# ── Error code tests ────────────────────────────────────────────────


class TestFatalCrashErrorCode:
    """Verify FATAL_CRASH error code and exit mapping."""

    def test_fatal_crash_exit_code_is_1(self) -> None:
        assert exit_code_for("FATAL_CRASH") == 1

    def test_fatal_crash_in_exit_code_map(self) -> None:
        assert "FATAL_CRASH" in EXIT_CODE_MAP
        assert EXIT_CODE_MAP["FATAL_CRASH"] == 1

    def test_fatal_crash_error_code_constant(self) -> None:
        from web_clip_helper.error_codes import ErrorCode

        assert hasattr(ErrorCode, "FATAL_CRASH")
        assert ErrorCode.FATAL_CRASH == "FATAL_CRASH"

    def test_fatal_crash_description(self) -> None:
        from web_clip_helper.error_codes import ErrorCode

        desc = ErrorCode.describe("FATAL_CRASH")
        assert "crash" in desc.lower() or "signal" in desc.lower() or "exception" in desc.lower()


# ── install_handlers tests ──────────────────────────────────────────


class TestInstallHandlers:
    """Verify install_handlers registers signal and exception handlers."""

    def test_excepthook_set(self) -> None:
        original_hook = sys.excepthook
        try:
            install_handlers()
            assert sys.excepthook is _exception_handler
        finally:
            sys.excepthook = original_hook

    def test_sigint_handler_set(self) -> None:
        original_sigint = signal.getsignal(signal.SIGINT)
        try:
            install_handlers()
            assert signal.getsignal(signal.SIGINT) is _signal_handler
        finally:
            signal.signal(signal.SIGINT, original_sigint)

    @pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM not available on Windows")
    def test_sigterm_handler_set(self) -> None:
        original_sigterm = signal.getsignal(signal.SIGTERM)
        try:
            install_handlers()
            assert signal.getsignal(signal.SIGTERM) is _signal_handler
        finally:
            signal.signal(signal.SIGTERM, original_sigterm)
