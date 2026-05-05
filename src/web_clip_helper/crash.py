"""Crash black box — signal capture and uncaught-exception handler.

On startup, call ``install_handlers()`` to register:

- A ``SIGTERM`` handler (non-Windows) and ``SIGINT`` handler that dump
  flight context + signal info to ``~/.web-clip-helper/crash_dumps/.last-crash.json``
  with an ``AGENT_ABORTED`` marker, emit a ``FATAL_CRASH`` JSONL line, and exit(1).
- A ``sys.excepthook`` override that dumps flight context + exception info
  to the same crash dump file, emits ``FATAL_CRASH``, and exits with code 1.

The ``FlightContext`` singleton tracks the current command name, args, and
phase so the crash dump captures what the app was doing when it died.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from web_clip_helper.app import get_crash_dumps_dir
from web_clip_helper.error_codes import exit_code_for
from web_clip_helper.io_guard import get_real_stderr, get_real_stdout

__all__ = [
    "FlightContext",
    "flight_context",
    "install_handlers",
    "write_crash_dump",
]

# ── Crash dump paths (resolved lazily via paths module) ─────────────

# Module-level defaults, overridable by tests via monkeypatch.
# Initialized lazily on first access to avoid import-time side effects.
_CRASH_DUMP_DIR: Path | None = None
_CRASH_DUMP_FILE: Path | None = None


def _resolve_crash_dump_dir() -> Path:
    """Resolve crash dump dir, using monkeypatched value if set."""
    global _CRASH_DUMP_DIR
    if _CRASH_DUMP_DIR is not None:
        return _CRASH_DUMP_DIR
    return get_crash_dumps_dir()


def _resolve_crash_dump_file() -> Path:
    """Resolve crash dump file, using monkeypatched value if set."""
    global _CRASH_DUMP_FILE
    if _CRASH_DUMP_FILE is not None:
        return _CRASH_DUMP_FILE
    return _resolve_crash_dump_dir() / ".last-crash.json"

# ── Re-entry guard ──────────────────────────────────────────────────

_in_handler: bool = False


# ── FlightContext ────────────────────────────────────────────────────


class FlightContext:
    """Thread-safe dict tracking the current command, args, and phase.

    CPython's GIL makes simple dict get/set atomic for our use case
    (single writer, single reader at crash time).  If the project moves
    to free-threaded Python, add a ``threading.Lock`` here.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def update(self, **kwargs: Any) -> None:
        """Set one or more fields (command, args, phase, etc.)."""
        self._data.update(kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Return a shallow copy for serialization."""
        return dict(self._data)

    def clear(self) -> None:
        """Reset all tracked fields."""
        self._data.clear()


# Module-level singleton
flight_context = FlightContext()


# ── Crash dump writer ───────────────────────────────────────────────


def write_crash_dump(data: dict[str, Any]) -> Path | None:
    """Write crash data to ``<state_dir>/crash_dumps/.last-crash.json``.

    Uses atomic write (write to ``.tmp``, then ``rename``) so partial
    writes don't corrupt the file.  Returns the path on success or
    ``None`` if the write fails (non-fatal — logs to stderr).
    """
    try:
        crash_dir = _resolve_crash_dump_dir()
        crash_file = _resolve_crash_dump_file()
        crash_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = crash_file.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        # Atomic rename (same filesystem)
        tmp_path.replace(crash_file)
        return crash_file
    except Exception as exc:
        # Non-fatal — log to real stderr and move on
        try:
            real_stderr = get_real_stderr()
            real_stderr.write(f"[crash] Failed to write crash dump: {exc}\n")
            real_stderr.flush()
        except Exception:
            pass
        return None


# ── Signal handler ──────────────────────────────────────────────────


def _signal_handler(signum: int, frame: Any) -> None:
    """Handle SIGTERM/SIGINT: dump crash data, emit FATAL_CRASH, exit(1)."""
    global _in_handler

    if _in_handler:
        # Prevent re-entry from nested signals
        return
    _in_handler = True

    # Resolve signal name
    signal_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)

    # Include trace_id if available for log correlation.
    _trace_id: str | None = None
    try:
        from web_clip_helper.output import get_trace_id
        _trace_id = get_trace_id()
    except Exception:
        pass

    crash_data: dict[str, Any] = {
        "AGENT_ABORTED": True,
        "source": "signal",
        "signal": signal_name,
        "signal_number": signum,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "flight_context": flight_context.to_dict(),
        "call_stack": traceback.format_stack(frame),
    }
    if _trace_id is not None:
        crash_data["trace_id"] = _trace_id

    write_crash_dump(crash_data)

    # Emit FATAL_CRASH JSONL — best-effort
    try:
        from web_clip_helper.output import jsonl_emit_error

        jsonl_emit_error(
            stage="crash",
            detail=f"Process received {signal_name}",
            error_code="FATAL_CRASH",
            signal=signal_name,
        )
    except Exception:
        pass

    sys.exit(1)


# ── Uncaught exception handler ──────────────────────────────────────


def _exception_handler(exc_type: type, exc_value: BaseException, exc_tb: Any) -> None:
    """Handle uncaught exceptions: dump crash data, emit FATAL_CRASH, exit(1)."""
    global _in_handler

    if _in_handler:
        # Prevent re-entry
        os._exit(1)
    _in_handler = True

    # Include trace_id if available for log correlation.
    _trace_id: str | None = None
    try:
        from web_clip_helper.output import get_trace_id
        _trace_id = get_trace_id()
    except Exception:
        pass

    crash_data: dict[str, Any] = {
        "AGENT_ABORTED": True,
        "source": "exception",
        "exception_type": exc_type.__name__,
        "exception_value": str(exc_value),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "flight_context": flight_context.to_dict(),
        "traceback": traceback.format_tb(exc_tb),
    }
    if _trace_id is not None:
        crash_data["trace_id"] = _trace_id

    write_crash_dump(crash_data)

    # Emit FATAL_CRASH JSONL — best-effort
    try:
        from web_clip_helper.output import jsonl_emit_error

        jsonl_emit_error(
            stage="crash",
            detail=f"Uncaught exception: {exc_type.__name__}: {exc_value}",
            error_code="FATAL_CRASH",
            exception_type=exc_type.__name__,
        )
    except Exception:
        pass

    sys.exit(exit_code_for("FATAL_CRASH"))


# ── Installer ───────────────────────────────────────────────────────


def install_handlers() -> None:
    """Install signal and exception handlers for crash black box.

    - On non-Windows: registers SIGTERM and SIGINT handlers.
    - On Windows: registers SIGINT only (SIGTERM is not available).
    - Overrides ``sys.excepthook`` for uncaught exceptions.
    """
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    sys.excepthook = _exception_handler
