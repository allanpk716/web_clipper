"""Tests for --dry-run mode on the clip command.

Verifies that --dry-run:
  - Returns a structured ExecutionPlan as JSONL with dry_run=True
  - Performs NO network fetch, filesystem writes, or SQLite writes
  - Handles URL routing, text input, and error paths correctly

Uses run_sdk_cli for CLI tests and _capture_jsonl for direct pipeline tests.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex
from web_clip_helper.models import RawContent

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
def cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Return a Config pointing at temp directories, patched into get_config."""
    import web_clip_helper.config as cfg_mod

    cfg = Config(
        storage_path=str(tmp_path / "clips"),
        db_path=str(tmp_path / "test.db"),
    )
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    cfg.save(config_dir / "config.json")
    monkeypatch.setattr(cfg_mod, "_cached_config", cfg)
    return cfg


def _unwrap_result_data(envelope: dict) -> dict:
    """Return the data payload from a result-type envelope."""
    assert envelope.get("type") == "result", (
        f"Expected result envelope, got type={envelope.get('type')!r}"
    )
    return envelope["data"]


# ── URL dry-run tests ──────────────────────────────────────────────


class TestDryRunURL:
    """Tests for --dry-run with URL input."""

    @patch("web_clip_helper.services.clip.route_url")
    def test_dry_run_url_returns_plan(self, mock_route: MagicMock, cli_config: Config, run_sdk_cli) -> None:
        """--dry-run with URL emits a result with dry_run=True and plan dict."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        code, envelopes = run_sdk_cli(["clip", "--dry-run", "https://example.com/article"])

        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1

        data = _unwrap_result_data(results[0])
        assert data.get("dry_run") is True
        assert "plan" in data
        plan = data["plan"]
        assert plan["adapter"] == "GenericWebAdapter"
        assert plan["source_type"] == "web"
        assert plan["duplicate"] is False
        assert isinstance(plan["estimated_actions"], list)
        assert len(plan["estimated_actions"]) > 0

    @patch("web_clip_helper.services.clip.route_url")
    def test_dry_run_url_no_real_io(self, mock_route: MagicMock, cli_config: Config, run_sdk_cli) -> None:
        """--dry-run must NOT call adapter.fetch, StorageManager, or ClipIndex.save_clip."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        with (
            patch("web_clip_helper.services.clip.StorageManager") as mock_storage,
            patch("web_clip_helper.services.clip.LLMClient") as mock_llm,
            patch("web_clip_helper.services.clip.download_images") as mock_dl,
        ):
            run_sdk_cli(["clip", "--dry-run", "https://example.com/article"])

            mock_storage.assert_not_called()
            mock_llm.assert_not_called()
            mock_dl.assert_not_called()

    @patch("web_clip_helper.services.clip.route_url")
    def test_dry_run_url_detects_duplicate(self, mock_route: MagicMock, cli_config: Config, tmp_path: Path, run_sdk_cli) -> None:
        """--dry-run detects existing URL in the index (read-only check)."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        # Insert a record so the duplicate check finds it
        idx = ClipIndex(cli_config.db_path)
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

        code, envelopes = run_sdk_cli(["clip", "--dry-run", "https://example.com/article"])

        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1

        data = _unwrap_result_data(results[0])
        plan = data["plan"]
        assert plan["duplicate"] is True
        assert plan["existing_id"] is not None

    def test_dry_run_url_routing_error(self, cli_config: Config, run_sdk_cli) -> None:
        """--dry-run emits error JSONL on routing failure (empty URL)."""
        # Passing just --dry-run with no URL and no text triggers INPUT_INVALID first
        code, envelopes = run_sdk_cli(["clip", "--dry-run"])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert errors[0].get("error_code") == "INPUT_INVALID"


# ── Text dry-run tests ──────────────────────────────────────────────


class TestDryRunText:
    """Tests for --dry-run with text input."""

    def test_dry_run_text_returns_plan(self, cli_config: Config, run_sdk_cli) -> None:
        """--dry-run with text emits a result with dry_run=True and text plan."""
        code, envelopes = run_sdk_cli(["clip", "--dry-run", "--text", "Hello world this is a test"])

        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1

        data = _unwrap_result_data(results[0])
        assert data.get("dry_run") is True
        assert "plan" in data
        plan = data["plan"]
        assert plan["source_type"] == "text"
        assert plan["duplicate"] is False
        assert plan["existing_id"] is None
        assert "estimated_title" in plan
        assert isinstance(plan["estimated_actions"], list)

    def test_dry_run_text_no_real_io(self, cli_config: Config, run_sdk_cli) -> None:
        """--dry-run text must NOT call StorageManager, LLMClient, or download_images."""
        with (
            patch("web_clip_helper.services.clip.StorageManager") as mock_storage,
            patch("web_clip_helper.services.clip.LLMClient") as mock_llm,
            patch("web_clip_helper.services.clip.download_images") as mock_dl,
        ):
            run_sdk_cli(["clip", "--dry-run", "--text", "Some text content"])

            mock_storage.assert_not_called()
            mock_llm.assert_not_called()
            mock_dl.assert_not_called()

    def test_dry_run_text_empty_input(self, cli_config: Config, run_sdk_cli) -> None:
        """--dry-run with empty text emits INPUT_INVALID error."""
        code, envelopes = run_sdk_cli(["clip", "--dry-run", "--text", ""])

        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    def test_dry_run_text_title_truncation(self, cli_config: Config, run_sdk_cli) -> None:
        """--dry-run text truncates title to first 50 characters."""
        long_text = "A" * 100
        code, envelopes = run_sdk_cli(["clip", "--dry-run", "--text", long_text])

        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_result_data(results[0])
        assert len(data["plan"]["estimated_title"]) == 50


# ── JSONL purity tests ──────────────────────────────────────────────


class TestDryRunJSONLPurity:
    """Verify all dry-run output is valid SDK Envelope JSONL."""

    @patch("web_clip_helper.services.clip.route_url")
    def test_dry_run_url_all_lines_valid_jsonl(self, mock_route: MagicMock, cli_config: Config, run_sdk_cli) -> None:
        """Every stdout line from --dry-run URL is a valid SDK envelope."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        code, envelopes = run_sdk_cli(["clip", "--dry-run", "https://github.com/psf/requests"])

        # All envelopes are parsed and validated by _parse_envelopes in conftest
        assert len(envelopes) >= 2  # At least progress + result

    def test_dry_run_text_all_lines_valid_jsonl(self, cli_config: Config, run_sdk_cli) -> None:
        """Every stdout line from --dry-run text is a valid SDK envelope."""
        code, envelopes = run_sdk_cli(["clip", "--dry-run", "--text", "Sample text"])

        # All envelopes are parsed and validated by _parse_envelopes in conftest
        assert len(envelopes) >= 2  # At least progress + result

    @patch("web_clip_helper.services.clip.route_url")
    def test_dry_run_result_has_envelope_fields(self, mock_route: MagicMock, cli_config: Config, run_sdk_cli) -> None:
        """Result lines include version, tool, and timestamp envelope fields."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        code, envelopes = run_sdk_cli(["clip", "--dry-run", "https://example.com/page"])

        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1

        result = results[0]
        assert "version" in result
        assert "tool" in result
        assert "timestamp" in result
        assert result["tool"] == "web-clip-helper"


# ── Direct pipeline function tests ──────────────────────────────────


class TestPlanFunctions:
    """Tests for plan_clip_url and plan_clip_text functions directly.

    Uses _capture_jsonl fixture to capture SDK Writer output.
    """

    @patch("web_clip_helper.services.clip.route_url")
    def test_plan_clip_url_emits_plan(self, mock_route: MagicMock, config: Config, _capture_jsonl) -> None:
        """plan_clip_url emits JSONL result with dry_run=True."""
        from web_clip_helper.adapters.generic import GenericWebAdapter
        from web_clip_helper.pipeline import plan_clip_url

        mock_route.return_value = GenericWebAdapter

        plan_clip_url("https://example.com/test", config)

        envelopes = _capture_jsonl()
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_result_data(results[0])
        assert data["dry_run"] is True
        assert data["plan"]["adapter"] == "GenericWebAdapter"

    def test_plan_clip_text_emits_plan(self, config: Config, _capture_jsonl) -> None:
        """plan_clip_text emits JSONL result with dry_run=True."""
        from web_clip_helper.pipeline import plan_clip_text

        plan_clip_text("Hello world", config)

        envelopes = _capture_jsonl()
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_result_data(results[0])
        assert data["dry_run"] is True
        assert data["plan"]["source_type"] == "text"

    def test_plan_clip_text_empty_raises(self, config: Config) -> None:
        """plan_clip_text raises SystemExit on empty input."""
        from web_clip_helper.pipeline import plan_clip_text

        with pytest.raises(SystemExit):
            plan_clip_text("", config)

    @patch("web_clip_helper.services.clip.route_url")
    def test_plan_clip_url_routing_error_raises(self, mock_route: MagicMock, config: Config) -> None:
        """plan_clip_url raises SystemExit on routing error."""
        from web_clip_helper.pipeline import plan_clip_url

        mock_route.side_effect = ValueError("No adapter found")

        with pytest.raises(SystemExit):
            plan_clip_url("invalid-url", config)

    @patch("web_clip_helper.services.clip.route_url")
    def test_plan_clip_url_duplicate_check_failure_non_fatal(self, mock_route: MagicMock, config: Config, _capture_jsonl) -> None:
        """Duplicate check failure in plan_clip_url is non-fatal."""
        from web_clip_helper.adapters.generic import GenericWebAdapter
        from web_clip_helper.pipeline import plan_clip_url

        mock_route.return_value = GenericWebAdapter

        with patch("web_clip_helper.services.clip.ClipIndex", side_effect=Exception("DB error")):
            plan_clip_url("https://example.com/test", config)

        envelopes = _capture_jsonl()
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_result_data(results[0])
        assert data["plan"]["duplicate"] is False


# ── No-side-effects tests ───────────────────────────────────────────


class TestNoSideEffects:
    """Verify dry-run produces no side effects (no files, no DB records)."""

    @patch("web_clip_helper.services.clip.route_url")
    def test_dry_run_creates_no_storage_files(self, mock_route: MagicMock, cli_config: Config, tmp_path: Path, run_sdk_cli) -> None:
        """--dry-run does not create any files in storage_path."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        run_sdk_cli(["clip", "--dry-run", "https://example.com/test"])

        storage_dir = tmp_path / "clips"
        if storage_dir.exists():
            assert not any(storage_dir.iterdir()), "dry-run should not create storage files"

    @patch("web_clip_helper.services.clip.route_url")
    def test_dry_run_creates_no_db_records(self, mock_route: MagicMock, cli_config: Config, run_sdk_cli) -> None:
        """--dry-run does not create any records in SQLite."""
        from web_clip_helper.adapters.generic import GenericWebAdapter

        mock_route.return_value = GenericWebAdapter

        run_sdk_cli(["clip", "--dry-run", "https://example.com/test"])

        idx = ClipIndex(cli_config.db_path)
        clips = idx.query_clips()
        idx.close()
        assert len(clips) == 0, "dry-run should not create DB records"
