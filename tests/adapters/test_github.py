"""Tests for the GitHub adapter — URL pattern, README fetch, metadata, images."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from web_clip_helper.adapter import AdapterError, adapter_router, route_url
from web_clip_helper.adapters.github import (
    GitHubAdapter,
    _extract_image_urls,
    _parse_owner_repo,
)
from web_clip_helper.models import RawContent


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_router():
    """Preserve/restore global router state."""
    saved = adapter_router.copy()
    adapter_router.clear()
    yield
    adapter_router.clear()
    adapter_router.extend(saved)


def _mock_response(
    status_code: int = 200,
    text: str = "",
    json_data: dict | None = None,
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data or {}
    resp.headers = {"content-type": "text/plain; charset=utf-8"}

    def raise_for_status():
        if status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{status_code}",
                request=MagicMock(),
                response=resp,
            )

    resp.raise_for_status = raise_for_status
    return resp


# ── URL parsing ─────────────────────────────────────────────────────


class TestParseOwnerRepo:
    def test_standard_url(self):
        owner, repo = _parse_owner_repo("https://github.com/pallets/flask")
        assert owner == "pallets"
        assert repo == "flask"

    def test_url_with_trailing_slash(self):
        owner, repo = _parse_owner_repo("https://github.com/pallets/flask/")
        assert owner == "pallets"
        assert repo == "flask"

    def test_url_with_git_suffix(self):
        owner, repo = _parse_owner_repo("https://github.com/pallets/flask.git")
        assert owner == "pallets"
        assert repo == "flask"

    def test_url_with_query_string(self):
        owner, repo = _parse_owner_repo("https://github.com/owner/repo?tab=readme")
        assert owner == "owner"
        assert repo == "repo"

    def test_url_with_fragment(self):
        owner, repo = _parse_owner_repo("https://github.com/owner/repo#readme")
        assert owner == "owner"
        assert repo == "repo"

    def test_url_with_subpath(self):
        """Sub-paths after owner/repo should still extract correctly."""
        owner, repo = _parse_owner_repo("https://github.com/owner/repo/issues/123")
        assert owner == "owner"
        assert repo == "repo"

    def test_invalid_url_too_short(self):
        with pytest.raises(AdapterError, match="Cannot parse"):
            _parse_owner_repo("https://github.com/")

    def test_invalid_url_empty_owner(self):
        with pytest.raises(AdapterError, match="Cannot parse"):
            _parse_owner_repo("https://github.com//repo")


# ── Image URL extraction ────────────────────────────────────────────


class TestExtractImageUrls:
    def test_markdown_images(self):
        md = "![alt](https://example.com/a.png) and ![other](https://example.com/b.png)"
        urls = _extract_image_urls(md)
        assert urls == ["https://example.com/a.png", "https://example.com/b.png"]

    def test_html_img_tags(self):
        md = '<img src="https://example.com/c.jpg" alt="test">'
        urls = _extract_image_urls(md)
        assert urls == ["https://example.com/c.jpg"]

    def test_mixed_syntax(self):
        md = '![md](url1.png)\n<img src="url2.gif">'
        urls = _extract_image_urls(md)
        assert urls == ["url1.png", "url2.gif"]

    def test_deduplication(self):
        md = "![a](same.png) ![b](same.png)"
        urls = _extract_image_urls(md)
        assert urls == ["same.png"]

    def test_no_images(self):
        md = "Just plain text with no images."
        urls = _extract_image_urls(md)
        assert urls == []


# ── URL pattern routing ─────────────────────────────────────────────


class TestGitHubRouting:
    def test_github_url_routes_to_github_adapter(self):
        """After importing the registry, GitHub URLs route to GitHubAdapter."""
        # Import triggers @register_adapter decorator
        import web_clip_helper.adapters.github  # noqa: F401

        # Re-register to ensure it's in the cleared router
        from web_clip_helper.adapters.github import GitHubAdapter as GA
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://github\.com/[^/]+/[^/]+", GA)
        cls = route_url("https://github.com/pallets/flask")
        assert cls is GA

    def test_non_github_url_not_matched(self):
        """Non-GitHub URLs should not route to GitHubAdapter."""
        from web_clip_helper.adapters.github import GitHubAdapter as GA
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://github\.com/[^/]+/[^/]+", GA)
        cls = route_url("https://example.com/page")
        assert cls is not GA

    def test_github_url_case_insensitive(self):
        """GitHub pattern matching is case-insensitive."""
        from web_clip_helper.adapters.github import GitHubAdapter as GA
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://github\.com/[^/]+/[^/]+", GA)
        cls = route_url("HTTPS://GITHUB.COM/Owner/Repo")
        assert cls is GA


# ── README fetch ────────────────────────────────────────────────────


class TestFetchReadme:
    def _setup_client_mock(self, responses: list[MagicMock]) -> MagicMock:
        """Create a mock httpx.Client that returns the given responses in order."""
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.return_value.__enter__ = lambda s: s
        mock_client.return_value.__exit__ = lambda s, *a: None
        mock_client.return_value.get = MagicMock(side_effect=responses)
        return mock_client

    def test_fetch_readme_main_branch(self):
        """Successfully fetches README.md from main branch."""
        adapter = GitHubAdapter()
        resp = _mock_response(200, text="# Hello World")

        with patch("web_clip_helper.adapters.github.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = lambda s: s
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            mock_client_cls.return_value.get.return_value = resp

            result = adapter._fetch_readme("owner", "repo")
        assert result == "# Hello World"

    def test_fetch_readme_fallback_to_master(self):
        """Falls back to master branch if main returns 404."""
        adapter = GitHubAdapter()
        resp_404 = _mock_response(404)
        resp_200 = _mock_response(200, text="# From master")

        with patch("web_clip_helper.adapters.github.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = lambda s: s
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            # main/README.md → 404, main/readme.md → 404, master/README.md → 200
            mock_client_cls.return_value.get = MagicMock(
                side_effect=[resp_404, resp_404, resp_200]
            )

            result = adapter._fetch_readme("owner", "repo")
        assert result == "# From master"

    def test_fetch_readme_fallback_readme_lowercase(self):
        """Falls back to readme.md if README.md returns 404."""
        adapter = GitHubAdapter()
        resp_404 = _mock_response(404)
        resp_200 = _mock_response(200, text="# Lowercase readme")

        with patch("web_clip_helper.adapters.github.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = lambda s: s
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            # main/README.md → 404, main/readme.md → 200
            mock_client_cls.return_value.get = MagicMock(
                side_effect=[resp_404, resp_200]
            )

            result = adapter._fetch_readme("owner", "repo")
        assert result == "# Lowercase readme"

    def test_fetch_readme_all_branches_fail(self):
        """Raises AdapterError if no README is found on any branch."""
        adapter = GitHubAdapter()
        resp_404 = _mock_response(404)

        with patch("web_clip_helper.adapters.github.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = lambda s: s
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            mock_client_cls.return_value.get.return_value = resp_404

            with pytest.raises(AdapterError, match="Cannot fetch README"):
                adapter._fetch_readme("owner", "nonexistent")

    def test_fetch_readme_network_error_skips_gracefully(self):
        """Network errors on one branch/variant are skipped, tries next."""
        adapter = GitHubAdapter()
        resp_err = httpx.ConnectError("network error")
        resp_200 = _mock_response(200, text="# Got it")

        with patch("web_clip_helper.adapters.github.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = lambda s: s
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            # main/README.md → error, main/readme.md → error, master/README.md → success
            mock_client_cls.return_value.get = MagicMock(
                side_effect=[resp_err, resp_err, resp_200]
            )

            result = adapter._fetch_readme("owner", "repo")
        assert result == "# Got it"


# ── Metadata fetch ──────────────────────────────────────────────────


class TestFetchMetadata:
    def test_successful_metadata(self):
        adapter = GitHubAdapter()
        api_data = {
            "description": "A web framework",
            "stargazers_count": 50000,
            "topics": ["python", "web"],
        }
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.github.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = lambda s: s
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            mock_client_cls.return_value.get.return_value = resp

            result = adapter._fetch_metadata("pallets", "flask")
        assert result["description"] == "A web framework"
        assert result["stars"] == 50000
        assert result["topics"] == ["python", "web"]

    def test_api_returns_404(self):
        """Non-200 API response returns empty dict (non-fatal)."""
        adapter = GitHubAdapter()
        resp = _mock_response(404)

        with patch("web_clip_helper.adapters.github.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = lambda s: s
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            mock_client_cls.return_value.get.return_value = resp

            result = adapter._fetch_metadata("owner", "nonexistent")
        assert result == {}

    def test_api_timeout_returns_empty(self):
        """API timeout returns empty dict (non-fatal)."""
        adapter = GitHubAdapter()

        with patch("web_clip_helper.adapters.github.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = lambda s: s
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            mock_client_cls.return_value.get.side_effect = httpx.TimeoutException("timed out")

            result = adapter._fetch_metadata("owner", "repo")
        assert result == {}

    def test_api_rate_limit_403(self):
        """GitHub API rate limit (403) returns empty dict gracefully."""
        adapter = GitHubAdapter()
        resp = _mock_response(403)

        with patch("web_clip_helper.adapters.github.httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__ = lambda s: s
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            mock_client_cls.return_value.get.return_value = resp

            result = adapter._fetch_metadata("owner", "repo")
        assert result == {}


# ── Full fetch integration ──────────────────────────────────────────


class TestGitHubAdapterFetch:
    def test_full_fetch_with_metadata(self):
        """End-to-end fetch with README and metadata."""
        adapter = GitHubAdapter()

        readme_resp = _mock_response(200, text="# Project\n\n![logo](logo.png)")
        api_data = {
            "description": "Test project",
            "stargazers_count": 42,
            "topics": ["test"],
        }
        api_resp = _mock_response(200, json_data=api_data)

        with patch.object(adapter, "_fetch_readme", return_value="# Project\n\n![logo](logo.png)"), \
             patch.object(adapter, "_fetch_metadata", return_value=api_data):
            result = adapter.fetch("https://github.com/test/project")

        assert isinstance(result, RawContent)
        assert result.source_type == "github"
        assert result.url == "https://github.com/test/project"
        assert "# Project" in result.content_md
        assert "logo.png" in result.images
        assert "Test project" in result.content_md
        assert result.title == "Test project"

    def test_full_fetch_without_metadata(self):
        """Fetch works even when metadata API fails."""
        adapter = GitHubAdapter()

        with patch.object(adapter, "_fetch_readme", return_value="# No Metadata Project"), \
             patch.object(adapter, "_fetch_metadata", return_value={}):
            result = adapter.fetch("https://github.com/test/nometa")

        assert isinstance(result, RawContent)
        assert "# No Metadata Project" in result.content_md
        assert result.title == "test/nometa"  # Falls back to owner/repo

    def test_fetch_with_no_images(self):
        """README with no images returns empty images list."""
        adapter = GitHubAdapter()

        with patch.object(adapter, "_fetch_readme", return_value="# Just text\n\nNo images here."), \
             patch.object(adapter, "_fetch_metadata", return_value={
                 "description": "D",
                 "stargazers_count": 0,
                 "topics": [],
             }):
            result = adapter.fetch("https://github.com/test/plain")

        assert result.images == []

    def test_fetch_readme_with_many_images(self):
        """README with many images extracts all of them."""
        readme_content = "# Project\n\n"
        for i in range(20):
            readme_content += f"![img{i}](https://example.com/img{i}.png)\n"

        adapter = GitHubAdapter()

        with patch.object(adapter, "_fetch_readme", return_value=readme_content), \
             patch.object(adapter, "_fetch_metadata", return_value={
                 "description": "Many images",
                 "stargazers_count": 0,
                 "topics": [],
             }):
            result = adapter.fetch("https://github.com/test/manyimg")

        assert len(result.images) == 20

    def test_fetch_failure_raises_adapter_error(self):
        """When README cannot be fetched, raises AdapterError."""
        adapter = GitHubAdapter()

        with patch.object(adapter, "_fetch_readme", side_effect=AdapterError("Cannot fetch README")):
            with pytest.raises(AdapterError, match="Cannot fetch README"):
                adapter.fetch("https://github.com/test/nonexistent")
