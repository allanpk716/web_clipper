"""Generic web adapter — fallback adapter for arbitrary HTML pages.

Uses readability-lxml to extract the main content area and markdownify
to convert HTML to Markdown.  Extracts image URLs from both ``<img>``
tags and CSS ``background-image`` properties.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import httpx
from markdownify import markdownify as md
from readability import Document

from .base import AdapterError
from ..models import RawContent
from ..output import jsonl_emit_error, jsonl_emit_progress, jsonl_emit_warning

__all__ = ["GenericWebAdapter"]

# ── Configuration ───────────────────────────────────────────────────

_TIMEOUT = 30.0
_MAX_RETRIES = 2
_BACKOFF_BASE = 1.0  # seconds

# Regex patterns for image URL extraction
_IMG_TAG_RE = re.compile(r'<img\s[^>]*src=["\']([^"\']+)["\']', re.IGNORECASE)
_BG_IMAGE_RE = re.compile(
    r'background-image\s*:\s*url\(\s*["\']?([^"\')\s]+)["\']?\s*\)',
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)


def _extract_title(html: str) -> str:
    """Extract the page title from the HTML ``<title>`` tag."""
    match = _TITLE_RE.search(html)
    if match:
        return match.group(1).strip()
    return ""


def _extract_image_urls(html: str) -> list[str]:
    """Extract image URLs from HTML content.

    Finds URLs in ``<img src>`` and ``background-image: url(...)``.
    Deduplicates while preserving order.
    """
    urls: list[str] = []
    seen: set[str] = set()

    for match in _IMG_TAG_RE.finditer(html):
        url = match.group(1)
        if url not in seen:
            seen.add(url)
            urls.append(url)

    for match in _BG_IMAGE_RE.finditer(html):
        url = match.group(1)
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls


class GenericWebAdapter:
    """Fallback adapter that converts arbitrary HTML pages to Markdown.

    Registered as the default when no other adapter's URL pattern matches.
    Uses readability-lxml to extract the main content and markdownify to
    convert it.
    """

    source_type = "web"

    def fetch(self, url: str) -> RawContent:
        """Fetch an arbitrary web page and convert to Markdown.

        Parameters
        ----------
        url:
            The fully-qualified URL to clip.

        Returns
        -------
        RawContent
            Converted Markdown content with image URLs extracted.

        Raises
        ------
        AdapterError
            If the page cannot be fetched or parsed.
        """
        jsonl_emit_progress(
            message=f"Fetching web page: {url}",
            stage="fetch",
            url=url,
        )

        html = self._fetch_html(url)
        title = _extract_title(html)
        images = _extract_image_urls(html)

        # Use readability-lxml to extract main content
        try:
            doc = Document(html)
            readable_title = doc.title() or title
            summary_html = doc.summary()
        except Exception as exc:
            jsonl_emit_warning(
                message=f"readability-lxml failed, using raw HTML: {exc}",
                url=url,
                error=str(exc),
            )
            readable_title = title
            summary_html = html

        # Convert HTML to Markdown
        content_md = md(summary_html)

        if not content_md.strip():
            jsonl_emit_warning(
                message=f"Converted markdown is empty for {url}",
                url=url,
            )

        # Prepend metadata header
        header_parts = [
            f"> Source: {url}",
            f"> Clipped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        header = "\n".join(header_parts)
        content_md = f"{header}\n\n---\n\n{content_md}"

        jsonl_emit_progress(
            message=f"Web page fetch complete: {url}",
            stage="fetch",
            url=url,
            images=len(images),
        )

        return RawContent(
            url=url,
            title=readable_title or title or url,
            content_md=content_md,
            images=images,
            source_type=self.source_type,
        )

    def _fetch_html(self, url: str) -> str:
        """Fetch HTML content with retry logic."""
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                with httpx.Client(
                    timeout=_TIMEOUT,
                    follow_redirects=True,
                    headers={"User-Agent": "web-clip-helper/0.1.0"},
                ) as client:
                    resp = client.get(url)
                    resp.raise_for_status()
                    return resp.text
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.RequestError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                    continue

        msg = f"Failed to fetch {url}: {last_exc}"
        jsonl_emit_error(stage="fetch", detail=msg, url=url)
        raise AdapterError(msg)
