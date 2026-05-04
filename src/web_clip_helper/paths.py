"""Single source of truth for all filesystem paths.

Uses ``platformdirs`` for cross-platform XDG-compliant directory layout:

- **Config dir** (``get_config_dir``): settings, ``config.yaml``
- **Data dir** (``get_data_dir``): ``clips/``, ``clips.db``
- **State dir** (``get_state_dir``): ``locks/``, ``cache/``, ``crash_dumps/``
- **Reports dir** (``get_reports_dir``): user feedback reports

On first run, if the legacy ``~/.web-clip-helper/`` directory exists and no
``.migrated`` marker is found, all data is copied (not moved) to the new
locations.  Migration failure is non-fatal: a JSONL warning is emitted and
the old path is used as a fallback.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from platformdirs import user_config_dir, user_data_dir, user_state_dir

__all__ = [
    "APP_NAME",
    "LEGACY_DIR",
    "get_config_dir",
    "get_data_dir",
    "get_state_dir",
    "get_crash_dump_dir",
    "get_reports_dir",
    "get_migration_marker",
    "migrate_legacy_data",
]

logger = logging.getLogger(__name__)

APP_NAME = "web-clip-helper"
LEGACY_DIR = Path.home() / ".web-clip-helper"


# ── Directory getters ───────────────────────────────────────────────


def get_config_dir() -> Path:
    """Return the config directory (XDG-compliant).

    Linux: ``~/.config/web-clip-helper``
    macOS: ``~/.config/web-clip-helper``
    Windows: ``%APPDATA%\\web-clip-helper``
    """
    d = Path(user_config_dir(APP_NAME, appauthor=False))
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_data_dir() -> Path:
    """Return the data directory (XDG-compliant).

    Linux: ``~/.local/share/web-clip-helper``
    macOS: ``~/.local/share/web-clip-helper``
    Windows: ``%LOCALAPPDATA%\\web-clip-helper``
    """
    d = Path(user_data_dir(APP_NAME, appauthor=False))
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_state_dir() -> Path:
    """Return the state directory (XDG-compliant).

    Linux: ``~/.local/state/web-clip-helper``
    macOS: ``~/.local/state/web-clip-helper``
    Windows: ``%LOCALAPPDATA%\\web-clip-helper\\state``
    """
    d = Path(user_state_dir(APP_NAME, appauthor=False))
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_crash_dump_dir() -> Path:
    """Return the crash dump directory (inside state dir)."""
    d = get_state_dir() / "crash_dumps"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_reports_dir() -> Path:
    """Return the reports directory (inside data dir)."""
    d = get_data_dir() / "reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Migration ───────────────────────────────────────────────────────


def get_migration_marker() -> Path:
    """Return the path to the migration marker file.

    The marker lives in the legacy directory — its presence means
    migration has already been performed (or was not needed).
    """
    return LEGACY_DIR / ".migrated"


def migrate_legacy_data(
    *,
    jsonl_emit_progress: Optional[object] = None,
) -> bool:
    """Copy legacy ``~/.web-clip-helper/`` data to XDG directories.

    Returns ``True`` if migration succeeded (or was already done).
    Returns ``False`` on failure (callers should fall back to legacy paths).

    Migration is idempotent — the ``.migrated`` marker prevents re-runs.
    Data is *copied* (not moved) so nothing is lost on failure.

    Items migrated:
    - ``config.yaml`` → config dir
    - ``clips.db`` → data dir
    - ``clips/`` directory → data dir
    - ``reports/`` directory → data dir
    - ``crash_dumps/`` directory → state dir
    """
    marker = get_migration_marker()

    # Already migrated or no legacy data — nothing to do
    if marker.exists():
        return True
    if not LEGACY_DIR.is_dir():
        # No legacy data at all — write marker so we never check again
        try:
            LEGACY_DIR.mkdir(parents=True, exist_ok=True)
            marker.write_text("no-legacy", encoding="utf-8")
        except OSError:
            pass
        return True

    _emit(jsonl_emit_progress, "migration_start", "Starting data migration from ~/.web-clip-helper/")

    try:
        config_dir = get_config_dir()
        data_dir = get_data_dir()
        state_dir = get_state_dir()

        _copy_item(LEGACY_DIR / "config.yaml", config_dir / "config.yaml")
        _copy_item(LEGACY_DIR / "clips.db", data_dir / "clips.db")
        _copy_tree(LEGACY_DIR / "clips", data_dir / "clips")
        _copy_tree(LEGACY_DIR / "reports", data_dir / "reports")
        _copy_tree(LEGACY_DIR / "crash_dumps", state_dir / "crash_dumps")

        # Write marker on success
        marker.write_text("ok", encoding="utf-8")
        _emit(jsonl_emit_progress, "migration_done", "Data migration completed successfully")
        return True

    except Exception as exc:
        logger.warning("Migration failed, falling back to legacy paths: %s", exc)
        _emit(jsonl_emit_progress, "migration_failed", f"Migration failed: {exc}")
        return False


# ── Internal helpers ────────────────────────────────────────────────


def _copy_item(src: Path, dst: Path) -> None:
    """Copy a single file with ``shutil.copy2`` (preserves metadata)."""
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
    """Copy a directory tree.  Skips if source doesn't exist."""
    if src.is_dir():
        if dst.exists():
            # Merge: copy contents into existing directory
            for item in src.iterdir():
                target = dst / item.name
                if item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, target)
        else:
            shutil.copytree(src, dst)


def _emit(
    jsonl_emit_progress: Optional[object],
    stage: str,
    message: str,
) -> None:
    """Emit a JSONL progress line if the callable is available."""
    if jsonl_emit_progress is not None and callable(jsonl_emit_progress):
        try:
            jsonl_emit_progress(stage=stage, message=message)
        except Exception:
            pass
