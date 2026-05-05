"""Tests for LLMClient — title generation, tag extraction, classification.

All tests mock ``openai.OpenAI`` so no real API calls are made.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.config import LLMConfig
from web_clip_helper.llm import MAX_CONTENT_CHARS, LLMClient


# ── Helpers ──────────────────────────────────────────────────────────


def _config(api_key: str = "sk-test-key") -> LLMConfig:
    return LLMConfig(api_key=api_key, base_url="https://api.example.com/v1", model="test-model")


def _mock_choice(content: str | None) -> MagicMock:
    """Build a mock ``choices[0]`` with the given content."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    return choice


def _mock_response(content: str | None) -> MagicMock:
    """Build a mock ``chat.completions.create`` return value."""
    resp = MagicMock()
    resp.choices = [_mock_choice(content)]
    return resp


SAMPLE_CHINESE = (
    "人工智能（Artificial Intelligence，简称AI）是计算机科学的一个分支，"
    "它企图了解智能的实质，并生产出一种新的能以人类智能相似的方式做出反应的智能机器。"
    "研究包括机器人、语言识别、图像识别、自然语言处理和专家系统等。"
    "人工智能从诞生以来，理论和技术日益成熟，应用领域不断扩大。"
) * 5  # ~500 chars

SAMPLE_ENGLISH = (
    "Machine learning is a subset of artificial intelligence that provides "
    "systems the ability to automatically learn and improve from experience "
    "without being explicitly programmed. Machine learning focuses on the "
    "development of computer programs that can access data and use it to "
    "learn for themselves."
) * 5

SAMPLE_MIXED = (
    "Python 是一种广泛使用的高级编程语言。It is known for its clear syntax "
    "and readability. Python supports multiple programming paradigms, including "
    "面向对象、函数式和过程式编程。"
) * 5


# ── No API key → immediate fallback ─────────────────────────────────


class TestNoApiKey:
    """When api_key is empty, every method returns a fallback immediately."""

    def test_generate_title_fallback_with_url(self) -> None:
        client = LLMClient(_config(api_key=""))
        title = client.generate_title("some content", "article", url="https://example.com/page")
        assert "example.com" in title
        assert len(title) <= 80  # reasonable

    def test_generate_title_fallback_without_url(self) -> None:
        client = LLMClient(_config(api_key=""))
        title = client.generate_title("First line of content\nmore", "article")
        assert title == "First line of content"

    def test_generate_title_fallback_empty_content(self) -> None:
        client = LLMClient(_config(api_key=""))
        title = client.generate_title("", "article")
        assert title == "Untitled"

    def test_extract_tags_returns_empty(self) -> None:
        client = LLMClient(_config(api_key=""))
        assert client.extract_tags(SAMPLE_CHINESE, "article") == []

    def test_classify_returns_empty(self) -> None:
        client = LLMClient(_config(api_key=""))
        assert client.classify_content(SAMPLE_CHINESE, "article") == ""

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_no_openai_instantiation(self, mock_openai_cls: MagicMock) -> None:
        """Verify that OpenAI() is never called when api_key is empty."""
        client = LLMClient(_config(api_key=""))
        client.generate_title("x", "article")
        client.extract_tags("x", "article")
        client.classify_content("x", "article")
        mock_openai_cls.assert_not_called()


# ── generate_title ───────────────────────────────────────────────────


class TestGenerateTitle:
    """LLM-generated title behaviour."""

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_successful_title(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("人工智能简介")

        client = LLMClient(_config())
        title = client.generate_title(SAMPLE_CHINESE, "article")
        assert title == "人工智能简介"

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_title_truncated_to_50(self, mock_openai_cls: MagicMock) -> None:
        long_title = "这是一个非常非常非常非常非常非常非常非常非常非常长的标题超出了限制"
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response(long_title)

        client = LLMClient(_config())
        title = client.generate_title(SAMPLE_CHINESE, "article")
        assert len(title) <= 50

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_title_strips_quotes(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response('"AI技术解析"')

        client = LLMClient(_config())
        title = client.generate_title(SAMPLE_CHINESE, "article")
        assert title == "AI技术解析"

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_title_empty_response_fallback(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("")

        client = LLMClient(_config())
        title = client.generate_title(SAMPLE_CHINESE, "article", url="https://example.com/a")
        assert "example.com" in title

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_title_none_response_fallback(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response(None)

        client = LLMClient(_config())
        title = client.generate_title("content", "article")
        assert title == "content"

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_title_api_error_fallback(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API error")

        client = LLMClient(_config())
        title = client.generate_title("content here", "article", url="https://test.com")
        assert "test.com" in title

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_title_timeout_fallback(self, mock_openai_cls: MagicMock) -> None:
        import openai

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = openai.APITimeoutError("timeout")

        client = LLMClient(_config())
        title = client.generate_title("content here", "article")
        assert title == "content here"


# ── extract_tags ─────────────────────────────────────────────────────


class TestExtractTags:
    """Tag extraction behaviour."""

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_successful_tags(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response(
            '["人工智能", "机器学习", "深度学习"]'
        )

        client = LLMClient(_config())
        tags = client.extract_tags(SAMPLE_CHINESE, "article")
        assert tags == ["人工智能", "机器学习", "深度学习"]

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_tags_capped_at_8(self, mock_openai_cls: MagicMock) -> None:
        nine_tags = json.dumps([f"tag{i}" for i in range(9)])
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response(nine_tags)

        client = LLMClient(_config())
        tags = client.extract_tags(SAMPLE_ENGLISH, "article")
        assert len(tags) == 8

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_tags_malformed_json_fallback(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        # LLM sometimes wraps JSON in prose
        mock_client.chat.completions.create.return_value = _mock_response(
            '标签如下：人工智能，机器学习，Python'
        )

        client = LLMClient(_config())
        tags = client.extract_tags(SAMPLE_MIXED, "article")
        assert isinstance(tags, list)
        assert len(tags) >= 1  # comma-split produces results

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_tags_empty_response(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("")

        client = LLMClient(_config())
        tags = client.extract_tags(SAMPLE_CHINESE, "article")
        assert tags == []

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_tags_api_error_returns_empty(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = ConnectionError("network down")

        client = LLMClient(_config())
        tags = client.extract_tags(SAMPLE_CHINESE, "article")
        assert tags == []

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_tags_embedded_json_array(self, mock_openai_cls: MagicMock) -> None:
        """LLM sometimes wraps JSON in text like 'Here are the tags: [...]'."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response(
            '以下是标签：["AI", "ML", "Python"]\n希望对你有帮助！'
        )

        client = LLMClient(_config())
        tags = client.extract_tags(SAMPLE_MIXED, "article")
        assert "AI" in tags
        assert "ML" in tags
        assert "Python" in tags


# ── classify_content ─────────────────────────────────────────────────


class TestClassifyContent:
    """Content classification behaviour."""

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_successful_classification(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("技术")

        client = LLMClient(_config())
        cat = client.classify_content(SAMPLE_CHINESE, "article")
        assert cat == "技术"

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_classification_strips_quotes(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response('"科学"')

        client = LLMClient(_config())
        cat = client.classify_content(SAMPLE_CHINESE, "article")
        assert cat == "科学"

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_classification_empty_response(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("")

        client = LLMClient(_config())
        cat = client.classify_content(SAMPLE_CHINESE, "article")
        assert cat == ""

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_classification_none_response(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response(None)

        client = LLMClient(_config())
        cat = client.classify_content(SAMPLE_CHINESE, "article")
        assert cat == ""

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_classification_api_error(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = RuntimeError("fail")

        client = LLMClient(_config())
        cat = client.classify_content(SAMPLE_CHINESE, "article")
        assert cat == ""


# ── Content truncation ───────────────────────────────────────────────


class TestContentTruncation:
    """Content is truncated before being sent to the LLM."""

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_long_content_is_truncated(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("title")

        long_content = "x" * (MAX_CONTENT_CHARS + 5000)
        client = LLMClient(_config())
        client.generate_title(long_content, "article")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages") or call_args[0][0]
        # Extract the user message content
        if isinstance(messages, list):
            user_msg = messages[0]["content"]
        else:
            user_msg = str(messages)

        assert len(user_msg) <= MAX_CONTENT_CHARS + 200  # allow for prefix text
        assert "...(内容已截断)" in user_msg

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_short_content_not_truncated(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("title")

        short_content = "Short content"
        client = LLMClient(_config())
        client.generate_title(short_content, "article")

        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        user_msg = messages[0]["content"]
        assert "...(内容已截断)" not in user_msg


# ── Title fallback details ──────────────────────────────────────────


class TestTitleFallback:
    """Title fallback derivation logic."""

    def test_fallback_with_domain(self) -> None:
        client = LLMClient(_config(api_key=""))
        title = client.generate_title("any", "article", url="https://www.example.com/path")
        assert "www.example.com" in title
        # Should contain a date-like pattern
        assert "20" in title  # year prefix

    def test_fallback_without_url_uses_content(self) -> None:
        client = LLMClient(_config(api_key=""))
        title = client.generate_title("My Article Title\nSecond line", "article")
        assert title == "My Article Title"

    def test_fallback_first_line_truncated_to_50(self) -> None:
        client = LLMClient(_config(api_key=""))
        long_line = "A" * 100
        title = client.generate_title(long_line, "article")
        assert len(title) == 50

    def test_fallback_empty_content_empty_url(self) -> None:
        client = LLMClient(_config(api_key=""))
        title = client.generate_title("", "article")
        assert title == "Untitled"


# ── API client initialisation ────────────────────────────────────────


class TestClientInit:
    """OpenAI client is lazily initialised with correct params."""

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_client_created_with_config(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("title")

        cfg = _config()
        client = LLMClient(cfg)
        client.generate_title("x", "article")

        mock_openai_cls.assert_called_once_with(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
        )

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_client_reused_across_calls(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("ok")

        client = LLMClient(_config())
        client.generate_title("x", "article")
        client.extract_tags("x", "article")
        client.classify_content("x", "article")

        # OpenAI() should be called only once (lazy init)
        assert mock_openai_cls.call_count == 1


# ── Mixed content types ─────────────────────────────────────────────


class TestMixedContent:
    """Verify methods work with various content types."""

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_chinese_content_title(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("AI技术概述")

        client = LLMClient(_config())
        assert client.generate_title(SAMPLE_CHINESE, "article") == "AI技术概述"

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_english_content_tags(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response(
            '["machine learning", "AI", "data science"]'
        )

        client = LLMClient(_config())
        tags = client.extract_tags(SAMPLE_ENGLISH, "article")
        assert len(tags) == 3

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_mixed_content_classification(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("技术")

        client = LLMClient(_config())
        assert client.classify_content(SAMPLE_MIXED, "article") == "技术"

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_tweet_source_type(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("今日动态")

        client = LLMClient(_config())
        title = client.generate_title("Just shipped a new feature!", "tweet")
        assert title == "今日动态"

    @patch("web_clip_helper.services.llm.OpenAI")
    def test_wechat_source_type(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_response("深度分析")

        client = LLMClient(_config())
        title = client.generate_title(SAMPLE_CHINESE, "wechat")
        assert title == "深度分析"


# ── _parse_string_list edge cases ───────────────────────────────────


class TestParseStringList:
    """Edge-case parsing of LLM tag output."""

    def test_valid_json_array(self) -> None:
        assert LLMClient._parse_string_list('["a", "b", "c"]') == ["a", "b", "c"]

    def test_json_with_surrounding_text(self) -> None:
        result = LLMClient._parse_string_list('Tags: ["x", "y"] end')
        assert "x" in result and "y" in result

    def test_comma_separated(self) -> None:
        result = LLMClient._parse_string_list("AI, ML, Python")
        assert len(result) == 3

    def test_chinese_comma_separated(self) -> None:
        result = LLMClient._parse_string_list("人工智能，机器学习，Python")
        assert len(result) >= 2

    def test_empty_string(self) -> None:
        assert LLMClient._parse_string_list("") == []

    def test_whitespace_only(self) -> None:
        result = LLMClient._parse_string_list("  \n  ")
        # All empty after strip
        assert all(r for r in result) or result == []
