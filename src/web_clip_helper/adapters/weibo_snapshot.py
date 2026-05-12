"""Weibo Snapshot (mapp.api.weibo.cn/fx) adapter — resolve redirect to extract post content.

URL pattern: ``https?://mapp\\.api\\.weibo\\.cn/fx/.*``

These short snapshot URLs return a 302 redirect to the canonical post URL
(e.g. ``https://m.weibo.cn/status/{mid}``). The adapter extracts the mid
from the redirect Location header, then fetches content via the same
``m.weibo.cn/statuses/show`` API used by :class:`WeiboAdapter`.

Strategy:
1. GET the snapshot URL with ``allow_redirects=False`` to capture the 302.
2. Extract the numeric post ID (mid) from the ``Location`` header.
3. Call ``GET https://m.weibo.cn/statuses/show?id={mid}`` with a mobile UA.
4. Parse JSON, extract text/images/metadata, convert HTML → Markdown.
5. Return a :class:`RawContent` with ``source_type="weibo_snapshot"``.

Registration order:
    This adapter must be registered BEFORE WeiboAdapter because the
    snapshot URL does not match the ``weibo.c(n|om)`` pattern, but we
    still want predictable ordering in the router.
"""

from __future__ import annotations

import re
from datetime import datetime

import httpx
from markdownify import markdownify as md

from ..adapter import AdapterError, register_adapter
from ..models import RawContent
from ..output import jsonl_emit_error, jsonl_emit_progress
from .weibo import WeiboAdapter

__all__ = ["WeiboSnapshotAdapter"]

# ── Configuration ───────────────────────────────────────────────────

_URL_PATTERN = r"https?://mapp\.api\.weibo\.cn/fx/.*"
_TIMEOUT = 30.0

# Mobile User-Agent for the redirect request
_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.0 Mobile/15E148 Safari/604.1"
)

# Regex to extract mid from redirect Location like:
#   https://m.weibo.cn/status/1234567890 or /status/1234567890
_MID_FROM_LOCATION_RE = re.compile(r"/status/(\d+)")


# ── Adapter ─────────────────────────────────────────────────────────


@register_adapter(_URL_PATTERN)
class WeiboSnapshotAdapter:
    """Adapter for Weibo snapshot URLs (``mapp.api.weibo.cn/fx/...``).

    Resolves the 302 redirect to extract the canonical post mid, then
    delegates content fetching to the same Weibo API used by
    :class:`WeiboAdapter`.
    """

    source_type = "weibo_snapshot"

    def fetch(self, url: str) -> RawContent:
        """Fetch a Weibo snapshot URL and return parsed content.

        Parameters
        ----------
        url:
            A Weibo snapshot URL (``mapp.api.weibo.cn/fx/{hash}.html``).

        Returns
        -------
        RawContent
            Post content with metadata header, Markdown body, and
            image URLs.

        Raises
        ------
        AdapterError
            If the snapshot URL does not redirect, the mid cannot be
            extracted, or the API call fails.
        """
        jsonl_emit_progress(
            message=f"Resolving Weibo snapshot redirect: {url[:80]}",
            stage="fetch",
            url=url,
        )

        # Step 1: GET snapshot URL without following redirects
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
                resp = client.get(url, headers={"User-Agent": _MOBILE_UA})
        except httpx.TimeoutException as exc:
            msg = f"Weibo snapshot redirect resolution timeout: {exc}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"Weibo snapshot redirect request failed: {exc}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc

        # Step 2: Expect a 302 redirect
        if resp.status_code != 302:
            msg = f"快照链接未返回预期的 redirect (got HTTP {resp.status_code})"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg)

        location = resp.headers.get("Location", "")
        if not location:
            msg = "快照 redirect 响应缺少 Location header"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg)

        # Step 3: Extract mid from Location header
        m = _MID_FROM_LOCATION_RE.search(location)
        if not m:
            msg = f"无法从快照 redirect 中提取帖子 ID: {location!r}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg)

        mid = m.group(1)

        jsonl_emit_progress(
            message=f"Snapshot redirect resolved: mid={mid}",
            stage="fetch",
            url=url,
        )

        # Step 4: Fetch content via Weibo API (same endpoint as WeiboAdapter)
        api_url = f"https://m.weibo.cn/statuses/show?id={mid}"
        headers = {
            "User-Agent": _MOBILE_UA,
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": url,
        }

        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=True, headers=headers) as client:
                resp = client.get(api_url, timeout=_TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as exc:
            msg = f"Weibo API timeout for mid={mid}: {exc}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc
        except httpx.HTTPStatusError as exc:
            msg = f"Weibo API returned HTTP {exc.response.status_code} for mid={mid}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"Weibo API request failed for mid={mid}: {exc}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg) from exc

        # Step 5: Parse response
        if not isinstance(data, dict):
            msg = f"Weibo API returned non-object response for mid={mid}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg)

        if data.get("ok") == 0 or "data" not in data:
            error_msg = data.get("msg", "unknown error")
            msg = f"Weibo API error for mid={mid}: {error_msg}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg)

        status = data.get("data", {})
        if not status:
            msg = f"Weibo API returned empty data for mid={mid}"
            jsonl_emit_error(stage="fetch", detail=msg, url=url)
            raise AdapterError(msg)

        # Extract content — reuse WeiboAdapter._extract_images for consistency
        text_html = status.get("text", "")
        content_md = md(text_html, strip=["script", "style"]) if text_html else ""
        images = WeiboAdapter._extract_images(status)

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

        title_status = status.get("status_title", "")
        title = title_status or author or f"Weibo post {mid}"

        full_md = f"{header}\n\n---\n\n{content_md}" if content_md else header

        jsonl_emit_progress(
            message=f"Weibo snapshot fetch complete: mid={mid}",
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
