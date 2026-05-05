"""JSONL output layer — delegates to SDK Writer for all envelope emission.

Every call emits exactly one JSON line via the agentsdk Writer obtained
from :func:`app.get_writer`.  The public function signatures are unchanged
so all existing callers continue to work.

The module still exports :data:`_TOOL_NAME` and :data:`__version__` as
module-level constants used by other parts of the codebase.
"""

from __future__ import annotations

from typing import Any

from web_clip_helper.app import get_writer

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

_TOOL_NAME = "web-clip-helper"


# ── Quiet / trace-id delegates ───────────────────────────────────


def set_quiet(mode: bool) -> None:
    """Enable or disable quiet mode (delegates to SDK Writer).

    When quiet mode is on, ``progress`` and ``warning`` messages are
    silently dropped by the SDK Writer.
    """
    get_writer().set_quiet(mode)


def set_trace_id(tid: str) -> None:
    """Set the trace ID for the current CLI invocation (delegates to SDK Writer)."""
    get_writer().set_trace_id(tid)


def get_trace_id() -> str | None:
    """Return the current trace ID, or ``None`` if unset.

    The SDK Writer stores an empty string when unset; we normalise
    to ``None`` for backward compatibility with callers that expect
    ``None`` rather than ``""``.
    """
    tid = get_writer().trace_id
    return tid if tid else None


# ── Core emit (backward-compatible) ──────────────────────────────

# "result", "help", "schema", "dict" all map to writer.success(data=kwargs).
# help/schema/dict are accepted directly by jsonl_emit() so callers can use
# either the generic entry-point or the convenience wrappers.
_RESULT_LIKE_TYPES = frozenset({"result", "help", "schema", "dict"})


def jsonl_emit(type: str, **kwargs: object) -> None:  # noqa: A002
    """Write one JSON line via the SDK Writer.

    Parameters
    ----------
    type:
        Message category — one of progress, result, error, warning,
        help, schema, dict.
    **kwargs:
        Arbitrary extra fields passed to the SDK Writer method.
    """
    writer = get_writer()

    if type == "progress":
        # writer.progress(percent: int, message: str)
        percent = kwargs.get("percent", 0)
        message = kwargs.get("message", "")
        writer.progress(int(percent), str(message))

    elif type in _RESULT_LIKE_TYPES:
        # writer.success(data) — pass all kwargs as data dict
        writer.success(data=kwargs)

    elif type == "error":
        # writer.error_with_code(code, message) or writer.error(message)
        error_code = kwargs.get("error_code")
        stage = kwargs.get("stage", "")
        detail = kwargs.get("detail", "")
        message = f"[{stage}] {detail}" if stage else str(detail)
        if error_code is not None:
            writer.error_with_code(str(error_code), message)
        else:
            writer.error(message)

    elif type == "warning":
        message = kwargs.get("message", "")
        writer.warning(str(message))

    else:
        raise ValueError(f"Invalid JSONL type: {type!r}")


# ── Convenience wrappers ─────────────────────────────────────────


def jsonl_emit_progress(message: str, percent: int | None = None, **extra: object) -> None:
    """Emit a progress message, optionally with a percentage."""
    payload: dict[str, Any] = {"message": message}
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

    When *error_code* is provided it is forwarded to the SDK Writer's
    ``error_with_code()`` method.  When omitted the generic ``error()``
    method is used.
    """
    if error_code is not None:
        jsonl_emit("error", stage=stage, detail=detail, error_code=error_code, **extra)
    else:
        jsonl_emit("error", stage=stage, detail=detail, **extra)


def jsonl_emit_warning(message: str, **extra: object) -> None:
    """Emit a non-fatal warning."""
    jsonl_emit("warning", message=message, **extra)


def jsonl_emit_schema(data: dict[str, object], **extra: object) -> None:
    """Emit a schema message (backward-compatible wrapper → type=result)."""
    jsonl_emit("result", data=data, **extra)


def jsonl_emit_dict(data: dict[str, object], **extra: object) -> None:
    """Emit a dictionary message (backward-compatible wrapper → type=result)."""
    jsonl_emit("result", data=data, **extra)


def jsonl_emit_help(commands: list[dict[str, str]], **extra: object) -> None:
    """Emit help text (backward-compatible wrapper → type=result)."""
    jsonl_emit("result", commands=commands, **extra)
