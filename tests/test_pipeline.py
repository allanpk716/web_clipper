"""End-to-end pipeline tests — clip_url and clip_text with mocked adapters."""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from agentsdk import Writer

from web_clip_helper.app import get_app
from web_clip_helper.config import Config
from web_clip_helper.models import RawContent
from web_clip_helper.pipeline import clip_text, clip_url

# Trigger adapter registration
import web_clip_helper.adapters._registry  # noqa: F401


@pytest.fixture(autouse=True)
def _reset_app():
    """Reset SDK App singleton and install a Writer targeting a StringIO buffer."""
    import web_clip_helper.app as mod
    mod._app = None
    app = get_app()
    _writer_buf = io.StringIO()
    app.set_writer(Writer(_writer_buf, tool_name="web-clip-helper"))
    yield
    mod._app = None


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


def _get_writer_buf() -> io.StringIO:
    """Return the StringIO buffer attached to the current test Writer."""
    return get_app().writer._output  # type: ignore[return-value]


def _capture_jsonl() -> list[dict]:
    """Parse JSONL lines written to the SDK Writer buffer.

    The SDK Writer produces structured envelopes.  This helper flattens
    them back to the shape the existing test assertions expect so that
    tests can continue to access fields like ``msg["source_type"]`` and
    ``msg["stage"]`` at the top level.

    Flattening rules:

    * ``result`` envelopes: merge ``data`` dict into the top level.
    * ``error`` envelopes: parse ``stage`` from the ``message`` field
      (format ``"[stage] detail"``) and add ``stage``/``detail`` keys.
    * ``progress`` / ``warning`` envelopes: already flat, returned as-is.
    """
    output = _get_writer_buf().getvalue()
    lines = [line for line in output.strip().split("\n") if line.strip()]
    messages: list[dict] = []
    for line in lines:
        msg = json.loads(line)
        msg_type = msg.get("type")
        if msg_type == "result" and "data" in msg:
            flat = {k: v for k, v in msg.items() if k != "data"}
            flat.update(msg["data"])
            messages.append(flat)
        elif msg_type == "error":
            # Parse "[stage] detail" from message
            raw_msg = msg.get("message", "")
            if raw_msg.startswith("[") and "]" in raw_msg:
                bracket_end = raw_msg.index("]")
                msg["stage"] = raw_msg[1:bracket_end]
                msg["detail"] = raw_msg[bracket_end + 1:].strip()
            else:
                msg["stage"] = ""
                msg["detail"] = raw_msg
            messages.append(msg)
        else:
            messages.append(msg)
    return messages


class TestClipUrl:
    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
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

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
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

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
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

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_url_jsonl_output(
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

        messages = _capture_jsonl()
        types = [m["type"] for m in messages]

        assert "progress" in types
        assert "result" in types

        # Find the result message
        result_msgs = [m for m in messages if m["type"] == "result"]
        assert len(result_msgs) == 1
        assert result_msgs[0]["source_type"] == "github"

    @patch("web_clip_helper.services.clip.route_url")
    def test_url_adapter_error(
        self,
        mock_route: MagicMock,
        config: Config,
    ) -> None:
        from web_clip_helper.adapter import AdapterError
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter

        with patch.object(GitHubAdapter, "fetch", side_effect=AdapterError("404 Not Found")):
            result = clip_url("https://github.com/nonexistent/repo", config)

        assert result is None
        messages = _capture_jsonl()
        error_msgs = [m for m in messages if m["type"] == "error"]
        assert len(error_msgs) >= 1
        assert error_msgs[0]["stage"] == "fetch"

    @patch("web_clip_helper.services.clip.route_url")
    def test_url_routing_error(
        self,
        mock_route: MagicMock,
        config: Config,
    ) -> None:
        mock_route.side_effect = ValueError("Invalid URL")

        result = clip_url("", config)
        assert result is None
        messages = _capture_jsonl()
        error_msgs = [m for m in messages if m["type"] == "error"]
        assert len(error_msgs) >= 1
        assert error_msgs[0]["stage"] == "routing"

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
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

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_url_image_download_failure_non_fatal(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
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
        messages = _capture_jsonl()
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


class TestLLMEnrichment:
    """Tests for LLM enrichment integration in the pipeline."""

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_llm_enrichment_populates_tags_and_category(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Pipeline with mocked LLM returns tags and category in SQLite."""
        from web_clip_helper.adapters.github import GitHubAdapter
        from web_clip_helper.config import LLMConfig

        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
            llm=LLMConfig(api_key="test-key", model="test-model"),
        )

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://example.com/article",
            title="Original Title",
            content_md="This is a test article about Python.",
            images=[],
            source_type="web",
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            with patch("web_clip_helper.services.clip.LLMClient") as MockLLM:
                mock_client = MockLLM.return_value
                mock_client.generate_title.return_value = "LLM Generated Title"
                mock_client.extract_tags.return_value = ["python", "programming"]
                mock_client.classify_content.return_value = "技术"

                result = clip_url("https://example.com/article", config)

        assert result is not None
        assert result.record_id is not None

        from web_clip_helper.index import ClipIndex
        idx = ClipIndex(config.db_path)
        record = idx.get_clip(result.record_id)
        assert record is not None
        assert record["title"] == "LLM Generated Title"
        assert record["tags"] == ["python", "programming"]
        assert record["category"] == "技术"
        idx.close()

        # Verify JSONL result includes tags and category
        messages = _capture_jsonl()
        result_msgs = [m for m in messages if m["type"] == "result"]
        assert len(result_msgs) == 1
        assert result_msgs[0]["tags"] == ["python", "programming"]
        assert result_msgs[0]["category"] == "技术"

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_llm_failure_uses_fallback(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        tmp_path: Path,
    ) -> None:
        """LLM throws exception → fallback title, empty tags/category, warning emitted."""
        from web_clip_helper.adapters.github import GitHubAdapter
        from web_clip_helper.config import LLMConfig

        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
            llm=LLMConfig(api_key="test-key"),
        )

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://example.com/article",
            title="Fallback Title",
            content_md="Content here",
            images=[],
            source_type="web",
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            with patch("web_clip_helper.services.clip.LLMClient") as MockLLM:
                mock_client = MockLLM.return_value
                mock_client.generate_title.side_effect = Exception("API error")

                result = clip_url("https://example.com/article", config)

        assert result is not None
        from web_clip_helper.index import ClipIndex
        idx = ClipIndex(config.db_path)
        record = idx.get_clip(result.record_id)
        assert record is not None
        assert record["title"] == "Fallback Title"
        assert record["tags"] == []
        assert record["category"] == ""
        idx.close()

        # Warning should be emitted
        messages = _capture_jsonl()
        warnings = [m for m in messages if m["type"] == "warning"]
        assert any("llm" in str(w).lower() for w in warnings)

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_no_api_key_skips_llm(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        tmp_path: Path,
    ) -> None:
        """No API key → LLMClient is never instantiated, warning emitted."""
        from web_clip_helper.adapters.github import GitHubAdapter

        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
        )

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://example.com/article",
            title="No API Key Title",
            content_md="Content",
            images=[],
            source_type="web",
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            with patch("web_clip_helper.services.clip.LLMClient") as MockLLM:
                result = clip_url("https://example.com/article", config)
                # LLMClient should NOT be instantiated
                MockLLM.assert_not_called()

        assert result is not None
        from web_clip_helper.index import ClipIndex
        idx = ClipIndex(config.db_path)
        record = idx.get_clip(result.record_id)
        assert record is not None
        assert record["tags"] == []
        assert record["category"] == ""
        idx.close()

        # Warning should be emitted about no API key
        messages = _capture_jsonl()
        warnings = [m for m in messages if m["type"] == "warning"]
        assert any("no API key" in str(w) for w in warnings)

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_llm_title_used_for_storage_directory(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        tmp_path: Path,
    ) -> None:
        """LLM-generated title is used for the storage directory name."""
        from web_clip_helper.adapters.github import GitHubAdapter
        from web_clip_helper.config import LLMConfig

        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
            llm=LLMConfig(api_key="test-key"),
        )

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://example.com/article",
            title="Original Title",
            content_md="Content",
            images=[],
            source_type="web",
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            with patch("web_clip_helper.services.clip.LLMClient") as MockLLM:
                mock_client = MockLLM.return_value
                mock_client.generate_title.return_value = "LLM Custom Title"
                mock_client.extract_tags.return_value = []
                mock_client.classify_content.return_value = ""

                result = clip_url("https://example.com/article", config)

        assert result is not None
        # Directory name should contain the LLM-generated title (spaces preserved)
        assert "LLM Custom Title" in result.folder_path.name

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_llm_enrichment_progress_messages(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        tmp_path: Path,
    ) -> None:
        """LLM enrichment emits start/complete progress messages."""
        from web_clip_helper.adapters.github import GitHubAdapter
        from web_clip_helper.config import LLMConfig

        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
            llm=LLMConfig(api_key="test-key"),
        )

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://example.com/article",
            title="Title",
            content_md="Content",
            images=[],
            source_type="web",
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            with patch("web_clip_helper.services.clip.LLMClient") as MockLLM:
                mock_client = MockLLM.return_value
                mock_client.generate_title.return_value = "Title"
                mock_client.extract_tags.return_value = []
                mock_client.classify_content.return_value = ""

                result = clip_url("https://example.com/article", config)

        assert result is not None
        messages = _capture_jsonl()
        progress_msgs = [m for m in messages if m["type"] == "progress"]
        progress_texts = [m["message"] for m in progress_msgs]
        assert any("LLM enrichment starting" in t for t in progress_texts)
        assert any("LLM enrichment complete" in t for t in progress_texts)

    def test_clip_text_with_llm_enrichment(
        self,
        tmp_path: Path,
    ) -> None:
        """clip_text also gets LLM enrichment when API key present."""
        from web_clip_helper.config import LLMConfig

        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
            llm=LLMConfig(api_key="test-key"),
        )

        with patch("web_clip_helper.services.clip.LLMClient") as MockLLM:
            mock_client = MockLLM.return_value
            mock_client.generate_title.return_value = "Text Clip Title"
            mock_client.extract_tags.return_value = ["notes"]
            mock_client.classify_content.return_value = "生活"

            result = clip_text("Some raw text content here", config)

        assert result is not None
        from web_clip_helper.index import ClipIndex
        idx = ClipIndex(config.db_path)
        record = idx.get_clip(result.record_id)
        assert record is not None
        assert record["title"] == "Text Clip Title"
        assert record["tags"] == ["notes"]
        assert record["category"] == "生活"
        idx.close()

    def test_clip_text_no_api_key_no_llm_call(
        self,
        tmp_path: Path,
    ) -> None:
        """clip_text with no API key: no LLM call, fallback values in SQLite."""
        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
        )

        with patch("web_clip_helper.services.clip.LLMClient") as MockLLM:
            result = clip_text("Some text content", config)
            MockLLM.assert_not_called()

        assert result is not None
        from web_clip_helper.index import ClipIndex
        idx = ClipIndex(config.db_path)
        record = idx.get_clip(result.record_id)
        assert record is not None
        assert record["tags"] == []
        assert record["category"] == ""
        idx.close()

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_llm_empty_response_uses_fallback(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        tmp_path: Path,
    ) -> None:
        """LLM returns empty/None for all methods → fallback values used."""
        from web_clip_helper.adapters.github import GitHubAdapter
        from web_clip_helper.config import LLMConfig

        config = Config(
            storage_path=str(tmp_path / "clips"),
            db_path=str(tmp_path / "test.db"),
            llm=LLMConfig(api_key="test-key"),
        )

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://example.com/article",
            title="Fallback Title",
            content_md="Content",
            images=[],
            source_type="web",
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            with patch("web_clip_helper.services.clip.LLMClient") as MockLLM:
                mock_client = MockLLM.return_value
                # generate_title returns empty → LLMClient itself falls back
                mock_client.generate_title.return_value = "Fallback Title"
                mock_client.extract_tags.return_value = []
                mock_client.classify_content.return_value = ""

                result = clip_url("https://example.com/article", config)

        assert result is not None
        from web_clip_helper.index import ClipIndex
        idx = ClipIndex(config.db_path)
        record = idx.get_clip(result.record_id)
        assert record is not None
        assert record["title"] == "Fallback Title"
        assert record["tags"] == []
        assert record["category"] == ""
        idx.close()


class TestNegativePaths:
    """Negative tests for error handling and boundary conditions."""

    @patch("web_clip_helper.services.clip.route_url")
    def test_unexpected_adapter_exception(
        self,
        mock_route: MagicMock,
        config: Config,
    ) -> None:
        """Adapter throws a non-AdapterError exception."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter

        with patch.object(GitHubAdapter, "fetch", side_effect=RuntimeError("boom")):
            result = clip_url("https://github.com/test/repo", config)

        assert result is None
        messages = _capture_jsonl()
        errors = [m for m in messages if m["type"] == "error"]
        assert any(e["stage"] == "fetch" for e in errors)

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_storage_write_failure(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
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
                "web_clip_helper.services.clip.StorageManager.create_entry",
                side_effect=OSError("Permission denied"),
            ):
                result = clip_url("https://github.com/test/repo", config)

        assert result is None
        messages = _capture_jsonl()
        errors = [m for m in messages if m["type"] == "error"]
        assert any(e["stage"] == "storage" for e in errors)

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_sqlite_failure(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
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
                "web_clip_helper.services.clip.ClipIndex.save_clip",
                side_effect=Exception("DB error"),
            ):
                result = clip_url("https://github.com/test/repo", config)

        assert result is None
        messages = _capture_jsonl()
        errors = [m for m in messages if m["type"] == "error"]
        assert any(e["stage"] == "index" for e in errors)

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
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

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
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


class TestExtraFiles:
    """Tests for pipeline extra_files (PDF, etc.) persistence."""

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_extra_files_triggers_file_saves(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
    ) -> None:
        """RawContent with extra_files causes files to be saved to disk."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        pdf_bytes = b"%PDF-1.4 fake content"
        raw = RawContent(
            url="https://arxiv.org/abs/2603.00195",
            title="Test Paper",
            content_md="# Test Paper\n\nAbstract here.",
            images=[],
            source_type="arxiv",
            extra_files={"paper.pdf": pdf_bytes},
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            result = clip_url("https://arxiv.org/abs/2603.00195", config)

        assert result is not None
        # The PDF file should exist in the entry directory
        pdf_path = result.folder_path / "paper.pdf"
        assert pdf_path.exists()
        assert pdf_path.read_bytes() == pdf_bytes

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_extra_files_jsonl_progress(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
    ) -> None:
        """Saving extra_files emits JSONL progress messages."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://arxiv.org/abs/2603.00195",
            title="Progress Test",
            content_md="# Test",
            images=[],
            source_type="arxiv",
            extra_files={"doc.pdf": b"%PDF-1.4 test"},
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            result = clip_url("https://arxiv.org/abs/2603.00195", config)

        assert result is not None
        messages = _capture_jsonl()
        progress_msgs = [m for m in messages if m["type"] == "progress"]
        progress_texts = [m["message"] for m in progress_msgs]
        assert any("Saved extra file" in t for t in progress_texts)

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_extra_file_save_failure_returns_none(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
    ) -> None:
        """If save_file fails for an extra file, pipeline returns None (fatal)."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://arxiv.org/abs/2603.00195",
            title="Fail Test",
            content_md="# Test",
            images=[],
            source_type="arxiv",
            extra_files={"bad.pdf": b"content"},
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            with patch(
                "web_clip_helper.services.clip.StorageManager.save_file",
                side_effect=OSError("disk full"),
            ):
                result = clip_url("https://arxiv.org/abs/2603.00195", config)

        assert result is None
        messages = _capture_jsonl()
        errors = [m for m in messages if m["type"] == "error"]
        assert any(e["stage"] == "storage" for e in errors)

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_extra_files_multiple(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
    ) -> None:
        """Multiple extra_files are all saved."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://arxiv.org/abs/2603.00195",
            title="Multi File Test",
            content_md="# Test",
            images=[],
            source_type="arxiv",
            extra_files={
                "paper.pdf": b"%PDF-1.4 content",
                "supplement.pdf": b"%PDF-1.5 supplement",
            },
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            result = clip_url("https://arxiv.org/abs/2603.00195", config)

        assert result is not None
        assert (result.folder_path / "paper.pdf").exists()
        assert (result.folder_path / "supplement.pdf").exists()
        assert (result.folder_path / "paper.pdf").read_bytes() == b"%PDF-1.4 content"
        assert (result.folder_path / "supplement.pdf").read_bytes() == b"%PDF-1.5 supplement"

    @patch("web_clip_helper.services.clip.download_images")
    @patch("web_clip_helper.services.clip.route_url")
    def test_no_extra_files_no_extra_saves(
        self,
        mock_route: MagicMock,
        mock_dl: MagicMock,
        config: Config,
    ) -> None:
        """RawContent without extra_files doesn't trigger save_file."""
        from web_clip_helper.adapters.github import GitHubAdapter

        mock_route.return_value = GitHubAdapter
        mock_dl.return_value = {}

        raw = RawContent(
            url="https://github.com/test/repo",
            title="No Extra",
            content_md="# Just markdown",
            images=[],
            source_type="github",
            extra_files={},
        )

        with patch.object(GitHubAdapter, "fetch", return_value=raw):
            with patch("web_clip_helper.services.clip.StorageManager.save_file") as mock_save:
                result = clip_url("https://github.com/test/repo", config)

        assert result is not None
        mock_save.assert_not_called()
