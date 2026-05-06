"""Weibo Headline (头条文章) adapter — fetch long-form Weibo articles.

URL pattern: ``https?://(m\\.)?weibo\\.c(n|om)/ttarticle/.*``

These are long-form articles hosted on the Weibo platform at URLs like
``https://weibo.com/ttarticle/p/show?id=230940...``. They differ from
regular Weibo posts in that the content is a full article with title,
author, and rich HTML body — not a short post.

Strategy:
1. Fetch the article HTML page with a desktop User-Agent.
2. Extract the title from ``<h1>`` or ``.article-title`` elements.
3. Extract the author from ``.author-name`` or similar selectors.
4. Extract the publish date from ``.article-time`` or ``<time>``.
5. Extract the article body from ``.article-content`` or ``#articlecontent``
   (Weibo Headline's main content containers).
6. Convert the body HTML to Markdown using ``markdownify``.
7. Extract image URLs from ``<img>`` tags inside the content area.
8. Build a metadata header with source, date, and author.
9. Return a :class:`RawContent` with ``source_type="weibo_headline"``.

Registration order:
    This adapter **must** be registered BEFORE the generic WeiboAdapter
    because its URL pattern (``/ttarticle/``) is more specific and
    would otherwise be shadowed by the broad ``weibo.c(n|om)/.*`` pattern.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import httpx
from markdownify import markdownify as md

from .base import AdapterError, register_adapter
from ..models import RawContent
from ..output import jsonl_emit_progress, jsonl_emit_warning

__all__ = ["WeiboHeadlineAdapter"]

# ── Configuration ───────────────────────────────────────────────────

# More specific than generic Weibo pattern — must be registered first.
_URL_PATTERN = r"https?://(m\.)?weibo\.c(n|om)/ttarticle/.*"
_TIMEOUT = 30.0
_MAX_RETRIES = 2
_BACKOFF_BASE = 1.0  # seconds

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


def _extract_text_from_tag(html: str, pattern: re.Pattern[str]) -> str:
    """Extract inner text from the first HTML tag matching *pattern*.

    Handles simple opening tags with attributes. Returns the stripped
    text content, or an empty string if no match.
    """
    m = pattern.search(html)
    if not m:
        return ""
    tag_text = m.group(0)
    tag_name_match = re.match(r"<(\w+)", tag_text)
    if not tag_name_match:
        return ""
    tag_name = tag_name_match.group(1)

    after_open = html[m.end():]
    close_tag = f"</{tag_name}>"
    close_idx = after_open.find(close_tag)
    if close_idx == -1:
        return ""
    return after_open[:close_idx].strip()


def _extract_title(html: str) -> str:
    """Extract article title from Weibo Headline HTML.

    Looks for ``<h1>`` inside an article header area, then falls back
    to the ``<title>`` tag with site name stripped.
    """
    # <h1 class="article-title">Title</h1>
    title = _extract_text_from_tag(
        html,
        re.compile(
            r'<h1[^>]*class\s*=\s*["\'][^"\']*article-title[^"\']*["\'][^>]*>',
            re.IGNORECASE,
        ),
    )
    if title:
        return title

    # Generic <h1>
    title = _extract_text_from_tag(
        html,
        re.compile(r"<h1[^>]*>", re.IGNORECASE),
    )
    if title:
        return title

    # Fallback: <title> tag — strip "– 头条文章" or similar suffixes
    title = _extract_text_from_tag(
        html,
        re.compile(r"<title[^>]*>", re.IGNORECASE),
    )
    if title:
        # Remove common suffixes like "– weibo.com" or "_头条文章"
        title = re.split(r"\s*[–\-_|]\s*(?:weibo|微博|头条)", title, flags=re.IGNORECASE)[0]
        title = title.strip()
    return title


def _extract_author(html: str) -> str:
    """Extract author name from Weibo Headline HTML.

    Looks for common author container selectors.
    """
    # <span class="author-name">Author</span> or similar
    author = _extract_text_from_tag(
        html,
        re.compile(
            r'<(?:span|a|div)[^>]*class\s*=\s*["\'][^"\']*author[^"\']*["\'][^>]*>',
            re.IGNORECASE,
        ),
    )
    if author:
        return author

    # <meta name="author" content="...">
    m = re.search(
        r'<meta[^>]*name\s*=\s*["\']author["\'][^>]*content\s*=\s*["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    # Also try content before name attribute
    m = re.search(
        r'<meta[^>]*content\s*=\s*["\']([^"\']+)["\'][^>]*name\s*=\s*["\']author["\']',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    return ""


def _extract_publish_date(html: str) -> str:
    """Extract publish date from Weibo Headline HTML."""
    # <time> tag or class-based selectors
    date = _extract_text_from_tag(
        html,
        re.compile(
            r'<(?:span|time|div)[^>]*class\s*=\s*["\'][^"\']*(?:article-time|pub-time|date|time)[^"\']*["\'][^>]*>',
            re.IGNORECASE,
        ),
    )
    if date:
        return date

    # <time datetime="...">
    m = re.search(
        r'<time[^>]*datetime\s*=\s*["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()

    return ""


def _extract_content_html(html: str) -> str:
    """Extract the article body HTML from the content container.

    Weibo Headline articles use ``#articlecontent`` or ``.article-content``
    as the main content container. Falls back to ``<article>`` tag.

    Returns the inner HTML, or an empty string if no container is found.
    """
    # Try #articlecontent
    content = _extract_div_content(html, "articlecontent")
    if content:
        return content

    # Try .article-content
    content = _extract_div_by_class(html, "article-content")
    if content:
        return content

    # Fallback: <article> tag
    content = _extract_div_content(html, None, tag="article")
    if content:
        return content

    return ""


def _extract_div_content(
    html: str,
    div_id: str | None,
    tag: str = "div",
) -> str:
    """Extract inner HTML from a container matched by ID."""
    if div_id:
        pattern = re.compile(
            rf'<{tag}[^>]*id\s*=\s*["\']' + re.escape(div_id) + r'["\'][^>]*>',
            re.IGNORECASE,
        )
    else:
        pattern = re.compile(rf"<{tag}[^>]*>", re.IGNORECASE)

    m = pattern.search(html)
    if not m:
        return ""

    after_open = html[m.end():]
    close_tag = f"</{tag}>"
    depth = 1
    pos = 0
    open_re = re.compile(rf"<{tag}[\s>]", re.IGNORECASE)
    close_re = re.compile(rf"</{tag}\s*>", re.IGNORECASE)

    while pos < len(after_open) and depth > 0:
        open_match = open_re.search(after_open[pos:])
        close_match = close_re.search(after_open[pos:])

        if close_match is None:
            break

        if open_match and open_match.start() < close_match.start():
            depth += 1
            pos += open_match.end()
        else:
            depth -= 1
            if depth == 0:
                return after_open[: pos + close_match.start()]
            pos += close_match.end()

    return after_open if depth == 0 else ""


def _extract_div_by_class(html: str, class_name: str) -> str:
    """Extract inner HTML from a ``<div>`` matched by class name."""
    pattern = re.compile(
        rf'<div[^>]*class\s*=\s*["\'][^"\']*'
        + re.escape(class_name)
        + r'[^"\']*["\'][^>]*>',
        re.IGNORECASE,
    )
    m = pattern.search(html)
    if not m:
        return ""

    after_open = html[m.end():]
    depth = 1
    pos = 0
    open_re = re.compile(r"<div[\s>]", re.IGNORECASE)
    close_re = re.compile(r"</div\s*>", re.IGNORECASE)

    while pos < len(after_open) and depth > 0:
        open_match = open_re.search(after_open[pos:])
        close_match = close_re.search(after_open[pos:])

        if close_match is None:
            break

        if open_match and open_match.start() < close_match.start():
            depth += 1
            pos += open_match.end()
        else:
            depth -= 1
            if depth == 0:
                return after_open[: pos + close_match.start()]
            pos += close_match.end()

    return after_open if depth == 0 else ""


def _extract_images(content_html: str) -> list[str]:
    """Extract image URLs from article body HTML.

    Checks ``data-src`` first (lazy-loading), then ``src``.
    """
    images: list[str] = []
    seen: set[str] = set()

    for m in re.finditer(r"<img\s[^>]*>", content_html, re.IGNORECASE):
        tag = m.group(0)

        # Try data-src first (lazy loading)
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
class WeiboHeadlineAdapter:
    """Adapter for Weibo Headline (头条文章) article URLs.

    Fetches long-form article content from Weibo's ``/ttarticle/`` URLs
    and converts to Markdown. Handles Weibo Headline's HTML structure
    including article title, author, publish date, and images.
    """

    source_type = "weibo_headline"

    def fetch(self, url: str) -> RawContent:
        """Fetch a Weibo Headline article and return parsed content.

        Parameters
        ----------
        url:
            A Weibo Headline article URL
            (``weibo.com/ttarticle/p/show?id=...``).

        Returns
        -------
        RawContent
            Article content with a metadata header, Markdown body,
            and image URLs.

        Raises
        ------
        AdapterError
            If the article cannot be fetched or the content container
            is missing from the HTML.
        """
        jsonl_emit_progress(
            message=f"Fetching Weibo Headline article: {url[:80]}",
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
            msg = f"Weibo Headline fetch timeout: {exc}"
            raise AdapterError(msg, error_code="FETCH_ERROR", url=url) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            msg = f"Weibo Headline returned HTTP {status}"
            code = "NOT_FOUND" if status in (404, 410) else "FETCH_ERROR"
            raise AdapterError(msg, error_code=code, url=url) from exc
        except httpx.RequestError as exc:
            msg = f"Weibo Headline fetch failed: {exc}"
            raise AdapterError(msg, error_code="FETCH_ERROR", url=url) from exc

        # Extract structured content
        title = _extract_title(html)
        author = _extract_author(html)
        publish_date = _extract_publish_date(html)
        content_html = _extract_content_html(html)

        if not content_html:
            msg = "Weibo Headline HTML missing content container"
            raise AdapterError(msg, error_code="PARSE_ERROR", url=url)

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
            title = "Weibo Headline Article"

        # Construct full markdown
        full_md = f"# {title}\n\n{header}\n\n---\n\n{content_md}"

        jsonl_emit_progress(
            message=f"Weibo Headline fetch complete: {title[:50]}",
            stage="fetch",
            url=url,
            images=len(images),
        )

        if not author and not publish_date:
            jsonl_emit_warning(
                message="Weibo Headline article missing author and date metadata",
                url=url,
            )

        return RawContent(
            url=url,
            title=title,
            content_md=full_md,
            images=images,
            source_type=self.source_type,
            is_dynamic=True,
        )
