"""LLM integration — auto-generate titles, extract tags, classify content.

Uses an OpenAI-compatible API.  All methods are *gracefully* fallback-capable:
if the API key is missing, the network is down, or the response is malformed,
the caller still gets a sensible default — the clip pipeline never crashes due
to LLM issues.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from openai import OpenAI

from web_clip_helper.config import LLMConfig, PromptConfig

__all__ = ["LLMClient"]

logger = logging.getLogger(__name__)

# Maximum characters of content_md sent to the LLM (keeps token usage bounded).
MAX_CONTENT_CHARS = 4000


class _SafeDict(dict):
    """Dict subclass that returns ``""`` for missing keys and logs a warning.

    Used with :meth:`str.format_map` so that user-supplied prompt templates
    containing unknown placeholder keys (e.g. ``{foo}``) render as an empty
    string instead of raising :exc:`KeyError`.
    """

    def __missing__(self, key: str) -> str:  # type: ignore[override]
        logger.warning("Prompt template contains unknown placeholder: {%s}", key)
        return ""


class LLMClient:
    """Wrapper around an OpenAI-compatible chat-completion API.

    Parameters
    ----------
    config:
        An :class:`LLMConfig` instance (api_key, base_url, model).
        If *api_key* is empty, every method returns a fallback value
        immediately — no network call is attempted.
    """

    def __init__(self, config: LLMConfig, prompts: PromptConfig | None = None) -> None:
        self._config = config
        self._prompts = prompts or PromptConfig()
        self._client: OpenAI | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_title(
        self,
        content_md: str,
        source_type: str,
        url: str = "",
    ) -> str:
        """Ask LLM to summarise *content_md* into a concise title (≤50 chars).

        Fallback (no API key, network error, bad response): timestamp + domain
        from *url*, or first 50 chars of *content_md*.
        """
        if not self._has_api_key:
            return self._title_fallback(content_md, url)

        template_vars = _SafeDict(
            content_type=source_type,
            content=self._truncate(content_md),
        )

        if self._prompts.title:
            prompt = self._prompts.title.format_map(template_vars)
        else:
            prompt = (
                "请为以下内容生成一个简洁的标题，不超过50个字符。"
                "只返回标题文字，不要加引号或其他格式。\n\n"
                f"内容类型：{source_type}\n\n"
                f"内容：\n{self._truncate(content_md)}"
            )

        raw = self._chat(prompt)
        if raw:
            title = raw.strip().strip('"').strip("'")[:50]
            if title:
                return title

        return self._title_fallback(content_md, url)

    def extract_tags(
        self,
        content_md: str,
        source_type: str,
    ) -> list[str]:
        """Ask LLM to extract 3-8 relevant tags.

        Fallback: empty list.
        """
        if not self._has_api_key:
            return []

        template_vars = _SafeDict(
            content_type=source_type,
            content=self._truncate(content_md),
        )

        if self._prompts.tags:
            prompt = self._prompts.tags.format_map(template_vars)
        else:
            prompt = (
                "请从以下内容中提取3到8个相关标签。"
                "以JSON数组格式返回，例如：[\"标签1\", \"标签2\"]。\n"
                "只返回JSON数组，不要其他文字。\n\n"
                f"内容类型：{source_type}\n\n"
                f"内容：\n{self._truncate(content_md)}"
            )

        raw = self._chat(prompt)
        if raw:
            tags = self._parse_string_list(raw)
            if tags:
                return tags[:8]

        return []

    def classify_content(
        self,
        content_md: str,
        source_type: str,
    ) -> str:
        """Ask LLM to classify content into a single category string.

        Fallback: empty string.
        """
        if not self._has_api_key:
            return ""

        template_vars = _SafeDict(
            content_type=source_type,
            content=self._truncate(content_md),
        )

        if self._prompts.classify:
            prompt = self._prompts.classify.format_map(template_vars)
        else:
            prompt = (
                "请将以下内容归类到一个类别，只返回类别名称，不要加引号或其他格式。\n"
                "可选类别：技术、商业、文化、教育、娱乐、健康、科学、社会、生活、其他\n\n"
                f"内容类型：{source_type}\n\n"
                f"内容：\n{self._truncate(content_md)}"
            )

        raw = self._chat(prompt)
        if raw:
            category = raw.strip().strip('"').strip("'")
            if category:
                return category

        return ""

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @property
    def _has_api_key(self) -> bool:
        return bool(self._config.api_key.strip())

    def _get_client(self) -> OpenAI:
        """Lazy-initialise the OpenAI client."""
        if self._client is None:
            self._client = OpenAI(
                api_key=self._config.api_key,
                base_url=self._config.base_url,
            )
        return self._client

    def _chat(self, user_prompt: str) -> str | None:
        """Send a single-turn chat completion and return the text, or *None*."""
        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=self._config.model,
                messages=[{"role": "user", "content": user_prompt}],
                temperature=0.3,
                max_tokens=200,
            )
            choice = resp.choices[0]
            if choice.message and choice.message.content:
                return choice.message.content
            return None
        except Exception:
            logger.warning("LLM call failed")
            return None

    @staticmethod
    def _truncate(text: str, max_chars: int = MAX_CONTENT_CHARS) -> str:
        """Truncate *text* to *max_chars*, preserving partial content."""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...(内容已截断)"

    @staticmethod
    def _title_fallback(content_md: str, url: str) -> str:
        """Derive a title from *url* or content when LLM is unavailable."""
        # Try domain from URL
        if url:
            parsed = urlparse(url)
            domain = parsed.netloc or ""
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            if domain:
                return f"{ts} {domain}"

        # Fall back to first 50 chars of content
        first_line = content_md.lstrip().split("\n", 1)[0]
        return first_line[:50] or "Untitled"

    @staticmethod
    def _parse_string_list(raw: str) -> list[str]:
        """Best-effort parse a JSON array of strings from LLM output."""
        # Try direct JSON parse
        try:
            obj = json.loads(raw)
            if isinstance(obj, list):
                return [str(item).strip() for item in obj if str(item).strip()]
        except json.JSONDecodeError:
            pass

        # Try extracting JSON array via regex
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group())
                if isinstance(obj, list):
                    return [str(item).strip() for item in obj if str(item).strip()]
            except json.JSONDecodeError:
                pass

        # Try splitting by comma
        items = re.split(r"[,，、\n]", raw)
        return [item.strip().strip('"').strip("'") for item in items if item.strip()]
