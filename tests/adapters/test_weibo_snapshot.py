"""Tests for the WeiboSnapshotAdapter — redirect resolution, mid extraction, API fetch, errors."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from web_clip_helper.adapter import AdapterError, adapter_router, route_url
from web_clip_helper.adapters.weibo_snapshot import WeiboSnapshotAdapter
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
    headers: dict | None = None,
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.json.return_value = json_data or {}
    resp.headers = headers or {"content-type": "application/json; charset=utf-8"}

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
    status_title: str = "",
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
            "status_title": status_title,
        },
    }


_SNAPSHOT_URL = "https://mapp.api.weibo.cn/fx/abc123def.html"


def _setup_two_clients(mock_cls, redirect_resp, api_resp):
    """Configure a patched httpx.Client for two sequential adapter calls.

    Returns (client0, client1) for further customisation.
    """
    client0 = MagicMock()
    client1 = MagicMock()
    client0.get.return_value = redirect_resp
    client1.get.return_value = api_resp
    idx = [0]

    def _enter(_self):
        inst = [client0, client1][idx[0]]
        idx[0] += 1
        return inst

    mock_cls.return_value.__enter__ = _enter
    mock_cls.return_value.__exit__ = MagicMock(return_value=False)
    return client0, client1


def _setup_single_client(mock_cls, redirect_resp):
    """Configure a patched httpx.Client for a single redirect-stage call."""
    client_inst = MagicMock()
    client_inst.get.return_value = redirect_resp
    mock_cls.return_value.__enter__ = lambda _s: client_inst
    mock_cls.return_value.__exit__ = MagicMock(return_value=False)
    return client_inst


# ── URL pattern routing ─────────────────────────────────────────────


class TestWeiboSnapshotRouting:
    def test_snapshot_url_routes_to_weibo_snapshot_adapter(self):
        """Snapshot URL routes to WeiboSnapshotAdapter after registration."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://mapp\.api\.weibo\.cn/fx/.*", WeiboSnapshotAdapter)
        cls = route_url(_SNAPSHOT_URL)
        assert cls is WeiboSnapshotAdapter

    def test_non_matching_url_not_routed(self):
        """Non-snapshot URLs should not route to WeiboSnapshotAdapter."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://mapp\.api\.weibo\.cn/fx/.*", WeiboSnapshotAdapter)
        cls = route_url("https://weibo.com/12345/ABCdef")
        assert cls is not WeiboSnapshotAdapter

    def test_mapp_api_weibo_cn_variants(self):
        """Various mapp.api.weibo.cn/fx URLs should match."""
        from web_clip_helper.adapter import register_adapter

        register_adapter(r"https?://mapp\.api\.weibo\.cn/fx/.*", WeiboSnapshotAdapter)
        for url in [
            "https://mapp.api.weibo.cn/fx/abc.html",
            "http://mapp.api.weibo.cn/fx/xyz123.html",
            "https://mapp.api.weibo.cn/fx/",
            "https://MAPP.API.WEIBO.CN/FX/abc.html",
        ]:
            cls = route_url(url)
            assert cls is WeiboSnapshotAdapter, f"{url} did not route correctly"


# ── 302 → mid extraction ────────────────────────────────────────────


class TestMidExtraction:
    """Test mid extraction from various redirect Location header formats."""

    def test_full_m_weibo_cn_status_url(self):
        """Extract mid from https://m.weibo.cn/status/{mid}."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(200, json_data=_sample_api_response())

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert isinstance(result, RawContent)
        assert result.source_type == "weibo_snapshot"

    def test_relative_status_path(self):
        """Extract mid from relative /status/{mid} path."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "/status/5123456789012345"},
        )
        api_resp = _mock_response(200, json_data=_sample_api_response())

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert isinstance(result, RawContent)

    def test_location_with_query_string(self):
        """Extract mid from Location with query string appended."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345?from=xxx"},
        )
        api_resp = _mock_response(200, json_data=_sample_api_response())

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert isinstance(result, RawContent)


# ── Full fetch happy path ───────────────────────────────────────────


class TestWeiboSnapshotFetch:
    def test_full_fetch_with_images_and_metadata(self):
        """End-to-end: 302 redirect + API response → complete RawContent."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_data = _sample_api_response(
            text_html="<p>Hello <b>Weibo Snapshot</b>!</p>",
            pics=[
                {"large": {"url": "https://wx1.sinaimg.cn/large/snap1.jpg"}},
                {"large": {"url": "https://wx2.sinaimg.cn/large/snap2.jpg"}},
            ],
            author="SnapshotUser",
            reposts=42,
            comments=8,
            likes=300,
            created_at="Mon Feb 12 15:00:00 +0800 2024",
        )
        api_resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert isinstance(result, RawContent)
        assert result.source_type == "weibo_snapshot"
        assert result.url == _SNAPSHOT_URL
        assert result.is_dynamic is True
        assert "Hello" in result.content_md
        assert "Weibo Snapshot" in result.content_md
        assert result.images == [
            "https://wx1.sinaimg.cn/large/snap1.jpg",
            "https://wx2.sinaimg.cn/large/snap2.jpg",
        ]
        # Metadata header checks
        assert "Source:" in result.content_md
        assert "Author: SnapshotUser" in result.content_md
        assert "Mon Feb 12" in result.content_md
        assert "42 reposts" in result.content_md
        assert "8 comments" in result.content_md
        assert "300 likes" in result.content_md

    def test_fetch_with_status_title(self):
        """When status_title is present, it becomes the title."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(
            200,
            json_data=_sample_api_response(
                status_title="My Important Announcement",
                author="Announcer",
            ),
        )

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert result.title == "My Important Announcement"

    def test_fetch_title_falls_back_to_author(self):
        """Without status_title, title falls back to author screen_name."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(
            200,
            json_data=_sample_api_response(status_title="", author="FallbackAuthor"),
        )

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert result.title == "FallbackAuthor"

    def test_fetch_title_falls_back_to_mid(self):
        """Without status_title or author, title falls back to 'Weibo post {mid}'."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/999888777"},
        )
        api_resp = _mock_response(
            200,
            json_data=_sample_api_response(status_title="", author=""),
        )

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert result.title == "Weibo post 999888777"

    def test_fetch_no_text_content(self):
        """Post with empty text still returns valid RawContent with metadata header."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(
            200,
            json_data=_sample_api_response(text_html="", author="NoTextUser"),
        )

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert isinstance(result, RawContent)
        assert "Author: NoTextUser" in result.content_md
        assert "---" not in result.content_md  # No content means no separator

    def test_fetch_missing_user_field(self):
        """Post without user field uses empty string for author."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
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
        api_resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert "No user info" in result.content_md
        assert "Weibo post" in result.title


# ── Image extraction ────────────────────────────────────────────────


class TestSnapshotImageExtraction:
    def test_images_extracted_via_weibo_adapter(self):
        """Images are extracted via WeiboAdapter._extract_images (shared logic)."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_data = _sample_api_response(
            pics=[
                {"large": {"url": "https://wx1.sinaimg.cn/large/img1.jpg"}, "url": "https://wx1.sinaimg.cn/orj480/img1.jpg"},
                {"url": "https://wx2.sinaimg.cn/orj480/img2.jpg"},  # no large → fallback
            ],
        )
        api_resp = _mock_response(200, json_data=api_data)

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert len(result.images) == 2
        assert "https://wx1.sinaimg.cn/large/img1.jpg" in result.images
        assert "https://wx2.sinaimg.cn/orj480/img2.jpg" in result.images

    def test_no_pics_returns_empty_images(self):
        """Post without pics field returns empty images list."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(
            200,
            json_data=_sample_api_response(pics=[]),
        )

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert result.images == []


# ── Error scenarios ─────────────────────────────────────────────────


class TestWeiboSnapshotErrors:
    """All failure modes must raise AdapterError with descriptive messages."""

    def test_snapshot_returns_200_not_302(self):
        """Snapshot URL returning 200 instead of 302 → AdapterError."""
        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_single_client(mock_cls, _mock_response(status_code=200))
            with pytest.raises(AdapterError, match="未返回预期的 redirect"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_snapshot_returns_404(self):
        """Snapshot URL returning 404 → AdapterError."""
        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_single_client(mock_cls, _mock_response(status_code=404))
            with pytest.raises(AdapterError, match="未返回预期的 redirect"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_snapshot_returns_301(self):
        """Snapshot URL returning 301 instead of 302 → AdapterError."""
        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_single_client(mock_cls, _mock_response(status_code=301))
            with pytest.raises(AdapterError, match="未返回预期的 redirect"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_302_missing_location_header(self):
        """302 response without Location header → AdapterError."""
        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_single_client(mock_cls, _mock_response(status_code=302, headers={}))
            with pytest.raises(AdapterError, match="缺少 Location header"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_302_location_no_mid_pattern(self):
        """302 Location without /status/{mid} → AdapterError."""
        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_single_client(
                mock_cls,
                _mock_response(status_code=302, headers={"Location": "https://m.weibo.cn/some/other/path"}),
            )
            with pytest.raises(AdapterError, match="无法从快照 redirect 中提取帖子 ID"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_api_returns_ok_0(self):
        """m.weibo.cn API returns ok=0 → AdapterError."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(200, json_data={"ok": 0, "msg": "post deleted"})

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            with pytest.raises(AdapterError, match="post deleted"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_api_timeout(self):
        """m.weibo.cn API timeout → AdapterError."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _, client1 = _setup_two_clients(mock_cls, redirect_resp, _mock_response(200))
            client1.get.side_effect = httpx.TimeoutException("timed out")
            with pytest.raises(AdapterError, match="timeout"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_api_http_error(self):
        """m.weibo.cn API returns HTTP 500 → AdapterError."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(status_code=500)

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            with pytest.raises(AdapterError, match="HTTP 500"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_api_connection_error(self):
        """m.weibo.cn API connection failure → AdapterError."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _, client1 = _setup_two_clients(mock_cls, redirect_resp, _mock_response(200))
            client1.get.side_effect = httpx.ConnectError("connection refused")
            with pytest.raises(AdapterError, match="request failed"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_api_non_dict_response(self):
        """m.weibo.cn API returns a non-dict JSON → AdapterError."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(200)
        api_resp.json.return_value = "not a dict"

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            with pytest.raises(AdapterError, match="non-object"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_api_empty_data_field(self):
        """m.weibo.cn API returns ok=1 with empty data → AdapterError."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(200, json_data={"ok": 1, "data": {}})

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            with pytest.raises(AdapterError, match="empty data"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_snapshot_redirect_timeout(self):
        """Timeout during redirect resolution → AdapterError."""
        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            client = _setup_single_client(mock_cls, _mock_response(status_code=302))
            client.get.side_effect = httpx.TimeoutException("timed out")
            with pytest.raises(AdapterError, match="timeout"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_snapshot_redirect_connection_error(self):
        """Connection error during redirect resolution → AdapterError."""
        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            client = _setup_single_client(mock_cls, _mock_response(status_code=302))
            client.get.side_effect = httpx.ConnectError("connection refused")
            with pytest.raises(AdapterError, match="request failed"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)


# ── Metadata header ─────────────────────────────────────────────────


class TestMetadataHeader:
    """Verify author, date, stats are correctly formatted in output markdown."""

    def test_header_contains_source_url(self):
        """Metadata header includes the original snapshot URL."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(200, json_data=_sample_api_response())

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert _SNAPSHOT_URL in result.content_md

    def test_header_contains_clipped_timestamp(self):
        """Metadata header includes a 'Clipped:' timestamp."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(200, json_data=_sample_api_response())

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert "Clipped:" in result.content_md

    def test_header_contains_author(self):
        """Metadata header includes author screen_name."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(
            200,
            json_data=_sample_api_response(author="HeaderTestAuthor"),
        )

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert "Author: HeaderTestAuthor" in result.content_md

    def test_header_contains_date(self):
        """Metadata header includes the post creation date."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(
            200,
            json_data=_sample_api_response(created_at="Wed Mar 20 09:15:00 +0800 2024"),
        )

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert "Date: Wed Mar 20" in result.content_md

    def test_header_contains_stats(self):
        """Metadata header includes reposts, comments, likes."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(
            200,
            json_data=_sample_api_response(reposts=99, comments=42, likes=888),
        )

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert "99 reposts" in result.content_md
        assert "42 comments" in result.content_md
        assert "888 likes" in result.content_md

    def test_header_zero_stats(self):
        """Zero stats are displayed correctly."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(
            200,
            json_data=_sample_api_response(reposts=0, comments=0, likes=0),
        )

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert "0 reposts, 0 comments, 0 likes" in result.content_md


# ── Registry integration ────────────────────────────────────────────


class TestRegistryIntegration:
    """Verify that WeiboSnapshotAdapter is wired correctly through the real registry."""

    @staticmethod
    def _reload_adapter_modules():
        """Reload adapter modules so @register_adapter decorators re-fire after router clear."""
        import importlib

        import web_clip_helper.adapters.weibo_snapshot
        import web_clip_helper.adapters.weibo
        import web_clip_helper.adapters.generic

        importlib.reload(web_clip_helper.adapters.weibo_snapshot)
        importlib.reload(web_clip_helper.adapters.weibo)
        importlib.reload(web_clip_helper.adapters.generic)

    def test_registry_routes_snapshot_url_to_weibo_snapshot_adapter(self):
        """Importing _registry should make snapshot URLs route to WeiboSnapshotAdapter."""
        import importlib

        import web_clip_helper.adapters._registry as _reg

        importlib.reload(_reg)
        self._reload_adapter_modules()
        cls = route_url(_SNAPSHOT_URL)
        assert cls.__name__ == "WeiboSnapshotAdapter"
        assert cls.__module__ == "web_clip_helper.adapters.weibo_snapshot"

    def test_registry_weibo_url_not_routed_to_snapshot_adapter(self):
        """Standard weibo.cn URLs should NOT route to WeiboSnapshotAdapter."""
        import importlib

        import web_clip_helper.adapters._registry as _reg

        importlib.reload(_reg)
        self._reload_adapter_modules()
        cls = route_url("https://weibo.cn/status/5123456789012345")
        assert cls.__name__ != "WeiboSnapshotAdapter"


class TestAdapterPriority:
    """Confirm snapshot URLs route to WeiboSnapshotAdapter, not WeiboAdapter or GenericWebAdapter."""

    @staticmethod
    def _reload_adapter_modules():
        import importlib

        import web_clip_helper.adapters.weibo_snapshot
        import web_clip_helper.adapters.weibo
        import web_clip_helper.adapters.generic

        importlib.reload(web_clip_helper.adapters.weibo_snapshot)
        importlib.reload(web_clip_helper.adapters.weibo)
        importlib.reload(web_clip_helper.adapters.generic)

    def test_snapshot_url_not_weibo_adapter(self):
        """Snapshot URL should not be handled by WeiboAdapter."""
        import importlib

        import web_clip_helper.adapters._registry as _reg

        importlib.reload(_reg)
        self._reload_adapter_modules()
        from web_clip_helper.adapters.weibo import WeiboAdapter

        cls = route_url(_SNAPSHOT_URL)
        assert cls.__name__ != "WeiboAdapter"

    def test_snapshot_url_not_generic_adapter(self):
        """Snapshot URL should not fall through to GenericWebAdapter."""
        import importlib

        import web_clip_helper.adapters._registry as _reg

        importlib.reload(_reg)
        self._reload_adapter_modules()
        cls = route_url(_SNAPSHOT_URL)
        # If it's the fallback _GenericAdapter, that also means it didn't match
        # WeiboSnapshotAdapter's pattern — but it should match.
        assert cls.__name__ not in ("GenericWebAdapter", "_GenericAdapter")

    def test_snapshot_url_is_weibo_snapshot_adapter(self):
        """Snapshot URL must route to WeiboSnapshotAdapter when all adapters loaded."""
        import importlib

        import web_clip_helper.adapters._registry as _reg

        importlib.reload(_reg)
        self._reload_adapter_modules()
        cls = route_url(_SNAPSHOT_URL)
        assert cls.__name__ == "WeiboSnapshotAdapter"
        assert cls.__module__ == "web_clip_helper.adapters.weibo_snapshot"


# ── Edge cases ──────────────────────────────────────────────────────


class TestEdgeCaseRedirects:
    """Non-302 redirect codes (303, 307, 308) should be rejected."""

    @pytest.mark.parametrize("code", [303, 307, 308])
    def test_non_302_redirect_code_fails(self, code):
        """Redirect codes other than 302 should raise AdapterError."""
        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_single_client(mock_cls, _mock_response(status_code=code))
            with pytest.raises(AdapterError, match="未返回预期的 redirect"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)


class TestEdgeCaseMidExtraction:
    """Edge cases in mid extraction from Location header."""

    def test_very_long_mid_19_digits(self):
        """Very long mid (19+ digits) should be extracted and used correctly."""
        long_mid = "5123456789012345678"  # 19 digits
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": f"https://m.weibo.cn/status/{long_mid}"},
        )
        api_resp = _mock_response(200, json_data=_sample_api_response(status_title="", author=""))

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            c0, c1 = _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert isinstance(result, RawContent)
        assert result.title == f"Weibo post {long_mid}"
        # Verify the API was called with the correct mid
        c1.get.assert_called_once()
        call_url = c1.get.call_args[0][0]
        assert long_mid in call_url

    def test_location_with_fragment(self):
        """Location header with URL fragment (#comment) should still extract mid."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345#comment"},
        )
        api_resp = _mock_response(200, json_data=_sample_api_response())

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            result = WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

        assert isinstance(result, RawContent)
        assert result.source_type == "weibo_snapshot"


class TestEdgeCaseApiResponse:
    """Edge cases in API response handling."""

    def test_api_json_decode_error(self):
        """Non-JSON body from API should raise an unhandled exception (adapter doesn't catch ValueError).

        NOTE: The adapter only catches httpx.TimeoutException, HTTPStatusError, and
        RequestError. A JSON decode error (ValueError subclass) propagates uncaught.
        This test documents the actual behavior — a future fix should wrap it in AdapterError.
        """
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(200, text="<html>Error</html>")
        api_resp.json.side_effect = ValueError("JSON decode error")

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            with pytest.raises(ValueError, match="JSON decode error"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)

    def test_api_ok_1_data_null(self):
        """API returns ok=1 but data is null → AdapterError (empty data)."""
        redirect_resp = _mock_response(
            status_code=302,
            headers={"Location": "https://m.weibo.cn/status/5123456789012345"},
        )
        api_resp = _mock_response(200, json_data={"ok": 1, "data": None})

        with patch("web_clip_helper.adapters.weibo_snapshot.httpx.Client") as mock_cls:
            _setup_two_clients(mock_cls, redirect_resp, api_resp)
            with pytest.raises(AdapterError, match="empty data"):
                WeiboSnapshotAdapter().fetch(_SNAPSHOT_URL)
