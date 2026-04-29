"""Storage layout manager — directory structure and file persistence.

Layout convention::

    <storage_path>/
      2024-01-15_Article Title/
        2024-01-15_Article Title.md
        images/
          img_001.jpg
          img_002.png
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .output import jsonl_emit_warning

__all__ = ["StorageManager"]

# Characters that are unsafe or problematic in directory/file names.
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Maximum filename length (conservative for cross-platform).
_MAX_NAME_LEN = 200


def _sanitize_title(title: str) -> str:
    """Replace filesystem-unsafe characters with underscores and truncate."""
    safe = _UNSAFE_CHARS.sub("_", title.strip())
    # Collapse consecutive underscores
    safe = re.sub(r"_{2,}", "_", safe)
    # Strip leading/trailing underscores and dots
    safe = safe.strip("_. ")
    if not safe:
        safe = "untitled"
    return safe[:_MAX_NAME_LEN]


class StorageManager:
    """Manages the on-disk layout for clipped articles.

    Parameters
    ----------
    base_path:
        Root storage directory (from config ``storage_path``).
    """

    def __init__(self, base_path: str | Path) -> None:
        self.base_path = Path(base_path)

    def create_entry(self, title: str, date: datetime | None = None) -> Path:
        """Create a directory for a new clip entry.

        Parameters
        ----------
        title:
            Article title — will be sanitized for the filesystem.
        date:
            Date for the entry (defaults to ``datetime.now()``).

        Returns
        -------
        Path
            The created entry directory.
        """
        if date is None:
            date = datetime.now()

        date_prefix = date.strftime("%Y-%m-%d")
        safe_title = _sanitize_title(title)
        dir_name = f"{date_prefix}_{safe_title}"

        entry_path = self.base_path / dir_name
        entry_path.mkdir(parents=True, exist_ok=True)

        # Ensure images subdirectory exists
        (entry_path / "images").mkdir(exist_ok=True)

        return entry_path

    def save_markdown(
        self,
        entry_path: Path,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> Path:
        """Write markdown content to the entry directory.

        The filename is derived from the directory name (date + title).

        Parameters
        ----------
        entry_path:
            Directory returned by ``create_entry()``.
        content:
            Markdown body text.
        metadata:
            Optional YAML-style metadata prepended as a comment header.

        Returns
        -------
        Path
            Path to the written markdown file.
        """
        md_filename = entry_path.name + ".md"
        md_path = entry_path / md_filename

        header = ""
        if metadata:
            lines = ["<!--"]
            for key, value in metadata.items():
                lines.append(f"  {key}: {value}")
            lines.append("-->")
            header = "\n".join(lines) + "\n\n"

        try:
            md_path.write_text(header + content, encoding="utf-8")
        except OSError as exc:
            raise OSError(
                f"Cannot write markdown file {md_path}: {exc}"
            ) from exc

        return md_path

    def save_file(
        self,
        entry_path: Path,
        filename: str,
        content: bytes,
    ) -> Path:
        """Write binary content to a file in the entry directory.

        Parameters
        ----------
        entry_path:
            Directory returned by ``create_entry()``.
        filename:
            Name for the file (e.g. ``paper.pdf``).
        content:
            Raw bytes to write.

        Returns
        -------
        Path
            Path to the written file.

        Raises
        ------
        OSError
            If the write fails (disk full, permissions, etc.).
        """
        file_path = entry_path / filename
        try:
            file_path.write_bytes(content)
        except OSError as exc:
            raise OSError(
                f"Cannot write file {file_path}: {exc}"
            ) from exc
        return file_path

    def get_images_dir(self, entry_path: Path) -> Path:
        """Return the ``images/`` subdirectory path for *entry_path*."""
        images_dir = entry_path / "images"
        images_dir.mkdir(exist_ok=True)
        return images_dir
