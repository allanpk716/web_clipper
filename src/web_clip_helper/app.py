"""SDK App singleton for web-clip-helper.

Initializes the agentsdk :class:`App` with all business error codes
registered and exposes convenience accessors used throughout the CLI.

The singleton is lazily initialized on first access via :func:`get_app`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from agentsdk import App, Sandbox

from web_clip_helper.error_codes import ErrorCode, EXIT_CODE_MAP

__all__ = ["get_app", "get_sandbox", "get_writer"]

# ── Module-level singletons ───────────────────────────────────────
_app: Optional[App] = None
_sandbox: Optional[Sandbox] = None

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


def get_sandbox() -> Sandbox:
    """Return the lazily-initialized SDK Sandbox singleton.

    The sandbox provides a single-root directory layout under
    ``~/.web-clip-helper/`` with sub-directories for data, cache,
    crash_dumps, and locks.  ``ensure()`` is called on first access
    to create all directories.
    """
    global _sandbox
    if _sandbox is None:
        _sandbox = Sandbox("web-clip-helper")
        _sandbox.ensure()
    return _sandbox


def get_writer():
    """Return the SDK Writer from the singleton App.

    Convenience accessor so callers don't need to chain
    ``get_app().writer``.
    """
    return get_app().writer


# ── Path accessors (replacing paths.py) ────────────────────────────
# Thin wrappers around sandbox properties so callers and tests have
# a stable, patchable target without reaching into the sandbox directly.


def get_reports_dir() -> Path:
    """Return the reports directory (``<sandbox>/data/reports``).

    Creates the directory on first access.
    """
    d = Path(get_sandbox().data_dir) / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_crash_dumps_dir() -> Path:
    """Return the crash dumps directory (``<sandbox>/crash_dumps``)."""
    return Path(get_sandbox().crash_dumps_dir)


def get_state_dir() -> Path:
    """Return the state/base directory (``<sandbox>/``).

    In the old XDG layout this was a separate state directory.
    In the SDK sandbox layout, base_dir serves this role.
    """
    return Path(get_sandbox().base_dir)


def get_data_dir() -> Path:
    """Return the data directory (``<sandbox>/data``)."""
    return Path(get_sandbox().data_dir)


def get_config_dir() -> Path:
    """Return the config directory (``<sandbox>/data``).

    Config (config.json) lives in the data directory in the
    SDK sandbox layout.
    """
    return Path(get_sandbox().data_dir)
