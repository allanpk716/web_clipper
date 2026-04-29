"""Tests for the Weibo Headline adapter — URL routing, HTML parsing, error handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from web_clip_helper.adapter import AdapterError, adapter_router, route_url
from web_clip_helper.adapters.weibo import WeiboAdapter
from web_clip_helper.adapters.weibo_headline import WeiboHeadlineAdapter
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


def _sample_headline_html(
    title: str = "测试头条文章标题",
    author: str = "测试作者",
    publish_date: str = "2024-03-15 10:30",
    body_html: str = "<p>这是一篇头条文章的内容。</p>",
    images: list[str] | None = None,
) -> str:
    """Build a sample Weibo Headline HTML page."""
    img_tags = ""
    for img_url in images or []:
        img_tags += f'<img data-src="{img_url}" src="">'

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title} – 头条文章</title>
</head>
<body>
    <h1 class="article-title">{title}</h1>
    <div class="author">{author}</div>
    <div class="article-time">{publish_date}</div>
    <div id="articlecontent">
        {body_html}
        {img_tags}
    </div>
</body>
</html>"""


# ── URL pattern routing ─────────────────────────────────────────────


class TestWeiboHeadlineRouting:
    def test_ttarticle_url_routes_to_headline_adapter(self):
        """ttarticle URLs route to WeiboHeadlineAdapter, not WeiboAdapter."""
        from web_clip_helper.adapter import register_adapter

        # Register in the correct order: headline first, then generic weibo
        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/ttarticle/.*",
            WeiboHeadlineAdapter,
        )
        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/.*",
            WeiboAdapter,
        )

        url = "https://weibo.com/ttarticle/p/show?id=2309401234567890"
        cls = route_url(url)
        assert cls is WeiboHeadlineAdapter
        assert cls is not WeiboAdapter

    def test_ttarticle_url_not_shadowed_by_weibo(self):
        """Even with generic Weibo registered first, headline still matches correctly
        when registered before it."""
        from web_clip_helper.adapter import register_adapter

        # Headline must be registered first for first-match-wins
        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/ttarticle/.*",
            WeiboHeadlineAdapter,
        )
        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/.*",
            WeiboAdapter,
        )

        url = "https://weibo.com/ttarticle/p/show?id=2309401234567890"
        cls = route_url(url)
        assert cls is WeiboHeadlineAdapter

    def test_regular_weibo_url_not_matched_by_headline(self):
        """Regular Weibo URLs should NOT match the headline pattern."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/ttarticle/.*",
            WeiboHeadlineAdapter,
        )
        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/.*",
            WeiboAdapter,
        )

        cls = route_url("https://weibo.com/12345/ABCdef")
        assert cls is WeiboAdapter
        assert cls is not WeiboHeadlineAdapter

    def test_ttarticle_m_weibo_cn_routes_correctly(self):
        """m.weibo.cn/ttarticle/ URLs also route to headline adapter."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/ttarticle/.*",
            WeiboHeadlineAdapter,
        )
        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/.*",
            WeiboAdapter,
        )

        url = "https://m.weibo.cn/ttarticle/p/show?id=2309401234567890"
        cls = route_url(url)
        assert cls is WeiboHeadlineAdapter

    def test_case_insensitive_matching(self):
        """URL pattern matching is case-insensitive."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(
            r"https?://(m\.)?weibo\.c(n|om)/ttarticle/.*",
            WeiboHeadlineAdapter,
        )

        cls = route_url("HTTPS://WEIBO.COM/TTARTICLE/P/SHOW?id=123")
        assert cls is WeiboHeadlineAdapter


# ── HTML parsing ────────────────────────────────────────────────────


class TestHtmlParsing:
    def test_extract_title_from_h1_class(self):
        """Title extracted from <h1 class='article-title'>."""
        html = '<h1 class="article-title">我的文章标题</h1>'
        from web_clip_helper.adapters.weibo_headline import _extract_title

        assert _extract_title(html) == "我的文章标题"

    def test_extract_title_from_plain_h1(self):
        """Title falls back to plain <h1>."""
        html = "<h1>普通标题</h1>"
        from web_clip_helper.adapters.weibo_headline import _extract_title

        assert _extract_title(html) == "普通标题"

    def test_extract_title_from_title_tag(self):
        """Title falls back to <title> with suffix stripped."""
        html = "<title>文章标题 – 头条文章</title>"
        from web_clip_helper.adapters.weibo_headline import _extract_title

        result = _extract_title(html)
        assert "文章标题" in result
        assert "头条文章" not in result

    def test_extract_author_from_class(self):
        """Author extracted from element with 'author' class."""
        html = '<span class="author">作者名</span>'
        from web_clip_helper.adapters.weibo_headline import _extract_author

        assert _extract_author(html) == "作者名"

    def test_extract_author_from_meta(self):
        """Author extracted from <meta name='author'>."""
        html = '<meta name="author" content="元数据作者">'
        from web_clip_helper.adapters.weibo_headline import _extract_author

        assert _extract_author(html) == "元数据作者"

    def test_extract_author_from_meta_reversed_attrs(self):
        """Author extracted when content comes before name in meta tag."""
        html = '<meta content="属性反转作者" name="author">'
        from web_clip_helper.adapters.weibo_headline import _extract_author

        assert _extract_author(html) == "属性反转作者"

    def test_extract_publish_date_from_class(self):
        """Date extracted from element with time-related class."""
        html = '<span class="article-time">2024-03-15 10:30</span>'
        from web_clip_helper.adapters.weibo_headline import _extract_publish_date

        assert _extract_publish_date(html) == "2024-03-15 10:30"

    def test_extract_publish_date_from_time_datetime(self):
        """Date extracted from <time datetime='...'>."""
        html = '<time datetime="2024-03-15T10:30:00+08:00"></time>'
        from web_clip_helper.adapters.weibo_headline import _extract_publish_date

        assert _extract_publish_date(html) == "2024-03-15T10:30:00+08:00"

    def test_extract_images_with_data_src(self):
        """Images extracted from data-src attribute (lazy loading)."""
        html = '<div><img data-src="https://wx1.sinaimg.cn/large/a.jpg" src=""><img data-src="https://wx2.sinaimg.cn/large/b.jpg" src=""></div>'
        from web_clip_helper.adapters.weibo_headline import _extract_images

        images = _extract_images(html)
        assert len(images) == 2
        assert "https://wx1.sinaimg.cn/large/a.jpg" in images

    def test_extract_images_fallback_to_src(self):
        """Images fall back to src when data-src is absent."""
        html = '<div><img src="https://example.com/img.jpg"></div>'
        from web_clip_helper.adapters.weibo_headline import _extract_images

        images = _extract_images(html)
        assert images == ["https://example.com/img.jpg"]

    def test_extract_images_dedup(self):
        """Duplicate image URLs are deduplicated."""
        html = '<div><img src="https://example.com/img.jpg"><img src="https://example.com/img.jpg"></div>'
        from web_clip_helper.adapters.weibo_headline import _extract_images

        images = _extract_images(html)
        assert len(images) == 1

    def test_extract_images_skips_data_uris(self):
        """data: URIs are skipped."""
        html = '<div><img src="data:image/png;base64,abc123"></div>'
        from web_clip_helper.adapters.weibo_headline import _extract_images

        images = _extract_images(html)
        assert len(images) == 0

    def test_extract_content_html_from_articlecontent(self):
        """Content extracted from #articlecontent div."""
        html = '<div id="articlecontent"><p>文章正文</p></div>'
        from web_clip_helper.adapters.weibo_headline import _extract_content_html

        content = _extract_content_html(html)
        assert "<p>文章正文</p>" in content

    def test_extract_content_html_from_article_class(self):
        """Content extracted from .article-content div."""
        html = '<div class="article-content"><p>文章内容</p></div>'
        from web_clip_helper.adapters.weibo_headline import _extract_content_html

        content = _extract_content_html(html)
        assert "<p>文章内容</p>" in content

    def test_extract_content_html_from_article_tag(self):
        """Content falls back to <article> tag."""
        html = "<article><p>后备内容</p></article>"
        from web_clip_helper.adapters.weibo_headline import _extract_content_html

        content = _extract_content_html(html)
        assert "<p>后备内容</p>" in content

    def test_extract_content_html_empty_when_no_container(self):
        """Returns empty string when no content container is found."""
        html = "<html><body><p>没有容器</p></body></html>"
        from web_clip_helper.adapters.weibo_headline import _extract_content_html

        content = _extract_content_html(html)
        assert content == ""


# ── Full fetch integration ──────────────────────────────────────────


class TestWeiboHeadlineFetch:
    def test_full_fetch_with_images(self):
        """End-to-end fetch with images and metadata."""
        html = _sample_headline_html(
            title="测试文章",
            author="测试作者",
            publish_date="2024-03-15",
            body_html="<p>正文内容<strong>加粗</strong></p>",
            images=["https://wx1.sinaimg.cn/large/test.jpg"],
        )

        adapter = WeiboHeadlineAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(
                "https://weibo.com/ttarticle/p/show?id=2309401234567890"
            )

        assert isinstance(result, RawContent)
        assert result.source_type == "weibo_headline"
        assert result.url == "https://weibo.com/ttarticle/p/show?id=2309401234567890"
        assert result.title == "测试文章"
        assert "正文内容" in result.content_md
        assert "加粗" in result.content_md
        assert "测试作者" in result.content_md
        assert "2024-03-15" in result.content_md
        assert "https://wx1.sinaimg.cn/large/test.jpg" in result.images

    def test_full_fetch_no_images(self):
        """Article with no images returns empty images list."""
        html = _sample_headline_html(
            title="无图文章",
            body_html="<p>纯文本文章</p>",
            images=[],
        )

        adapter = WeiboHeadlineAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(
                "https://weibo.com/ttarticle/p/show?id=230940999"
            )

        assert result.images == []
        assert "纯文本文章" in result.content_md

    def test_full_fetch_no_author_no_date(self):
        """Article missing author/date uses defaults and emits warning."""
        html = """<!DOCTYPE html>
<html><head><title>简单标题</title></head>
<body>
    <h1>简单文章</h1>
    <div id="articlecontent"><p>内容</p></div>
</body></html>"""

        adapter = WeiboHeadlineAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with patch("web_clip_helper.adapters.weibo_headline.jsonl_emit_warning") as mock_warn:
                result = adapter.fetch(
                    "https://weibo.com/ttarticle/p/show?id=123"
                )

        assert result.title == "简单文章"
        assert "Author:" not in result.content_md
        mock_warn.assert_called_once()

    def test_fetch_preserves_url(self):
        """The original URL is preserved in the result."""
        html = _sample_headline_html()
        url = "https://weibo.com/ttarticle/p/show?id=2309401234567890"

        adapter = WeiboHeadlineAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(url)

        assert result.url == url

    def test_fetch_long_article(self):
        """Very long article content is handled correctly."""
        long_body = "<p>" + "这是一段很长的头条文章内容。" * 500 + "</p>"
        html = _sample_headline_html(body_html=long_body)

        adapter = WeiboHeadlineAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(
                "https://weibo.com/ttarticle/p/show?id=999"
            )

        assert "头条文章内容" in result.content_md

    def test_fetch_many_images(self):
        """Article with many images extracts all of them."""
        images = [f"https://wx1.sinaimg.cn/large/img{i}.jpg" for i in range(20)]
        html = _sample_headline_html(images=images)

        adapter = WeiboHeadlineAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            result = adapter.fetch(
                "https://weibo.com/ttarticle/p/show?id=555"
            )

        assert len(result.images) == 20


# ── Error handling ──────────────────────────────────────────────────


class TestWeiboHeadlineErrorHandling:
    def test_http_404_raises(self):
        """HTTP 404 raises AdapterError."""
        adapter = WeiboHeadlineAdapter()
        resp = _mock_response(404)

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="HTTP 404"):
                adapter.fetch("https://weibo.com/ttarticle/p/show?id=0")

    def test_http_500_raises(self):
        """HTTP 500 raises AdapterError."""
        adapter = WeiboHeadlineAdapter()
        resp = _mock_response(500)

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="HTTP 500"):
                adapter.fetch("https://weibo.com/ttarticle/p/show?id=0")

    def test_network_timeout_raises(self):
        """Network timeout raises AdapterError after retries."""
        adapter = WeiboHeadlineAdapter()

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.side_effect = httpx.TimeoutException("timed out")

            with pytest.raises(AdapterError, match="timeout"):
                adapter.fetch("https://weibo.com/ttarticle/p/show?id=123")

    def test_connection_error_raises(self):
        """Connection error raises AdapterError."""
        adapter = WeiboHeadlineAdapter()

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.side_effect = httpx.ConnectError("connection refused")

            with pytest.raises(AdapterError, match="fetch failed"):
                adapter.fetch("https://weibo.com/ttarticle/p/show?id=123")

    def test_missing_content_container_raises(self):
        """HTML without content container raises AdapterError."""
        html = "<html><body><h1>标题</h1><p>没有容器</p></body></html>"
        adapter = WeiboHeadlineAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="missing content container"):
                adapter.fetch("https://weibo.com/ttarticle/p/show?id=123")

    def test_empty_html_raises(self):
        """Empty HTML response raises AdapterError."""
        adapter = WeiboHeadlineAdapter()
        resp = _mock_response(200, text="")

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            with pytest.raises(AdapterError, match="missing content container"):
                adapter.fetch("https://weibo.com/ttarticle/p/show?id=123")

    def test_invalid_headline_url_still_fetches(self):
        """Adapter attempts fetch even with unusual URL (validation is at router level)."""
        html = _sample_headline_html(title="有效内容")
        adapter = WeiboHeadlineAdapter()
        resp = _mock_response(200, text=html)

        with patch("web_clip_helper.adapters.weibo_headline.httpx.Client") as mock_client_cls:
            client_inst = MagicMock()
            mock_client_cls.return_value.__enter__ = lambda s: client_inst
            mock_client_cls.return_value.__exit__ = lambda s, *a: None
            client_inst.get.return_value = resp

            # The adapter itself doesn't validate URL format — that's the router's job
            result = adapter.fetch("https://weibo.com/ttarticle/p/show?id=invalid")

        assert result.title == "有效内容"
