"""WeChat adapter — fetch WeChat public account articles from mp.weixin.qq.com.

URL pattern: ``https?://mp\\.weixin\\.qq\\.com/.*``

Strategy:
1. Fetch the article HTML page with a browser-like User-Agent.
2. Extract the title from ``#activity-name`` or ``<h1>``.
3. Extract the author from ``#js_name`` or ``.rich_media_meta_nickname``.
4. Extract the publish date from ``#publish_time``.
5. Extract the article body from ``#js_content`` (WeChat's main content container).
6. Convert the body HTML to Markdown using ``markdownify``.
7. Extract image URLs from ``<img>`` tags inside ``#js_content`` — checking both
   ``data-src`` (WeChat's lazy-loading attribute) and ``src``.
8. Build a metadata header with source, date, and author.
9. Return a :class:`RawContent` with ``source_type="wechat"``.

Image anti-hotlinking:
    WeChat serves images with Referer checking. The adapter returns image URLs
    as-is; the pipeline's ``download_images()`` function should be called with
    ``referer=article_url`` to pass the correct Referer header.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import httpx
from markdownify import markdownify as md

from .base import AdapterError, register_adapter
from ..models import RawContent
from ..output import jsonl_emit_error, jsonl_emit_progress, jsonl_emit_warning

__all__ = ["WeChatAdapter"]

# ── Configuration ───────────────────────────────────────────────────

_URL_PATTERN = r"https?://mp\.weixin\.qq\.com/.*"
_TIMEOUT = 30.0
_MAX_RETRIES = 2
_BACKOFF_BASE = 1.0  # seconds

# Desktop User-Agent to mimic a normal browser visiting the article
_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ── HTTP helper ─────────────────────────────────────────────────────


def _http_get_with_retry(
    client: httpx.Client,
    url: str,
    headers: dict[str, str] | None = None,
    *,
    retries: int = _MAX_RETRIES,
    timeout: float = _TIMEOUT,
) -> httpx.Response:
    """GET with retry and exponential backoff. Raises on final failure."""
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = client.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.RequestError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                continue
    raise last_exc  # type: ignore[misc]


# ── HTML parsing helpers ────────────────────────────────────────────


def _extract_text_from_html(html: str, pattern: re.Pattern[str]) -> str:
    """Extract inner text from the first match of *pattern* in *html*.

    Handles simple opening tags with attributes. Returns the stripped
    text content with any inner HTML tags removed, or an empty string
    if no match.
    """
    m = pattern.search(html)
    if not m:
        return ""
    # Extract the tag name from the matched opening tag text
    tag_text = m.group(0)
    tag_name_match = re.match(r"<(\w+)", tag_text)
    if not tag_name_match:
        return ""
    tag_name = tag_name_match.group(1)

    # Find text between the opening and closing tags.
    after_open = html[m.end():]
    close_tag = f"</{tag_name}>"
    close_idx = after_open.find(close_tag)
    if close_idx == -1:
        return ""
    inner = after_open[:close_idx].strip()
    # Strip any inner HTML tags (e.g. <span class="js_title_inner">)
    inner = re.sub(r"<[^>]+>", "", inner).strip()
    return inner


def _extract_title(html: str) -> str:
    """Extract article title from WeChat HTML.

    Looks for ``#activity-name`` first, then falls back to ``<h1>``.
    """
    # <h1 id="activity-name" ...>Title</h1>
    title = _extract_text_from_html(
        html,
        re.compile(r'<h1[^>]*id\s*=\s*["\']activity-name["\'][^>]*>', re.IGNORECASE),
    )
    if title:
        return title

    # Fallback: any <h1> tag
    title = _extract_text_from_html(
        html,
        re.compile(r"<h1[^>]*>", re.IGNORECASE),
    )
    return title


def _extract_author(html: str) -> str:
    """Extract author/account name from WeChat HTML.

    Looks for ``#js_name`` first, then ``.rich_media_meta_nickname``.
    """
    # <span class="profile_nickname"> or <a id="js_name" ...>
    # WeChat uses: <strong class="profile_nickname">Author</strong>
    # or: <a id="js_name" ...>Author</a>
    author = _extract_text_from_html(
        html,
        re.compile(r'<a[^>]*id\s*=\s*["\']js_name["\'][^>]*>', re.IGNORECASE),
    )
    if author:
        return author

    author = _extract_text_from_html(
        html,
        re.compile(r'<strong[^>]*class\s*=\s*["\'][^"\']*profile_nickname[^"\']*["\'][^>]*>', re.IGNORECASE),
    )
    if author:
        return author

    # Fallback: .rich_media_meta_nickname
    author = _extract_text_from_html(
        html,
        re.compile(r'<span[^>]*class\s*=\s*["\'][^"\']*rich_media_meta_nickname[^"\']*["\'][^>]*>', re.IGNORECASE),
    )
    return author


def _extract_publish_date(html: str) -> str:
    """Extract publish date from ``#publish_time``."""
    # <em id="publish_time">2024-01-15 10:30</em>
    date = _extract_text_from_html(
        html,
        re.compile(r'<em[^>]*id\s*=\s*["\']publish_time["\'][^>]*>', re.IGNORECASE),
    )
    return date


def _extract_content_html(html: str) -> str:
    """Extract the article body HTML from ``#js_content`` div.

    WeChat wraps all article content inside ``<div id="js_content">``.
    Returns the inner HTML of that div, or raises AdapterError if
    the content div is missing.
    """
    pattern = re.compile(
        r'<div[^>]*id\s*=\s*["\']js_content["\'][^>]*>',
        re.IGNORECASE,
    )
    m = pattern.search(html)
    if not m:
        return ""

    after_open = html[m.end():]
    # Find the matching </div>. WeChat content divs are top-level within
    # the article body, so we can do a simple search for the next close.
    # Use a balanced tag counter for robustness.
    depth = 1
    pos = 0
    while pos < len(after_open) and depth > 0:
        open_match = re.search(r"<div[\s>]", after_open[pos:], re.IGNORECASE)
        close_match = re.search(r"</div\s*>", after_open[pos:], re.IGNORECASE)

        if close_match is None:
            break

        if open_match and open_match.start() < close_match.start():
            depth += 1
            pos += open_match.end()
        else:
            depth -= 1
            if depth == 0:
                return after_open[:pos + close_match.start()]
            pos += close_match.end()

    return after_open if depth == 0 else ""


def _extract_images(content_html: str) -> list[str]:
    """Extract image URLs from article body HTML.

    Checks ``data-src`` first (WeChat's lazy-loading attribute), then
    falls back to ``src``.
    """
    images: list[str] = []
    seen: set[str] = set()

    for m in re.finditer(r"<img\s[^>]*>", content_html, re.IGNORECASE):
        tag = m.group(0)

        # Try data-src first (WeChat lazy loading)
        url = None
        ds = re.search(r'data-src\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
        if ds:
            url = ds.group(1)

        # Fallback to src
        if not url:
            sr = re.search(r'src\s*=\s*["\']([^"\']+)["\']', tag, re.IGNORECASE)
            if sr:
                url = sr.group(1)

        if url and url not in seen and not url.startswith("data:"):
            seen.add(url)
            images.append(url)

    return images


# ── Adapter ─────────────────────────────────────────────────────────


@register_adapter(_URL_PATTERN)
class WeChatAdapter:
    """Adapter for WeChat public account (微信公众号) article URLs.

    Fetches article content from ``mp.weixin.qq.com`` HTML pages and
    converts to Markdown. Handles WeChat's ``data-src`` lazy-loaded
    images and provides image URLs that require Referer headers for
    anti-hotlinking bypass.
    """

    source_type = "wechat"

    def fetch(self, url: str) -> RawContent:
        """Fetch a WeChat article and return parsed content.

        Parameters
        ----------
        url:
            A WeChat article URL (``mp.weixin.qq.com/s?...``).

        Returns
        -------
        RawContent
            Article content with a metadata header, Markdown body,
            and image URLs (may require Referer header for download).

        Raises
        ------
        AdapterError
            If the article cannot be fetched or the content div is
            missing from the HTML.
        """
        jsonl_emit_progress(
            message=f"Fetching WeChat article: {url[:80]}",
            stage="fetch",
            url=url,
        )

        headers = {
            "User-Agent": _DESKTOP_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        try:
            with httpx.Client(
                timeout=_TIMEOUT,
                follow_redirects=True,
                headers=headers,
            ) as client:
                resp = _http_get_with_retry(client, url, timeout=_TIMEOUT)
                html = resp.text
        except httpx.TimeoutException as exc:
            msg = f"WeChat article fetch timeout: {exc}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc
        except httpx.HTTPStatusError as exc:
            msg = f"WeChat article returned HTTP {exc.response.status_code}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"WeChat article fetch failed: {exc}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc

        # Extract structured content
        title = _extract_title(html)
        author = _extract_author(html)
        publish_date = _extract_publish_date(html)
        content_html = _extract_content_html(html)

        if not content_html:
            msg = "WeChat article HTML missing #js_content div"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg)

        # Convert body to Markdown
        content_md = md(content_html, strip=["script", "style"])

        # Extract images
        images = _extract_images(content_html)

        # Build metadata header
        header_parts = [
            f"> Source: {url}",
            f"> Clipped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if author:
            header_parts.append(f"> Author: {author}")
        if publish_date:
            header_parts.append(f"> Date: {publish_date}")

        header = "\n".join(header_parts)

        # Use extracted title, or fallback
        if not title:
            title = author or "WeChat Article"

        # Construct full markdown
        full_md = f"# {title}\n\n{header}\n\n---\n\n{content_md}"

        jsonl_emit_progress(
            message=f"WeChat fetch complete: {title[:50]}",
            stage="fetch",
            url=url,
            images=len(images),
        )

        if not author and not publish_date:
            jsonl_emit_warning(
                message="WeChat article missing author and date metadata",
                url=url,
            )

        return RawContent(
            url=url,
            title=title,
            content_md=full_md,
            images=images,
            source_type=self.source_type,
        )
