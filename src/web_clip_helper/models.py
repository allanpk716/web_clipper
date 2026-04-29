"""Data models shared across adapters, storage, and the clip pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class RawContent:
    """The output of an adapter's ``fetch()`` — raw clipped content."""

    url: str
    title: str | None
    content_md: str
    images: list[str] = field(default_factory=list)
    extra_files: dict[str, bytes] = field(default_factory=dict)
    source_type: str = "generic"
    fetched_at: datetime = field(default_factory=datetime.now)


@dataclass
class ClipResult:
    """The outcome of a full clip pipeline run."""

    folder_path: Path
    markdown_path: Path
    image_count: int = 0
    file_count: int = 0
    record_id: int | None = None
