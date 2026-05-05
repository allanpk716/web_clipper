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

from web_clip_helper.adapters.base import AdapterError, route_url
from web_clip_helper.config import Config
from web_clip_helper.services.images import download_images
from web_clip_helper.repository.index import ClipIndex
from web_clip_helper.services.llm import LLMClient
from web_clip_helper.models import ClipResult, RawContent
from web_clip_helper.output import (
    jsonl_emit_error,
    jsonl_emit_progress,
    jsonl_emit_result,
    jsonl_emit_warning,
)
from web_clip_helper.repository.storage import StorageManager
from web_clip_helper.url_utils import normalize_url

__all__ = ["clip_text", "clip_url", "plan_clip_text", "plan_clip_url"]


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


def clip_url(url: str, config: Config, *, skip_images: bool = False) -> ClipResult | None:
    """Clip a URL end-to-end: route → fetch → images → store → index.

    Parameters
    ----------
    url:
        The URL to clip.
    config:
        Application configuration.
    skip_images:
        When ``True``, skip image downloading entirely.  The result
        will report ``image_count=0`` and original remote URLs are
        left untouched in the markdown.

    Returns
    -------
    ClipResult or None
        Result on success, ``None`` on unrecoverable error.
    """
    jsonl_emit_progress(message=f"Starting clip for URL: {url}", percent=0)

    # 0. Idempotent duplicate check — skip fetch if URL already clipped
    try:
        index = ClipIndex(config.db_path)
        existing = index.find_by_url(url)
        index.close()
    except Exception:
        # Duplicate check failure must not block clipping
        existing = None

    if existing is not None:
        jsonl_emit_progress(
            message="Duplicate URL detected",
            percent=95,
        )
        result = ClipResult(
            folder_path=Path(existing["folder_path"]),
            markdown_path=Path(existing["markdown_path"]),
            image_count=existing.get("image_count", 0),
            record_id=existing["id"],
        )
        jsonl_emit_result(
            stage="clip",
            url=existing.get("url", ""),
            title=existing.get("title", ""),
            source_type=existing.get("source_type", ""),
            folder=existing["folder_path"],
            markdown=existing["markdown_path"],
            image_count=existing.get("image_count", 0),
            file_count=0,
            record_id=existing["id"],
            tags=existing.get("tags", []),
            category=existing.get("category", ""),
            duplicate=True,
            existing_id=existing["id"],
        )
        jsonl_emit_progress(message="Clip complete (duplicate)", percent=100)
        return result

    # 1. Route to adapter
    try:
        adapter_cls = route_url(url)
    except ValueError as exc:
        jsonl_emit_error(stage="routing", detail=str(exc), error_code="ROUTING_ERROR")
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
        jsonl_emit_error(stage="fetch", detail=str(exc), error_code="FETCH_ERROR")
        return None
    except Exception as exc:
        jsonl_emit_error(stage="fetch", detail=f"Unexpected error: {exc}", error_code="INTERNAL_ERROR")
        return None

    jsonl_emit_progress(
        message=f"Fetched content: {raw.title or 'untitled'}",
        percent=30,
    )

    # Delegate to shared storage pipeline
    return _store_and_index(raw, config, skip_images=skip_images)


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
        jsonl_emit_error(stage="clip_text", detail="Empty text input", error_code="INPUT_INVALID")
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


def _enrich_with_llm(
    raw: RawContent,
    config: Config,
) -> tuple[str, list[str], str]:
    """Try LLM enrichment; return (title, tags, category) with fallback.

    When the LLM is unavailable (no API key, network error, malformed
    response) the pipeline keeps running with sensible defaults:
    title from *raw.title* or a timestamp-derived string, empty tags,
    and an empty category.
    """
    # Fast path: no API key → skip LLM entirely
    if not config.llm.api_key or not config.llm.api_key.strip():
        jsonl_emit_warning(
            message="LLM enrichment skipped: no API key configured",
            stage="llm",
        )
        title = raw.title or "untitled"
        return title, [], ""

    jsonl_emit_progress(message="LLM enrichment starting", percent=35)

    client = LLMClient(config.llm, prompts=config.prompts)
    try:
        title = client.generate_title(raw.content_md, raw.source_type, raw.url)
        tags = client.extract_tags(raw.content_md, raw.source_type)
        category = client.classify_content(raw.content_md, raw.source_type)
    except Exception as exc:
        jsonl_emit_warning(
            message=f"LLM enrichment failed: {exc}",
            stage="llm",
        )
        title = raw.title or "untitled"
        tags: list[str] = []
        category = ""
        return title, tags, category

    jsonl_emit_progress(message="LLM enrichment complete", percent=45)
    return title, tags, category


def _store_and_index(raw: RawContent, config: Config, *, skip_images: bool = False) -> ClipResult | None:
    """Shared pipeline: LLM enrichment → storage → images → markdown save → SQLite index."""
    storage = StorageManager(config.storage_path)

    # 2b. LLM enrichment
    llm_title, llm_tags, llm_category = _enrich_with_llm(raw, config)
    title = llm_title

    # 3. Create storage entry
    try:
        entry_path = storage.create_entry(title, raw.fetched_at)
    except OSError as exc:
        jsonl_emit_error(stage="storage", detail=str(exc), error_code="STORAGE_ERROR")
        return None

    jsonl_emit_progress(
        message=f"Created storage entry: {entry_path.name}",
        percent=40,
    )

    # 4. Download images
    image_count = 0
    url_map: dict[str, str] = {}

    if raw.images and not skip_images:
        images_dir = storage.get_images_dir(entry_path)
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
        jsonl_emit_error(stage="storage", detail=str(exc), error_code="STORAGE_ERROR")
        return None

    jsonl_emit_progress(
        message=f"Saved markdown: {md_path.name}",
        percent=85,
    )

    # 6b. Save extra files (PDF, etc.)
    extra_file_count = 0
    if raw.extra_files:
        for fname, content in raw.extra_files.items():
            try:
                fp = storage.save_file(entry_path, fname, content)
                extra_file_count += 1
                jsonl_emit_progress(
                    message=f"Saved extra file: {fp.name}",
                    percent=87,
                )
            except OSError as exc:
                jsonl_emit_error(
                    stage="storage",
                    detail=f"Failed to save extra file {fname}: {exc}",
                    error_code="STORAGE_ERROR",
                )
                return None

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
            "tags": llm_tags,
            "category": llm_category,
            "is_dynamic": 1 if raw.is_dynamic else 0,
        })
        index.close()
    except Exception as exc:
        jsonl_emit_error(stage="index", detail=str(exc), error_code="INDEX_ERROR")
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
        stage="clip",
        url=raw.url or "",
        title=title,
        source_type=raw.source_type,
        folder=str(entry_path),
        markdown=str(md_path),
        image_count=image_count,
        file_count=extra_file_count,
        record_id=record_id,
        tags=llm_tags,
        category=llm_category,
    )

    # Emit a summary warning if LLM was skipped (no API key)
    if not config.llm.api_key or not config.llm.api_key.strip():
        jsonl_emit_warning(
            message=(
                "LLM 未配置：标题/标签/分类使用默认值。"
                "请运行 `web-clip-helper config set llm.api_key <key>` "
                "或设置环境变量 WEB_CLIP_LLM_API_KEY。"
            ),
            stage="llm",
        )

    jsonl_emit_progress(message="Clip complete", percent=100)

    return result


# ── Dry-run (plan-only) entry points ──────────────────────────────────


def plan_clip_url(url: str, config: Config) -> None:
    """Preview clip execution plan for a URL without performing real IO.

    Read-only operations (route_url, duplicate check) are performed.
    No network fetch, no filesystem writes, no SQLite writes occur.

    Emits JSONL:
      - ``progress`` lines for plan stages
      - ``result`` with ``dry_run=True`` and an ``ExecutionPlan`` payload
      - ``error`` on routing failure

    Raises
    ------
    SystemExit
        On unrecoverable routing errors (via jsonl_emit_error).
    """
    jsonl_emit_progress(message=f"[dry-run] Planning clip for URL: {url}", percent=0)

    # 1. Route to adapter (read-only — just URL pattern matching)
    try:
        adapter_cls = route_url(url)
    except ValueError as exc:
        jsonl_emit_error(stage="routing", detail=str(exc), error_code="ROUTING_ERROR")
        raise SystemExit(1)

    adapter_name = adapter_cls.__name__
    source_type = getattr(adapter_cls, "source_type", "generic")

    jsonl_emit_progress(
        message=f"[dry-run] Routed to adapter: {adapter_name}",
        percent=50,
    )

    # 2. Duplicate check (read-only SELECT)
    duplicate = False
    existing_id: int | None = None
    try:
        index = ClipIndex(config.db_path)
        existing = index.find_by_url(url)
        index.close()
        if existing is not None:
            duplicate = True
            existing_id = existing["id"]
    except Exception:
        # Duplicate check failure is non-fatal in dry-run too
        pass

    # 3. Build estimated execution plan
    estimated_actions = [
        "route_url (completed)",
        f"adapter.fetch via {adapter_name}",
    ]

    if duplicate:
        estimated_actions.append("return duplicate result (no further IO)")
    else:
        estimated_actions.extend([
            "llm_enrichment (title, tags, category)",
            "storage.create_entry",
            "download_images",
            "save_markdown",
            "save_clip to SQLite index",
        ])

    jsonl_emit_result(
        stage="clip",
        dry_run=True,
        url=url,
        plan={
            "adapter": adapter_name,
            "source_type": source_type,
            "duplicate": duplicate,
            "existing_id": existing_id,
            "estimated_actions": estimated_actions,
        },
    )

    jsonl_emit_progress(message="[dry-run] Plan complete", percent=100)


def plan_clip_text(text: str, config: Config) -> None:
    """Preview clip execution plan for raw text without performing real IO.

    Emits JSONL:
      - ``progress`` lines for plan stages
      - ``result`` with ``dry_run=True`` and an ``ExecutionPlan`` payload

    Raises
    ------
    SystemExit
        On empty text input (via jsonl_emit_error).
    """
    if not text or not text.strip():
        jsonl_emit_error(stage="clip_text", detail="Empty text input", error_code="INPUT_INVALID")
        raise SystemExit(1)

    estimated_title = text.strip()[:50].replace("\n", " ") or "text-clip"

    jsonl_emit_progress(message="[dry-run] Planning clip for raw text", percent=50)

    estimated_actions = [
        "create RawContent (source_type=text)",
        "llm_enrichment (title, tags, category)",
        "storage.create_entry",
        "save_markdown",
        "save_clip to SQLite index",
    ]

    jsonl_emit_result(
        stage="clip",
        dry_run=True,
        plan={
            "adapter": None,
            "source_type": "text",
            "duplicate": False,
            "existing_id": None,
            "estimated_title": estimated_title,
            "estimated_actions": estimated_actions,
        },
    )

    jsonl_emit_progress(message="[dry-run] Plan complete", percent=100)
