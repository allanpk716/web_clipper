"""Tests for the WeChat adapter — URL pattern, HTML parsing, image extraction, error handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from web_clip_helper.adapter import AdapterError, adapter_router, route_url
from web_clip_helper.adapters.wechat import (
    WeChatAdapter,
    _extract_author,
    _extract_content_html,
    _extract_images,
    _extract_publish_date,
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
    json_data: dict | None = None,
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data or {}
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


def _sample_wechat_html(
    title: str = "Test WeChat Article",
    author: str = "TestAccount",
    publish_date: str = "2024-01-15 10:30",
    body_html: str = "<p>Hello <strong>WeChat</strong>!</p>",
    images: list[str] | None = None,
    has_content_div: bool = True,
    has_activity_name: bool = True,
    has_js_name: bool = True,
    has_publish_time: bool = True,
) -> str:
    """Build a sample WeChat article HTML page."""
    img_tags = ""
    if images:
        for img_url in images:
            img_tags += f'<img data-src="{img_url}" src="" />\n'

    content_inner = f"{body_html}\n{img_tags}" if images else body_html

    activity_name_html = (
        f'<h1 id="activity-name" class="rich_media_title">{title}</h1>'
        if has_activity_name
        else ""
    )

    js_name_html = (
        f'<a id="js_name" class="rich_media_meta_link">{author}</a>'
        if has_js_name
        else ""
    )

    publish_time_html = (
        f'<em id="publish_time">{publish_date}</em>'
        if has_publish_time
        else ""
    )

    content_div = (
        f'<div id="js_content" class="rich_media_content">{content_inner}</div>'
        if has_content_div
        else ""
    )

    return f"""<!DOCTYPE html>
<html>
<head><title>{title}</title></head>
<body>
<div id="page-content">
    {activity_name_html}
    {js_name_html}
    {publish_time_html}
    <div class="rich_media_area_primary">
        {content_div}
    </div>
</div>
</body>
</html>"""


# ── Title extraction ────────────────────────────────────────────────


class TestExtractTitle:
    def test_activity_name_title(self):
        """Extracts title from #activity-name."""
        html = _sample_wechat_html(title="我的微信文章")
        assert _extract_title(html) == "我的微信文章"

    def test_fallback_h1_without_activity_name(self):
        """Falls back to <h1> when #activity-name is missing."""
        html = _sample_wechat_html(has_activity_name=False)
        html = html.replace(
            '<div id="page-content">',
            '<div id="page-content"><h1>Fallback Title</h1>',
        )
        assert _extract_title(html) == "Fallback Title"

    def test_no_title_returns_empty(self):
        """Returns empty string when no title elements exist."""
        html = "<html><body><p>No title here</p></body></html>"
        assert _extract_title(html) == ""

    def test_title_with_extra_attributes(self):
        """Handles h1 with many attributes."""
        html = '<h1 id="activity-name" class="rich_media_title" style="color:red;">Complex Title</h1>'
        assert _extract_title(html) == "Complex Title"


# ── Author extraction ───────────────────────────────────────────────


class TestExtractAuthor:
    def test_js_name_author(self):
        """Extracts author from #js_name."""
        html = _sample_wechat_html(author="MyPublicAccount")
        assert _extract_author(html) == "MyPublicAccount"

    def test_profile_nickname_fallback(self):
        """Falls back to .profile_nickname when #js_name is missing."""
        html = _sample_wechat_html(has_js_name=False)
        html = html.replace(
            '<div class="rich_media_area_primary">',
            '<div class="rich_media_area_primary"><strong class="profile_nickname">NicknameAuthor</strong>',
        )
        assert _extract_author(html) == "NicknameAuthor"

    def test_no_author_returns_empty(self):
        """Returns empty string when no author elements exist."""
        html = "<html><body><p>No author</p></body></html>"
        assert _extract_author(html) == ""


# ── Date extraction ─────────────────────────────────────────────────


class TestExtractPublishDate:
    def test_publish_time(self):
        """Extracts date from #publish_time."""
        html = _sample_wechat_html(publish_date="2024-03-20 14:30")
        assert _extract_publish_date(html) == "2024-03-20 14:30"

    def test_no_publish_time(self):
        """Returns empty string when #publish_time is missing."""
        html = _sample_wechat_html(has_publish_time=False)
        # The sample HTML without publish_time should yield empty
        assert _extract_publish_date(html) == ""


# ── Content HTML extraction ─────────────────────────────────────────


class TestExtractContentHtml:
    def test_extracts_js_content(self):
        """Extracts inner HTML from #js_content div."""
        html = _sample_wechat_html(body_html="<p>Content here</p>")
        content = _extract_content_html(html)
        assert "<p>Content here</p>" in content

    def test_missing_js_content_returns_empty(self):
        """Returns empty string when #js_content is missing."""
        html = _sample_wechat_html(has_content_div=False)
        assert _extract_content_html(html) == ""

    def test_nested_divs(self):
        """Handles nested divs inside #js_content."""
        body = "<div><p>Level 1</p><div><p>Level 2</p></div></div>"
        html = _sample_wechat_html(body_html=body)
        content = _extract_content_html(html)
        assert "Level 1" in content
        assert "Level 2" in content

    def test_empty_content_div(self):
        """Handles empty #js_content div."""
        html = '<div id="js_content"></div>'
        content = _extract_content_html(html)
        # Empty div should return empty string
        assert content == ""


# ── Image extraction ────────────────────────────────────────────────


class TestExtractImages:
    def test_data_src_images(self):
        """Extracts image URLs from data-src attribute."""
        content = '<img data-src="https://mmbiz.qpic.cn/img1.jpg" src="" /><img data-src="https://mmbiz.qpic.cn/img2.jpg" src="" />'
        images = _extract_images(content)
        assert images == [
            "https://mmbiz.qpic.cn/img1.jpg",
            "https://mmbiz.qpic.cn/img2.jpg",
        ]

    def test_src_fallback(self):
        """Falls back to src when data-src is not present."""
        content = '<img src="https://mmbiz.qpic.cn/img3.jpg" />'
        images = _extract_images(content)
        assert images == ["https://mmbiz.qpic.cn/img3.jpg"]

    def test_data_src_preferred_over_src(self):
        """data-src takes priority over src when both exist."""
        content = '<img data-src="https://mmbiz.qpic.cn/lazy.jpg" src="https://placeholder.com/1x1.png" />'
        images = _extract_images(content)
        assert images == ["https://mmbiz.qpic.cn/lazy.jpg"]

    def test_no_images(self):
        """Returns empty list when no img tags present."""
        content = "<p>Just text, no images</p>"
        assert _extract_images(content) == []

    def test_deduplication(self):
        """Deduplicates identical image URLs."""
        content = '<img data-src="https://mmbiz.qpic.cn/same.jpg" /><img data-src="https://mmbiz.qpic.cn/same.jpg" />'
        images = _extract_images(content)
        assert images == ["https://mmbiz.qpic.cn/same.jpg"]

    def test_skips_data_uris(self):
        """Skips data: URIs (inline base64 images)."""
        content = '<img src="data:image/png;base64,iVBOR..." />'
        assert _extract_images(content) == []

    def test_mixed_images(self):
        """Handles mix of data-src and src images."""
        content = """
        <img data-src="https://mmbiz.qpic.cn/lazy1.jpg" src="" />
        <img src="https://mmbiz.qpic.cn/normal.jpg" />
        <img data-src="https://mmbiz.qpic.cn/lazy2.jpg" />
        """
        images = _extract_images(content)
        assert len(images) == 3
        assert "https://mmbiz.qpic.cn/lazy1.jpg" in images
        assert "https://mmbiz.qpic.cn/normal.jpg" in images
        assert "https://mmbiz.qpic.cn/lazy2.jpg" in images


# ── URL pattern routing ─────────────────────────────────────────────


class TestWeChatRouting:
    def test_wechat_url_routes_to_wechat_adapter(self):
        """mp.weixin.qq.com URLs route to WeChatAdapter."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://mp\.weixin\.qq\.com/.*", WeChatAdapter)
        cls = route_url("https://mp.weixin.qq.com/s?__biz=Test&mid=123&idx=1&sn=abc")
        assert cls is WeChatAdapter

    def test_http_scheme_routes(self):
        """HTTP (non-HTTPS) WeChat URLs also route correctly."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://mp\.weixin\.qq\.com/.*", WeChatAdapter)
        cls = route_url("http://mp.weixin.qq.com/s?__biz=Test")
        assert cls is WeChatAdapter

    def test_non_wechat_url_not_matched(self):
        """Non-WeChat URLs should not route to WeChatAdapter."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://mp\.weixin\.qq\.com/.*", WeChatAdapter)
        cls = route_url("https://weibo.com/12345/ABCdef")
        assert cls is not WeChatAdapter

    def test_case_insensitive_matching(self):
        """Pattern matching is case-insensitive."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://mp\.weixin\.qq\.com/.*", WeChatAdapter)
        cls = route_url("HTTPS://MP.WEIXIN.QQ.COM/s?test=1")
        assert cls is WeChatAdapter


# ── Full fetch integration ──────────────────────────────────────────


class TestWeChatAdapterFetch:
    def test_full_fetch_with_images(self):
        """End-to-end fetch with images and metadata."""
        html = _sample_wechat_html(
            title="微信测试文章",
            author="测试公众号",
            publish_date="2024-01-15 10:30",
            body_html="<p>这是一篇<strong>微信</strong>文章</p>",
            images=[
                "https://mmbiz.qpic.cn/mmbiz_jpg/test1/0?wx_fmt=jpeg",
                "https://mmbiz.qpic.cn/mmbiz_png/test2/0?wx_fmt=png",
            ],
        )

        adapter = WeChatAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            url = "https://mp.weixin.qq.com/s?__biz=Test&mid=123&idx=1&sn=abc"
            result = adapter.fetch(url)

        assert isinstance(result, RawContent)
        assert result.source_type == "wechat"
        assert result.url == url
        assert result.title == "微信测试文章"
        assert "微信" in result.content_md
        assert "测试公众号" in result.content_md
        assert "2024-01-15 10:30" in result.content_md
        assert len(result.images) == 2
        assert "https://mmbiz.qpic.cn/mmbiz_jpg/test1/0?wx_fmt=jpeg" in result.images

    def test_full_fetch_no_images(self):
        """Article with no images returns empty images list."""
        html = _sample_wechat_html(body_html="<p>纯文本文章</p>", images=None)

        adapter = WeChatAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://mp.weixin.qq.com/s?__biz=Test&mid=456")

        assert result.images == []
        assert "纯文本文章" in result.content_md

    def test_fetch_only_data_src_images(self):
        """Article with only data-src images (no src) extracts correctly."""
        html = """<html><body>
        <h1 id="activity-name">Data-src Test</h1>
        <a id="js_name">TestAcct</a>
        <em id="publish_time">2024-06-01</em>
        <div id="js_content">
            <img data-src="https://mmbiz.qpic.cn/img1.jpg" />
            <img data-src="https://mmbiz.qpic.cn/img2.jpg" />
        </div>
        </body></html>"""

        adapter = WeChatAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://mp.weixin.qq.com/s?test=1")

        assert len(result.images) == 2
        assert "https://mmbiz.qpic.cn/img1.jpg" in result.images
        assert "https://mmbiz.qpic.cn/img2.jpg" in result.images

    def test_fetch_no_title_falls_back(self):
        """Article without #activity-name falls back for title."""
        html = _sample_wechat_html(has_activity_name=False)
        # Remove any h1 too
        html = html.replace("<title>Test WeChat Article</title>", "")
        # Add an h1 fallback
        html = html.replace(
            '<div id="page-content">',
            '<div id="page-content"><h1>Fallback Title</h1>',
        )

        adapter = WeChatAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://mp.weixin.qq.com/s?test=1")

        assert result.title == "Fallback Title"

    def test_fetch_no_title_no_author_falls_back(self):
        """Article without title or author falls back to 'WeChat Article'."""
        html = _sample_wechat_html(has_activity_name=False, has_js_name=False)
        html = html.replace("<title>Test WeChat Article</title>", "")

        adapter = WeChatAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://mp.weixin.qq.com/s?test=1")

        assert result.title == "WeChat Article"

    def test_fetch_metadata_header(self):
        """Metadata header includes source, author, and date."""
        html = _sample_wechat_html(
            author="MyAccount",
            publish_date="2024-03-20 15:00",
        )

        adapter = WeChatAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            url = "https://mp.weixin.qq.com/s?__biz=Test&mid=789"
            result = adapter.fetch(url)

        assert f"Source: {url}" in result.content_md
        assert "Author: MyAccount" in result.content_md
        assert "Date: 2024-03-20 15:00" in result.content_md

    def test_fetch_very_long_article(self):
        """Very long article content is handled correctly."""
        long_body = "<p>" + "这是一段很长的微信文章内容。" * 500 + "</p>"
        html = _sample_wechat_html(body_html=long_body)

        adapter = WeChatAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch("https://mp.weixin.qq.com/s?test=long")

        assert isinstance(result, RawContent)
        assert "微信文章内容" in result.content_md


# ── Error handling ──────────────────────────────────────────────────


class TestWeChatErrorHandling:
    def test_403_forbidden_raises(self):
        """HTTP 403 raises AdapterError."""
        adapter = WeChatAdapter()
        resp = _mock_response(403)

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="HTTP 403"):
                adapter.fetch("https://mp.weixin.qq.com/s?__biz=blocked")

    def test_network_timeout_raises(self):
        """Network timeout raises AdapterError after retries."""
        adapter = WeChatAdapter()

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.side_effect = httpx.TimeoutException("timed out")

            with pytest.raises(AdapterError, match="timeout"):
                adapter.fetch("https://mp.weixin.qq.com/s?test=timeout")

    def test_missing_js_content_raises(self):
        """HTML without #js_content div raises AdapterError."""
        html = _sample_wechat_html(has_content_div=False)

        adapter = WeChatAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="missing #js_content"):
                adapter.fetch("https://mp.weixin.qq.com/s?test=nocontent")

    def test_connection_error_raises(self):
        """Network connection error raises AdapterError."""
        adapter = WeChatAdapter()

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.side_effect = httpx.ConnectError("connection refused")

            with pytest.raises(AdapterError, match="fetch failed"):
                adapter.fetch("https://mp.weixin.qq.com/s?test=connerr")

    def test_http_500_raises(self):
        """HTTP 500 raises AdapterError."""
        adapter = WeChatAdapter()
        resp = _mock_response(500)

        with patch("web_clip_helper.adapters.wechat.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="HTTP 500"):
                adapter.fetch("https://mp.weixin.qq.com/s?test=servererr")

    def test_non_wechat_url_raises_value_error(self):
        """Non-WeChat URL passed to route_url doesn't match."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://mp\.weixin\.qq\.com/.*", WeChatAdapter)
        cls = route_url("https://example.com/page")
        assert cls is not WeChatAdapter


# ── Adapter routing via route_url ───────────────────────────────────


class TestWeChatRouteUrlIntegration:
    def test_route_url_returns_wechat_adapter(self):
        """route_url returns WeChatAdapter for WeChat URLs after registration."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://mp\.weixin\.qq\.com/.*", WeChatAdapter)
        url = "https://mp.weixin.qq.com/s?__biz=MzIwNDM0NzUyNA==&mid=2247483660&idx=1&sn=test&scene=0"
        assert route_url(url) is WeChatAdapter

    def test_route_url_with_short_url(self):
        """Short WeChat URLs also route correctly."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://mp\.weixin\.qq\.com/.*", WeChatAdapter)
        assert route_url("https://mp.weixin.qq.com/s/ABC123") is WeChatAdapter
