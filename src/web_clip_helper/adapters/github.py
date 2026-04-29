"""GitHub adapter — fetch README and metadata from GitHub repositories.

URL pattern: ``https?://github\\.com/[^/]+/[^/]+``

Strategy:
1. Extract owner/repo from the URL.
2. Fetch README via raw.githubusercontent.com — try ``main`` then ``master``.
3. Fetch repo metadata from the GitHub API (description, stars, topics).
4. Extract image URLs from the README markdown.
5. Return a :class:`RawContent` with ``source_type="github"``.
"""

from __future__ import annotations

import re
import time
from datetime import datetime

import httpx

from ..adapter import AdapterError, register_adapter
from ..models import RawContent
from ..output import jsonl_emit_error, jsonl_emit_progress, jsonl_emit_warning

__all__ = ["GitHubAdapter"]

# ── Configuration ───────────────────────────────────────────────────

_URL_PATTERN = r"https?://github\.com/[^/]+/[^/]+"
_TIMEOUT = 30.0
_MAX_RETRIES = 2
_BACKOFF_BASE = 1.0  # seconds
_BRANCHES_TO_TRY = ("main", "master")
_README_VARIANTS = ("README.md", "readme.md")

# Regex to extract image URLs from markdown: ![alt](url) or <img src="url">
_IMG_MD_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
_IMG_HTML_RE = re.compile(r'<img\s[^>]*src=["\']([^"\']+)["\']', re.IGNORECASE)


def _extract_image_urls(markdown: str) -> list[str]:
    """Extract image URLs from markdown content (both MD and HTML img syntax)."""
    urls: list[str] = []
    seen: set[str] = set()
    for match in _IMG_MD_RE.finditer(markdown):
        url = match.group(1)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    for match in _IMG_HTML_RE.finditer(markdown):
        url = match.group(1)
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _parse_owner_repo(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL like https://github.com/owner/repo."""
    # Strip trailing slashes and remove query string / fragment
    clean = url.rstrip("/").split("?")[0].split("#")[0]
    parts = clean.split("/")
    # https: / / github.com / owner / repo
    if len(parts) < 5:
        raise AdapterError(f"Cannot parse owner/repo from GitHub URL: {url}")
    owner = parts[3]
    repo = parts[4]
    if not owner or not repo:
        raise AdapterError(f"Cannot parse owner/repo from GitHub URL: {url}")
    # Remove .git suffix if present
    if repo.endswith(".git"):
        repo = repo[:-4]
    return owner, repo


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


@register_adapter(_URL_PATTERN)
class GitHubAdapter:
    """Adapter for GitHub repository URLs.

    Fetches README.md content and repository metadata (description,
    stars, topics) and returns a :class:`RawContent` with
    ``source_type="github"``.
    """

    source_type = "github"

    def fetch(self, url: str) -> RawContent:
        """Fetch a GitHub repository's README and metadata.

        Parameters
        ----------
        url:
            A GitHub repository URL (e.g. ``https://github.com/owner/repo``).

        Returns
        -------
        RawContent
            README content with a metadata header prepended.

        Raises
        ------
        AdapterError
            If the README cannot be fetched from any branch.
        """
        owner, repo = _parse_owner_repo(url)

        jsonl_emit_progress(
            message=f"Fetching GitHub repo: {owner}/{repo}",
            stage="fetch",
            url=url,
        )

        readme_content = self._fetch_readme(owner, repo)
        metadata = self._fetch_metadata(owner, repo)

        # Build final markdown with metadata header
        header_parts = [
            f"> Source: {url}",
            f"> Clipped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if metadata.get("description"):
            header_parts.append(f"> Description: {metadata['description']}")
        if metadata.get("stars") is not None:
            header_parts.append(f"> Stars: {metadata['stars']}")
        if metadata.get("topics"):
            header_parts.append(f"> Topics: {', '.join(metadata['topics'])}")

        header = "\n".join(header_parts)
        content_md = f"{header}\n\n---\n\n{readme_content}"

        images = _extract_image_urls(readme_content)

        title = metadata.get("description") or f"{owner}/{repo}"

        jsonl_emit_progress(
            message=f"GitHub fetch complete: {owner}/{repo}",
            stage="fetch",
            url=url,
            images=len(images),
        )

        return RawContent(
            url=url,
            title=title,
            content_md=content_md,
            images=images,
            source_type=self.source_type,
        )

    def _fetch_readme(self, owner: str, repo: str) -> str:
        """Fetch README content from raw.githubusercontent.com.

        Tries branch names in order (main, master) and filename
        variants (README.md, readme.md).
        """
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            for branch in _BRANCHES_TO_TRY:
                for variant in _README_VARIANTS:
                    raw_url = (
                        f"https://raw.githubusercontent.com/{owner}/{repo}"
                        f"/{branch}/{variant}"
                    )
                    jsonl_emit_progress(
                        message=f"Trying {branch}/{variant}",
                        stage="fetch",
                        url=raw_url,
                    )
                    try:
                        resp = client.get(raw_url, timeout=_TIMEOUT)
                        if resp.status_code == 200:
                            return resp.text
                    except (httpx.TimeoutException, httpx.RequestError):
                        continue

        # If we get here, no README was found
        msg = (
            f"Cannot fetch README for {owner}/{repo}: "
            f"tried branches {_BRANCHES_TO_TRY} "
            f"and variants {_README_VARIANTS}"
        )
        jsonl_emit_error(stage="fetch", detail=msg, url=f"https://github.com/{owner}/{repo}")
        raise AdapterError(msg)

    def _fetch_metadata(self, owner: str, repo: str) -> dict[str, object]:
        """Fetch repo metadata from the GitHub API.

        Returns a dict with keys: description, stars, topics.
        On failure, returns an empty dict (non-fatal).
        """
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(api_url, timeout=_TIMEOUT)
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "description": data.get("description", ""),
                        "stars": data.get("stargazers_count", 0),
                        "topics": data.get("topics", []),
                    }
                else:
                    jsonl_emit_warning(
                        message=f"GitHub API returned {resp.status_code} for {owner}/{repo}",
                        url=api_url,
                        status_code=resp.status_code,
                    )
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            jsonl_emit_warning(
                message=f"GitHub API request failed for {owner}/{repo}: {exc}",
                url=api_url,
                error=str(exc),
            )
        return {}
