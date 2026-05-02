"""JSONL output layer — every piece of output goes through here.

Each call emits exactly one JSON line to stdout.  The ``type`` field is
always present and must be one of: progress, result, error, warning, help.
"""

from __future__ import annotations

import json
import sys

__all__ = [
    "jsonl_emit",
    "jsonl_emit_error",
    "jsonl_emit_progress",
    "jsonl_emit_result",
    "jsonl_emit_warning",
    "jsonl_emit_help",
    "set_quiet",
]

_VALID_TYPES = {"progress", "result", "error", "warning", "help"}

# Module-level quiet-mode flag — when True, progress and warning messages
# are silently dropped so only result, error, and help lines are emitted.
_quiet_mode: bool = False


def set_quiet(mode: bool) -> None:
    """Enable or disable quiet mode.

    When quiet mode is on, ``jsonl_emit`` silently drops ``progress`` and
    ``warning`` type messages.  ``result``, ``error``, and ``help`` types
    are always emitted regardless of this setting.
    """
    global _quiet_mode
    _quiet_mode = mode


def jsonl_emit(type: str, **kwargs: object) -> None:  # noqa: A002
    """Write one JSON line to stdout.

    Parameters
    ----------
    type:
        Message category — one of progress, result, error, warning, help.
    **kwargs:
        Arbitrary extra fields merged into the JSON object.
    """
    # Quiet mode: suppress progress and warning, keep result/error/help
    if _quiet_mode and type in ("progress", "warning"):
        return

    if type not in _VALID_TYPES:
        raise ValueError(f"Invalid JSONL type: {type!r}. Must be one of {_VALID_TYPES}")
    payload = {"type": type, **kwargs}
    line = json.dumps(payload, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


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


def jsonl_emit_help(commands: list[dict[str, str]], **extra: object) -> None:
    """Emit help text (used for ``--help`` output)."""
    jsonl_emit("help", commands=commands, **extra)
