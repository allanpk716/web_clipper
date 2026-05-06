"""XDG → SDK Sandbox migration.

Detects legacy XDG-compliant data directories (created by the old
``paths.py`` / ``config.py``), reads ``config.yaml`` and converts it to
JSON, then copies user data (clips.db, clips/, reports/, crash_dumps/)
into the SDK Sandbox layout.

Idempotent: after a successful migration a ``.xdg_migrated`` marker is
written to ``Sandbox.base_dir``.  Subsequent runs are skipped.  If a
previous run only partially succeeded the marker contains ``partial``
and the remaining items are retried.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

import yaml
from platformdirs import user_config_dir, user_data_dir, user_state_dir

__all__ = ["run_migration"]

logger = logging.getLogger(__name__)

_APP_NAME = "web-clip-helper"

_MARKER_OK = "ok"
_MARKER_PARTIAL = "partial"


# ── SDK Writer helper (fallback to logging) ────────────────────────


def _emit(message: str, *, percent: int | None = None) -> None:
    """Emit a progress message via the SDK Writer, or fall back to logging."""
    try:
        from web_clip_helper.app import get_writer

        writer = get_writer()
        writer.progress(message=message, percent=percent)
    except Exception:
        logger.info("migration: %s", message)


def _warn(message: str) -> None:
    """Emit a warning via the SDK Writer, or fall back to logging."""
    try:
        from web_clip_helper.app import get_writer

        writer = get_writer()
        writer.warning(message=message)
    except Exception:
        logger.warning("migration: %s", message)


# ── XDG directory resolution ───────────────────────────────────────


def _get_xdg_dirs() -> tuple[Path, Path, Path]:
    """Return (config_dir, data_dir, state_dir) using platformdirs."""
    config_dir = Path(user_config_dir(_APP_NAME, appauthor=False))
    data_dir = Path(user_data_dir(_APP_NAME, appauthor=False))
    state_dir = Path(user_state_dir(_APP_NAME, appauthor=False))
    return config_dir, data_dir, state_dir


# ── File copy helpers ──────────────────────────────────────────────


def _copy_item(src: Path, dst: Path) -> bool:
    """Copy a single file.  Returns True on success, False on failure."""
    if not src.exists():
        return True  # nothing to copy — not a failure
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except (PermissionError, OSError) as exc:
        _warn(f"Failed to copy {src} → {dst}: {exc}")
        return False


def _copy_tree(src: Path, dst: Path) -> bool:
    """Copy a directory tree.  Returns True on success, False on failure."""
    if not src.is_dir():
        return True  # nothing to copy — not a failure
    try:
        if dst.exists():
            for item in src.iterdir():
                target = dst / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)
        else:
            shutil.copytree(src, dst)
        return True
    except (PermissionError, OSError) as exc:
        _warn(f"Failed to copy tree {src} → {dst}: {exc}")
        return False


# ── Config migration ───────────────────────────────────────────────

# Default config values — mirrors the dataclass defaults in the old config.py
_DEFAULT_CONFIG: dict[str, Any] = {
    "storage_path": "",
    "db_path": "",
    "llm": {
        "api_key": "",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "refresh": {
        "default_interval_days": 7,
    },
    "prompts": {
        "title": "",
        "tags": "",
        "classify": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, returning a new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _migrate_config(xdg_config_dir: Path, sandbox_base_dir: Path) -> bool:
    """Read old config.yaml, convert to JSON, write to Sandbox.

    Returns True on success (or if there was nothing to migrate).
    """
    src_yaml = xdg_config_dir / "config.yaml"
    dst_json = sandbox_base_dir / "config.json"

    if not src_yaml.exists():
        return True

    # Don't overwrite an existing config.json that already has content
    if dst_json.exists() and dst_json.stat().st_size > 0:
        _emit("config.json already exists, skipping config migration")
        return True

    try:
        raw_text = src_yaml.read_text(encoding="utf-8")
        loaded = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        _warn(f"config.yaml is malformed, using defaults: {exc}")
        loaded = None
    except OSError as exc:
        _warn(f"Cannot read config.yaml: {exc}")
        loaded = None

    if not isinstance(loaded, dict):
        loaded = {}

    merged = _deep_merge(_DEFAULT_CONFIG, loaded)

    try:
        dst_json.parent.mkdir(parents=True, exist_ok=True)
        dst_json.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _emit("Migrated config.yaml → config.json")
        return True
    except OSError as exc:
        _warn(f"Cannot write config.json: {exc}")
        return False


# ── Data migration ─────────────────────────────────────────────────


def _migrate_data(
    xdg_data_dir: Path,
    xdg_state_dir: Path,
    sandbox: Any,
) -> dict[str, bool]:
    """Copy data files from XDG dirs to Sandbox dirs.

    Returns a dict mapping item names to success booleans.
    """
    results: dict[str, bool] = {}

    # clips.db → sandbox.data_dir
    results["clips.db"] = _copy_item(
        xdg_data_dir / "clips.db",
        sandbox.data_dir / "clips.db",
    )

    # clips/ → sandbox.data_dir/clips
    results["clips/"] = _copy_tree(
        xdg_data_dir / "clips",
        sandbox.data_dir / "clips",
    )

    # reports/ → sandbox.data_dir/reports
    results["reports/"] = _copy_tree(
        xdg_data_dir / "reports",
        sandbox.data_dir / "reports",
    )

    # crash_dumps/ → sandbox.crash_dumps_dir
    results["crash_dumps/"] = _copy_tree(
        xdg_state_dir / "crash_dumps",
        sandbox.crash_dumps_dir,
    )

    return results


# ── Marker management ──────────────────────────────────────────────


def _read_marker(sandbox_base_dir: Path) -> str | None:
    """Read the migration marker.  Returns content or None if absent."""
    marker = sandbox_base_dir / ".xdg_migrated"
    if not marker.exists():
        return None
    try:
        return marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _write_marker(sandbox_base_dir: Path, status: str) -> None:
    """Write the migration marker."""
    marker = sandbox_base_dir / ".xdg_migrated"
    try:
        sandbox_base_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(status, encoding="utf-8")
    except OSError as exc:
        _warn(f"Cannot write migration marker: {exc}")


# ── Public entry point ─────────────────────────────────────────────


def run_migration(sandbox: Any | None = None) -> bool:
    """Run the XDG → Sandbox migration.

    Parameters
    ----------
    sandbox:
        An :class:`agentsdk.Sandbox` instance.  If *None*, one is created
        with the default app name ``web-clip-helper``.

    Returns
    -------
    bool
        ``True`` if migration succeeded (or was already done).
    """
    if sandbox is None:
        from agentsdk import Sandbox

        sandbox = Sandbox(_APP_NAME)

    marker_status = _read_marker(Path(sandbox.base_dir))

    # Already fully migrated — skip
    if marker_status == _MARKER_OK:
        _emit("Migration already completed, skipping")
        return True

    # No legacy XDG data to migrate — just write the marker
    xdg_config_dir, xdg_data_dir, xdg_state_dir = _get_xdg_dirs()
    has_legacy = (
        (xdg_config_dir / "config.yaml").exists()
        or (xdg_data_dir / "clips.db").exists()
        or (xdg_data_dir / "clips").is_dir()
        or (xdg_data_dir / "reports").is_dir()
        or (xdg_state_dir / "crash_dumps").is_dir()
    )

    if not has_legacy:
        _write_marker(Path(sandbox.base_dir), _MARKER_OK)
        _emit("No legacy XDG data found, marking migration as done")
        return True

    _emit("Starting XDG → Sandbox migration")

    # Step 1: Migrate config
    config_ok = _migrate_config(xdg_config_dir, Path(sandbox.base_dir))

    # Step 2: Migrate data files
    data_results = _migrate_data(xdg_data_dir, xdg_state_dir, sandbox)

    all_ok = config_ok and all(data_results.values())

    if all_ok:
        _write_marker(Path(sandbox.base_dir), _MARKER_OK)
        _emit("Migration completed successfully", percent=100)
    else:
        # Report what failed
        failed = [k for k, v in data_results.items() if not v]
        if not config_ok:
            failed.insert(0, "config")
        _warn(f"Partial migration — failed items: {', '.join(failed)}")
        _write_marker(Path(sandbox.base_dir), _MARKER_PARTIAL)
        _emit(f"Migration completed with {len(failed)} item(s) skipped", percent=100)

    return all_ok
