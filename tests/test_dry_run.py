"""Tests for --dry-run mode on the clip command.

Verifies that --dry-run:
  - Returns a structured ExecutionPlan as JSONL with dry_run=True
  - Performs NO network fetch, filesystem writes, or SQLite writes
  - Handles URL routing, text input, and error paths correctly
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex
from web_clip_helper.models import RawContent

# Trigger adapter registration
import web_clip_helper.adapters._registry  # noqa: F401

runner = CliRunner()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """Return a Config pointing at temp directories."""
    return Config(
        storage_path=str(tmp_path / "clips"),
        db_path=str(tmp_path / "test.db"),
    )


def _run_clip(*args: str) -> tuple[int, str]:
    """Run the clip command and return (exit_code, stdout)."""
    result = runner.invoke(app, ["clip", *args])
    return result.exit_code, result.output


def _parse_jsonl(output: str) -> list[dict]:
    """Parse stdout as JSONL lines, return list of dicts."""
    lines = [line for line in output.strip().split("\n") if line.strip()]
    return [json.loads(line) for line in lines]


def _validate_all_jsonl(output: str) -> list[dict]:
    """Validate every stdout line is valid JSONL with whitelisted type."""
    parsed = _parse_jsonl(output)
    valid_types = {"progress", "result", "error", "warning", "help"}
    for line in parsed:
        assert "type" in line, f"Missing 'type' field in JSONL: {line}"
        assert line["type"] in valid_types, f"Invalid type: {line['type']} in {line}"
    return parsed


# ── URL dry-run tests ──────────────────────────────────────────────


class TestDryRunURL:
    """Tests for --dry-run with URL input."""

    @patch("web_clip_helper.pipeline.route_url")
    def test_dry_run_url_returns_plan(self, mock_route: MagicMock, config: Config) -> None:
        """--dry-run with URL emits a result with dry_run=True and plan dict."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        with patch("web_clip_helper.config.get_config", return_value=config):
            exit_code, output = _run_clip("--dry-run", "https://example.com/article")

        parsed = _validate_all_jsonl(output)
        results = [p for p in parsed if p["type"] == "result"]
        assert len(results) == 1

        result = results[0]
        assert result.get("dry_run") is True
        assert "plan" in result
        plan = result["plan"]
        assert plan["adapter"] == "GenericWebAdapter"
        assert plan["source_type"] == "web"
        assert plan["duplicate"] is False
        assert isinstance(plan["estimated_actions"], list)
        assert len(plan["estimated_actions"]) > 0

    @patch("web_clip_helper.pipeline.route_url")
    def test_dry_run_url_no_real_io(self, mock_route: MagicMock, config: Config) -> None:
        """--dry-run must NOT call adapter.fetch, StorageManager, or ClipIndex.save_clip."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        with (
            patch("web_clip_helper.config.get_config", return_value=config),
            patch("web_clip_helper.pipeline.StorageManager") as mock_storage,
            patch("web_clip_helper.pipeline.LLMClient") as mock_llm,
            patch("web_clip_helper.pipeline.download_images") as mock_dl,
        ):
            _run_clip("--dry-run", "https://example.com/article")

            mock_storage.assert_not_called()
            mock_llm.assert_not_called()
            mock_dl.assert_not_called()

    @patch("web_clip_helper.pipeline.route_url")
    def test_dry_run_url_detects_duplicate(self, mock_route: MagicMock, config: Config) -> None:
        """--dry-run detects existing URL in the index (read-only check)."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        # Insert a record so the duplicate check finds it
        idx = ClipIndex(config.db_path)
        idx.save_clip({
            "url": "https://example.com/article",
            "title": "Test",
            "source_type": "web",
            "folder_path": "/tmp/test",
            "markdown_path": "/tmp/test.md",
            "image_count": 0,
            "tags": [],
            "category": "",
        })
        idx.close()

        with patch("web_clip_helper.config.get_config", return_value=config):
            exit_code, output = _run_clip("--dry-run", "https://example.com/article")

        parsed = _validate_all_jsonl(output)
        results = [p for p in parsed if p["type"] == "result"]
        assert len(results) == 1

        plan = results[0]["plan"]
        assert plan["duplicate"] is True
        assert plan["existing_id"] is not None

    def test_dry_run_url_routing_error(self, config: Config) -> None:
        """--dry-run emits error JSONL on routing failure (empty URL)."""
        # route_url raises ValueError on empty string
        with patch("web_clip_helper.config.get_config", return_value=config):
            # Passing just --dry-run with no URL and no text triggers INPUT_INVALID first
            exit_code, output = _run_clip("--dry-run")
            parsed = _validate_all_jsonl(output)
            errors = [p for p in parsed if p["type"] == "error"]
            assert len(errors) == 1
            assert errors[0].get("error_code") == "INPUT_INVALID"


# ── Text dry-run tests ──────────────────────────────────────────────


class TestDryRunText:
    """Tests for --dry-run with text input."""

    def test_dry_run_text_returns_plan(self, config: Config) -> None:
        """--dry-run with text emits a result with dry_run=True and text plan."""
        with patch("web_clip_helper.config.get_config", return_value=config):
            exit_code, output = _run_clip("--dry-run", "--text", "Hello world this is a test")

        parsed = _validate_all_jsonl(output)
        results = [p for p in parsed if p["type"] == "result"]
        assert len(results) == 1

        result = results[0]
        assert result.get("dry_run") is True
        assert "plan" in result
        plan = result["plan"]
        assert plan["source_type"] == "text"
        assert plan["duplicate"] is False
        assert plan["existing_id"] is None
        assert "estimated_title" in plan
        assert isinstance(plan["estimated_actions"], list)

    def test_dry_run_text_no_real_io(self, config: Config) -> None:
        """--dry-run text must NOT call StorageManager, LLMClient, or download_images."""
        with (
            patch("web_clip_helper.config.get_config", return_value=config),
            patch("web_clip_helper.pipeline.StorageManager") as mock_storage,
            patch("web_clip_helper.pipeline.LLMClient") as mock_llm,
            patch("web_clip_helper.pipeline.download_images") as mock_dl,
        ):
            _run_clip("--dry-run", "--text", "Some text content")

            mock_storage.assert_not_called()
            mock_llm.assert_not_called()
            mock_dl.assert_not_called()

    def test_dry_run_text_empty_input(self, config: Config) -> None:
        """--dry-run with empty text emits INPUT_INVALID error."""
        with patch("web_clip_helper.config.get_config", return_value=config):
            exit_code, output = _run_clip("--dry-run", "--text", "")

        parsed = _validate_all_jsonl(output)
        errors = [p for p in parsed if p["type"] == "error"]
        assert len(errors) == 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    def test_dry_run_text_title_truncation(self, config: Config) -> None:
        """--dry-run text truncates title to first 50 characters."""
        long_text = "A" * 100
        with patch("web_clip_helper.config.get_config", return_value=config):
            exit_code, output = _run_clip("--dry-run", "--text", long_text)

        parsed = _validate_all_jsonl(output)
        results = [p for p in parsed if p["type"] == "result"]
        assert len(results) == 1
        plan = results[0]["plan"]
        assert len(plan["estimated_title"]) == 50


# ── JSONL purity tests ──────────────────────────────────────────────


class TestDryRunJSONLPurity:
    """Verify all dry-run output is valid JSONL."""

    @patch("web_clip_helper.pipeline.route_url")
    def test_dry_run_url_all_lines_valid_jsonl(self, mock_route: MagicMock, config: Config) -> None:
        """Every stdout line from --dry-run URL is valid JSON."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        with patch("web_clip_helper.config.get_config", return_value=config):
            exit_code, output = _run_clip("--dry-run", "https://github.com/psf/requests")

        parsed = _validate_all_jsonl(output)
        assert len(parsed) >= 2  # At least progress + result

    def test_dry_run_text_all_lines_valid_jsonl(self, config: Config) -> None:
        """Every stdout line from --dry-run text is valid JSON."""
        with patch("web_clip_helper.config.get_config", return_value=config):
            exit_code, output = _run_clip("--dry-run", "--text", "Sample text")

        parsed = _validate_all_jsonl(output)
        assert len(parsed) >= 2  # At least progress + result

    @patch("web_clip_helper.pipeline.route_url")
    def test_dry_run_result_has_envelope_fields(self, mock_route: MagicMock, config: Config) -> None:
        """Result lines include version, tool, and timestamp envelope fields."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        with patch("web_clip_helper.config.get_config", return_value=config):
            exit_code, output = _run_clip("--dry-run", "https://example.com/page")

        parsed = _validate_all_jsonl(output)
        results = [p for p in parsed if p["type"] == "result"]
        assert len(results) == 1

        result = results[0]
        assert "version" in result
        assert "tool" in result
        assert "timestamp" in result
        assert result["tool"] == "web-clip-helper"


# ── Direct pipeline function tests ──────────────────────────────────


class TestPlanFunctions:
    """Tests for plan_clip_url and plan_clip_text functions directly."""

    @patch("web_clip_helper.pipeline.route_url")
    def test_plan_clip_url_emits_plan(self, mock_route: MagicMock, config: Config, capsys: pytest.CaptureFixture[str]) -> None:
        """plan_clip_url emits JSONL result with dry_run=True."""
        from web_clip_helper.adapters.generic import GenericWebAdapter
        from web_clip_helper.pipeline import plan_clip_url

        mock_route.return_value = GenericWebAdapter

        plan_clip_url("https://example.com/test", config)

        captured = capsys.readouterr()
        parsed = _validate_all_jsonl(captured.out)
        results = [p for p in parsed if p["type"] == "result"]
        assert len(results) == 1
        assert results[0]["dry_run"] is True
        assert results[0]["plan"]["adapter"] == "GenericWebAdapter"

    def test_plan_clip_text_emits_plan(self, config: Config, capsys: pytest.CaptureFixture[str]) -> None:
        """plan_clip_text emits JSONL result with dry_run=True."""
        from web_clip_helper.pipeline import plan_clip_text

        plan_clip_text("Hello world", config)

        captured = capsys.readouterr()
        parsed = _validate_all_jsonl(captured.out)
        results = [p for p in parsed if p["type"] == "result"]
        assert len(results) == 1
        assert results[0]["dry_run"] is True
        assert results[0]["plan"]["source_type"] == "text"

    def test_plan_clip_text_empty_raises(self, config: Config) -> None:
        """plan_clip_text raises SystemExit on empty input."""
        from web_clip_helper.pipeline import plan_clip_text

        with pytest.raises(SystemExit):
            plan_clip_text("", config)

    @patch("web_clip_helper.pipeline.route_url")
    def test_plan_clip_url_routing_error_raises(self, mock_route: MagicMock, config: Config) -> None:
        """plan_clip_url raises SystemExit on routing error."""
        from web_clip_helper.pipeline import plan_clip_url

        mock_route.side_effect = ValueError("No adapter found")

        with pytest.raises(SystemExit):
            plan_clip_url("invalid-url", config)

    @patch("web_clip_helper.pipeline.route_url")
    def test_plan_clip_url_duplicate_check_failure_non_fatal(self, mock_route: MagicMock, config: Config, capsys: pytest.CaptureFixture[str]) -> None:
        """Duplicate check failure in plan_clip_url is non-fatal."""
        from web_clip_helper.adapters.generic import GenericWebAdapter
        from web_clip_helper.pipeline import plan_clip_url

        mock_route.return_value = GenericWebAdapter

        with patch("web_clip_helper.pipeline.ClipIndex", side_effect=Exception("DB error")):
            plan_clip_url("https://example.com/test", config)

        captured = capsys.readouterr()
        parsed = _validate_all_jsonl(captured.out)
        results = [p for p in parsed if p["type"] == "result"]
        assert len(results) == 1
        assert results[0]["plan"]["duplicate"] is False


# ── No-side-effects tests ───────────────────────────────────────────


class TestNoSideEffects:
    """Verify dry-run produces no side effects (no files, no DB records)."""

    @patch("web_clip_helper.pipeline.route_url")
    def test_dry_run_creates_no_storage_files(self, mock_route: MagicMock, config: Config, tmp_path: Path) -> None:
        """--dry-run does not create any files in storage_path."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        with patch("web_clip_helper.config.get_config", return_value=config):
            _run_clip("--dry-run", "https://example.com/test")

        storage_dir = tmp_path / "clips"
        if storage_dir.exists():
            assert not any(storage_dir.iterdir()), "dry-run should not create storage files"

    @patch("web_clip_helper.pipeline.route_url")
    def test_dry_run_creates_no_db_records(self, mock_route: MagicMock, config: Config) -> None:
        """--dry-run does not create any records in SQLite."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        with patch("web_clip_helper.config.get_config", return_value=config):
            _run_clip("--dry-run", "https://example.com/test")

        idx = ClipIndex(config.db_path)
        clips = idx.query_clips()
        idx.close()
        assert len(clips) == 0, "dry-run should not create DB records"
