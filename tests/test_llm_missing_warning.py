"""Tests for LLM missing summary warning."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.config import Config, LLMConfig
from web_clip_helper.models import RawContent


class TestLLMMissingSummaryWarning:
    """Verify that a summary warning is emitted when LLM API key is missing."""

    def test_no_api_key_emits_summary_warning(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        """When no API key is configured, clip should emit a summary warning at the end."""
        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
            # No API key — default is empty string
        )

        from web_clip_helper.pipeline import clip_text

        result = clip_text("test content for warning", config)

        assert result is not None
        captured = capsys.readouterr()
        lines = [
            json.loads(line)
            for line in captured.out.strip().split("\n")
            if line.strip()
        ]

        warnings = [l for l in lines if l["type"] == "warning" and l.get("stage") == "llm"]
        # Should have at least 2 warnings: the early one + the summary
        assert len(warnings) >= 1
        # The summary warning should contain actionable guidance
        summary = [w for w in warnings if "config set llm.api_key" in w.get("message", "")]
        assert len(summary) >= 1, f"Expected summary warning with config guidance, got: {warnings}"
        assert "WEB_CLIP_LLM_API_KEY" in summary[0]["message"]

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_with_api_key_no_summary_warning(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        tmp_path: Path,
        capsys,
    ) -> None:
        """When API key is configured, no summary warning should be emitted."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
            llm=LLMConfig(api_key="test-key"),
        )

        sample_raw = RawContent(
            url="https://example.com/test",
            title="Test",
            content_md="# Test",
            images=[],
            source_type="web",
            fetched_at=datetime.now(),
        )

        mock_route.return_value = GenericWebAdapter
        mock_dl.return_value = {}

        with patch.object(GenericWebAdapter, "fetch", return_value=sample_raw):
            with patch("web_clip_helper.services.clip.LLMClient") as MockLLM:
                mock_client = MockLLM.return_value
                mock_client.generate_title.return_value = "Title"
                mock_client.extract_tags.return_value = ["tag"]
                mock_client.classify_content.return_value = "tech"

                from web_clip_helper.pipeline import clip_url

                result = clip_url("https://example.com/test", config)

        assert result is not None
        captured = capsys.readouterr()
        lines = [
            json.loads(line)
            for line in captured.out.strip().split("\n")
            if line.strip()
        ]

        # No summary warning about missing API key
        llm_warnings = [
            l for l in lines
            if l["type"] == "warning" and l.get("stage") == "llm" and "config set" in l.get("message", "")
        ]
        assert len(llm_warnings) == 0, f"Unexpected LLM summary warning when API key is set: {llm_warnings}"
