"""End-to-end pipeline tests — clip_url and clip_text with mocked adapters."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.config import Config
from web_clip_helper.models import RawContent
from web_clip_helper.pipeline import clip_text, clip_url

# Trigger adapter registration
import web_clip_helper.adapters._registry  # noqa: F401


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """Return a Config pointing at temp directories."""
    return Config(
        storage_path=str(tmp_path / "clips"),
        db_path=str(tmp_path / "test.db"),
    )


@pytest.fixture
def sample_raw() -> RawContent:
    """Return a sample RawContent from a GitHub adapter."""
    return RawContent(
        url="https://github.com/psf/requests",
        title="psf/requests",
        content_md="# Requests\n\nA simple HTTP library.\n\n![logo](https://example.com/logo.png)",
        images=["https://example.com/logo.png"],
        source_type="github",
        fetched_at=datetime(2024, 1, 15, 12, 0, 0),
    )


def _capture_jsonl(capsys):
    """Parse captured stdout as JSONL lines."""
    output = capsys.readouterr().out
    lines = [line for line in output.strip().split("\n") if line.strip()]
    return [json.loads(line) for line in lines]


class TestClipUrl:
    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_url_creates_markdown_file(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        tmp_path: Path,
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {"https://example.com/logo.png": "images/img_001.jpg"}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url("https://github.com/psf/requests", config)

        assert result is not None
        assert result.markdown_path.exists()
        content = result.markdown_path.read_text(encoding="utf-8")
        assert "Requests" in content
        assert "images/img_001.jpg" in content

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_url_creates_sqlite_record(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url("https://github.com/psf/requests", config)

        assert result is not None
        assert result.record_id is not None

        from web_clip_helper.index import ClipIndex
        idx = ClipIndex(config.db_path)
        record = idx.get_clip(result.record_id)
        assert record is not None
        assert record["url"] == "https://github.com/psf/requests"
        assert record["source_type"] == "github"
        idx.close()

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_url_creates_images_dir(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {"https://example.com/logo.png": "images/img_001.jpg"}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url("https://github.com/psf/requests", config)

        assert result is not None
        images_dir = result.folder_path / "images"
        assert images_dir.exists()

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_url_jsonl_output(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        capsys,
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url("https://github.com/psf/requests", config)

        messages = _capture_jsonl(capsys)
        types = [m["type"] for m in messages]

        assert "progress" in types
        assert "result" in types

        # Find the result message
        result_msgs = [m for m in messages if m["type"] == "result"]
        assert len(result_msgs) == 1
        assert result_msgs[0]["source_type"] == "github"

    @patch("web_clip_helper.pipeline.route_url")
    def test_url_adapter_error(
        self,
        mock_route: MagicMock,
        config: Config,
        capsys,
    ) -> None:
        from web_clip_helper.adapter import AdapterError
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter

        with patch.object(GitHubAdapter, "fetch", side_effect=AdapterError("404 Not Found")):
            result = clip_url("https://github.com/nonexistent/repo", config)

        assert result is None
        messages = _capture_jsonl(capsys)
        error_msgs = [m for m in messages if m["type"] == "error"]
        assert len(error_msgs) >= 1
        assert error_msgs[0]["stage"] == "fetch"

    @patch("web_clip_helper.pipeline.route_url")
    def test_url_routing_error(
        self,
        mock_route: MagicMock,
        config: Config,
        capsys,
    ) -> None:
        mock_route.side_effect = ValueError("Invalid URL")

        result = clip_url("", config)
        assert result is None
        messages = _capture_jsonl(capsys)
        error_msgs = [m for m in messages if m["type"] == "error"]
        assert len(error_msgs) >= 1
        assert error_msgs[0]["stage"] == "routing"

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_url_no_images(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
    ) -> None:
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://example.com/article",
            title="No Images Article",
            content_md="Just text, no images.",
            images=[],
            source_type="web",
        )

        with patch.object(GenericWebAdapter, "fetch", return_value=raw):
            result = clip_url("https://example.com/article", config)

        assert result is not None
        assert result.image_count == 0

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_url_image_download_failure_non_fatal(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        capsys,
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        # Image download fails — returns original URL (not a local path)
        mock_dl.return_value = {"https://example.com/img.png": "https://example.com/img.png"}

        raw = RawContent(
            url="https://github.com/test/repo",
            title="Image Fail Test",
            content_md="![img](https://example.com/img.png)",
            images=["https://example.com/img.png"],
            source_type="github",
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            result = clip_url("https://github.com/test/repo", config)

        assert result is not None
        assert result.image_count == 0
        messages = _capture_jsonl(capsys)
        # Should still complete (with warning possibly)
        result_msgs = [m for m in messages if m["type"] == "result"]
        assert len(result_msgs) == 1


class TestClipText:
    def test_text_creates_markdown(self, config: Config, tmp_path: Path) -> None:
        result = clip_text("Hello, this is some raw text to clip.", config)

        assert result is not None
        assert result.markdown_path.exists()
        content = result.markdown_path.read_text(encoding="utf-8")
        assert "Hello, this is some raw text" in content

    def test_text_creates_sqlite_record(self, config: Config) -> None:
        result = clip_text("Some text content", config)

        assert result is not None
        assert result.record_id is not None

        from web_clip_helper.index import ClipIndex
        idx = ClipIndex(config.db_path)
        record = idx.get_clip(result.record_id)
        assert record is not None
        assert record["source_type"] == "text"
        assert record["url"] == ""
        idx.close()

    def test_text_title_from_first_50_chars(self, config: Config) -> None:
        text = "This is a fairly long piece of text that should be truncated for the title"
        result = clip_text(text, config)

        assert result is not None
        from web_clip_helper.index import ClipIndex
        idx = ClipIndex(config.db_path)
        record = idx.get_clip(result.record_id)
        assert record is not None
        assert record["title"] == text[:50]
        idx.close()

    def test_text_empty_returns_none(self, config: Config) -> None:
        result = clip_text("", config)
        assert result is None

    def test_text_whitespace_only_returns_none(self, config: Config) -> None:
        result = clip_text("   \n\t  ", config)
        assert result is None

    def test_text_no_images(self, config: Config) -> None:
        result = clip_text("Just text", config)
        assert result is not None
        assert result.image_count == 0


class TestReplaceImageUrls:
    def test_replaces_markdown_images(self) -> None:
        from web_clip_helper.pipeline import _replace_image_urls

        md = "![logo](https://example.com/logo.png)"
        result = _replace_image_urls(md, {"https://example.com/logo.png": "images/img_001.jpg"})
        assert "images/img_001.jpg" in result
        assert "https://example.com/logo.png" not in result

    def test_replaces_multiple_images(self) -> None:
        from web_clip_helper.pipeline import _replace_image_urls

        md = "![a](https://a.com/a.png) and ![b](https://b.com/b.png)"
        result = _replace_image_urls(md, {
            "https://a.com/a.png": "images/img_001.jpg",
            "https://b.com/b.png": "images/img_002.png",
        })
        assert "images/img_001.jpg" in result
        assert "images/img_002.png" in result

    def test_preserves_unmapped_urls(self) -> None:
        from web_clip_helper.pipeline import _replace_image_urls

        md = "![logo](https://example.com/logo.png)"
        result = _replace_image_urls(md, {})
        assert "https://example.com/logo.png" in result


class TestNegativePaths:
    """Negative tests for error handling and boundary conditions."""

    @patch("web_clip_helper.pipeline.route_url")
    def test_unexpected_adapter_exception(
        self,
        mock_route: MagicMock,
        config: Config,
        capsys,
    ) -> None:
        """Adapter throws a non-AdapterError exception."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter

        with patch.object(GitHubAdapter, "fetch", side_effect=RuntimeError("boom")):
            result = clip_url("https://github.com/test/repo", config)

        assert result is None
        messages = _capture_jsonl(capsys)
        errors = [m for m in messages if m["type"] == "error"]
        assert any(e["stage"] == "fetch" for e in errors)

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_storage_write_failure(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        capsys,
    ) -> None:
        """StorageManager.create_entry raises OSError."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://github.com/test/repo",
            title="Test",
            content_md="content",
            images=[],
            source_type="github",
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            with patch(
                "web_clip_helper.pipeline.StorageManager.create_entry",
                side_effect=OSError("Permission denied"),
            ):
                result = clip_url("https://github.com/test/repo", config)

        assert result is None
        messages = _capture_jsonl(capsys)
        errors = [m for m in messages if m["type"] == "error"]
        assert any(e["stage"] == "storage" for e in errors)

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_sqlite_failure(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        capsys,
    ) -> None:
        """ClipIndex.save_clip raises an exception."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://github.com/test/repo",
            title="Test",
            content_md="content",
            images=[],
            source_type="github",
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            with patch(
                "web_clip_helper.pipeline.ClipIndex.save_clip",
                side_effect=Exception("DB error"),
            ):
                result = clip_url("https://github.com/test/repo", config)

        assert result is None
        messages = _capture_jsonl(capsys)
        errors = [m for m in messages if m["type"] == "error"]
        assert any(e["stage"] == "index" for e in errors)

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_very_long_content(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
    ) -> None:
        """Content with very long markdown body."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter
        mock_dl.return_value = {}

        long_md = "A" * 100_000
        raw = RawContent(
            url="https://example.com/long",
            title="Long Article",
            content_md=long_md,
            images=[],
            source_type="web",
        )

        with patch.object(GenericWebAdapter, "fetch", return_value=raw):
            result = clip_url("https://example.com/long", config)

        assert result is not None
        assert result.markdown_path.stat().st_size > 100_000

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_many_images(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
    ) -> None:
        """Content with 50+ images."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter

        urls = [f"https://example.com/img_{i}.png" for i in range(55)]
        url_map = {u: f"images/img_{i:03d}.png" for i, u in enumerate(urls, 1)}
        mock_dl.return_value = url_map

        md = "\n".join(f"![img {i}]({u})" for i, u in enumerate(urls))
        raw = RawContent(
            url="https://github.com/test/many-images",
            title="Many Images",
            content_md=md,
            images=urls,
            source_type="github",
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            result = clip_url("https://github.com/test/many-images", config)

        assert result is not None
        assert result.image_count == 55
