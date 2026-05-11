"""Tests for structured logging in the clip pipeline (T01, S02).

Verifies that each pipeline stage emits structured log records with:
  - ``stage`` extra field identifying the stage
  - ``elapsed_ms`` extra field (float) for timing
  - Stage-specific fields (adapter, content_length, tags_count, etc.)
  - Error details on failure paths

No full markdown content, config values, image URLs, or API keys should
appear in any log record.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.config import Config
from web_clip_helper.models import RawContent
from web_clip_helper.pipeline import _enrich_with_llm, _time_stage, clip_text, clip_url

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
    """Return a sample RawContent."""
    return RawContent(
        url="https://github.com/psf/requests",
        title="psf/requests",
        content_md="# Requests\n\nA simple HTTP library.\n\n![logo](https://example.com/logo.png)",
        images=["https://example.com/logo.png"],
        source_type="github",
        fetched_at=datetime(2024, 1, 15, 12, 0, 0),
    )


@pytest.fixture
def log_records() -> list[logging.LogRecord]:
    """Capture log records from web_clip_helper.pipeline."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    logger = logging.getLogger("web_clip_helper.pipeline")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield records
    logger.removeHandler(handler)


# ── _time_stage helper ─────────────────────────────────────────────


class TestTimeStage:
    def test_returns_non_negative_elapsed(self) -> None:
        _t0, elapsed = _time_stage()
        ms = elapsed()
        assert ms >= 0

    def test_elapsed_increases(self) -> None:
        import time

        _t0, elapsed = _time_stage()
        ms1 = elapsed()
        time.sleep(0.01)
        ms2 = elapsed()
        assert ms2 > ms1


# ── Route stage ────────────────────────────────────────────────────


class TestRouteStageLogging:
    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_route_success_logs_adapter_and_elapsed(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        log_records: list[logging.LogRecord],
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            clip_url("https://github.com/psf/requests", config)

        route_logs = [r for r in log_records if getattr(r, "stage", None) == "route"]
        assert len(route_logs) >= 1
        log = route_logs[0]
        assert log.adapter == "GitHubAdapter"
        assert isinstance(log.elapsed_ms, float)
        assert log.elapsed_ms >= 0

    @patch("web_clip_helper.pipeline.route_url")
    def test_route_error_logs_error_detail(
        self,
        mock_route: MagicMock,
        config: Config,
        log_records: list[logging.LogRecord],
    ) -> None:
        mock_route.side_effect = ValueError("unsupported URL")

        result = clip_url("https://bad.example.com", config)

        assert result is None
        route_logs = [r for r in log_records if getattr(r, "stage", None) == "route"]
        assert len(route_logs) >= 1
        log = route_logs[0]
        assert log.levelno == logging.ERROR
        assert "error" in log.__dict__


# ── Fetch stage ────────────────────────────────────────────────────


class TestFetchStageLogging:
    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_fetch_success_logs_content_length(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        log_records: list[logging.LogRecord],
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            clip_url("https://github.com/psf/requests", config)

        fetch_logs = [r for r in log_records if getattr(r, "stage", None) == "fetch"]
        assert len(fetch_logs) >= 1
        log = fetch_logs[0]
        assert log.content_length == len(sample_raw.content_md)
        assert isinstance(log.elapsed_ms, float)

    @patch("web_clip_helper.pipeline.route_url")
    def test_fetch_adapter_error_logs_error(
        self,
        mock_route: MagicMock,
        config: Config,
        log_records: list[logging.LogRecord],
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter
        from web_clip_helper.adapter import AdapterError

        mock_route.return_value = GitHubAdapter

        with patch.object(GitHubAdapter, "fetch", side_effect=AdapterError("fetch fail")):
            result = clip_url("https://github.com/psf/requests", config)

        assert result is None
        fetch_logs = [r for r in log_records if getattr(r, "stage", None) == "fetch"]
        assert len(fetch_logs) >= 1
        assert fetch_logs[0].levelno == logging.ERROR


# ── LLM stage ──────────────────────────────────────────────────────


class TestLLMStageLogging:
    def test_llm_skip_no_api_key(
        self,
        sample_raw: RawContent,
        config: Config,
        log_records: list[logging.LogRecord],
    ) -> None:
        title, tags, category = _enrich_with_llm(sample_raw, config)

        assert title == "psf/requests"
        llm_logs = [r for r in log_records if getattr(r, "stage", None) == "llm"]
        assert len(llm_logs) >= 1
        log = llm_logs[0]
        assert log.reason == "no_api_key"
        assert log.elapsed_ms == 0

    def test_llm_success_logs_tags_and_category(
        self,
        sample_raw: RawContent,
        config: Config,
        log_records: list[logging.LogRecord],
    ) -> None:
        config.llm.api_key = "sk-test-key"
        mock_client = MagicMock()
        mock_client.generate_title.return_value = "Enhanced Title"
        mock_client.extract_tags.return_value = ["python", "http"]
        mock_client.classify_content.return_value = "library"

        with patch("web_clip_helper.pipeline.LLMClient", return_value=mock_client):
            title, tags, category = _enrich_with_llm(sample_raw, config)

        assert title == "Enhanced Title"
        assert tags == ["python", "http"]
        assert category == "library"

        llm_logs = [r for r in log_records if getattr(r, "stage", None) == "llm"]
        success_logs = [r for r in llm_logs if r.levelno == logging.INFO]
        assert len(success_logs) >= 1
        log = success_logs[0]
        assert log.tags_count == 2
        assert log.category == "library"
        assert isinstance(log.elapsed_ms, float)

    def test_llm_failure_logs_error(
        self,
        sample_raw: RawContent,
        config: Config,
        log_records: list[logging.LogRecord],
    ) -> None:
        config.llm.api_key = "sk-test-key"
        mock_client = MagicMock()
        mock_client.generate_title.side_effect = RuntimeError("LLM timeout")

        with patch("web_clip_helper.pipeline.LLMClient", return_value=mock_client):
            title, tags, category = _enrich_with_llm(sample_raw, config)

        assert title == "psf/requests"  # fallback
        assert tags == []
        assert category == ""

        llm_logs = [r for r in log_records if getattr(r, "stage", None) == "llm"]
        error_logs = [r for r in llm_logs if r.levelno == logging.ERROR]
        assert len(error_logs) >= 1
        assert isinstance(error_logs[0].elapsed_ms, float)


# ── Store / Index stages ───────────────────────────────────────────


class TestStoreAndIndexLogging:
    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_store_stage_logs_entry_name(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        log_records: list[logging.LogRecord],
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url("https://github.com/psf/requests", config)

        assert result is not None

        store_logs = [r for r in log_records if getattr(r, "stage", None) == "store"]
        assert len(store_logs) >= 1
        log = store_logs[0]
        assert "entry_name" in log.__dict__
        assert isinstance(log.elapsed_ms, float)

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_index_stage_logs_record_id(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        log_records: list[logging.LogRecord],
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url("https://github.com/psf/requests", config)

        assert result is not None

        index_logs = [r for r in log_records if getattr(r, "stage", None) == "index"]
        assert len(index_logs) >= 1
        log = index_logs[0]
        assert log.record_id == result.record_id
        assert isinstance(log.elapsed_ms, float)

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_save_stage_logs_md_path(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        log_records: list[logging.LogRecord],
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result = clip_url("https://github.com/psf/requests", config)

        assert result is not None

        save_logs = [r for r in log_records if getattr(r, "stage", None) == "save"]
        assert len(save_logs) >= 1
        log = save_logs[0]
        assert "md_path" in log.__dict__
        assert isinstance(log.elapsed_ms, float)


# ── Duplicate path ─────────────────────────────────────────────────


class TestDuplicateLogging:
    @patch("web_clip_helper.pipeline.route_url")
    def test_duplicate_logs_existing_id(
        self,
        mock_route: MagicMock,
        config: Config,
        log_records: list[logging.LogRecord],
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter
        from web_clip_helper.index import ClipIndex

        mock_route.return_value = GitHubAdapter

        # Pre-insert a record
        idx = ClipIndex(config.db_path)
        rid = idx.save_clip({
            "url": "https://github.com/psf/requests",
            "title": "Requests",
            "source_type": "github",
            "folder_path": "/tmp/test",
            "markdown_path": "/tmp/test.md",
            "image_count": 0,
            "tags": [],
            "category": "",
            "is_dynamic": 0,
        })
        idx.close()

        result = clip_url("https://github.com/psf/requests", config)

        assert result is not None
        assert result.record_id == rid

        route_logs = [r for r in log_records if getattr(r, "stage", None) == "route"]
        dup_logs = [r for r in route_logs if getattr(r, "action", None) == "duplicate"]
        assert len(dup_logs) >= 1
        assert dup_logs[0].existing_id == rid


# ── Image stage ────────────────────────────────────────────────────


class TestImageStageLogging:
    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_image_success_logs_count(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        log_records: list[logging.LogRecord],
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {"https://example.com/logo.png": "images/img_001.jpg"}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            clip_url("https://github.com/psf/requests", config)

        img_logs = [r for r in log_records if getattr(r, "stage", None) == "images"]
        success_logs = [r for r in img_logs if r.levelno == logging.INFO]
        assert len(success_logs) >= 1
        assert success_logs[0].image_count == 1

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_image_failure_logs_warning(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        log_records: list[logging.LogRecord],
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.side_effect = RuntimeError("download fail")

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            clip_url("https://github.com/psf/requests", config)

        img_logs = [r for r in log_records if getattr(r, "stage", None) == "images"]
        warn_logs = [r for r in img_logs if r.levelno == logging.WARNING]
        assert len(warn_logs) >= 1


# ── Redaction constraints ──────────────────────────────────────────


class TestRedactionConstraints:
    """No full markdown, config values, image URLs, or API keys in log messages."""

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_no_full_content_in_logs(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        log_records: list[logging.LogRecord],
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            clip_url("https://github.com/psf/requests", config)

        # Check that no log message contains the full markdown content
        full_content = sample_raw.content_md
        for rec in log_records:
            assert full_content not in rec.getMessage(), (
                f"Log record contains full markdown content: {rec.getMessage()}"
            )

    @patch("web_clip_helper.pipeline.download_images")
    @patch("web_clip_helper.pipeline.route_url")
    def test_no_image_urls_in_logs(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
        log_records: list[logging.LogRecord],
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {"https://example.com/logo.png": "images/img_001.jpg"}

        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            clip_url("https://github.com/psf/requests", config)

        # Check that no log message contains image URLs
        for rec in log_records:
            msg = rec.getMessage()
            for img_url in sample_raw.images:
                assert img_url not in msg, (
                    f"Log record contains image URL: {msg}"
                )
