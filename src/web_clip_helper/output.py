"""JSONL output layer — every piece of output goes through here.

Each call emits exactly one JSON line to stdout.  The ``type`` field is
always present and must be one of: progress, result, error, warning, help.

Every JSONL line also carries three envelope fields for log correlation and
version-aware parsing:

- ``version`` — the tool's semantic version (e.g. ``"0.2.0"``).
- ``tool`` — the tool name (``"web-clip-helper"``).
- ``timestamp`` — ISO 8601 UTC timestamp with millisecond precision.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from web_clip_helper.io_guard import get_real_stdout

__all__ = [
    "jsonl_emit",
    "jsonl_emit_error",
    "jsonl_emit_progress",
    "jsonl_emit_result",
    "jsonl_emit_warning",
    "jsonl_emit_help",
    "jsonl_emit_schema",
    "jsonl_emit_dict",
    "set_quiet",
    "get_trace_id",
    "set_trace_id",
]

_VALID_TYPES = {"progress", "result", "error", "warning", "help", "schema", "dict", "diagnostics"}

_TOOL_NAME = "web-clip-helper"

# Module-level quiet-mode flag — when True, progress and warning messages
# are silently dropped so only result, error, and help lines are emitted.
_quiet_mode: bool = False

# Module-level trace ID — correlated across all JSONL lines in one CLI invocation.
# Set via set_trace_id(); read via get_trace_id().
_current_trace_id: str | None = None


def set_quiet(mode: bool) -> None:
    """Enable or disable quiet mode.

    When quiet mode is on, ``jsonl_emit`` silently drops ``progress`` and
    ``warning`` type messages.  ``result``, ``error``, and ``help`` types
    are always emitted regardless of this setting.
    """
    global _quiet_mode
    _quiet_mode = mode


def set_trace_id(tid: str) -> None:
    """Set the trace ID for the current CLI invocation.

    Every subsequent ``jsonl_emit`` call will include ``trace_id`` in the
    JSONL envelope.  This should be called once at CLI startup.
    """
    global _current_trace_id
    _current_trace_id = tid


def get_trace_id() -> str | None:
    """Return the current trace ID, or ``None`` if unset."""
    return _current_trace_id


def jsonl_emit(type: str, **kwargs: object) -> None:  # noqa: A002
    """Write one JSON line to stdout.

    Parameters
    ----------
    type:
        Message category — one of progress, result, error, warning, help.
    **kwargs:
        Arbitrary extra fields merged into the JSON object.

    Envelope Fields
    ---------------
    Every line includes ``version``, ``tool``, and ``timestamp`` fields.
    These are injected automatically and cannot be overridden by *kwargs*.
    """
    # Quiet mode: suppress progress and warning, keep result/error/help
    if _quiet_mode and type in ("progress", "warning"):
        return

    if type not in _VALID_TYPES:
        raise ValueError(f"Invalid JSONL type: {type!r}. Must be one of {_VALID_TYPES}")

    # Build envelope — import version lazily to avoid circular imports at
    # module-load time, and generate a millisecond-precision UTC timestamp.
    from web_clip_helper import __version__  # noqa: F811

    now = datetime.now(timezone.utc)
    # ISO 8601 with milliseconds: "2025-01-15T12:34:56.789Z"
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    # Merge user kwargs first, then overlay envelope fields so they always win.
    # This silently ignores any user-supplied version/tool/timestamp kwargs
    # rather than raising — callers that pass them (e.g. the version command)
    # simply get the authoritative envelope value.
    payload = {"type": type, **kwargs, "version": __version__, "tool": _TOOL_NAME, "timestamp": timestamp}

    # Inject trace_id into the envelope when set (non-None).
    # When trace_id is None the field is omitted for backward compatibility.
    if _current_trace_id is not None:
        payload["trace_id"] = _current_trace_id
    line = json.dumps(payload, ensure_ascii=False)
    _stdout = get_real_stdout()
    _stdout.write(line + "\n")
    _stdout.flush()


# ── Convenience wrappers ────────────────────────────────────────────


def jsonl_emit_progress(message: str, percent: int | None = None, **extra: object) -> None:
    """Emit a progress message, optionally with a percentage."""
    payload: dict[str, object] = {"message": message}
    if percent is not None:
        payload["percent"] = percent
    jsonl_emit("progress", **payload, **extra)


def jsonl_emit_result(**kwargs: object) -> None:
    """Emit a result message."""
    jsonl_emit("result", **kwargs)


def jsonl_emit_error(
    stage: str,
    detail: str,
    *,
    error_code: str | None = None,
    **extra: object,
) -> None:
    """Emit an error message with *stage* and *detail* for diagnosis.

    When *error_code* is provided it is included as ``error_code`` in the
    JSONL payload.  When omitted the field is absent entirely — this
    preserves backward compatibility with existing consumers.
    """
    if error_code is not None:
        jsonl_emit("error", stage=stage, detail=detail, error_code=error_code, **extra)
    else:
        jsonl_emit("error", stage=stage, detail=detail, **extra)


def jsonl_emit_warning(message: str, **extra: object) -> None:
    """Emit a non-fatal warning."""
    jsonl_emit("warning", message=message, **extra)


def jsonl_emit_schema(data: dict[str, object], **extra: object) -> None:
    """Emit a schema message (command parameter descriptions, etc.)."""
    jsonl_emit("schema", data=data, **extra)


def jsonl_emit_dict(data: dict[str, object], **extra: object) -> None:
    """Emit a dictionary message (error codes, diagnostics lookups, etc.)."""
    jsonl_emit("dict", data=data, **extra)


def jsonl_emit_help(commands: list[dict[str, str]], **extra: object) -> None:
    """Emit help text (used for ``--help`` output)."""
    jsonl_emit("help", commands=commands, **extra)
