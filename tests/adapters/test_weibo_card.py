"""Tests for the Weibo Card adapter — URL routing, API parsing, error handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from web_clip_helper.adapter import AdapterError, adapter_router, route_url
from web_clip_helper.adapters.weibo import WeiboAdapter
from web_clip_helper.adapters.weibo_card import WeiboCardAdapter
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
    resp.headers = {"content-type": "application/json; charset=utf-8"}

    def raise_for_status():
        if status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{status_code}",
                request=MagicMock(),
                response=resp,
            )

    resp.raise_for_status = raise_for_status
    return resp


def _sample_api_response(
    title: str = "测试微博长文标题",
    author: str = "测试作者",
    date: str = "2024-03-15 10:30:00",
    body_html: str = "<p>这是一篇微博长文的内容。</p>",
    images: list[str] | None = None,
    api_code: int = 100000,
) -> dict:
    """Build a sample Weibo Card API JSON response."""
    img_tags = ""
    for img_url in images or []:
        img_tags += f'<img data-src="{img_url}" src="">'

    return {
        "code": api_code,
        "data": {
            "title": title,
            "content": f"{body_html}{img_tags}",
            "complete_create_at": date,
            "create_at": date.split(" ")[0][5:] + " " + date.split(" ")[1][:5] if date else "",
            "userinfo": {
                "uid": 12345,
                "screen_name": author,
            },
            "object_id": "1022:2309405287021303431221",
        },
    }


# ── URL pattern routing ─────────────────────────────────────────────


class TestWeiboCardRouting:
    def test_card_weibo_url_routes_to_card_adapter(self):
        """card.weibo.com/article URLs route to WeiboCardAdapter."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(
            r"https?://card\.weibo\.com/article/.*",
            WeiboCardAdapter,
        )
        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/.*",
            WeiboAdapter,
        )

        url = "https://card.weibo.com/article/m/show/id/2309405287021303431221"
        cls = route_url(url)
        assert cls is WeiboCardAdapter
        assert cls is not WeiboAdapter

    def test_card_weibo_not_shadowed_by_generic_weibo(self):
        """card.weibo.com is not matched by generic WeiboAdapter when card is registered first."""
        from web_clip_helper.adapter import register_adapter

        # Card must be registered first for first-match-wins
        register_adapter(
            r"https?://card\.weibo\.com/article/.*",
            WeiboCardAdapter,
        )
        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/.*",
            WeiboAdapter,
        )

        url = "https://card.weibo.com/article/m/show/id/2309405287021303431221"
        cls = route_url(url)
        assert cls is WeiboCardAdapter

    def test_regular_weibo_url_not_matched_by_card(self):
        """Regular Weibo URLs should NOT match the card pattern."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(
            r"https?://card\.weibo\.com/article/.*",
            WeiboCardAdapter,
        )
        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/.*",
            WeiboAdapter,
        )

        cls = route_url("https://weibo.com/12345/ABCdef")
        assert cls is WeiboAdapter
        assert cls is not WeiboCardAdapter

    def test_case_insensitive_matching(self):
        """URL pattern matching is case-insensitive."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(
            r"https?://card\.weibo\.com/article/.*",
            WeiboCardAdapter,
        )

        cls = route_url("HTTPS://CARD.WEIBO.COM/ARTICLE/M/SHOW/ID/12345")
        assert cls is WeiboCardAdapter

    def test_http_url_routes_to_card_adapter(self):
        """HTTP (non-HTTPS) card.weibo.com URL also routes correctly."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(
            r"https?://card\.weibo\.com/article/.*",
            WeiboCardAdapter,
        )
        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/.*",
            WeiboAdapter,
        )

        cls = route_url("http://card.weibo.com/article/m/show/id/2309405287021303431221")
        assert cls is WeiboCardAdapter

    def test_empty_string_url_raises_valueerror(self):
        """Empty string URL raises ValueError from route_url."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(
            r"https?://card\.weibo\.com/article/.*",
            WeiboCardAdapter,
        )

        with pytest.raises(ValueError, match="Invalid URL"):
            route_url("")

    def test_non_card_weibo_url_not_matched(self):
        """Non-card weibo URLs (e.g. m.weibo.cn) don't match card adapter."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(
            r"https?://card\.weibo\.com/article/.*",
            WeiboCardAdapter,
        )
        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/.*",
            WeiboAdapter,
        )

        cls = route_url("https://m.weibo.cn/status/5127357410259489")
        assert cls is WeiboAdapter
        assert cls is not WeiboCardAdapter


# ── Article ID extraction ───────────────────────────────────────────


class TestArticleIdExtraction:
    def test_extract_id_from_standard_url(self):
        """Extract article ID from standard card URL."""
        from web_clip_helper.adapters.weibo_card import _extract_article_id

        url = "https://card.weibo.com/article/m/show/id/2309405287021303431221"
        assert _extract_article_id(url) == "2309405287021303431221"

    def test_extract_id_from_http_url(self):
        """Extract article ID from HTTP (non-HTTPS) URL."""
        from web_clip_helper.adapters.weibo_card import _extract_article_id

        url = "http://card.weibo.com/article/m/show/id/12345"
        assert _extract_article_id(url) == "12345"

    def test_extract_id_raises_on_invalid_url(self):
        """Raises AdapterError for URL without article ID."""
        from web_clip_helper.adapters.weibo_card import _extract_article_id

        with pytest.raises(AdapterError, match="Cannot extract article ID"):
            _extract_article_id("https://card.weibo.com/something/else")


# ── Image extraction ────────────────────────────────────────────────


class TestImageExtraction:
    def test_extract_images_with_data_src(self):
        """Images extracted from data-src attribute (lazy loading)."""
        html = '<div><img data-src="https://wx1.sinaimg.cn/large/a.jpg" src=""><img data-src="https://wx2.sinaimg.cn/large/b.jpg" src=""></div>'
        from web_clip_helper.adapters.weibo_card import _extract_images

        images = _extract_images(html)
        assert len(images) == 2
        assert "https://wx1.sinaimg.cn/large/a.jpg" in images

    def test_extract_images_fallback_to_src(self):
        """Images fall back to src when data-src is absent."""
        html = '<div><img src="https://example.com/img.jpg"></div>'
        from web_clip_helper.adapters.weibo_card import _extract_images

        images = _extract_images(html)
        assert images == ["https://example.com/img.jpg"]

    def test_extract_images_dedup(self):
        """Duplicate image URLs are deduplicated."""
        html = '<div><img src="https://example.com/img.jpg"><img src="https://example.com/img.jpg"></div>'
        from web_clip_helper.adapters.weibo_card import _extract_images

        images = _extract_images(html)
        assert len(images) == 1

    def test_extract_images_skips_data_uris(self):
        """data: URIs are skipped."""
        html = '<div><img src="data:image/png;base64,abc123"></div>'
        from web_clip_helper.adapters.weibo_card import _extract_images

        images = _extract_images(html)
        assert len(images) == 0

    def test_data_src_priority_over_src_both_nonempty(self):
        """When both data-src and src have different non-empty values, data-src wins."""
        html = '<img data-src="https://wx1.sinaimg.cn/large/a.jpg" src="https://placeholder.com/default.gif">'
        from web_clip_helper.adapters.weibo_card import _extract_images

        images = _extract_images(html)
        assert len(images) == 1
        assert images[0] == "https://wx1.sinaimg.cn/large/a.jpg"

    def test_mixed_images_data_src_and_src(self):
        """Mix of images with data-src only, src only, and both."""
        html = """<div>
            <img data-src="https://wx1.sinaimg.cn/large/a.jpg" src="">
            <img src="https://example.com/b.jpg">
            <img data-src="https://wx2.sinaimg.cn/large/c.jpg" src="https://placeholder.com/c.gif">
        </div>"""
        from web_clip_helper.adapters.weibo_card import _extract_images

        images = _extract_images(html)
        assert len(images) == 3
        assert images[0] == "https://wx1.sinaimg.cn/large/a.jpg"
        assert images[1] == "https://example.com/b.jpg"
        # data-src wins over src for the third image
        assert images[2] == "https://wx2.sinaimg.cn/large/c.jpg"


# ── Full fetch integration ──────────────────────────────────────────


class TestWeiboCardFetch:
    def test_full_fetch_with_images(self):
        """End-to-end fetch with images and metadata."""
        api_data = _sample_api_response(
            title="测试文章",
            author="测试作者",
            date="2024-03-15 10:30:00",
            body_html="<p>正文内容<strong>加粗</strong></p>",
            images=["https://wx1.sinaimg.cn/large/test.jpg"],
        )

        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(
                "https://card.weibo.com/article/m/show/id/2309405287021303431221"
            )

        assert isinstance(result, RawContent)
        assert result.source_type == "weibo_card"
        assert result.url == "https://card.weibo.com/article/m/show/id/2309405287021303431221"
        assert result.title == "测试文章"
        assert "正文内容" in result.content_md
        assert "加粗" in result.content_md
        assert "测试作者" in result.content_md
        assert "2024-03-15 10:30:00" in result.content_md
        assert "https://wx1.sinaimg.cn/large/test.jpg" in result.images

    def test_full_fetch_no_images(self):
        """Article with no images returns empty images list."""
        api_data = _sample_api_response(
            title="无图文章",
            body_html="<p>纯文本文章</p>",
            images=[],
        )

        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(
                "https://card.weibo.com/article/m/show/id/999"
            )

        assert result.images == []
        assert "纯文本文章" in result.content_md

    def test_full_fetch_no_author_no_date(self):
        """Article missing author/date uses defaults and emits warning."""
        api_data = {
            "code": 100000,
            "data": {
                "title": "简单文章",
                "content": "<p>内容</p>",
                "userinfo": {},
            },
        }

        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with patch("web_clip_helper.adapters.weibo_card.jsonl_emit_warning") as mock_warn:
                result = adapter.fetch(
                    "https://card.weibo.com/article/m/show/id/123"
                )

        assert result.title == "简单文章"
        assert "Author:" not in result.content_md
        mock_warn.assert_called_once()

    def test_fetch_preserves_url(self):
        """The original URL is preserved in the result."""
        api_data = _sample_api_response()
        url = "https://card.weibo.com/article/m/show/id/2309405287021303431221"

        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(url)

        assert result.url == url

    def test_fetch_long_article(self):
        """Very long article content is handled correctly."""
        long_body = "<p>" + "这是一段很长的微博长文内容。" * 500 + "</p>"
        api_data = _sample_api_response(body_html=long_body)

        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(
                "https://card.weibo.com/article/m/show/id/999"
            )

        assert "微博长文内容" in result.content_md

    def test_fetch_many_images(self):
        """Article with many images extracts all of them."""
        images = [f"https://wx1.sinaimg.cn/large/img{i}.jpg" for i in range(20)]
        api_data = _sample_api_response(images=images)

        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(
                "https://card.weibo.com/article/m/show/id/555"
            )

        assert len(result.images) == 20

    def test_fetch_calls_api_with_article_id(self):
        """Fetch calls the correct API URL with extracted article ID."""
        api_data = _sample_api_response()
        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            adapter.fetch(
                "https://card.weibo.com/article/m/show/id/2309405287021303431221"
            )

        # Verify the API was called with the correct URL
        call_args = client_inst.get.call_args
        assert "2309405287021303431221" in call_args[0][0]
        assert "ttarticle/x/m/aj/detail" in call_args[0][0]

    def test_fetch_uses_complete_create_at_preferred(self):
        """Prefers complete_create_at over create_at for publish date."""
        api_data = _sample_api_response(date="2024-03-15 10:30:00")
        api_data["data"]["create_at"] = "03-15 10:30"

        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(
                "https://card.weibo.com/article/m/show/id/123"
            )

        assert "2024-03-15 10:30:00" in result.content_md

    def test_fetch_fallback_to_create_at(self):
        """Falls back to create_at when complete_create_at is empty."""
        api_data = _sample_api_response()
        api_data["data"]["complete_create_at"] = ""
        api_data["data"]["create_at"] = "03-15 10:30"

        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(
                "https://card.weibo.com/article/m/show/id/123"
            )

        assert "03-15 10:30" in result.content_md

    def test_empty_title_fallback_to_default(self):
        """When API returns empty title, falls back to 'Weibo Card Article'."""
        api_data = _sample_api_response(title="")
        api_data["data"]["title"] = ""

        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(
                "https://card.weibo.com/article/m/show/id/123"
            )

        assert result.title == "Weibo Card Article"
        assert "Weibo Card Article" in result.content_md


# ── Error handling ──────────────────────────────────────────────────


class TestWeiboCardErrorHandling:
    def test_http_404_raises(self):
        """HTTP 404 raises AdapterError."""
        adapter = WeiboCardAdapter()
        resp = _mock_response(404)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="HTTP 404"):
                adapter.fetch("https://card.weibo.com/article/m/show/id/0")

    def test_http_500_raises(self):
        """HTTP 500 raises AdapterError."""
        adapter = WeiboCardAdapter()
        resp = _mock_response(500)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="HTTP 500"):
                adapter.fetch("https://card.weibo.com/article/m/show/id/0")

    def test_network_timeout_raises(self):
        """Network timeout raises AdapterError after retries."""
        adapter = WeiboCardAdapter()

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.side_effect = httpx.TimeoutException("timed out")

            with pytest.raises(AdapterError, match="timeout"):
                adapter.fetch("https://card.weibo.com/article/m/show/id/123")

    def test_connection_error_raises(self):
        """Connection error raises AdapterError."""
        adapter = WeiboCardAdapter()

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.side_effect = httpx.ConnectError("connection refused")

            with pytest.raises(AdapterError, match="fetch failed"):
                adapter.fetch("https://card.weibo.com/article/m/show/id/123")

    def test_missing_content_raises(self):
        """API response with empty content raises AdapterError."""
        api_data = _sample_api_response(body_html="")
        api_data["data"]["content"] = ""

        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="missing content"):
                adapter.fetch("https://card.weibo.com/article/m/show/id/123")

    def test_invalid_api_code_raises(self):
        """API response with non-100000 code raises AdapterError."""
        api_data = _sample_api_response(api_code=200015)

        adapter = WeiboCardAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="API error"):
                adapter.fetch("https://card.weibo.com/article/m/show/id/123")

    def test_invalid_url_raises(self):
        """URL without article ID raises AdapterError."""
        adapter = WeiboCardAdapter()

        with pytest.raises(AdapterError, match="Cannot extract article ID"):
            adapter.fetch("https://card.weibo.com/article/invalid")

    def test_malformed_json_raises(self):
        """Malformed JSON response raises AdapterError."""
        adapter = WeiboCardAdapter()
        resp = _mock_response(200)
        resp.json.side_effect = ValueError("bad json")

        with patch("web_clip_helper.adapters.weibo_card.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="invalid JSON"):
                adapter.fetch("https://card.weibo.com/article/m/show/id/123")
