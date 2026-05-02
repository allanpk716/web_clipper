"""Structured error codes for JSONL error output.

Every ``jsonl_emit_error()`` call should include an ``error_code`` so that
Agent consumers can branch on a stable, machine-readable identifier rather
than parsing free-form ``detail`` strings.

Each code is a short ``UPPER_SNAKE_CASE`` string.  The mapping below also
provides a human-readable description for documentation / ``--help`` output.
"""

from __future__ import annotations

__all__ = ["ErrorCode"]


class ErrorCode:
    """Registry of all error codes used by the web-clip-helper CLI.

    Usage::

        jsonl_emit_error(stage="clip", detail="...", error_code=ErrorCode.INPUT_INVALID)

    The codes are plain strings so they serialise directly in JSONL without
    custom encoders.
    """

    # ── Input validation ──────────────────────────────────────────
    INPUT_INVALID = "INPUT_INVALID"

    # ── Not found ─────────────────────────────────────────────────
    NOT_FOUND = "NOT_FOUND"

    # ── Storage (file-system) errors ──────────────────────────────
    STORAGE_ERROR = "STORAGE_ERROR"

    # ── Index (SQLite) errors ─────────────────────────────────────
    INDEX_ERROR = "INDEX_ERROR"

    # ── Network errors ────────────────────────────────────────────
    NETWORK_ERROR = "NETWORK_ERROR"

    # ── URL routing errors ────────────────────────────────────────
    ROUTING_ERROR = "ROUTING_ERROR"

    # ── Fetch (adapter) errors ────────────────────────────────────
    FETCH_ERROR = "FETCH_ERROR"

    # ── Configuration errors ──────────────────────────────────────
    CONFIG_ERROR = "CONFIG_ERROR"

    # ── Internal / unexpected errors ──────────────────────────────
    INTERNAL_ERROR = "INTERNAL_ERROR"

    # ── Refresh errors ────────────────────────────────────────────
    REFRESH_ERROR = "REFRESH_ERROR"

    # ── Description mapping ───────────────────────────────────────

    _DESCRIPTIONS: dict[str, str] = {
        "INPUT_INVALID": "Invalid or missing input argument",
        "NOT_FOUND": "Requested resource (clip, config key) does not exist",
        "STORAGE_ERROR": "File-system storage operation failed",
        "INDEX_ERROR": "SQLite index operation failed",
        "NETWORK_ERROR": "Network connectivity or DNS failure",
        "ROUTING_ERROR": "URL could not be routed to an adapter",
        "FETCH_ERROR": "Adapter failed to fetch content from the URL",
        "CONFIG_ERROR": "Configuration load/save/validation error",
        "INTERNAL_ERROR": "Unexpected internal error (possible bug)",
        "REFRESH_ERROR": "Dynamic clip refresh failed",
    }

    @classmethod
    def describe(cls, code: str) -> str:
        """Return a human-readable description for *code*."""
        return cls._DESCRIPTIONS.get(code, "Unknown error code")

    @classmethod
    def all_codes(cls) -> dict[str, str]:
        """Return the full code → description mapping."""
        return dict(cls._DESCRIPTIONS)
