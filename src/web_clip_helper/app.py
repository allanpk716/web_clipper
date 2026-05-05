"""SDK App singleton for web-clip-helper.

Initializes the agentsdk :class:`App` with all business error codes
registered and exposes convenience accessors used throughout the CLI.

The singleton is lazily initialized on first access via :func:`get_app`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from agentsdk import App, Sandbox

from web_clip_helper.config import Config
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

    # Register SDK providers: ConfigProvider, HealthChecks, CommandMeta.
    _register_providers(app)

    return app


# ── Provider registration ─────────────────────────────────────────


def _register_providers(app: App) -> None:
    """Register all SDK providers on the App singleton.

    - ConfigManager as ConfigProvider (enables SDK agent config list/set)
    - 4 health check functions (migrated from cli.py)
    - CommandMeta for all business commands (replaces agent_schema.py)
    """
    # (a) ConfigManager as ConfigProvider
    from agentsdk import ConfigManager

    config_path = str(get_config_dir() / "config.json")
    cm = ConfigManager(Config, config_path)
    app.register_config("default", cm)

    # (b) Health checks
    app.register_health_check("storage_dirs", _check_storage_dirs)
    app.register_health_check("sqlite", _check_sqlite)
    app.register_health_check("config", _check_config)
    app.register_health_check("llm_connectivity", _check_llm_connectivity)

    # (c) CommandMeta for all business commands
    from agentsdk.agent_commands import CommandMeta

    for cmd_path, meta in _build_command_meta().items():
        app.register_command_meta(cmd_path, CommandMeta(**meta))


# ── Health check functions (migrated from cli.py) ─────────────────


def _check_storage_dirs() -> dict[str, Any]:
    """Verify sandbox data/base directories are writable."""
    import time
    import uuid

    start = time.monotonic()
    try:
        dirs = {
            "config": get_config_dir(),
            "data": get_data_dir(),
            "state": get_state_dir(),
        }
        for label, d in dirs.items():
            probe = d / f".doctor_{uuid.uuid4().hex[:8]}"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        elapsed = (time.monotonic() - start) * 1000
        return {
            "check": "storage_dirs",
            "status": "pass",
            "detail": f"All {len(dirs)} storage directories writable",
            "duration_ms": round(elapsed, 2),
        }
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {
            "check": "storage_dirs",
            "status": "fail",
            "detail": f"Storage directory check failed: {exc}",
            "duration_ms": round(elapsed, 2),
        }


def _check_sqlite() -> dict[str, Any]:
    """Verify SQLite database is accessible and schema initialized."""
    import time

    from web_clip_helper.config import get_config
    from web_clip_helper.repository.index import ClipIndex

    start = time.monotonic()
    config = get_config()
    try:
        idx = ClipIndex(config.db_path)
        conn = idx._connect()
        conn.execute("SELECT 1").fetchone()
        idx.close()
        elapsed = (time.monotonic() - start) * 1000
        return {
            "check": "sqlite",
            "status": "pass",
            "detail": f"SQLite accessible at {config.db_path}",
            "duration_ms": round(elapsed, 2),
        }
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {
            "check": "sqlite",
            "status": "fail",
            "detail": f"SQLite check failed: {exc}",
            "duration_ms": round(elapsed, 2),
        }


def _check_config() -> dict[str, Any]:
    """Verify config loads and has required llm section."""
    import time

    from web_clip_helper.config import get_config

    start = time.monotonic()
    try:
        config = get_config()
        if not hasattr(config, "llm"):
            raise ValueError("Missing 'llm' section in config")
        if not config.llm.base_url or not config.llm.base_url.strip():
            raise ValueError("llm.base_url is empty")
        elapsed = (time.monotonic() - start) * 1000
        return {
            "check": "config",
            "status": "pass",
            "detail": f"Config valid (model={config.llm.model}, base_url={config.llm.base_url})",
            "duration_ms": round(elapsed, 2),
        }
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {
            "check": "config",
            "status": "fail",
            "detail": f"Config check failed: {exc}",
            "duration_ms": round(elapsed, 2),
        }


def _check_llm_connectivity() -> dict[str, Any]:
    """Verify LLM API is reachable (skip if no api_key configured)."""
    import time

    import httpx

    from web_clip_helper.config import get_config

    start = time.monotonic()
    try:
        config = get_config()
        if not config.llm.api_key or not config.llm.api_key.strip():
            elapsed = (time.monotonic() - start) * 1000
            return {
                "check": "llm_connectivity",
                "status": "skip",
                "detail": "No api_key configured — LLM connectivity check skipped",
                "duration_ms": round(elapsed, 2),
            }

        url = f"{config.llm.base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.llm.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.llm.model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }
        resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
        resp.raise_for_status()
        elapsed = (time.monotonic() - start) * 1000
        return {
            "check": "llm_connectivity",
            "status": "pass",
            "detail": f"LLM API reachable at {config.llm.base_url} (HTTP {resp.status_code})",
            "duration_ms": round(elapsed, 2),
        }
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        return {
            "check": "llm_connectivity",
            "status": "fail",
            "detail": f"LLM connectivity check failed: {exc}",
            "duration_ms": round(elapsed, 2),
        }


# ── Command metadata (replaces agent_schema.py) ───────────────────


def _build_command_meta() -> dict[str, dict[str, Any]]:
    """Return command metadata for all business commands.

    Each key is the CLI command path matching what SDK _walk_commands produces
    (e.g. ``"web-clip-helper clip"``, ``"web-clip-helper config list"``).
    Each value is a dict with ``description`` and ``is_idempotent`` — matching
    the schema previously in agent_schema.py.

    The SDK _schema_command merges CommandMeta by matching the ``path`` field
    from _walk_commands against the keys here, so they must include the tool
    name prefix.
    """
    tool = "web-clip-helper"
    return {
        f"{tool} clip": {
            "description": "Clip a URL or raw text into Markdown + storage",
            "is_idempotent": False,
        },
        f"{tool} list": {
            "description": "List clipped items with optional filters and pagination",
            "is_idempotent": True,
        },
        f"{tool} get": {
            "description": "Get a single clipped item by ID",
            "is_idempotent": True,
        },
        f"{tool} search": {
            "description": "Search clipped items by keyword in title and URL",
            "is_idempotent": True,
        },
        f"{tool} tags": {
            "description": "List all unique tags with usage counts",
            "is_idempotent": True,
        },
        f"{tool} delete": {
            "description": "Delete a clipped item by ID. Removes record from DB and folder from disk",
            "is_idempotent": True,
        },
        f"{tool} update": {
            "description": "Update clip fields (title, tags, category, dynamic flag, refresh interval)",
            "is_idempotent": True,
        },
        f"{tool} refresh": {
            "description": "Refresh dynamic clipped items that are due for re-clip",
            "is_idempotent": True,
        },
        f"{tool} version": {
            "description": "Print the current version",
            "is_idempotent": True,
        },
        f"{tool} config list": {
            "description": "List all configuration values (api_key is masked)",
            "is_idempotent": True,
        },
        f"{tool} config get": {
            "description": "Get a single configuration value by dot-path key",
            "is_idempotent": True,
        },
        f"{tool} config set": {
            "description": "Set a configuration value by dot-path key and save to file",
            "is_idempotent": True,
        },
        f"{tool} config prompt test": {
            "description": "Compare built-in and custom prompt results",
            "is_idempotent": True,
        },
        f"{tool} report submit": {
            "description": "Submit a structured feedback report",
            "is_idempotent": False,
        },
        f"{tool} report list": {
            "description": "List all submitted reports",
            "is_idempotent": True,
        },
        f"{tool} report show": {
            "description": "Show a specific report by ID",
            "is_idempotent": True,
        },
    }


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
