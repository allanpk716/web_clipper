"""Backup service — create zip archives from XDG multi-directory layout.

Collects files from two XDG directories:
- **Config dir**: ``config.yaml``
- **Data dir**: ``clips.db``, ``clips/``

Produces a single zip file with forward-slash entry paths, atomic write
via ``.tmp`` + ``os.replace()``, and collision-safe filename generation.
"""

from __future__ import annotations

import logging
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .. import paths

__all__ = [
    "BACKUP_PREFIX",
    "create_backup",
    "get_backup_config_path",
    "get_default_output_dir",
]

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
