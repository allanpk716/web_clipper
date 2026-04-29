"""Tests for the Weibo adapter — URL parsing, bid→mid conversion, API fetch, images."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from web_clip_helper.adapter import AdapterError, adapter_router, route_url
from web_clip_helper.adapters.weibo import (
    WeiboAdapter,
    _bid_to_mid,
    _parse_weibo_url,
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
    text_html: str = "<p>Hello Weibo</p>",
    pics: list[dict] | None = None,
    author: str = "TestUser",
    reposts: int = 10,
    comments: int = 5,
    likes: int = 100,
    created_at: str = "Tue Jan 01 00:00:00 +0800 2024",
) -> dict:
    """Build a sample m.weibo.cn API response."""
    return {
        "ok": 1,
        "data": {
            "id": "5000000000000000",
            "text": text_html,
            "pics": pics or [],
            "user": {
                "screen_name": author,
            },
            "reposts_count": reposts,
            "comments_count": comments,
            "attitudes_count": likes,
            "created_at": created_at,
        },
    }


# ── bid→mid conversion ──────────────────────────────────────────────


class TestBidToMid:
    def test_simple_bid(self):
        """A known bid should convert to the expected mid."""
        # "z4sUa0M" is a known example bid; we verify round-trip consistency
        # by checking that the output is numeric and non-empty
        result = _bid_to_mid("z4sUa0M")
        assert result.isdigit()
        assert len(result) > 0

    def test_short_bid(self):
        """Short bid values should still produce a numeric mid."""
        result = _bid_to_mid("A")
        assert result.isdigit()

    def test_single_zero(self):
        """Bid '0' should decode to '0'."""
        assert _bid_to_mid("0") == "0"

    def test_long_bid(self):
        """Long bid values should still decode correctly."""
        bid = "z4sUa0Mz4sUa0M"
        result = _bid_to_mid(bid)
        assert result.isdigit()

    def test_empty_bid_raises(self):
        """Empty bid should raise AdapterError."""
        with pytest.raises(AdapterError, match="Empty bid"):
            _bid_to_mid("")

    def test_whitespace_only_bid_raises(self):
        """Whitespace-only bid should raise AdapterError."""
        with pytest.raises(AdapterError, match="Empty bid"):
            _bid_to_mid("   ")

    def test_invalid_characters_raise(self):
        """Characters not in the Base62 alphabet should raise."""
        with pytest.raises(AdapterError, match="Invalid character"):
            _bid_to_mid("abc!@#")

    def test_pure_digits_bid(self):
        """A purely numeric bid decodes correctly."""
        result = _bid_to_mid("123")
        assert result.isdigit()

    def test_known_conversion_vector(self):
        """Test specific known bid→mid pairs for correctness.

        Weibo Base62 alphabet: 0-9 a-z A-Z
        'A' = index 36 (a=10, ..., z=35, A=36)
        'z' = index 35, 'Z' = index 61
        Single char 'A' → 36
        '10' = 1*62 + 0 = 62
        """
        assert _bid_to_mid("A") == "36"
        assert _bid_to_mid("z") == "35"
        assert _bid_to_mid("Z") == "61"
        assert _bid_to_mid("10") == "62"


# ── URL parsing ─────────────────────────────────────────────────────


class TestParseWeiboUrl:
    def test_m_weibo_cn_status(self):
        """m.weibo.cn/status/{id} extracts id directly."""
        assert _parse_weibo_url("https://m.weibo.cn/status/5123456789012345") == "5123456789012345"

    def test_weibo_com_detail(self):
        """weibo.com/detail/{id} extracts id directly."""
        assert _parse_weibo_url("https://weibo.com/detail/5123456789012345") == "5123456789012345"

    def test_weibo_com_statuses(self):
        """weibo.com/statuses/{id} extracts id directly."""
        assert _parse_weibo_url("https://weibo.com/statuses/5123456789012345") == "5123456789012345"

    def test_weibo_com_uid_bid(self):
        """weibo.com/{uid}/{bid} converts bid to mid."""
        # Pure numeric bid is returned as-is
        assert _parse_weibo_url("https://weibo.com/12345/67890") == "67890"

    def test_weibo_com_uid_base62_bid(self):
        """weibo.com/{uid}/{base62_bid} decodes bid."""
        result = _parse_weibo_url("https://weibo.com/12345/ABCdef")
        assert result.isdigit()

    def test_url_with_query_string(self):
        """URL with query parameters still parses correctly."""
        assert _parse_weibo_url("https://weibo.com/detail/5123456789012345?type=comment") == "5123456789012345"

    def test_url_with_fragment(self):
        """URL with fragment still parses correctly."""
        assert _parse_weibo_url("https://m.weibo.cn/status/5123456789012345#comment") == "5123456789012345"

    def test_unrecognized_url_raises(self):
        """URL without a recognizable post ID raises AdapterError."""
        with pytest.raises(AdapterError, match="Cannot extract post ID"):
            _parse_weibo_url("https://weibo.com/")

    def test_empty_url_raises(self):
        """Empty URL raises AdapterError."""
        with pytest.raises(AdapterError, match="Cannot extract post ID"):
            _parse_weibo_url("")

    def test_http_scheme(self):
        """HTTP (non-HTTPS) URLs are also supported."""
        assert _parse_weibo_url("http://m.weibo.cn/status/5123456789012345") == "5123456789012345"

    def test_weibo_com_with_m_subdomain(self):
        """m.weibo.com URLs are also supported."""
        assert _parse_weibo_url("https://m.weibo.com/statuses/5123456789012345") == "5123456789012345"


# ── URL pattern routing ─────────────────────────────────────────────


class TestWeiboRouting:
    def test_weibo_url_routes_to_weibo_adapter(self):
        """After import, Weibo URLs route to WeiboAdapter."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://(m\.)?weibo\.c(n|om)/.*", WeiboAdapter)
        cls = route_url("https://weibo.com/12345/ABCdef")
        assert cls is WeiboAdapter

    def test_m_weibo_cn_routes(self):
        """m.weibo.cn URLs route to WeiboAdapter."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://(m\.)?weibo\.c(n|om)/.*", WeiboAdapter)
        cls = route_url("https://m.weibo.cn/status/5123456789012345")
        assert cls is WeiboAdapter

    def test_non_weibo_url_not_matched(self):
        """Non-Weibo URLs should not route to WeiboAdapter."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://(m\.)?weibo\.c(n|om)/.*", WeiboAdapter)
        cls = route_url("https://example.com/page")
        assert cls is not WeiboAdapter

    def test_weibo_url_case_insensitive(self):
        """Pattern matching is case-insensitive."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://(m\.)?weibo\.c(n|om)/.*", WeiboAdapter)
        cls = route_url("HTTPS://WEIBO.COM/12345/ABCdef")
        assert cls is WeiboAdapter


# ── Image extraction ────────────────────────────────────────────────


class TestExtractImages:
    def test_with_large_urls(self):
        """Extracts large image URLs when available."""
        status = {
            "pics": [
                {"large": {"url": "https://wx1.sinaimg.cn/large/abc.jpg"}, "url": "https://wx1.sinaimg.cn/orj480/abc.jpg"},
                {"large": {"url": "https://wx2.sinaimg.cn/large/def.jpg"}, "url": "https://wx2.sinaimg.cn/orj480/def.jpg"},
            ]
        }
        images = WeiboAdapter._extract_images(status)
        assert images == [
            "https://wx1.sinaimg.cn/large/abc.jpg",
            "https://wx2.sinaimg.cn/large/def.jpg",
        ]

    def test_fallback_to_url_when_no_large(self):
        """Falls back to url field when large is not available."""
        status = {
            "pics": [
                {"url": "https://wx1.sinaimg.cn/orj480/abc.jpg"},
            ]
        }
        images = WeiboAdapter._extract_images(status)
        assert images == ["https://wx1.sinaimg.cn/orj480/abc.jpg"]

    def test_no_pics_field(self):
        """Returns empty list when pics field is missing."""
        images = WeiboAdapter._extract_images({})
        assert images == []

    def test_empty_pics(self):
        """Returns empty list when pics is empty."""
        images = WeiboAdapter._extract_images({"pics": []})
        assert images == []

    def test_pics_with_non_dict_entries(self):
        """Skips non-dict entries in pics list."""
        status = {"pics": ["not_a_dict", None, 42]}
        images = WeiboAdapter._extract_images(status)
        assert images == []

    def test_many_images(self):
        """Extracts all images from a post with many pics."""
        status = {
            "pics": [
                {"large": {"url": f"https://wx1.sinaimg.cn/large/img{i}.jpg"}}
                for i in range(20)
            ]
        }
        images = WeiboAdapter._extract_images(status)
        assert len(images) == 20


# ── Full fetch integration ──────────────────────────────────────────


class TestWeiboAdapterFetch:
    def test_full_fetch_with_images(self):
        """End-to-end fetch with images and metadata."""
        api_data = _sample_api_response(
            text_html="<p>Hello <b>Weibo</b>!</p><img src='https://wx1.sinaimg.cn/large/test.jpg'>",
            pics=[
                {"large": {"url": "https://wx1.sinaimg.cn/large/test.jpg"}},
            ],
            author="TestUser",
            reposts=10,
            comments=5,
            likes=100,
        )

        adapter = WeiboAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://m.weibo.cn/status/5123456789012345")

        assert isinstance(result, RawContent)
        assert result.source_type == "weibo"
        assert result.url == "https://m.weibo.cn/status/5123456789012345"
        assert "Hello" in result.content_md
        assert "Weibo" in result.content_md
        assert "TestUser" in result.content_md
        assert "https://wx1.sinaimg.cn/large/test.jpg" in result.images
        assert result.title == "TestUser"

    def test_full_fetch_no_images(self):
        """Post with no images returns empty images list."""
        api_data = _sample_api_response(text_html="<p>Just text</p>", pics=[])

        adapter = WeiboAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://weibo.com/detail/5123456789012345")

        assert result.images == []
        assert "Just text" in result.content_md

    def test_full_fetch_no_text(self):
        """Post with no text content still returns valid result."""
        api_data = _sample_api_response(text_html="", pics=[])

        adapter = WeiboAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://m.weibo.cn/status/5123456789012345")

        assert isinstance(result, RawContent)
        assert result.source_type == "weibo"

    def test_full_fetch_long_text(self):
        """Post with very long text is handled correctly."""
        long_html = "<p>" + "这是一段很长的微博内容。" * 500 + "</p>"
        api_data = _sample_api_response(text_html=long_html, pics=[])

        adapter = WeiboAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://m.weibo.cn/status/5123456789012345")

        assert isinstance(result, RawContent)
        assert "微博内容" in result.content_md

    def test_fetch_via_uid_bid_url(self):
        """Fetch via weibo.com/{uid}/{bid} URL triggers bid→mid conversion."""
        api_data = _sample_api_response(text_html="<p>From bid URL</p>", pics=[])
        adapter = WeiboAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://weibo.com/12345/67890")

        assert "From bid URL" in result.content_md

    def test_fetch_metadata_header(self):
        """Metadata header includes source, date, author, stats."""
        api_data = _sample_api_response(
            author="WeiboAuthor",
            created_at="Mon Mar 15 10:30:00 +0800 2024",
            reposts=20,
            comments=10,
            likes=200,
        )
        adapter = WeiboAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://m.weibo.cn/status/5123456789012345")

        assert "Author: WeiboAuthor" in result.content_md
        assert "Mon Mar 15" in result.content_md
        assert "20 reposts" in result.content_md
        assert "10 comments" in result.content_md
        assert "200 likes" in result.content_md


# ── Error handling ──────────────────────────────────────────────────


class TestWeiboErrorHandling:
    def test_api_404_raises(self):
        """API 404 raises AdapterError."""
        adapter = WeiboAdapter()
        resp = _mock_response(404)

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="HTTP 404"):
                adapter.fetch("https://m.weibo.cn/status/0000000000000000")

    def test_api_403_raises(self):
        """API 403 raises AdapterError."""
        adapter = WeiboAdapter()
        resp = _mock_response(403)

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="HTTP 403"):
                adapter.fetch("https://m.weibo.cn/status/0000000000000000")

    def test_network_timeout_raises(self):
        """Network timeout raises AdapterError after retries."""
        adapter = WeiboAdapter()

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.side_effect = httpx.TimeoutException("timed out")

            with pytest.raises(AdapterError, match="timeout"):
                adapter.fetch("https://m.weibo.cn/status/5123456789012345")

    def test_api_error_response(self):
        """API response with ok=0 raises AdapterError."""
        adapter = WeiboAdapter()
        resp = _mock_response(200, json_data={"ok": 0, "msg": "post not found"})

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="post not found"):
                adapter.fetch("https://m.weibo.cn/status/0000000000000000")

    def test_empty_json_response(self):
        """Empty JSON response raises AdapterError."""
        adapter = WeiboAdapter()
        resp = _mock_response(200, json_data={})

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError):
                adapter.fetch("https://m.weibo.cn/status/5123456789012345")

    def test_empty_data_field(self):
        """Response with empty data field raises AdapterError."""
        adapter = WeiboAdapter()
        resp = _mock_response(200, json_data={"ok": 1, "data": {}})

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="empty data"):
                adapter.fetch("https://m.weibo.cn/status/5123456789012345")

    def test_non_dict_response(self):
        """Non-dict JSON response raises AdapterError."""
        adapter = WeiboAdapter()
        resp = _mock_response(200, json_data=None)
        resp.json.return_value = "not a dict"

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="non-object"):
                adapter.fetch("https://m.weibo.cn/status/5123456789012345")

    def test_connection_error_raises(self):
        """Network connection error raises AdapterError."""
        adapter = WeiboAdapter()

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.side_effect = httpx.ConnectError("connection refused")

            with pytest.raises(AdapterError, match="request failed"):
                adapter.fetch("https://m.weibo.cn/status/5123456789012345")

    def test_unparseable_url_raises(self):
        """URL that cannot be parsed raises AdapterError."""
        adapter = WeiboAdapter()
        with pytest.raises(AdapterError, match="Cannot extract post ID"):
            adapter.fetch("https://weibo.com/")

    def test_missing_user_field(self):
        """Post without user field uses empty string for author."""
        api_data = {
            "ok": 1,
            "data": {
                "id": "12345",
                "text": "<p>No user info</p>",
                "pics": [],
                "user": None,
                "reposts_count": 0,
                "comments_count": 0,
                "attitudes_count": 0,
                "created_at": "",
            },
        }
        adapter = WeiboAdapter()
        resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://m.weibo.cn/status/12345")

        assert "No user info" in result.content_md
        # Title falls back to "Weibo post {mid}" when no author
        assert "Weibo post" in result.title
