"""Weibo adapter — fetch Weibo posts via m.weibo.cn public API.

URL pattern: ``https?://(m\\.)?weibo\\.c(n|om)/.*``

Strategy:
1. Parse the URL to extract a numeric post ID (mid).
2. If the URL contains a Base62-encoded bid (e.g. ``weibo.com/{uid}/{bid}``),
   convert it to the numeric mid via Weibo's custom Base62 alphabet.
3. Call ``GET https://m.weibo.cn/statuses/show?id={mid}`` with a mobile
   User-Agent header.
4. Parse the JSON response: extract text (HTML), images (large URLs),
   author info, reposts/comments/likes counts, created_at.
5. Convert HTML text to Markdown using ``markdownify``.
6. Return a :class:`RawContent` with ``source_type="weibo"``.
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

__all__ = ["WeiboAdapter"]

# ── Configuration ───────────────────────────────────────────────────

_URL_PATTERN = r"https?://(m\.)?weibo\.c(n|om)/.*"
_TIMEOUT = 30.0
_MAX_RETRIES = 2
_BACKOFF_BASE = 1.0  # seconds

# Weibo's custom Base62 alphabet (not the standard 0-9A-Za-z)
_BASE62_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

# Mobile User-Agent to avoid desktop redirects
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.0 Mobile/15E148 Safari/604.1"
)


# ── Base62 bid→mid conversion ───────────────────────────────────────


def _bid_to_mid(bid: str) -> str:
    """Convert a Weibo Base62-encoded bid to a numeric mid string.

    Weibo uses a custom Base62 alphabet:
    ``0-9 a-z A-Z`` (different from the standard ``0-9 A-Z a-z``).

    The bid is split into 4-character chunks (except the first chunk
    which may be shorter) and each chunk is decoded independently,
    then concatenated.

    Parameters
    ----------
    bid:
        The Base62-encoded bid string (e.g. ``"ABCDE1"``).

    Returns
    -------
    str
        The numeric mid string (e.g. ``"1234567890"``).

    Raises
    ------
    AdapterError
        If the bid is empty or contains invalid characters.
    """
    if not bid or not bid.strip():
        raise AdapterError("Empty bid cannot be converted to mid")

    bid = bid.strip()

    # Validate characters
    valid_chars = set(_BASE62_ALPHABET)
    for ch in bid:
        if ch not in valid_chars:
            raise AdapterError(f"Invalid character {ch!r} in bid: {bid!r}")

    result_parts: list[str] = []

    # Weibo splits the bid into chunks: the first chunk is
    # len(bid) % 4 characters (if non-zero), then 4-char chunks.
    first_len = len(bid) % 4
    if first_len == 0 and len(bid) > 0:
        first_len = 4

    pos = 0
    first_chunk = True

    while pos < len(bid):
        if first_chunk:
            chunk = bid[pos : pos + first_len]
            pos += first_len
            first_chunk = False
        else:
            chunk = bid[pos : pos + 4]
            pos += 4

        # Decode this chunk from base62 to decimal
        value = 0
        for ch in chunk:
            value = value * 62 + _BASE62_ALPHABET.index(ch)

        result_parts.append(str(value))

    return "".join(result_parts)


# ── URL parsing ─────────────────────────────────────────────────────

# URL format patterns (order matters — more specific first)
_UID_BID_RE = re.compile(
    r"https?://(?:m\.)?weibo\.c(?:n|om)/(\d+)/([A-Za-z0-9]+)(?:\?.*)?$"
)
_M_STATUS_RE = re.compile(
    r"https?://m\.weibo\.cn/status/(\d+)"
)
_DETAIL_RE = re.compile(
    r"https?://(?:m\.)?weibo\.c(?:n|om)/detail/(\d+)"
)
_STATUSES_RE = re.compile(
    r"https?://(?:m\.)?weibo\.c(?:n|om)/statuses/(\d+)"
)
# Generic fallback: try to find any numeric ID in the URL path
_GENERIC_ID_RE = re.compile(
    r"https?://(?:m\.)?weibo\.c(?:n|om)/.*?/(\d{5,})"
)


def _parse_weibo_url(url: str) -> str:
    """Extract the numeric post ID (mid) from a Weibo URL.

    Supports these formats:
    - ``weibo.com/{uid}/{bid}`` — bid is Base62-encoded, converted to mid
    - ``m.weibo.cn/status/{id}`` — id directly
    - ``weibo.com/detail/{id}`` — id directly
    - ``weibo.com/statuses/{id}`` — id directly

    Parameters
    ----------
    url:
        A Weibo post URL.

    Returns
    -------
    str
        The numeric mid (post ID).

    Raises
    ------
    AdapterError
        If the URL does not contain a recognizable post ID.
    """
    url = url.strip()

    # m.weibo.cn/status/{id}
    m = _M_STATUS_RE.search(url)
    if m:
        return m.group(1)

    # weibo.com/detail/{id} or m.weibo.cn/detail/{id}
    m = _DETAIL_RE.search(url)
    if m:
        return m.group(1)

    # weibo.com/statuses/{id}
    m = _STATUSES_RE.search(url)
    if m:
        return m.group(1)

    # weibo.com/{uid}/{bid} — need bid→mid conversion
    m = _UID_BID_RE.search(url)
    if m:
        bid = m.group(2)
        # If the bid is purely numeric, it's already a mid
        if bid.isdigit():
            return bid
        return _bid_to_mid(bid)

    # Generic fallback: look for any long numeric ID
    m = _GENERIC_ID_RE.search(url)
    if m:
        return m.group(1)

    raise AdapterError(f"Cannot extract post ID from Weibo URL: {url!r}")


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


# ── Adapter ─────────────────────────────────────────────────────────


@register_adapter(_URL_PATTERN)
class WeiboAdapter:
    """Adapter for Weibo (微博) post URLs.

    Fetches post content via the m.weibo.cn public API and converts
    HTML text to Markdown. Extracts large image URLs from the ``pics``
    field in the API response.
    """

    source_type = "weibo"

    def fetch(self, url: str) -> RawContent:
        """Fetch a Weibo post and return parsed content.

        Parameters
        ----------
        url:
            A Weibo post URL in any supported format.

        Returns
        -------
        RawContent
            Post content with a metadata header, Markdown body,
            and large image URLs.

        Raises
        ------
        AdapterError
            If the post cannot be fetched or parsed.
        """
        mid = _parse_weibo_url(url)

        jsonl_emit_progress(
            message=f"Fetching Weibo post: mid={mid}",
            stage="fetch",
            url=url,
        )

        api_url = f"https://m.weibo.cn/statuses/show?id={mid}"
        headers = {
            "User-Agent": _MOBILE_UA,
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": url,
        }

        try:
            with httpx.Client(
                timeout=_TIMEOUT,
                follow_redirects=True,
                headers=headers,
            ) as client:
                resp = _http_get_with_retry(client, api_url, timeout=_TIMEOUT)
                data = resp.json()
        except httpx.TimeoutException as exc:
            msg = f"Weibo API timeout for mid={mid}: {exc}"
            raise AdapterError(msg, error_code="FETCH_ERROR", url=url) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            msg = f"Weibo API returned HTTP {status} for mid={mid}"
            code = "NOT_FOUND" if status in (404, 410) else "FETCH_ERROR"
            raise AdapterError(msg, error_code=code, url=url) from exc
        except httpx.RequestError as exc:
            msg = f"Weibo API request failed for mid={mid}: {exc}"
            raise AdapterError(msg, error_code="FETCH_ERROR", url=url) from exc

        # Validate response structure
        if not isinstance(data, dict):
            msg = f"Weibo API returned non-object response for mid={mid}"
            raise AdapterError(msg, error_code="PARSE_ERROR", url=url)

        # Check for API-level errors
        if data.get("ok") == 0 or "data" not in data:
            error_msg = data.get("msg", "unknown error")
            msg = f"Weibo API error for mid={mid}: {error_msg}"
            raise AdapterError(msg, error_code="NOT_FOUND", url=url)

        status = data.get("data", {})
        if not status:
            msg = f"Weibo API returned empty data for mid={mid}"
            raise AdapterError(msg, error_code="PARSE_ERROR", url=url)

        # Extract content
        text_html = status.get("text", "")
        content_md = md(text_html, strip=["script", "style"]) if text_html else ""

        # Extract large image URLs from pics field
        images = self._extract_images(status)

        # Build metadata
        user = status.get("user", {}) or {}
        author = user.get("screen_name", "")
        created_at = status.get("created_at", "")
        reposts_count = status.get("reposts_count", 0)
        comments_count = status.get("comments_count", 0)
        attitudes_count = status.get("attitudes_count", 0)

        header_parts = [
            f"> Source: {url}",
            f"> Clipped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if author:
            header_parts.append(f"> Author: {author}")
        if created_at:
            header_parts.append(f"> Date: {created_at}")
        header_parts.append(
            f"> Stats: {reposts_count} reposts, {comments_count} comments, {attitudes_count} likes"
        )

        header = "\n".join(header_parts)

        # Use page title or first line of content as title
        title_status = status.get("status_title", "")
        title = title_status or author or f"Weibo post {mid}"

        # Construct full markdown
        full_md = f"{header}\n\n---\n\n{content_md}" if content_md else header

        jsonl_emit_progress(
            message=f"Weibo fetch complete: mid={mid}",
            stage="fetch",
            url=url,
            images=len(images),
        )

        return RawContent(
            url=url,
            title=title,
            content_md=full_md,
            images=images,
            source_type=self.source_type,
            is_dynamic=True,
        )

    @staticmethod
    def _extract_images(status: dict) -> list[str]:
        """Extract large image URLs from a Weibo API status object.

        Looks for ``pics`` list with ``large.url`` entries. Falls back
        to ``url`` if ``large`` is not available.

        Parameters
        ----------
        status:
            The ``data`` field from the m.weibo.cn API response.

        Returns
        -------
        list[str]
            Large image URLs extracted from the post.
        """
        images: list[str] = []
        pics = status.get("pics")
        if not pics or not isinstance(pics, list):
            return images

        for pic in pics:
            if not isinstance(pic, dict):
                continue
            # Prefer large image URL
            large = pic.get("large")
            if isinstance(large, dict) and large.get("url"):
                images.append(large["url"])
            elif pic.get("url"):
                images.append(pic["url"])

        return images
