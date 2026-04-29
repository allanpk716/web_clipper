"""Tests for the generic web adapter — HTML fetch, conversion, images."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from web_clip_helper.adapter import AdapterError, adapter_router, route_url
from web_clip_helper.adapters.generic import (
    GenericWebAdapter,
    _extract_image_urls,
    _extract_title,
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
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.headers = {"content-type": "text/html; charset=utf-8"}

    def raise_for_status():
        if status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{status_code}",
                request=MagicMock(),
                response=resp,
            )

    resp.raise_for_status = raise_for_status
    return resp


# ── Title extraction ────────────────────────────────────────────────


class TestExtractTitle:
    def test_standard_title(self):
        html = "<html><head><title>My Page</title></head><body></body></html>"
        assert _extract_title(html) == "My Page"

    def test_empty_title(self):
        html = "<html><head><title></title></head><body></body></html>"
        assert _extract_title(html) == ""

    def test_no_title_tag(self):
        html = "<html><body>No title here</body></html>"
        assert _extract_title(html) == ""

    def test_title_with_attributes(self):
        html = '<html><head><title lang="en">Attributed Title</title></head></html>'
        assert _extract_title(html) == "Attributed Title"

    def test_title_with_whitespace(self):
        html = "<html><head><title>  Spaced Title  </title></head></html>"
        assert _extract_title(html) == "Spaced Title"


# ── Image URL extraction ────────────────────────────────────────────


class TestExtractImageUrls:
    def test_img_tags(self):
        html = '<img src="https://example.com/a.jpg"><img src="https://example.com/b.png">'
        urls = _extract_image_urls(html)
        assert urls == ["https://example.com/a.jpg", "https://example.com/b.png"]

    def test_background_image_css(self):
        html = 'style="background-image: url(\'https://example.com/bg.png\')"'
        urls = _extract_image_urls(html)
        assert urls == ["https://example.com/bg.png"]

    def test_background_image_no_quotes(self):
        html = 'style="background-image: url(https://example.com/bg2.jpg)"'
        urls = _extract_image_urls(html)
        assert urls == ["https://example.com/bg2.jpg"]

    def test_mixed_sources(self):
        html = '<img src="img1.png">\n<div style="background-image: url(\'img2.gif\')">'
        urls = _extract_image_urls(html)
        assert urls == ["img1.png", "img2.gif"]

    def test_deduplication(self):
        html = '<img src="same.png"><img src="same.png">'
        urls = _extract_image_urls(html)
        assert urls == ["same.png"]

    def test_no_images(self):
        html = "<p>Just text</p>"
        urls = _extract_image_urls(html)
        assert urls == []


# ── Routing ─────────────────────────────────────────────────────────


class TestGenericRouting:
    def test_non_matching_url_routes_to_generic(self):
        """URLs not matching any specific adapter get the generic fallback."""
        cls = route_url("https://example.com/some/article")
        adapter = cls()
        assert adapter.source_type == "web"


# ── Full fetch ──────────────────────────────────────────────────────


class TestGenericWebAdapterFetch:
    def _sample_html(self, title: str = "Test Page", body: str = "<p>Hello world</p>") -> str:
        return (
            f"<html><head><title>{title}</title></head>"
            f"<body><article>{body}</article></body></html>"
        )

    def test_basic_fetch(self):
        """Fetch converts HTML to Markdown."""
        adapter = GenericWebAdapter()
        html = self._sample_html(body="<p>Hello world</p>")
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.generic.httpx.Client") as mock_cls:
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.get.return_value = resp
            mock_cls.return_value = m

            result = adapter.fetch("https://example.com/article")

        assert isinstance(result, RawContent)
        assert result.source_type == "web"
        assert result.url == "https://example.com/article"
        assert "Hello world" in result.content_md
        assert "example.com/article" in result.content_md

    def test_title_extraction(self):
        """Title is extracted from the HTML <title> tag."""
        adapter = GenericWebAdapter()
        html = self._sample_html(title="My Article Title", body="<p>Content</p>")
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.generic.httpx.Client") as mock_cls:
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.get.return_value = resp
            mock_cls.return_value = m

            result = adapter.fetch("https://example.com/article")

        assert result.title == "My Article Title"

    def test_image_extraction(self):
        """Image URLs are extracted from HTML content."""
        adapter = GenericWebAdapter()
        html = self._sample_html(
            body='<p>Text</p><img src="https://cdn.example.com/photo.jpg"><p>More</p>'
        )
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.generic.httpx.Client") as mock_cls:
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.get.return_value = resp
            mock_cls.return_value = m

            result = adapter.fetch("https://example.com/article")

        assert "https://cdn.example.com/photo.jpg" in result.images

    def test_metadata_header_in_markdown(self):
        """Output markdown includes source URL and clip time header."""
        adapter = GenericWebAdapter()
        html = self._sample_html(body="<p>Content</p>")
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.generic.httpx.Client") as mock_cls:
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.get.return_value = resp
            mock_cls.return_value = m

            result = adapter.fetch("https://example.com/article")

        assert "> Source: https://example.com/article" in result.content_md
        assert "> Clipped:" in result.content_md

    def test_fetch_404_raises(self):
        """404 response raises AdapterError."""
        adapter = GenericWebAdapter()
        resp = _mock_response(404)

        with patch("web_clip_helper.adapters.generic.httpx.Client") as mock_cls:
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.get.return_value = resp
            mock_cls.return_value = m

            with pytest.raises(AdapterError, match="Failed to fetch"):
                adapter.fetch("https://example.com/notfound")

    def test_fetch_network_timeout_raises(self):
        """Network timeout raises AdapterError after retries."""
        adapter = GenericWebAdapter()

        with patch("web_clip_helper.adapters.generic.httpx.Client") as mock_cls:
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.get.side_effect = httpx.TimeoutException("timed out")
            mock_cls.return_value = m

            with pytest.raises(AdapterError, match="Failed to fetch"):
                adapter.fetch("https://slow.example.com/page")

    def test_fetch_connection_error_raises(self):
        """Connection error raises AdapterError."""
        adapter = GenericWebAdapter()

        with patch("web_clip_helper.adapters.generic.httpx.Client") as mock_cls:
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.get.side_effect = httpx.ConnectError("no network")
            mock_cls.return_value = m

            with pytest.raises(AdapterError, match="Failed to fetch"):
                adapter.fetch("https://nonexistent.invalid/page")

    def test_empty_html_page(self):
        """Empty HTML page is handled gracefully."""
        adapter = GenericWebAdapter()
        resp = _mock_response(200, text="")

        with patch("web_clip_helper.adapters.generic.httpx.Client") as mock_cls:
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.get.return_value = resp
            mock_cls.return_value = m

            # Should not raise — readability handles empty HTML
            result = adapter.fetch("https://example.com/empty")

        assert isinstance(result, RawContent)
        assert result.url == "https://example.com/empty"

    def test_no_title_falls_back_to_url(self):
        """When no title tag exists, title falls back to the URL."""
        adapter = GenericWebAdapter()
        html = "<html><body><p>Just a paragraph</p></body></html>"
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.generic.httpx.Client") as mock_cls:
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.get.return_value = resp
            mock_cls.return_value = m

            result = adapter.fetch("https://example.com/notitle")

        # Title should be the URL or readability-extracted title
        assert result.title is not None and len(result.title) > 0

    def test_large_html_page(self):
        """Large HTML page is handled without error."""
        adapter = GenericWebAdapter()
        # Generate a large page
        paragraphs = "<p>" + "</p><p>".join(f"Paragraph {i}." for i in range(500)) + "</p>"
        html = self._sample_html(title="Large Page", body=paragraphs)
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.generic.httpx.Client") as mock_cls:
            m = MagicMock()
            m.__enter__ = lambda s: s
            m.__exit__ = lambda s, *a: None
            m.get.return_value = resp
            mock_cls.return_value = m

            result = adapter.fetch("https://example.com/large")

        assert isinstance(result, RawContent)
        assert "Paragraph 0" in result.content_md
