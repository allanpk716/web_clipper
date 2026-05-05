"""Tests for is_dynamic field propagation: RawContent → adapters → pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.models import RawContent


# ── RawContent unit tests ───────────────────────────────────────────


class TestRawContentIsDynamic:
    """Verify the is_dynamic field on the RawContent dataclass."""

    def test_default_is_false(self) -> None:
        r = RawContent(url="https://example.com", title="t", content_md="c")
        assert r.is_dynamic is False

    def test_can_set_true(self) -> None:
        r = RawContent(
            url="https://example.com",
            title="t",
            content_md="c",
            is_dynamic=True,
        )
        assert r.is_dynamic is True


# ── Adapter tests ───────────────────────────────────────────────────


class TestWeiboAdapterIsDynamic:
    """WeiboAdapter.fetch() must return is_dynamic=True."""

    @patch("web_clip_helper.adapters.weibo.httpx.Client")
    def test_weibo_adapter_dynamic(self, mock_client_cls: MagicMock) -> None:
        from web_clip_helper.adapters.weibo import WeiboAdapter

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": 1,
            "data": {
                "text": "<p>Hello</p>",
                "pics": [],
                "user": {"screen_name": "test_user"},
                "created_at": "2024-01-01",
                "reposts_count": 0,
                "comments_count": 0,
                "attitudes_count": 0,
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        adapter = WeiboAdapter()
        result = adapter.fetch("https://m.weibo.cn/status/123456")
        assert result.is_dynamic is True


class TestWeiboHeadlineAdapterIsDynamic:
    """WeiboHeadlineAdapter.fetch() must return is_dynamic=True."""

    @patch("web_clip_helper.adapters.weibo_headline.httpx.Client")
    def test_headline_adapter_dynamic(self, mock_client_cls: MagicMock) -> None:
        from web_clip_helper.adapters.weibo_headline import WeiboHeadlineAdapter

        html = (
            "<html><body>"
            '<h1 class="article-title">Test Article</h1>'
            '<div id="articlecontent"><p>Content here</p></div>'
            "</body></html>"
        )
        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        adapter = WeiboHeadlineAdapter()
        result = adapter.fetch(
            "https://weibo.com/ttarticle/p/show?id=230940123"
        )
        assert result.is_dynamic is True


class TestWeiboCardAdapterIsDynamic:
    """WeiboCardAdapter.fetch() must return is_dynamic=True."""

    @patch("web_clip_helper.adapters.weibo_card.httpx.Client")
    def test_card_adapter_dynamic(self, mock_client_cls: MagicMock) -> None:
        from web_clip_helper.adapters.weibo_card import WeiboCardAdapter

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": "100000",
            "data": {
                "title": "Card Article",
                "content": "<p>Card content</p>",
                "userinfo": {"screen_name": "author"},
                "complete_create_at": "2024-01-01",
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

        adapter = WeiboCardAdapter()
        result = adapter.fetch(
            "https://card.weibo.com/article/m/show/id/123456"
        )
        assert result.is_dynamic is True


class TestGitHubAdapterIsDynamic:
    """GitHubAdapter.fetch() must return is_dynamic=False (default)."""

    def test_github_adapter_not_dynamic(self) -> None:
        from unittest.mock import patch, MagicMock

        readme_resp = MagicMock()
        readme_resp.status_code = 200
        readme_resp.text = "# Hello World"

        mock_client = MagicMock()
        mock_client.get.return_value = readme_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        from web_clip_helper.adapters.github import GitHubAdapter

        with patch("web_clip_helper.adapters.github.httpx.Client", return_value=mock_client):
            adapter = GitHubAdapter()
            result = adapter.fetch("https://github.com/user/repo")
            assert result.is_dynamic is False


# ── Pipeline propagation tests ──────────────────────────────────────


class TestPipelineIsDynamicPropagation:
    """Verify pipeline passes is_dynamic to save_clip."""

    @patch("web_clip_helper.services.clip.ClipIndex")
    @patch("web_clip_helper.services.clip.StorageManager")
    @patch("web_clip_helper.services.clip._enrich_with_llm")
    def test_clip_url_passes_dynamic(
        self,
        mock_llm: MagicMock,
        mock_storage_cls: MagicMock,
        mock_index_cls: MagicMock,
    ) -> None:
        from web_clip_helper.pipeline import _store_and_index

        mock_llm.return_value = ("title", [], "")
        mock_storage = MagicMock()
        mock_storage.create_entry.return_value = __import__("pathlib").Path("/tmp/test-entry")
        mock_storage.get_images_dir.return_value = __import__("pathlib").Path("/tmp/test-entry/images")
        mock_storage.save_markdown.return_value = __import__("pathlib").Path("/tmp/test-entry/index.md")
        mock_storage_cls.return_value = mock_storage

        mock_index = MagicMock()
        mock_index.save_clip.return_value = 1
        mock_index_cls.return_value = mock_index

        config = MagicMock()
        config.storage_path = "/tmp/storage"
        config.db_path = "/tmp/test.db"
        config.llm.api_key = ""

        raw = RawContent(
            url="https://m.weibo.cn/status/123",
            title="Test",
            content_md="Hello",
            images=[],
            source_type="weibo",
            is_dynamic=True,
        )

        _store_and_index(raw, config)

        # Verify save_clip was called with is_dynamic=1
        call_args = mock_index.save_clip.call_args[0][0]
        assert call_args["is_dynamic"] == 1

    @patch("web_clip_helper.services.clip.ClipIndex")
    @patch("web_clip_helper.services.clip.StorageManager")
    @patch("web_clip_helper.services.clip._enrich_with_llm")
    def test_clip_text_keeps_dynamic_false(
        self,
        mock_llm: MagicMock,
        mock_storage_cls: MagicMock,
        mock_index_cls: MagicMock,
    ) -> None:
        from web_clip_helper.pipeline import _store_and_index

        mock_llm.return_value = ("text clip", [], "")
        mock_storage = MagicMock()
        mock_storage.create_entry.return_value = __import__("pathlib").Path("/tmp/test-entry")
        mock_storage.get_images_dir.return_value = __import__("pathlib").Path("/tmp/test-entry/images")
        mock_storage.save_markdown.return_value = __import__("pathlib").Path("/tmp/test-entry/index.md")
        mock_storage_cls.return_value = mock_storage

        mock_index = MagicMock()
        mock_index.save_clip.return_value = 1
        mock_index_cls.return_value = mock_index

        config = MagicMock()
        config.storage_path = "/tmp/storage"
        config.db_path = "/tmp/test.db"
        config.llm.api_key = ""

        raw = RawContent(
            url="",
            title="text clip",
            content_md="Some text",
            images=[],
            source_type="text",
        )

        _store_and_index(raw, config)

        # Verify save_clip was called with is_dynamic=0 (default)
        call_args = mock_index.save_clip.call_args[0][0]
        assert call_args["is_dynamic"] == 0
