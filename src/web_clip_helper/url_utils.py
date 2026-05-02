"""URL normalization utilities for idempotent clip detection.

Provides minimal normalization (trailing-slash removal + http→https
scheme upgrade) so that equivalent URLs match in the SQLite index.
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

__all__ = ["normalize_url"]


def normalize_url(url: str) -> str:
    """Return a minimally-normalized form of *url*.

    Normalizations applied (order matters):

    1. Strip leading/trailing whitespace.
    2. Upgrade ``http`` scheme to ``https``.
    3. Remove trailing ``/`` from the path (root ``/`` becomes empty).

    These are **exact-match** normalizations only — no punycode,
    percent-encoding, or case folding beyond what urlparse already does.

    Parameters
    ----------
    url:
        Raw URL string.

    Returns
    -------
    str
        Normalized URL.

    Examples
    --------
    >>> normalize_url("http://example.com/article/")
    'https://example.com/article'
    >>> normalize_url("  https://example.com  ")
    'https://example.com'
    """
    url = url.strip()
    parsed = urlparse(url)

    # Upgrade http → https
    scheme = parsed.scheme
    if scheme == "http":
        scheme = "https"

    # Remove trailing slash from path (but keep root "/" as "/")
    path = parsed.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    return urlunparse(
        (
            scheme,
            parsed.netloc,
            path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )
