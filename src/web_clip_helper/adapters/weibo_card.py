"""Weibo Card (card.weibo.com/article) adapter — fetch Weibo long-form articles.

URL pattern: ``https?://card\\.weibo\\.com/article/.*``

These are long-form articles hosted at ``card.weibo.com/article/m/show/id/*``.
The page is a JavaScript SPA that loads article content via an AJAX API
endpoint at ``weibo.com/ttarticle/x/m/aj/detail?id={article_id}``.

Strategy:
1. Parse the article ID from the URL path.
2. Fetch article JSON from the mobile API endpoint.
3. Extract title, author (from userinfo), date, and HTML body from JSON.
4. Convert the body HTML to Markdown using ``markdownify``.
5. Extract image URLs from ``<img>`` tags inside the content area.
6. Build a metadata header with source, date, and author.
7. Return a :class:`RawContent` with ``source_type="weibo_card"``.

Registration order:
    This adapter **must** be registered BEFORE the generic WeiboAdapter
    because ``card.weibo.com`` contains ``weibo.com`` which would be
    matched by the broad ``weibo.c(n|om)/.*`` pattern first.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import httpx
from markdownify import markdownify as md

from ..adapter import AdapterError, register_adapter
from ..models import RawContent
from ..output import jsonl_emit_error, jsonl_emit_progress, jsonl_emit_warning

__all__ = ["WeiboCardAdapter"]

# ── Configuration ───────────────────────────────────────────────────

_URL_PATTERN = r"https?://card\.weibo\.com/article/.*"
_API_BASE = "https://weibo.com/ttarticle/x/m/aj/detail"
_TIMEOUT = 30.0
_MAX_RETRIES = 2
_BACKOFF_BASE = 1.0  # seconds

_DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Regex to extract article ID from URL paths like:
#   card.weibo.com/article/m/show/id/2309405287021303431221
_ARTICLE_ID_RE = re.compile(r"/article/m/show/id/(\d+)", re.IGNORECASE)


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


# ── ID extraction ───────────────────────────────────────────────────


def _extract_article_id(url: str) -> str:
    """Extract the numeric article ID from a card.weibo.com URL.

    Returns the ID string, or raises AdapterError if not found.
    """
    m = _ARTICLE_ID_RE.search(url)
    if m:
        return m.group(1)
    raise AdapterError(f"Cannot extract article ID from URL: {url}")


# ── Image extraction ────────────────────────────────────────────────


def _extract_images(content_html: str) -> list[str]:
    """Extract image URLs from article body HTML.

    Checks ``data-src`` first (lazy-loading), then ``src``.
    Skips ``data:`` URIs.
    """
    images: list[str] = []
    seen: set[str] = set()

    for m in re.finditer(r"<img\s[^>]*>", content_html, re.IGNORECASE):
        tag = m.group(0)

        # Try data-src first (lazy loading)
        url: str | None = None
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
class WeiboCardAdapter:
    """Adapter for Weibo Card (card.weibo.com/article) article URLs.

    Fetches long-form article content from Weibo's card article URLs
    via the mobile API endpoint. Converts to Markdown with metadata.
    """

    source_type = "weibo_card"

    def fetch(self, url: str) -> RawContent:
        """Fetch a Weibo Card article and return parsed content.

        Parameters
        ----------
        url:
            A Weibo Card article URL
            (``card.weibo.com/article/m/show/id/...``).

        Returns
        -------
        RawContent
            Article content with a metadata header, Markdown body,
            and image URLs.

        Raises
        ------
        AdapterError
            If the article cannot be fetched, the API returns an error,
            or the content is missing.
        """
        jsonl_emit_progress(
            message=f"Fetching Weibo Card article: {url[:80]}",
            stage="fetch",
            url=url,
        )

        # Extract article ID from URL
        try:
            article_id = _extract_article_id(url)
        except AdapterError:
            msg = f"Cannot extract article ID from URL: {url}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise

        api_url = f"{_API_BASE}?id={article_id}"

        headers = {
            "User-Agent": _DESKTOP_UA,
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": url,
        }

        # Fetch article data from API
        try:
            with httpx.Client(
                timeout=_TIMEOUT,
                follow_redirects=True,
                headers=headers,
            ) as client:
                resp = _http_get_with_retry(client, api_url, timeout=_TIMEOUT)
                data = resp.json()
        except httpx.TimeoutException as exc:
            msg = f"Weibo Card fetch timeout: {exc}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc
        except httpx.HTTPStatusError as exc:
            msg = f"Weibo Card API returned HTTP {exc.response.status_code}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"Weibo Card fetch failed: {exc}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc
        except (ValueError, KeyError) as exc:
            msg = f"Weibo Card API returned invalid JSON: {exc}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc

        # Check API response code (string or int — Weibo returns "100000" as string)
        api_code = data.get("code")
        if str(api_code) != "100000":
            msg = f"Weibo Card API error: code={api_code}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg)

        article = data.get("data", data)

        # Extract structured content
        title = (article.get("title") or "").strip()
        content_html = (article.get("content") or "").strip()

        if not content_html:
            msg = "Weibo Card article missing content"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg)

        # Author from userinfo
        userinfo = article.get("userinfo", {})
        author = ""
        if isinstance(userinfo, dict):
            author = (userinfo.get("screen_name") or "").strip()

        # Date
        publish_date = (article.get("complete_create_at") or "").strip()
        if not publish_date:
            publish_date = (article.get("create_at") or "").strip()

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
            title = "Weibo Card Article"

        # Construct full markdown
        full_md = f"# {title}\n\n{header}\n\n---\n\n{content_md}"

        jsonl_emit_progress(
            message=f"Weibo Card fetch complete: {title[:50]}",
            stage="fetch",
            url=url,
            images=len(images),
        )

        if not author and not publish_date:
            jsonl_emit_warning(
                message="Weibo Card article missing author and date metadata",
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
