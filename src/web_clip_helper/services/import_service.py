"""Import service — bulk-import previously clipped data.

Scans external directories for ``DATE_Title/DATE_Title.md`` structures,
reads ``_manifest.json`` files for metadata, and registers entries in the
SQLite index.

This module contains only pure business logic.  CLI wiring and JSONL
output live in ``cli.py``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from web_clip_helper.index import ClipIndex
from web_clip_helper.storage import StorageManager

__all__ = [
    "ImportCandidate",
    "ImportResult",
    "scan_import_dir",
    "extract_url_from_markdown",
    "build_clip_record",
    "execute_import",
    "preview_import",
    "run_import",
]

logger = logging.getLogger(__name__)

# Pattern: YYYY-MM-DD_Title
_FOLDER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+)$")

# URL extraction patterns, tried in priority order
_URL_PATTERNS = [
    # **链接**: URL / **链接**：URL (Markdown bold)
    re.compile(
        r"(?:链接|Link|URL|来源|Source)\s*\**\s*[:：]\s*(https?://\S+)",
        re.IGNORECASE,
    ),
    # Markdown link: [text](url)
    re.compile(r"\[[^\]]*\]\((https?://[^\s\)]+)\)"),
    # Bare URL line (starts with https://)
    re.compile(r"^(https?://\S+)", re.MULTILINE),
]

# Source types that are considered dynamic (auto-refresh)
_DYNAMIC_SOURCE_TYPES = frozenset({"weibo", "weibo-headline", "weibo-card"})


# ── Data classes ──────────────────────────────────────────────────────


@dataclass
class ImportCandidate:
    """A scanned folder that could be imported."""

    folder: Path
    folder_name: str
    date_str: str
    title_raw: str  # from folder name, may contain underscores
    markdown_path: Path
    manifest_entry: dict[str, Any] = field(default_factory=dict)
    url_from_manifest: str = ""
    source_type_from_manifest: str = ""


@dataclass
class ImportResult:
    """Summary of an import operation."""

    imported: int = 0
    skipped: int = 0
    errors: int = 0
    total_scanned: int = 0
    imported_ids: list[int] = field(default_factory=list)


# ── Scanning ──────────────────────────────────────────────────────────


def scan_import_dir(source_dir: Path) -> list[ImportCandidate]:
    """Recursively scan *source_dir* for clip folders.

    Searches all subdirectories (not just ``dynamic``/``static``) for
    directories matching ``YYYY-MM-DD_Title`` pattern.

    Also loads ``_manifest.json`` files from *source_dir* and all its
    subdirectories for metadata enrichment.

    Parameters
    ----------
    source_dir:
        Root directory to scan.  Must exist.

    Returns
    -------
    list[ImportCandidate]
        Sorted by path.
    """
    # Collect manifests from all levels
    manifests: dict[str, dict[str, Any]] = {}
    _load_all_manifests(source_dir, manifests)

    candidates: list[ImportCandidate] = []
    _scan_recursive(source_dir, manifests, candidates)

    # Sort for deterministic ordering
    candidates.sort(key=lambda c: c.folder)
    return candidates


def _load_all_manifests(root: Path, manifests: dict[str, dict]) -> None:
    """Walk *root* and load every ``_manifest.json`` found."""
    for dirpath, _dirnames, filenames in _walk_safe(root):
        if "_manifest.json" in filenames:
            mf_path = dirpath / "_manifest.json"
            try:
                data = json.loads(mf_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Skipping manifest %s: %s", mf_path, exc)
                continue
            items = data.get("items") or data.get("repos") or []
            for entry in items:
                folder = entry.get("folder", "")
                if folder:
                    manifests[folder] = entry


def _walk_safe(root: Path):
    """os.walk equivalent using pathlib, safe for permission errors."""
    dirs = [root]
    while dirs:
        current = dirs.pop(0)
        try:
            entries = sorted(current.iterdir())
        except PermissionError:
            continue
        subdirs = []
        filenames = []
        for e in entries:
            if e.is_dir():
                subdirs.append(e)
            else:
                filenames.append(e.name)
        yield current, subdirs, filenames
        dirs.extend(subdirs)


def _scan_recursive(
    parent: Path,
    manifests: dict[str, dict],
    candidates: list[ImportCandidate],
) -> None:
    """Depth-first scan of *parent* for clip folders."""
    try:
        children = sorted(parent.iterdir())
    except PermissionError:
        return

    for child in children:
        if not child.is_dir():
            continue
        name = child.name
        # Skip metadata/artifact directories
        if name.startswith("_") or name == "images":
            continue

        match = _FOLDER_RE.match(name)
        if match:
            _add_candidate(child, match, manifests, candidates)
        else:
            # Recurse into any non-matching directory (not just dynamic/static)
            _scan_recursive(child, manifests, candidates)


def _add_candidate(
    folder: Path,
    match: re.Match,
    manifests: dict[str, dict],
    candidates: list[ImportCandidate],
) -> None:
    """Create an ImportCandidate from a matched folder."""
    folder_name = folder.name
    date_str = match.group(1)
    title_raw = match.group(2)

    # Find markdown file
    md_file = folder / f"{folder_name}.md"
    if not md_file.exists():
        md_candidates = list(folder.glob("*.md"))
        if not md_candidates:
            return  # No markdown → skip silently (caller handles via total_scanned)
        md_file = md_candidates[0]

    manifest_entry = manifests.get(folder_name, {})

    candidates.append(ImportCandidate(
        folder=folder,
        folder_name=folder_name,
        date_str=date_str,
        title_raw=title_raw,
        markdown_path=md_file,
        manifest_entry=manifest_entry,
        url_from_manifest=manifest_entry.get("url", ""),
        source_type_from_manifest=manifest_entry.get("source_type", ""),
    ))


# ── URL extraction ────────────────────────────────────────────────────


def extract_url_from_markdown(md_text: str) -> str:
    """Extract the first URL from markdown content.

    Tries patterns in priority order:
    1. Labelled patterns: ``链接/Link/URL/来源/Source: URL``
    2. Markdown link: ``[text](url)``
    3. Bare URL line

    Returns empty string if no URL found.
    """
    for pattern in _URL_PATTERNS:
        match = pattern.search(md_text)
        if match:
            url = match.group(1).rstrip(")>")
            if url:
                return url
    return ""


# ── Record building ───────────────────────────────────────────────────


def build_clip_record(
    candidate: ImportCandidate,
    *,
    source_type_override: str = "",
) -> dict[str, Any]:
    """Build a clip record dict ready for ``ClipIndex.save_clip()``.

    Parameters
    ----------
    candidate:
        Scanned folder with metadata.
    source_type_override:
        If non-empty, overrides manifest source_type for candidates
        that don't have a manifest entry.
    """
    # Determine URL
    url = candidate.url_from_manifest
    if not url:
        try:
            md_text = candidate.markdown_path.read_text(encoding="utf-8")
            url = extract_url_from_markdown(md_text)
        except OSError:
            url = ""

    # Determine source_type: manifest > override > unknown
    source_type = candidate.source_type_from_manifest
    if not source_type:
        source_type = source_type_override or "unknown"

    # Title: replace underscores with spaces
    title = candidate.title_raw.replace("_", " ").strip()
    if not title:
        title = candidate.folder_name

    # Count images
    images_dir = candidate.folder / "images"
    image_count = 0
    if images_dir.is_dir():
        try:
            image_count = sum(1 for f in images_dir.iterdir() if f.is_file())
        except PermissionError:
            pass

    # Determine dynamic flag
    is_dynamic = 1 if source_type in _DYNAMIC_SOURCE_TYPES else 0

    manifest = candidate.manifest_entry

    return {
        "url": url,
        "title": title,
        "source_type": source_type,
        "category": manifest.get("category", ""),
        "tags": manifest.get("tags", []),
        "folder_path": str(candidate.folder),
        "markdown_path": str(candidate.markdown_path),
        "image_count": image_count,
        "is_dynamic": is_dynamic,
        "refresh_interval_days": manifest.get("refresh_interval_days", 7),
        "created_at": f"{candidate.date_str}T00:00:00",
        "updated_at": f"{candidate.date_str}T00:00:00",
    }


# ── Import execution ──────────────────────────────────────────────────


def execute_import(
    index: ClipIndex,
    candidates: list[ImportCandidate],
    *,
    copy_to: str | Path | None = None,
    source_type_override: str = "",
    storage: StorageManager | None = None,
) -> ImportResult:
    """Import candidates into the index.

    Parameters
    ----------
    index:
        Open ClipIndex instance.
    candidates:
        Scanned folders to import.
    copy_to:
        If set, copy files into this storage_path.
    source_type_override:
        Override source_type for candidates without manifest data.
    storage:
        Pre-created StorageManager (required if copy_to is set).
        Avoids creating a new one per candidate.

    Returns
    -------
    ImportResult
        Summary with counts and imported IDs.
    """
    result = ImportResult(total_scanned=len(candidates))

    for candidate in candidates:
        record = build_clip_record(
            candidate,
            source_type_override=source_type_override,
        )

        # Handle copy mode
        if copy_to and storage:
            record = _copy_files(record, candidate, storage)

        # Dedup by folder_path
        if index.find_by_folder_path(record["folder_path"]):
            result.skipped += 1
            logger.info(
                "import skip existing folder=%s",
                candidate.folder_name,
            )
            continue

        try:
            record_id = index.save_clip(record)
            result.imported += 1
            result.imported_ids.append(record_id)
            logger.info(
                "import ok record_id=%d folder=%s",
                record_id,
                candidate.folder_name,
            )
        except Exception as exc:
            result.errors += 1
            logger.error(
                "import error folder=%s error=%s",
                candidate.folder_name,
                exc,
            )

    logger.info(
        "import complete imported=%d skipped=%d errors=%d total=%d",
        result.imported,
        result.skipped,
        result.errors,
        result.total_scanned,
    )
    return result


def _copy_files(
    record: dict[str, Any],
    candidate: ImportCandidate,
    storage: StorageManager,
) -> dict[str, Any]:
    """Copy files into storage and update record paths."""
    title = record["title"]
    dest_entry = storage.create_entry(title)

    try:
        md_text = candidate.markdown_path.read_text(encoding="utf-8")
        storage.save_markdown(dest_entry, md_text)
    except OSError as exc:
        logger.warning("Failed to copy markdown: %s", exc)

    # Copy images
    images_dir = candidate.folder / "images"
    if images_dir.is_dir():
        dest_images = storage.get_images_dir(dest_entry)
        for img in images_dir.iterdir():
            if img.is_file():
                try:
                    (dest_images / img.name).write_bytes(img.read_bytes())
                except OSError as exc:
                    logger.warning("Failed to copy image %s: %s", img.name, exc)

    # Update record to point to new location
    # save_markdown uses entry_path.name + ".md" as filename
    actual_md_name = dest_entry.name + ".md"
    record["folder_path"] = str(dest_entry)
    record["markdown_path"] = str(dest_entry / actual_md_name)
    return record


# ── Preview ──────────────────────────────────────────────────────────


def preview_import(candidates: list[ImportCandidate]) -> list[dict[str, Any]]:
    """Build preview dicts for dry-run mode.

    Returns a list of dicts suitable for JSONL emission, one per candidate.
    """
    return [
        {
            "folder": str(c.folder),
            "markdown_exists": c.markdown_path.exists(),
            "manifest": bool(c.manifest_entry),
            "url": c.url_from_manifest,
            "source_type": c.source_type_from_manifest or "unknown",
        }
        for c in candidates
    ]


# ── High-level import orchestrator ───────────────────────────────────


def run_import(
    source_dir: Path,
    *,
    copy_files: bool = False,
    source_type_override: str = "",
) -> tuple[list[dict[str, Any]], ImportResult]:
    """Scan *source_dir* and import all candidates.

    Returns (preview_rows, result).  If *copy_files* is True, a
    :class:`StorageManager` is created from the project config.

    This is the single entry-point for the CLI layer — it handles
    scanning, storage setup, and execution in one call.
    """
    from web_clip_helper.config import get_config

    candidates = scan_import_dir(source_dir)
    previews = preview_import(candidates)

    idx = ClipIndex(get_config().db_path)
    try:
        storage = None
        copy_to: str | None = None
        if copy_files:
            from web_clip_helper.storage import StorageManager

            copy_to = get_config().storage_path
            storage = StorageManager(copy_to)

        result = execute_import(
            idx,
            candidates,
            copy_to=copy_to,
            source_type_override=source_type_override,
            storage=storage,
        )
    finally:
        idx.close()

    return previews, result
