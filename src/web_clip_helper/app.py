"""SDK App singleton for web-clip-helper.

Initializes the agentsdk :class:`App` with all business error codes
registered and exposes convenience accessors used throughout the CLI.

The singleton is lazily initialized on first access via :func:`get_app`.
"""

from __future__ import annotations

from typing import Optional

from agentsdk import App

from web_clip_helper.error_codes import ErrorCode, EXIT_CODE_MAP

__all__ = ["get_app", "get_writer"]

# ── Module-level singleton ───────────────────────────────────────
_app: Optional[App] = None

# SDK built-in codes — these are pre-registered by ErrorCodeRegistry
# and must NOT be passed to register_error_code().
_BUILTIN_CODES = frozenset({
    "FATAL_CRASH",
    "INTERNAL_ERROR",
    "INPUT_INVALID",
    "NOT_FOUND",
    "RESOURCE_LOCKED",
})


def _init_app() -> App:
    """Create and configure the agentsdk App singleton."""
    app = App("web-clip-helper", "0.2.0")

    # Register all custom (non-built-in) error codes from EXIT_CODE_MAP.
    for code, exit_code in EXIT_CODE_MAP.items():
        if code in _BUILTIN_CODES:
            continue
        description = ErrorCode.describe(code)
        app.register_error_code(code, exit_code, description)

    return app


def get_app() -> App:
    """Return the lazily-initialized SDK App singleton."""
    global _app
    if _app is None:
        _app = _init_app()
    return _app


def get_writer():
    """Return the SDK Writer from the singleton App.

    Convenience accessor so callers don't need to chain
    ``get_app().writer``.
    """
    return get_app().writer
