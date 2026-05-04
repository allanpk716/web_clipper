"""Structured error codes for JSONL error output.

Every ``jsonl_emit_error()`` call should include an ``error_code`` so that
Agent consumers can branch on a stable, machine-readable identifier rather
than parsing free-form ``detail`` strings.

Each code is a short ``UPPER_SNAKE_CASE`` string.  The mapping below also
provides a human-readable description for documentation / ``--help`` output.
"""

from __future__ import annotations

__all__ = ["ErrorCode", "EXIT_CODE_MAP", "exit_code_for"]

# ── Semantic exit codes ──────────────────────────────────────────
# 0  success
# 1  fatal / unknown error
# 2  input / config error
# 3  resource / dependency error
# 4  network / third-party error
# 5  concurrency error

EXIT_CODE_MAP: dict[str, int] = {
    # Exit 1 — fatal / unknown
    "INTERNAL_ERROR": 1,
    "FATAL_CRASH": 1,
    # Exit 2 — input / config
    "INPUT_INVALID": 2,
    "CONFIG_ERROR": 2,
    "INVALID_TYPE": 2,
    "NO_CUSTOM_PROMPT": 2,
    # Exit 3 — resource / dependency
    "NOT_FOUND": 3,
    "STORAGE_ERROR": 3,
    "INDEX_ERROR": 3,
    "REFRESH_ERROR": 3,
    # Exit 4 — network / third-party
    "NETWORK_ERROR": 4,
    "FETCH_ERROR": 4,
    "ROUTING_ERROR": 4,
    "URL_ROUTE_ERROR": 4,
    "TIMEOUT_ERROR": 4,
    # Exit 5 — concurrency
    "RESOURCE_LOCKED": 5,
}
"""Map an ``error_code`` string to a semantic process exit code (0-5)."""


def exit_code_for(error_code: str) -> int:
    """Return the semantic exit code for *error_code*.

    Falls back to ``1`` (fatal / unknown) for unknown codes so that new
    codes are always safe to use.
    """
    return EXIT_CODE_MAP.get(error_code, 1)


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

    # ── Fatal crash (signal or unhandled exception) ────────────────
    FATAL_CRASH = "FATAL_CRASH"

    # ── Refresh errors ────────────────────────────────────────────
    REFRESH_ERROR = "REFRESH_ERROR"

    # ── Timeout errors ────────────────────────────────────────────
    TIMEOUT_ERROR = "TIMEOUT_ERROR"

    # ── Concurrency / resource lock errors ────────────────────────
    RESOURCE_LOCKED = "RESOURCE_LOCKED"

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
        "FATAL_CRASH": "Unrecoverable crash (signal or unhandled exception)",
        "REFRESH_ERROR": "Dynamic clip refresh failed",
        "TIMEOUT_ERROR": "Clip operation exceeded the configured wall-clock timeout",
        "RESOURCE_LOCKED": "Concurrent access conflict — resource is locked by another process",
    }

    # ── Guidance mapping (troubleshooting hints) ──────────────────

    _GUIDANCE: dict[str, str] = {
        "INPUT_INVALID": "Check command arguments and required options. Run with --help for usage.",
        "NOT_FOUND": "Verify the resource ID or key exists. Use list/search commands to find valid identifiers.",
        "STORAGE_ERROR": "Check disk space and file permissions on the storage directory.",
        "INDEX_ERROR": "The SQLite database may be locked or corrupted. Try again or delete the .db file to rebuild.",
        "NETWORK_ERROR": "Check internet connectivity and DNS resolution. Retry after network recovery.",
        "ROUTING_ERROR": "The URL scheme/host is not supported. Ensure the URL matches a registered adapter.",
        "FETCH_ERROR": "The adapter could not retrieve content. The site may be down or blocking automated access.",
        "CONFIG_ERROR": "Validate the config file syntax (YAML). Check file path and permissions.",
        "INTERNAL_ERROR": "An unexpected error occurred. Check logs for details and consider filing a bug report.",
        "FATAL_CRASH": "The process crashed unexpectedly. Check crash dump files in the reports directory.",
        "REFRESH_ERROR": "Dynamic clip refresh failed. Verify the source URL is still accessible.",
        "TIMEOUT_ERROR": "The operation took too long. Increase --timeout or check network/server responsiveness.",
        "RESOURCE_LOCKED": "Another process holds a lock on the resource. Wait for it to finish or remove stale lock files.",
    }

    @classmethod
    def describe(cls, code: str) -> str:
        """Return a human-readable description for *code*."""
        return cls._DESCRIPTIONS.get(code, "Unknown error code")

    @classmethod
    def guidance(cls, code: str) -> str:
        """Return troubleshooting guidance for *code*."""
        return cls._GUIDANCE.get(code, "No specific guidance available.")

    @classmethod
    def all_codes(cls) -> dict[str, str]:
        """Return the full code → description mapping."""
        return dict(cls._DESCRIPTIONS)
