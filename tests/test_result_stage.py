"""Tests that all JSONL result messages contain a 'stage' field."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.config import Config
from web_clip_helper.models import RawContent


class TestResultStageField:
    """Verify that every jsonl_emit_result call includes a stage field."""

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_clip_result_has_stage(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        tmp_path: Path,
        _capture_jsonl,
    ) -> None:
        """clip_url result should include stage='clip'."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
        )

        sample_raw = RawContent(
            url="https://example.com/test",
            title="Stage Test",
            content_md="# Test",
            images=[],
            source_type="web",
            fetched_at=datetime.now(),
        )

        mock_route.return_value = GenericWebAdapter
        mock_dl.return_value = {}

        with patch.object(GenericWebAdapter, "fetch", return_value=sample_raw):
            from web_clip_helper.pipeline import clip_url

            result = clip_url("https://example.com/test", config)

        assert result is not None
        envelopes = _capture_jsonl()
        results = [e for e in envelopes if e.get("type") == "result"]
        assert len(results) >= 1
        for r in results:
            data = r.get("data", {})
            assert "stage" in data, f"result missing 'stage' field in data: {r}"
            assert data["stage"] == "clip"

    def test_clip_text_result_has_stage(
        self,
        tmp_path: Path,
        _capture_jsonl,
    ) -> None:
        """clip_text result should include stage='clip'."""
        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
        )

        from web_clip_helper.pipeline import clip_text

        result = clip_text("text for stage test", config)

        assert result is not None
        envelopes = _capture_jsonl()
        results = [e for e in envelopes if e.get("type") == "result"]
        assert len(results) >= 1
        for r in results:
            data = r.get("data", {})
            assert "stage" in data, f"result missing 'stage' field in data: {r}"
            assert data["stage"] == "clip"
