"""Tests for --no-images and --timeout flags on the clip command."""

from __future__ import annotations

import json
import time
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


class TestTimeoutFlag:
    """Tests for --timeout flag and TIMEOUT_ERROR code."""

    def test_timeout_triggers_timeout_error(self) -> None:
        """When pipeline exceeds timeout, a TIMEOUT_ERROR JSONL line is emitted."""
        from typer.testing import CliRunner
        from web_clip_helper.cli import app

        def _slow_clip(*args, **kwargs):
            time.sleep(5)
            return None

        with patch("web_clip_helper.pipeline.clip_url", side_effect=_slow_clip):
            runner = CliRunner()
            result = runner.invoke(app, ["clip", "https://example.com/slow-test-timeout", "--timeout", "1"])

        assert result.exit_code == 1
        output = result.output
        lines = [json.loads(line) for line in output.strip().split("\n") if line.strip()]
        error_lines = [l for l in lines if l.get("type") == "error"]
        assert len(error_lines) >= 1
        assert error_lines[0]["error_code"] == "TIMEOUT_ERROR"
        assert "1s" in error_lines[0]["detail"]

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_normal_completes_within_timeout(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        """When pipeline finishes within timeout, no TIMEOUT_ERROR is emitted."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {"https://example.com/logo.png": "images/img_001.jpg"}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            from typer.testing import CliRunner
            from web_clip_helper.cli import app

            runner = CliRunner()
            result = runner.invoke(app, ["clip", "https://github.com/psf/requests", "--timeout", "60"])

        assert result.exit_code == 0
        output = result.output
        lines = [json.loads(line) for line in output.strip().split("\n") if line.strip()]
        error_lines = [l for l in lines if l.get("type") == "error" and l.get("error_code") == "TIMEOUT_ERROR"]
        assert len(error_lines) == 0

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_default_timeout_is_60(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        """Default timeout of 60s allows normal clips to complete."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {"https://example.com/logo.png": "images/img_001.jpg"}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            from typer.testing import CliRunner
            from web_clip_helper.cli import app

            runner = CliRunner()
            result = runner.invoke(app, ["clip", "https://github.com/psf/requests"])

        assert result.exit_code == 0

    def test_timeout_error_code_in_registry(self) -> None:
        """TIMEOUT_ERROR is registered in ErrorCode with a description."""
        from web_clip_helper.error_codes import ErrorCode

        assert hasattr(ErrorCode, "TIMEOUT_ERROR")
        assert ErrorCode.TIMEOUT_ERROR == "TIMEOUT_ERROR"
        assert "TIMEOUT_ERROR" in ErrorCode.all_codes()
        desc = ErrorCode.describe("TIMEOUT_ERROR")
        assert "timeout" in desc.lower()

    def test_timeout_error_jsonl_includes_stage(self) -> None:
        """TIMEOUT_ERROR JSONL line includes stage='clip'."""
        from typer.testing import CliRunner
        from web_clip_helper.cli import app

        def _slow_clip(*args, **kwargs):
            time.sleep(5)
            return None

        with patch("web_clip_helper.pipeline.clip_url", side_effect=_slow_clip):
            runner = CliRunner()
            result = runner.invoke(app, ["clip", "https://example.com/slow-test-stage", "--timeout", "1"])

        output = result.output
        lines = [json.loads(line) for line in output.strip().split("\n") if line.strip()]
        error_lines = [l for l in lines if l.get("type") == "error" and l.get("error_code") == "TIMEOUT_ERROR"]
        assert len(error_lines) >= 1
        assert error_lines[0]["stage"] == "clip"
