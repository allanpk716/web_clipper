"""Tests for idempotent duplicate detection in clip_url pipeline.

Verifies that clipping the same URL twice:
- Returns duplicate:true + existing_id on the second call
- DB contains exactly one record
- Cross-normalization works (http vs https, trailing slash)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex
from web_clip_helper.models import ClipResult, RawContent
from web_clip_helper.pipeline import clip_url

# Trigger adapter registration
import web_clip_helper.adapters._registry  # noqa: F401


def _capture_jsonl(capsys):
    """Parse captured stdout as JSONL lines."""
    output = capsys.readouterr().out
    lines = [line for line in output.strip().split("\n") if line.strip()]
    return [json.loads(line) for line in lines]


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
        content_md="# Requests\n\nA simple HTTP library.",
        images=[],
        source_type="github",
        fetched_at=datetime(2024, 1, 15, 12, 0, 0),
    )


def _clip_first(url: str, config: Config, sample_raw: RawContent) -> ClipResult | None:
    """Helper: perform first clip (with mocked adapter)."""
    from web_clip_helper.adapters.github import GitHubAdapter

    with (
        patch("web_clip_helper.services.clip.route_url", return_value=GitHubAdapter),
        patch("web_clip_helper.services.clip.download_images", return_value={}),
        patch.object(GitHubAdapter, "fetch", return_value=sample_raw),
    ):
        return clip_url(url, config)


class TestDuplicateDetection:
    """Duplicate URL returns existing record without re-fetching."""

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_second_clip_returns_duplicate_flag(
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

        # First clip — normal flow
        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result1 = clip_url("https://github.com/psf/requests", config)

        assert result1 is not None
        assert result1.record_id is not None

        # Second clip — should be detected as duplicate
        result2 = clip_url("https://github.com/psf/requests", config)
        assert result2 is not None

        messages = _capture_jsonl(capsys)
        result_msgs = [m for m in messages if m["type"] == "result"]

        # Second clip result should have duplicate: true
        second_result = result_msgs[-1]
        assert second_result.get("duplicate") is True
        assert second_result.get("existing_id") == result1.record_id

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_second_clip_same_record_id(
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
            result1 = clip_url("https://github.com/psf/requests", config)

        result2 = clip_url("https://github.com/psf/requests", config)
        assert result2 is not None
        assert result2.record_id == result1.record_id

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_db_has_exactly_one_record(
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
            clip_url("https://github.com/psf/requests", config)

        # Second clip (duplicate)
        clip_url("https://github.com/psf/requests", config)

        index = ClipIndex(config.db_path)
        all_clips = index.query_clips()
        index.close()

        assert len(all_clips) == 1

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_second_clip_does_not_call_adapter(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        # First clip
        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw) as mock_fetch:
            clip_url("https://github.com/psf/requests", config)
            assert mock_fetch.call_count == 1

        # Second clip — adapter.fetch should NOT be called again
        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw) as mock_fetch2:
            result2 = clip_url("https://github.com/psf/requests", config)
            mock_fetch2.assert_not_called()

        assert result2 is not None
        assert result2.record_id is not None

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_duplicate_progress_message(
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
            clip_url("https://github.com/psf/requests", config)

        # Clear captured output
        capsys.readouterr()

        clip_url("https://github.com/psf/requests", config)

        messages = _capture_jsonl(capsys)
        progress_msgs = [m for m in messages if m["type"] == "progress"]
        progress_texts = [m["message"] for m in progress_msgs]

        assert "Duplicate URL detected" in progress_texts


class TestCrossNormalization:
    """http→https and trailing slash variations resolve to the same record."""

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_http_vs_https_detected_as_duplicate(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        # Clip with https
        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result1 = clip_url("https://github.com/psf/requests", config)

        # Clip same URL with http should be detected as duplicate
        result2 = clip_url("http://github.com/psf/requests", config)
        assert result2 is not None
        assert result2.record_id == result1.record_id

        # DB has only one record
        index = ClipIndex(config.db_path)
        all_clips = index.query_clips()
        index.close()
        assert len(all_clips) == 1

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_trailing_slash_detected_as_duplicate(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        # Clip without trailing slash
        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result1 = clip_url("https://github.com/psf/requests", config)

        # Clip with trailing slash should be detected as duplicate
        raw2 = RawContent(
            url="https://github.com/psf/requests/",
            title="psf/requests",
            content_md="# Requests\n\nA simple HTTP library.",
            images=[],
            source_type="github",
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
        )
        # The duplicate check happens before routing, so this shouldn't
        # even need the adapter — but if it did, we're prepared
        result2 = clip_url("https://github.com/psf/requests/", config)
        assert result2 is not None
        assert result2.record_id == result1.record_id


class TestDifferentUrlsNotDuplicate:
    """Different URLs should NOT be treated as duplicates."""

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_different_url_not_detected_as_duplicate(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        # First clip
        with patch.object(GitHubAdapter, "fetch", return_value=sample_raw):
            result1 = clip_url("https://github.com/psf/requests", config)

        # Different URL — should NOT be duplicate
        raw2 = RawContent(
            url="https://github.com/psf/httpx",
            title="psf/httpx",
            content_md="# HTTPX\n\nA modern HTTP client.",
            images=[],
            source_type="github",
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
        )
        with patch.object(GitHubAdapter, "fetch", return_value=raw2):
            result2 = clip_url("https://github.com/psf/httpx", config)

        assert result2 is not None
        assert result2.record_id != result1.record_id

        index = ClipIndex(config.db_path)
        all_clips = index.query_clips()
        index.close()
        assert len(all_clips) == 2


class TestDuplicateCheckFailure:
    """Duplicate check failure must not block clipping."""

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_index_error_falls_through_to_normal_clip(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
        sample_raw: RawContent,
    ) -> None:
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        # Make find_by_url raise — but the clip should still work
        with (
            patch.object(GitHubAdapter, "fetch", return_value=sample_raw),
            patch("web_clip_helper.services.clip.ClipIndex") as MockIndex,
        ):
            # First call: find_by_url raises (simulating DB corruption)
            mock_instance = MagicMock()
            mock_instance.find_by_url.side_effect = Exception("DB broken")
            mock_instance.save_clip.return_value = 42
            mock_instance.close.return_value = None

            # The second ClipIndex() call (inside _store_and_index) should work normally
            def make_index(*args, **kwargs):
                # First invocation is the dup check — return broken mock
                # Subsequent invocations are in _store_and_index — use real ClipIndex
                if make_index.call_count == 0:
                    make_index.call_count += 1
                    return mock_instance
                # For save_clip, return a working mock
                real = ClipIndex(config.db_path)
                return real

            make_index.call_count = 0
            MockIndex.side_effect = make_index

            result = clip_url("https://github.com/psf/requests", config)

        # Clip should succeed despite duplicate check failure
        assert result is not None


class TestClipTextNotAffected:
    """clip_text should never be affected by duplicate detection."""

    def test_clip_text_twice_creates_two_records(
        self,
        config: Config,
    ) -> None:
        from web_clip_helper.pipeline import clip_text

        result1 = clip_text("Hello world", config)
        assert result1 is not None

        result2 = clip_text("Hello world", config)
        assert result2 is not None
        assert result2.record_id != result1.record_id

        index = ClipIndex(config.db_path)
        all_clips = index.query_clips()
        index.close()
        assert len(all_clips) == 2
