"""Tests for custom prompt template rendering in LLMClient.

Covers:
- Custom prompt templates override built-in prompts for title/tags/classify
- Empty prompt strings fall back to built-in prompts
- Unknown placeholder keys return empty string with logger.warning
- Pipeline passes config.prompts to LLMClient
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.config import Config, LLMConfig, PromptConfig
from web_clip_helper.llm import LLMClient, _SafeDict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(
    api_key: str = "test-key",
    prompts: PromptConfig | None = None,
) -> LLMClient:
    cfg = LLMConfig(api_key=api_key, base_url="http://localhost:11434/v1", model="test")
    return LLMClient(cfg, prompts=prompts)


# ---------------------------------------------------------------------------
# TestPromptRendering
# ---------------------------------------------------------------------------


class TestPromptRendering:
    """Custom prompt templates are used when set; built-ins used otherwise."""

    def test_custom_title_prompt_used(self) -> None:
        """When prompts.title is set, it replaces the built-in title prompt."""
        client = _make_client(
            prompts=PromptConfig(title="Custom title for: {content}"),
        )
        with patch.object(client, "_chat", return_value="My Title") as mock_chat:
            result = client.generate_title("hello world", "article")
        assert result == "My Title"
        mock_chat.assert_called_once()
        actual_prompt = mock_chat.call_args[0][0]
        assert actual_prompt == "Custom title for: hello world"

    def test_custom_tags_prompt_used(self) -> None:
        """When prompts.tags is set, it replaces the built-in tags prompt."""
        client = _make_client(
            prompts=PromptConfig(tags='Tags for {content_type}: {content}'),
        )
        with patch.object(client, "_chat", return_value='["tag1", "tag2"]') as mock_chat:
            result = client.extract_tags("some text", "blog")
        assert result == ["tag1", "tag2"]
        mock_chat.assert_called_once()
        actual_prompt = mock_chat.call_args[0][0]
        assert actual_prompt == "Tags for blog: some text"

    def test_custom_classify_prompt_used(self) -> None:
        """When prompts.classify is set, it replaces the built-in classify prompt."""
        client = _make_client(
            prompts=PromptConfig(classify="Classify this {content_type} stuff"),
        )
        with patch.object(client, "_chat", return_value="技术") as mock_chat:
            result = client.classify_content("some text", "article")
        assert result == "技术"
        mock_chat.assert_called_once()
        actual_prompt = mock_chat.call_args[0][0]
        assert actual_prompt == "Classify this article stuff"

    def test_empty_prompt_uses_builtin(self) -> None:
        """When PromptConfig fields are empty strings, built-in prompts are used."""
        client = _make_client(prompts=PromptConfig(title="", tags="", classify=""))

        # Verify generate_title uses built-in prompt
        with patch.object(client, "_chat", return_value="A Title") as mock_chat:
            client.generate_title("content", "article")
        prompt = mock_chat.call_args[0][0]
        assert "请为以下内容生成一个简洁的标题" in prompt

        # Verify extract_tags uses built-in prompt
        with patch.object(client, "_chat", return_value='["t"]') as mock_chat:
            client.extract_tags("content", "article")
        prompt = mock_chat.call_args[0][0]
        assert "请从以下内容中提取3到8个相关标签" in prompt

        # Verify classify_content uses built-in prompt
        with patch.object(client, "_chat", return_value="技术") as mock_chat:
            client.classify_content("content", "article")
        prompt = mock_chat.call_args[0][0]
        assert "请将以下内容归类到一个类别" in prompt

    def test_unknown_placeholder_returns_empty(self) -> None:
        """Templates with unknown placeholders render without error (empty string)."""
        client = _make_client(
            prompts=PromptConfig(title="Hello {unknown_key} world"),
        )
        with patch.object(client, "_chat", return_value="Result") as mock_chat:
            result = client.generate_title("content", "article")
        assert result == "Result"
        actual_prompt = mock_chat.call_args[0][0]
        assert actual_prompt == "Hello  world"

    def test_unknown_placeholder_logs_warning(self) -> None:
        """Unknown placeholder keys trigger a logger.warning."""
        with patch("web_clip_helper.services.llm.logger") as mock_logger:
            sd = _SafeDict({"content": "hello"})
            result = sd["nonexistent_key"]
            assert result == ""
            mock_logger.warning.assert_called_once()
            # Verify the warning message mentions the unknown key
            args = mock_logger.warning.call_args[0]
            assert "nonexistent_key" in str(args)

    def test_missing_content_type_in_template(self) -> None:
        """A template that omits {content_type} still works — the value is unused."""
        client = _make_client(
            prompts=PromptConfig(title="Just content: {content}"),
        )
        with patch.object(client, "_chat", return_value="Title") as mock_chat:
            result = client.generate_title("my text", "article")
        assert result == "Title"
        actual_prompt = mock_chat.call_args[0][0]
        assert actual_prompt == "Just content: my text"


# ---------------------------------------------------------------------------
# TestPipelineIntegration
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    """Pipeline wiring passes config.prompts to LLMClient."""

    @patch("web_clip_helper.services.clip.LLMClient")
    def test_pipeline_passes_prompts_to_llm_client(self, mock_llm_cls: MagicMock) -> None:
        """_enrich_with_llm constructs LLMClient with config.prompts."""
        from web_clip_helper.pipeline import _enrich_with_llm
        from web_clip_helper.models import RawContent
        from datetime import datetime

        prompts = PromptConfig(title="Custom: {content}", tags="", classify="")
        config = Config(
            storage_path="/tmp/test",
            db_path="/tmp/test.db",
            llm=LLMConfig(api_key="key", base_url="http://localhost:11434/v1"),
            prompts=prompts,
        )

        mock_instance = MagicMock()
        mock_instance.generate_title.return_value = "Title"
        mock_instance.extract_tags.return_value = ["tag"]
        mock_instance.classify_content.return_value = "tech"
        mock_llm_cls.return_value = mock_instance

        raw = RawContent(
            url="https://example.com",
            title="Test",
            content_md="Some content",
            images=[],
            source_type="article",
            fetched_at=datetime.now(),
        )

        _enrich_with_llm(raw, config)

        mock_llm_cls.assert_called_once()
        call_args = mock_llm_cls.call_args
        # Check that prompts was passed — could be positional or keyword
        assert call_args.kwargs.get("prompts") is prompts or (
            len(call_args.args) >= 2 and call_args.args[1] is prompts
        ), f"Expected prompts kwarg, got call_args={call_args}"
