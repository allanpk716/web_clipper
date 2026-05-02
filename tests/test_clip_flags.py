"""Tests for --no-images flag on the clip command."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.config import Config
from web_clip_helper.models import RawContent
from web_clip_helper.pipeline import clip_url

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
    """Return a sample RawContent with images."""
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


class TestNoImagesFlag:
    """Tests for skip_images parameter propagation and behavior."""

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_skip_images_does_not_call_download_images(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        """When skip_images=True, download_images() should never be called."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url(
                "https://github.com/psf/requests",
                config,
                skip_images=True,
            )

        mock_dl.assert_not_called()
        assert result is not None
        assert result.image_count == 0

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_skip_images_preserves_remote_urls(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        tmp_path: Path,
    ) -> None:
        """When skip_images=True, remote URLs remain untouched in markdown."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url(
                "https://github.com/psf/requests",
                config,
                skip_images=True,
            )

        assert result is not None
        md_content = result.markdown_path.read_text(encoding="utf-8")
        assert "https://example.com/logo.png" in md_content
        assert "images/" not in md_content.split("https://example.com/logo.png")[0][-20:]

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_skip_images_reports_zero_count(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        capsys,
    ) -> None:
        """When skip_images=True, image_count in JSONL result is 0."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url(
                "https://github.com/psf/requests",
                config,
                skip_images=True,
            )

        assert result is not None
        assert result.image_count == 0

        lines = _capture_jsonl(capsys)
        result_lines = [l for l in lines if l.get("type") == "result" and l.get("stage") == "clip"]
        assert len(result_lines) == 1
        assert result_lines[0]["image_count"] == 0

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_default_downloads_images(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        """Without skip_images, download_images() is called normally."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {"https://example.com/logo.png": "images/img_001.jpg"}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url(
                "https://github.com/psf/requests",
                config,
            )

        mock_dl.assert_called_once()
        assert result is not None
        assert result.image_count == 1

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_skip_images_empty_images_dir(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        """When skip_images=True, the images directory should be empty."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url(
                "https://github.com/psf/requests",
                config,
                skip_images=True,
            )

        assert result is not None
        images_dir = result.folder_path / "images"
        # storage.create_entry always creates the images dir, but it should be empty
        assert images_dir.exists()
        assert not list(images_dir.iterdir())
