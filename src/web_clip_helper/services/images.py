"""Image downloader — download images with retry, referer, and extension detection.

Downloads images to ``<target_dir>/images/img_NNN.<ext>``.  Returns a mapping
of original_url → local_path (or original_url on failure).
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

import httpx

from web_clip_helper.output import jsonl_emit_warning

__all__ = ["download_images"]

# Timeouts and retry config
_TIMEOUT = 30.0
_MAX_RETRIES = 2
_BACKOFF_BASE = 1.0  # seconds

# Extension from Content-Type mapping
_EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/avif": ".avif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


def _detect_extension(content_type: str | None, url: str) -> str:
    """Determine file extension from Content-Type header or URL path."""
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        ext = _EXT_MAP.get(ct)
        if ext:
            return ext

    # Fall back to URL path
    url_path = url.rsplit("?", 1)[0]  # strip query string
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif", ".bmp", ".tiff"):
        if url_path.lower().endswith(ext):
            return ext if ext != ".jpeg" else ".jpg"

    return ".jpg"


def download_images(
    urls: list[str],
    target_dir: Path,
    referer: str | None = None,
) -> dict[str, str]:
    """Download images and return an original_url → local_path mapping.

    Parameters
    ----------
    urls:
        List of image URLs to download.
    target_dir:
        Directory to save images into (will be created if needed).
    referer:
        Optional Referer header for anti-hotlinking bypass.

    Returns
    -------
    dict[str, str]
        Mapping of original URL → local relative path (or original URL on
        failure).
    """
    if not urls:
        return {}

    target_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_urls: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique_urls.append(url)

    headers: dict[str, str] = {}
    if referer:
        headers["Referer"] = referer

    img_index = 0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for url in unique_urls:
            img_index += 1
            success = False

            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    response = client.get(url, headers=headers)
                    response.raise_for_status()

                    content_type = response.headers.get("content-type")
                    ext = _detect_extension(content_type, url)
                    filename = f"img_{img_index:03d}{ext}"
                    local_path = target_dir / filename

                    local_path.write_bytes(response.content)

                    # Use relative path from the parent of images/
                    rel_path = f"images/{filename}"
                    mapping[url] = rel_path
                    success = True
                    break

                except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.RequestError) as exc:
                    if attempt < _MAX_RETRIES:
                        import time
                        time.sleep(_BACKOFF_BASE * (2 ** (attempt - 1)))
                        continue

                    # Final attempt failed
                    jsonl_emit_warning(
                        message=f"Image download failed: {url}",
                        url=url,
                        error=str(exc),
                    )

            if not success:
                mapping[url] = url

    return mapping
