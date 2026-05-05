"""Tests for clip --text option and backward-compatible clip <url>."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.config import Config
from web_clip_helper.models import RawContent


class TestClipTextOption:
    """Verify that clip_text works correctly (used by clip --text)."""

    def test_clip_text_produces_result(self, tmp_path: Path) -> None:
        """clip --text 'content' should produce a result with source_type='text'."""
        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
        )

        from web_clip_helper.pipeline import clip_text

        result = clip_text("hello world from --text option", config)

        assert result is not None
        assert result.record_id is not None

        from web_clip_helper.index import ClipIndex

        idx = ClipIndex(config.db_path)
        record = idx.get_clip(result.record_id)
        assert record is not None
        assert record["source_type"] == "text"
        idx.close()

    def test_clip_text_content_saved(self, tmp_path: Path) -> None:
        """clip --text should save the text content into the markdown file."""
        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
        )

        from web_clip_helper.pipeline import clip_text

        result = clip_text("unique text content for verification", config)

        assert result is not None
        md_content = result.markdown_path.read_text(encoding="utf-8")
        assert "unique text content for verification" in md_content


class TestClipUrlBackwardCompat:
    """Verify that clip <url> still works after the --text change."""

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_clip_url_still_works(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        tmp_path: Path,
    ) -> None:
        """clip <url> should route to adapter and produce a result."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
        )

        sample_raw = RawContent(
            url="https://example.com/article",
            title="Test Article",
            content_md="# Test\nHello world.",
            images=[],
            source_type="web",
            fetched_at=datetime.now(),
        )

        mock_route.return_value = GenericWebAdapter
        mock_dl.return_value = {}

        with patch.object(GenericWebAdapter, "fetch", return_value=sample_raw):
            from web_clip_helper.pipeline import clip_url

            result = clip_url("https://example.com/article", config)

        assert result is not None
        assert result.record_id is not None

        from web_clip_helper.index import ClipIndex

        idx = ClipIndex(config.db_path)
        record = idx.get_clip(result.record_id)
        assert record is not None
        assert record["source_type"] == "web"
        idx.close()
