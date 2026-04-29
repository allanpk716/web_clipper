"""End-to-end clip pipeline — orchestrate adapter → images → storage → index.

Two entry points:

* ``clip_url(url, config)`` — fetch a URL via the adapter framework.
* ``clip_text(text, config)`` — clip raw text input directly.

Both produce the same artefacts: Markdown file, images directory, and a
SQLite index record.  All progress and results are emitted as JSONL.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .adapter import AdapterError, route_url
from .config import Config
from .images import download_images
from .index import ClipIndex
from .models import ClipResult, RawContent
from .output import (
    jsonl_emit_error,
    jsonl_emit_progress,
    jsonl_emit_result,
    jsonl_emit_warning,
)
from .storage import StorageManager

__all__ = ["clip_text", "clip_url"]


def _replace_image_urls(
    markdown: str,
    url_map: dict[str, str],
) -> str:
    """Replace remote image URLs in *markdown* with local relative paths.

    Handles both ``![alt](url)`` and ``<img src="url">`` syntax.
    """

    def _replacer(m: re.Match[str]) -> str:
        url = m.group(2) or m.group(4)
        local = url_map.get(url, url)
        if m.group(1):  # markdown syntax
            return f"![{m.group(1)}]({local})"
        return f'<img src="{local}"'

    # Pattern 1: ![alt](url)
    pattern_md = r"!\[([^\]]*)\]\(([^)]+)\)"
    # Pattern 2: <img src="url">
    pattern_html = r'<img\s+src="([^"]+)"'

    result = markdown
    for url, local in url_map.items():
        result = result.replace(url, local)
    return result


def clip_url(url: str, config: Config) -> ClipResult | None:
    """Clip a URL end-to-end: route → fetch → images → store → index.

    Parameters
    ----------
    url:
        The URL to clip.
    config:
        Application configuration.

    Returns
    -------
    ClipResult or None
        Result on success, ``None`` on unrecoverable error.
    """
    jsonl_emit_progress(message=f"Starting clip for URL: {url}", percent=0)

    # 1. Route to adapter
    try:
        adapter_cls = route_url(url)
    except ValueError as exc:
        jsonl_emit_error(stage="routing", detail=str(exc))
        return None

    jsonl_emit_progress(
        message=f"Using adapter: {adapter_cls.__name__}",
        percent=10,
    )

    # 2. Fetch content
    try:
        adapter = adapter_cls()
        raw: RawContent = adapter.fetch(url)
    except AdapterError as exc:
        jsonl_emit_error(stage="fetch", detail=str(exc))
        return None
    except Exception as exc:
        jsonl_emit_error(stage="fetch", detail=f"Unexpected error: {exc}")
        return None

    jsonl_emit_progress(
        message=f"Fetched content: {raw.title or 'untitled'}",
        percent=30,
    )

    # Delegate to shared storage pipeline
    return _store_and_index(raw, config)


def clip_text(text: str, config: Config) -> ClipResult | None:
    """Clip raw text input.

    Parameters
    ----------
    text:
        Raw text to clip.
    config:
        Application configuration.

    Returns
    -------
    ClipResult or None
        Result on success, ``None`` on unrecoverable error.
    """
    if not text or not text.strip():
        jsonl_emit_error(stage="clip_text", detail="Empty text input")
        return None

    jsonl_emit_progress(message="Starting clip for raw text", percent=0)

    title = text.strip()[:50].replace("\n", " ") or "text-clip"
    now = datetime.now()

    raw = RawContent(
        url="",
        title=title,
        content_md=text,
        images=[],
        source_type="text",
        fetched_at=now,
    )

    return _store_and_index(raw, config)


def _store_and_index(raw: RawContent, config: Config) -> ClipResult | None:
    """Shared pipeline: storage → images → markdown save → SQLite index."""
    storage = StorageManager(config.storage_path)
    title = raw.title or "untitled"

    # 3. Create storage entry
    try:
        entry_path = storage.create_entry(title, raw.fetched_at)
    except OSError as exc:
        jsonl_emit_error(stage="storage", detail=str(exc))
        return None

    jsonl_emit_progress(
        message=f"Created storage entry: {entry_path.name}",
        percent=40,
    )

    # 4. Download images
    images_dir = storage.get_images_dir(entry_path)
    image_count = 0
    url_map: dict[str, str] = {}

    if raw.images:
        try:
            url_map = download_images(
                raw.images,
                images_dir,
                referer=raw.url or None,
            )
            image_count = sum(
                1 for v in url_map.values() if not v.startswith("http")
            )
        except Exception as exc:
            jsonl_emit_warning(
                message=f"Image download stage failed: {exc}",
            )
            # Non-fatal — continue without images

    jsonl_emit_progress(
        message=f"Downloaded {image_count} images",
        percent=70,
    )

    # 5. Replace image URLs in markdown
    content_md = _replace_image_urls(raw.content_md, url_map)

    # 6. Save markdown
    metadata = {
        "url": raw.url or "",
        "source_type": raw.source_type,
        "fetched_at": raw.fetched_at.isoformat(),
        "title": title,
    }

    try:
        md_path = storage.save_markdown(entry_path, content_md, metadata)
    except OSError as exc:
        jsonl_emit_error(stage="storage", detail=str(exc))
        return None

    jsonl_emit_progress(
        message=f"Saved markdown: {md_path.name}",
        percent=85,
    )

    # 7. Save to SQLite index
    record_id: int | None = None
    try:
        index = ClipIndex(config.db_path)
        record_id = index.save_clip({
            "url": raw.url or "",
            "title": title,
            "source_type": raw.source_type,
            "folder_path": str(entry_path),
            "markdown_path": str(md_path),
            "image_count": image_count,
        })
        index.close()
    except Exception as exc:
        jsonl_emit_error(stage="index", detail=str(exc))
        return None

    jsonl_emit_progress(
        message=f"Saved to index: record #{record_id}",
        percent=95,
    )

    # 8. Emit JSONL result
    result = ClipResult(
        folder_path=entry_path,
        markdown_path=md_path,
        image_count=image_count,
        record_id=record_id,
    )

    jsonl_emit_result(
        url=raw.url or "",
        title=title,
        source_type=raw.source_type,
        folder=str(entry_path),
        markdown=str(md_path),
        image_count=image_count,
        record_id=record_id,
    )

    jsonl_emit_progress(message="Clip complete", percent=100)

    return result
