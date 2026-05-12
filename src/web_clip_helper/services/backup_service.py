"""Backup service — create zip archives from XDG multi-directory layout.

Collects files from two XDG directories:
- **Config dir**: ``config.yaml``
- **Data dir**: ``clips.db``, ``clips/``

Produces a single zip file with forward-slash entry paths, atomic write
via ``.tmp`` + ``os.replace()``, and collision-safe filename generation.

Also provides helpers for listing backups, rotating old backups via
grandfather-father-son policy, and reading/writing backup configuration.
"""

from __future__ import annotations

import logging
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import agentsdk.backup

from .. import paths

__all__ = [
    "BACKUP_PREFIX",
    "cleanup_backups",
    "create_backup",
    "get_backup_config_path",
    "get_default_output_dir",
    "list_backups",
    "set_backup_config",
    "show_backup_config",
]

_ALLOWED_CONFIG_KEYS = frozenset(
    [
        "retention_policy.daily",
        "retention_policy.weekly",
        "retention_policy.monthly",
        "output_dir",
    ]
)

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "wch"


# ── Public helpers ─────────────────────────────────────────────────


def get_default_output_dir() -> Path:
    """Return the default backup output directory (inside data dir)."""
    return paths.get_data_dir() / "backups"


def get_backup_config_path() -> Path:
    """Return the path to the backup configuration file."""
    return paths.get_data_dir() / "backup-config.json"


def create_backup(
    config_dir: Path | None = None,
    data_dir: Path | None = None,
    output_dir: Path | None = None,
) -> dict:
    """Create a backup zip and return metadata.

    Parameters
    ----------
    config_dir:
        Source directory for ``config.yaml``.  Defaults to
        :func:`~web_clip_helper.paths.get_config_dir`.
    data_dir:
        Source directory for ``clips.db`` and ``clips/``.  Defaults to
        :func:`~web_clip_helper.paths.get_data_dir`.
    output_dir:
        Directory to write the zip into.  Defaults to
        :func:`get_default_output_dir`.

    Returns
    -------
    dict
        ``path``, ``size_bytes``, ``output_dir``, ``filename``.

    Raises
    ------
    OSError
        If the data directory does not exist or the output directory
        cannot be created/written.
    """
    if config_dir is None:
        config_dir = paths.get_config_dir()
    if data_dir is None:
        data_dir = paths.get_data_dir()
    if output_dir is None:
        output_dir = get_default_output_dir()

    zip_path, size_bytes = _create_backup(
        config_dir=config_dir,
        data_dir=data_dir,
        output_dir=output_dir,
        prefix=BACKUP_PREFIX,
    )

    return {
        "path": str(zip_path),
        "size_bytes": size_bytes,
        "output_dir": str(output_dir),
        "filename": zip_path.name,
    }


def list_backups(output_dir: str | None = None) -> list[dict]:
    """List existing backups in *output_dir*.

    Parameters
    ----------
    output_dir:
        Directory to scan.  Defaults to :func:`get_default_output_dir`.

    Returns
    -------
    list[dict]
        Each dict has ``filename``, ``size_bytes``, and ``created_at``
        (ISO-8601 string or ``None``).  Returns an empty list when no
        backups are found.
    """
    if output_dir is None:
        output_dir = str(get_default_output_dir())

    logger.info("backup_list_start output_dir=%r", output_dir)
    metas = agentsdk.backup.ListBackups(str(output_dir), BACKUP_PREFIX)

    result = []
    for m in metas:
        created_at = m.created_at.isoformat() if m.created_at is not None else None
        result.append(
            {
                "filename": m.filename,
                "size_bytes": m.size,
                "created_at": created_at,
            }
        )

    logger.info("backup_list_complete count=%d", len(result))
    return result


def cleanup_backups(
    output_dir: str | None = None,
    config_path: str | None = None,
) -> dict:
    """Rotate backups according to the retention policy.

    Parameters
    ----------
    output_dir:
        Directory containing backups.  Defaults to
        :func:`get_default_output_dir`.
    config_path:
        Path to the backup config JSON file.  Defaults to
        :func:`get_backup_config_path`.

    Returns
    -------
    dict
        ``kept`` (list of filenames), ``removed`` (list of filenames),
        ``total_before`` (int).
    """
    if output_dir is None:
        output_dir = str(get_default_output_dir())
    if config_path is None:
        config_path = str(get_backup_config_path())

    logger.info("backup_cleanup_start output_dir=%r config_path=%r", output_dir, config_path)

    config = agentsdk.backup.LoadBackupConfig(config_path)
    backups = agentsdk.backup.ListBackups(output_dir, BACKUP_PREFIX)
    total_before = len(backups)

    # Nothing to rotate if no backups found or dir doesn't exist
    if total_before == 0:
        logger.info("backup_cleanup_complete kept=0 removed=0 total_before=0")
        return {"kept": [], "removed": [], "total_before": 0}

    rotation = agentsdk.backup.GFSRotate(
        backups, config.retention_policy, output_dir,
    )

    logger.info(
        "backup_cleanup_complete kept=%d removed=%d total_before=%d",
        len(rotation.kept),
        len(rotation.removed),
        total_before,
    )

    return {
        "kept": list(rotation.kept),
        "removed": list(rotation.removed),
        "total_before": total_before,
    }


def show_backup_config(config_path: str | None = None) -> dict:
    """Load and return the effective backup configuration.

    Parameters
    ----------
    config_path:
        Path to the backup config JSON file.  Defaults to
        :func:`get_backup_config_path`.

    Returns
    -------
    dict
        ``retention_policy`` (dict with ``daily``, ``weekly``, ``monthly``),
        ``output_dir``, and ``source`` (``"file"`` if the config file
        existed on disk, ``"defaults"`` otherwise).
    """
    if config_path is None:
        config_path = str(get_backup_config_path())

    logger.info("backup_config_show_start config_path=%r", config_path)

    config = agentsdk.backup.LoadBackupConfig(config_path)
    # Determine source: if the file exists, it came from disk
    source = "file" if Path(config_path).is_file() else "defaults"

    result = {
        "retention_policy": {
            "daily": config.retention_policy.daily,
            "weekly": config.retention_policy.weekly,
            "monthly": config.retention_policy.monthly,
        },
        "output_dir": config.output_dir,
        "source": source,
    }

    logger.info("backup_config_show_complete source=%r", source)
    return result


def set_backup_config(
    key: str,
    value: str,
    config_path: str | None = None,
) -> dict:
    """Update a single config key and persist to disk.

    Parameters
    ----------
    key:
        Dot-path key to set.  One of ``retention_policy.daily``,
        ``retention_policy.weekly``, ``retention_policy.monthly``, or
        ``output_dir``.
    value:
        New value as a string.  Retention values are coerced to
        ``int``; ``output_dir`` is kept as-is.
    config_path:
        Path to the backup config JSON file.  Defaults to
        :func:`get_backup_config_path`.

    Returns
    -------
    dict
        The full updated config dict (same shape as :func:`show_backup_config`)
        with ``source`` set to ``"file"``.

    Raises
    ------
    ValueError
        If *key* is not in the allowed set, or if a retention value
        is not a positive integer, or if *output_dir* is empty.
    """
    if key not in _ALLOWED_CONFIG_KEYS:
        raise ValueError(
            f"Unknown config key {key!r}. Allowed: {sorted(_ALLOWED_CONFIG_KEYS)}"
        )

    if config_path is None:
        config_path = str(get_backup_config_path())

    logger.info("backup_config_set_start key=%r value=%r config_path=%r", key, value, config_path)

    config = agentsdk.backup.LoadBackupConfig(config_path)

    # Apply the update
    if key == "output_dir":
        if not value:
            raise ValueError("output_dir must be a non-empty string")
        config.output_dir = value
    else:
        # key is retention_policy.daily / weekly / monthly
        attr = key.split(".")[-1]  # "daily", "weekly", or "monthly"
        try:
            int_val = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a positive integer, got {value!r}")
        if int_val < 1:
            raise ValueError(f"{key} must be a positive integer, got {int_val}")
        setattr(config.retention_policy, attr, int_val)

    agentsdk.backup.SaveBackupConfig(config_path, config)

    result = {
        "retention_policy": {
            "daily": config.retention_policy.daily,
            "weekly": config.retention_policy.weekly,
            "monthly": config.retention_policy.monthly,
        },
        "output_dir": config.output_dir,
        "source": "file",
    }

    logger.info("backup_config_set_complete key=%r", key)
    return result


# ── Internal implementation ────────────────────────────────────────


def _generate_filename(prefix: str, output_dir: Path) -> str:
    """Generate a timestamped backup filename, handling collisions.

    Format: ``{prefix}-backup-YYYYMMDD-HHMMSS.zip``

    If the base name already exists, appends ``-2``, ``-3``, etc.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = f"{prefix}-backup-{ts}.zip"

    if not (output_dir / base).exists():
        return base

    # Collision — try suffixes -2, -3, ...
    for n in range(2, 100):
        candidate = f"{prefix}-backup-{ts}-{n}.zip"
        if not (output_dir / candidate).exists():
            return candidate

    # Extremely unlikely — fall back to unique suffix
    return f"{prefix}-backup-{ts}-{os.getpid()}.zip"


def _create_backup(
    config_dir: Path,
    data_dir: Path,
    output_dir: Path,
    prefix: str,
) -> tuple[Path, int]:
    """Create the backup zip file atomically.

    Returns ``(zip_path, size_bytes)``.
    """
    t0 = time.monotonic()
    logger.info(
        "backup_create_start prefix=%r config_dir=%r data_dir=%r output_dir=%r",
        prefix,
        str(config_dir),
        str(data_dir),
        str(output_dir),
    )

    # Validate data_dir exists
    if not data_dir.is_dir():
        msg = f"Data directory does not exist: {data_dir}"
        logger.error("backup_create_error error=%s", msg)
        raise OSError(msg)

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = _generate_filename(prefix, output_dir)
    zip_path = output_dir / filename
    tmp_path = output_dir / f"{filename}.tmp"

    try:
        with zipfile.ZipFile(
            tmp_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zf:
            # config.yaml from config_dir
            config_yaml = config_dir / "config.yaml"
            if config_yaml.is_file():
                zf.write(config_yaml, arcname="config.yaml")

            # clips.db from data_dir
            clips_db = data_dir / "clips.db"
            if clips_db.is_file():
                zf.write(clips_db, arcname="clips.db")

            # clips/ directory from data_dir
            clips_dir = data_dir / "clips"
            if clips_dir.is_dir():
                for file_path in sorted(clips_dir.rglob("*")):
                    if file_path.is_file():
                        arcname = str(
                            PurePosixPath("clips") / file_path.relative_to(clips_dir)
                        )
                        zf.write(file_path, arcname=arcname)

        # Atomic replace
        os.replace(str(tmp_path), str(zip_path))

    except BaseException:
        # Clean up partial file on any error
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise

    size_bytes = zip_path.stat().st_size
    elapsed_ms = (time.monotonic() - t0) * 1000
    logger.info(
        "backup_create_complete path=%r size_bytes=%d elapsed_ms=%.1f",
        str(zip_path),
        size_bytes,
        elapsed_ms,
    )

    return zip_path, size_bytes
