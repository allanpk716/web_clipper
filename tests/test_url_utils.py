"""Tests for URL normalization and ClipIndex.find_by_url()."""

from __future__ import annotations

from pathlib import Path

import pytest

from web_clip_helper.index import ClipIndex
from web_clip_helper.url_utils import normalize_url


# ── normalize_url ────────────────────────────────────────────────────


class TestNormalizeUrl:
    """Unit tests for ``normalize_url``."""

    # -- scheme upgrade --

    def test_http_to_https(self) -> None:
        assert normalize_url("http://example.com/article") == "https://example.com/article"

    def test_https_unchanged(self) -> None:
        assert normalize_url("https://example.com/article") == "https://example.com/article"

    # -- trailing slash removal --

    def test_trailing_slash_removed(self) -> None:
        assert normalize_url("https://example.com/article/") == "https://example.com/article"

    def test_multiple_trailing_slashes(self) -> None:
        assert normalize_url("https://example.com/article///") == "https://example.com/article"

    def test_root_path_preserved(self) -> None:
        assert normalize_url("https://example.com/") == "https://example.com/"

    def test_bare_domain_no_slash(self) -> None:
        assert normalize_url("https://example.com") == "https://example.com"

    # -- combined normalizations --

    def test_http_trailing_slash_combined(self) -> None:
        assert normalize_url("http://example.com/article/") == "https://example.com/article"

    # -- whitespace --

    def test_strips_whitespace(self) -> None:
        assert normalize_url("  https://example.com/article  ") == "https://example.com/article"

    # -- idempotency --

    def test_idempotent(self) -> None:
        url = "https://example.com/article"
        assert normalize_url(normalize_url(url)) == url

    # -- query strings and fragments --

    def test_preserves_query_string(self) -> None:
        assert normalize_url("https://example.com/search?q=test") == "https://example.com/search?q=test"

    def test_preserves_fragment(self) -> None:
        assert normalize_url("https://example.com/page#section") == "https://example.com/page#section"

    def test_http_query_fragment_combined(self) -> None:
        assert (
            normalize_url("http://example.com/page/?q=1#sec")
            == "https://example.com/page?q=1#sec"
        )

    # -- edge cases --

    def test_empty_path(self) -> None:
        assert normalize_url("https://example.com") == "https://example.com"

    def test_no_scheme_passthrough(self) -> None:
        """Without a scheme, urlparse treats the input as a path."""
        result = normalize_url("example.com/article")
        # urlparse without scheme puts everything in path; result is still valid
        assert isinstance(result, str)

    def test_complex_path(self) -> None:
        assert (
            normalize_url("http://example.com/a/b/c/")
            == "https://example.com/a/b/c"
        )

    def test_file_extension_preserved(self) -> None:
        assert normalize_url("https://example.com/page.html") == "https://example.com/page.html"

    def test_trailing_slash_with_file_extension(self) -> None:
        assert normalize_url("https://example.com/page.html/") == "https://example.com/page.html"


# ── ClipIndex.find_by_url ────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path: Path) -> ClipIndex:
    """Return a ClipIndex backed by a temp database."""
    db_path = tmp_path / "test.db"
    return ClipIndex(db_path)


def _save(tmp_db: ClipIndex, url: str, title: str = "Test") -> int:
    return tmp_db.save_clip({
        "url": url,
        "title": title,
        "source_type": "web",
        "folder_path": f"/tmp/{title}",
        "markdown_path": f"/tmp/{title}/article.md",
    })


class TestFindByUrl:
    """Tests for ``ClipIndex.find_by_url`` with URL normalization."""

    def test_exact_match(self, tmp_db: ClipIndex) -> None:
        rid = _save(tmp_db, "https://example.com/article")
        result = tmp_db.find_by_url("https://example.com/article")
        assert result is not None
        assert result["id"] == rid

    def test_trailing_slash_match(self, tmp_db: ClipIndex) -> None:
        rid = _save(tmp_db, "https://example.com/article")
        result = tmp_db.find_by_url("https://example.com/article/")
        assert result is not None
        assert result["id"] == rid

    def test_http_to_https_match(self, tmp_db: ClipIndex) -> None:
        rid = _save(tmp_db, "https://example.com/article")
        result = tmp_db.find_by_url("http://example.com/article")
        assert result is not None
        assert result["id"] == rid

    def test_http_and_trailing_slash_match(self, tmp_db: ClipIndex) -> None:
        rid = _save(tmp_db, "https://example.com/article")
        result = tmp_db.find_by_url("http://example.com/article/")
        assert result is not None
        assert result["id"] == rid

    def test_no_match(self, tmp_db: ClipIndex) -> None:
        _save(tmp_db, "https://example.com/article")
        result = tmp_db.find_by_url("https://example.com/different")
        assert result is None

    def test_empty_db(self, tmp_db: ClipIndex) -> None:
        result = tmp_db.find_by_url("https://example.com/article")
        assert result is None

    def test_returns_most_recent_when_multiple(self, tmp_db: ClipIndex) -> None:
        """If somehow two records share a URL, return the newer one."""
        _save(tmp_db, "https://example.com/article", title="Old")
        rid2 = _save(tmp_db, "https://example.com/article", title="New")
        result = tmp_db.find_by_url("https://example.com/article")
        assert result is not None
        assert result["id"] == rid2
        assert result["title"] == "New"

    def test_stored_with_trailing_slash_still_matches(self, tmp_db: ClipIndex) -> None:
        """DB stored a trailing-slash URL; query without slash still matches."""
        rid = _save(tmp_db, "https://example.com/article/")
        result = tmp_db.find_by_url("https://example.com/article")
        assert result is not None
        assert result["id"] == rid

    def test_stored_http_still_matches_https(self, tmp_db: ClipIndex) -> None:
        """DB stored http URL; query with https still matches after normalization."""
        rid = _save(tmp_db, "http://example.com/article")
        result = tmp_db.find_by_url("https://example.com/article")
        assert result is not None
        assert result["id"] == rid

    def test_whitespace_in_query_match(self, tmp_db: ClipIndex) -> None:
        rid = _save(tmp_db, "https://example.com/article")
        result = tmp_db.find_by_url("  https://example.com/article  ")
        assert result is not None
        assert result["id"] == rid

    def test_different_domain_no_match(self, tmp_db: ClipIndex) -> None:
        _save(tmp_db, "https://example.com/article")
        result = tmp_db.find_by_url("https://other.com/article")
        assert result is None

    def test_different_path_no_match(self, tmp_db: ClipIndex) -> None:
        _save(tmp_db, "https://example.com/article")
        result = tmp_db.find_by_url("https://example.com/article-extra")
        assert result is None
