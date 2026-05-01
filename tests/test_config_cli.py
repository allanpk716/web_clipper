"""Integration tests for the ``config`` CLI subcommands."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from web_clip_helper.cli import app

runner = CliRunner()


# ── Helpers ─────────────────────────────────────────────────────────


def _write_config(path: Path, data: dict) -> None:
    """Write a YAML config dict to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output into a list of dicts."""
    return [json.loads(line) for line in output.strip().splitlines() if line.strip()]


def _config_args(path: Path | None = None) -> list[str]:
    """Build --path argument list when a custom path is provided."""
    return ["--path", str(path)] if path else []


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Return a path to a temporary config.yaml with some data."""
    p = tmp_path / "config.yaml"
    _write_config(p, {
        "llm": {"api_key": "sk-test-secret-key-1234", "base_url": "https://api.example.com/v1", "model": "gpt-4"},
        "refresh": {"default_interval_days": 14},
    })
    return p


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure no LLM env-var overrides leak into config CLI tests."""
    for var in ("WEB_CLIP_LLM_API_KEY", "WEB_CLIP_LLM_BASE_URL", "WEB_CLIP_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)


# ── config list ─────────────────────────────────────────────────────


class TestConfigList:
    """Tests for ``config list``."""

    def test_list_returns_jsonl_with_masked_api_key(self, config_file: Path) -> None:
        result = runner.invoke(app, ["config", "list", "--path", str(config_file)])
        assert result.exit_code == 0, result.output
        lines = _parse_jsonl(result.output)
        # Should contain llm.api_key with masked value
        api_key_entries = [l for l in lines if l.get("key") == "llm.api_key"]
        assert len(api_key_entries) == 1
        assert "sk-****" in api_key_entries[0]["value"]
        assert "secret" not in api_key_entries[0]["value"]

    def test_list_shows_all_fields(self, config_file: Path) -> None:
        result = runner.invoke(app, ["config", "list", "--path", str(config_file)])
        assert result.exit_code == 0, result.output
        lines = _parse_jsonl(result.output)
        keys = {l["key"] for l in lines if "key" in l}
        # Must cover all config fields
        assert "llm.api_key" in keys
        assert "llm.base_url" in keys
        assert "llm.model" in keys
        assert "refresh.default_interval_days" in keys
        assert "prompts.title" in keys
        assert "prompts.tags" in keys
        assert "prompts.classify" in keys

    def test_list_with_defaults(self, tmp_path: Path) -> None:
        """Config list on a fresh (auto-created) config shows defaults."""
        fresh = tmp_path / "subdir" / "config.yaml"
        result = runner.invoke(app, ["config", "list", "--path", str(fresh)])
        assert result.exit_code == 0, result.output
        lines = _parse_jsonl(result.output)
        model_entries = [l for l in lines if l.get("key") == "llm.model"]
        assert len(model_entries) == 1
        assert model_entries[0]["value"] == "gpt-4o-mini"

    def test_list_path_option(self, config_file: Path) -> None:
        """--path routes to the specified file."""
        result = runner.invoke(app, ["config", "list", "--path", str(config_file)])
        assert result.exit_code == 0
        lines = _parse_jsonl(result.output)
        model_entries = [l for l in lines if l.get("key") == "llm.model"]
        assert model_entries[0]["value"] == "gpt-4"


# ── config get ──────────────────────────────────────────────────────


class TestConfigGet:
    """Tests for ``config get <key>``."""

    def test_get_masked_api_key(self, config_file: Path) -> None:
        result = runner.invoke(app, ["config", "get", "llm.api_key", "--path", str(config_file)])
        assert result.exit_code == 0, result.output
        lines = _parse_jsonl(result.output)
        assert len(lines) == 1
        entry = lines[0]
        assert entry["key"] == "llm.api_key"
        assert "sk-****" in entry["value"]
        # Raw secret must NOT appear
        assert "secret" not in entry["value"]

    def test_get_plaintext_value(self, config_file: Path) -> None:
        result = runner.invoke(app, ["config", "get", "llm.model", "--path", str(config_file)])
        assert result.exit_code == 0, result.output
        lines = _parse_jsonl(result.output)
        assert len(lines) == 1
        assert lines[0]["key"] == "llm.model"
        assert lines[0]["value"] == "gpt-4"

    def test_get_nonexistent_key_returns_error(self, config_file: Path) -> None:
        result = runner.invoke(app, ["config", "get", "nonexistent.key", "--path", str(config_file)])
        assert result.exit_code == 1, result.output
        lines = _parse_jsonl(result.output)
        error_lines = [l for l in lines if l.get("type") == "error"]
        assert len(error_lines) >= 1
        assert "config" in error_lines[0].get("stage", "")

    def test_get_nested_field(self, config_file: Path) -> None:
        result = runner.invoke(app, ["config", "get", "refresh.default_interval_days", "--path", str(config_file)])
        assert result.exit_code == 0, result.output
        lines = _parse_jsonl(result.output)
        assert lines[0]["value"] == "14"

    def test_get_path_option(self, config_file: Path) -> None:
        result = runner.invoke(app, ["config", "get", "llm.base_url", "--path", str(config_file)])
        assert result.exit_code == 0
        lines = _parse_jsonl(result.output)
        assert lines[0]["value"] == "https://api.example.com/v1"


# ── config set ──────────────────────────────────────────────────────


class TestConfigSet:
    """Tests for ``config set <key> <value>``."""

    def test_set_string_persists(self, config_file: Path) -> None:
        result = runner.invoke(app, ["config", "set", "llm.model", "gpt-4", "--path", str(config_file)])
        assert result.exit_code == 0, result.output
        lines = _parse_jsonl(result.output)
        assert len(lines) == 1
        assert lines[0]["key"] == "llm.model"
        assert lines[0]["value"] == "gpt-4"
        assert lines[0].get("message") == "Config updated"

        # Verify persisted to file
        with open(config_file, encoding="utf-8") as fh:
            saved = yaml.safe_load(fh)
        assert saved["llm"]["model"] == "gpt-4"

    def test_set_api_key_shows_raw_confirmation(self, config_file: Path) -> None:
        """config set for api_key echoes the raw value as user confirmation."""
        result = runner.invoke(app, ["config", "set", "llm.api_key", "sk-newkey123", "--path", str(config_file)])
        assert result.exit_code == 0, result.output
        lines = _parse_jsonl(result.output)
        # Confirmation shows raw value (user intentionally set it)
        assert lines[0]["value"] == "sk-newkey123"

        # Verify persisted
        with open(config_file, encoding="utf-8") as fh:
            saved = yaml.safe_load(fh)
        assert saved["llm"]["api_key"] == "sk-newkey123"

    def test_set_int_coercion(self, config_file: Path) -> None:
        result = runner.invoke(app, ["config", "set", "refresh.default_interval_days", "14", "--path", str(config_file)])
        assert result.exit_code == 0, result.output

        # Load from file and verify type coercion
        from web_clip_helper.config import Config

        loaded = Config.load(config_file)
        assert loaded.refresh.default_interval_days == 14

    def test_set_then_load_returns_updated(self, config_file: Path) -> None:
        """After config set, loading from the same file returns the updated value."""
        runner.invoke(app, ["config", "set", "llm.model", "claude-3", "--path", str(config_file)])

        from web_clip_helper.config import Config

        loaded = Config.load(config_file)
        assert loaded.llm.model == "claude-3"

    def test_set_nonexistent_key_returns_error(self, config_file: Path) -> None:
        result = runner.invoke(app, ["config", "set", "nonexistent.key", "val", "--path", str(config_file)])
        assert result.exit_code == 1, result.output
        lines = _parse_jsonl(result.output)
        error_lines = [l for l in lines if l.get("type") == "error"]
        assert len(error_lines) >= 1

    def test_set_path_option(self, tmp_path: Path) -> None:
        """config set --path writes to the specified file."""
        cfg = tmp_path / "custom.yaml"
        _write_config(cfg, {"llm": {"model": "gpt-4o-mini"}})
        result = runner.invoke(app, ["config", "set", "llm.model", "gpt-4", "--path", str(cfg)])
        assert result.exit_code == 0

        from web_clip_helper.config import Config

        loaded = Config.load(cfg)
        assert loaded.llm.model == "gpt-4"

    def test_set_invalid_int_returns_error(self, config_file: Path) -> None:
        """Setting an int field to a non-int value should error."""
        result = runner.invoke(app, ["config", "set", "refresh.default_interval_days", "not-a-number", "--path", str(config_file)])
        assert result.exit_code == 1, result.output


# ── config prompt test ────────────────────────────────────────────


class TestConfigPromptTest:
    """Tests for ``config prompt test`` command."""

    def _config_with_prompts(self, tmp_path: Path, api_key: str = "sk-test-key", prompts: dict | None = None) -> Path:
        """Helper: create a config file with custom prompts."""
        p = tmp_path / "config.yaml"
        data = {
            "llm": {
                "api_key": api_key,
                "base_url": "https://api.example.com/v1",
                "model": "gpt-4",
            },
        }
        if prompts:
            data["prompts"] = prompts
        _write_config(p, data)
        return p

    def test_prompt_test_with_custom_title(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Side-by-side output shows both built-in and custom results for title."""
        cfg = self._config_with_prompts(tmp_path, prompts={"title": "Custom: {content}"})

        # Mock the adapter fetch to return predictable content
        from unittest.mock import MagicMock
        from web_clip_helper import adapter as adapter_mod

        mock_raw = MagicMock()
        mock_raw.content_md = "Test article content about Python."
        mock_raw.source_type = "web"
        mock_adapter_cls = MagicMock(return_value=MagicMock(fetch=MagicMock(return_value=mock_raw)))
        monkeypatch.setattr(adapter_mod, "route_url", lambda url: mock_adapter_cls)

        # Mock LLMClient._chat to return different results based on prompt content
        original_chat = None
        call_count = {"n": 0}

        def _mock_chat(self_llm, user_prompt: str):
            call_count["n"] += 1
            if "Custom:" in user_prompt:
                return "Custom Title Result"
            return "Built-in Title Result"

        from web_clip_helper.llm import LLMClient
        monkeypatch.setattr(LLMClient, "_chat", _mock_chat)

        result = runner.invoke(app, [
            "config", "prompt", "test",
            "--type", "title",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert result.exit_code == 0, result.output
        assert "提示词对比测试 — title" in result.output
        assert "URL: https://example.com" in result.output
        assert "【内置提示词结果】" in result.output
        assert "Built-in Title Result" in result.output
        assert "【自定义提示词结果】" in result.output
        assert "Custom Title Result" in result.output

    def test_prompt_test_with_custom_tags(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Side-by-side output shows both built-in and custom results for tags."""
        cfg = self._config_with_prompts(tmp_path, prompts={"tags": "Tag: {content}"})

        from unittest.mock import MagicMock
        from web_clip_helper import adapter as adapter_mod

        mock_raw = MagicMock()
        mock_raw.content_md = "Test content."
        mock_raw.source_type = "web"
        mock_adapter_cls = MagicMock(return_value=MagicMock(fetch=MagicMock(return_value=mock_raw)))
        monkeypatch.setattr(adapter_mod, "route_url", lambda url: mock_adapter_cls)

        from web_clip_helper.llm import LLMClient

        def _mock_chat(self_llm, user_prompt: str):
            if "Tag:" in user_prompt:
                return '["custom-tag"]'
            return '["built-in-tag"]'

        monkeypatch.setattr(LLMClient, "_chat", _mock_chat)

        result = runner.invoke(app, [
            "config", "prompt", "test",
            "--type", "tags",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert result.exit_code == 0, result.output
        assert "提示词对比测试 — tags" in result.output
        assert "built-in-tag" in result.output
        assert "custom-tag" in result.output

    def test_prompt_test_with_custom_classify(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Side-by-side output shows both built-in and custom results for classify."""
        cfg = self._config_with_prompts(tmp_path, prompts={"classify": "Classify: {content}"})

        from unittest.mock import MagicMock
        from web_clip_helper import adapter as adapter_mod

        mock_raw = MagicMock()
        mock_raw.content_md = "Test content."
        mock_raw.source_type = "web"
        mock_adapter_cls = MagicMock(return_value=MagicMock(fetch=MagicMock(return_value=mock_raw)))
        monkeypatch.setattr(adapter_mod, "route_url", lambda url: mock_adapter_cls)

        from web_clip_helper.llm import LLMClient

        def _mock_chat(self_llm, user_prompt: str):
            if "Classify:" in user_prompt:
                return "自定义类别"
            return "技术"

        monkeypatch.setattr(LLMClient, "_chat", _mock_chat)

        result = runner.invoke(app, [
            "config", "prompt", "test",
            "--type", "classify",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert result.exit_code == 0, result.output
        assert "提示词对比测试 — classify" in result.output
        assert "技术" in result.output
        assert "自定义类别" in result.output

    def test_prompt_test_no_custom_prompt(self, tmp_path: Path) -> None:
        """When custom prompt for the given type is empty, error message is shown."""
        cfg = self._config_with_prompts(tmp_path, prompts={"tags": "some tags template"})

        result = runner.invoke(app, [
            "config", "prompt", "test",
            "--type", "title",  # title has no custom prompt set
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert result.exit_code == 1, result.output
        assert "未设置自定义提示词" in result.output
        assert "prompts.title" in result.output

    def test_prompt_test_no_api_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """When api_key is empty, both sides show [未配置 API Key]."""
        cfg = self._config_with_prompts(tmp_path, api_key="", prompts={"title": "Custom: {content}"})

        from unittest.mock import MagicMock
        from web_clip_helper import adapter as adapter_mod

        mock_raw = MagicMock()
        mock_raw.content_md = "Test content."
        mock_raw.source_type = "web"
        mock_adapter_cls = MagicMock(return_value=MagicMock(fetch=MagicMock(return_value=mock_raw)))
        monkeypatch.setattr(adapter_mod, "route_url", lambda url: mock_adapter_cls)

        result = runner.invoke(app, [
            "config", "prompt", "test",
            "--type", "title",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert result.exit_code == 0, result.output
        assert "[未配置 API Key]" in result.output

    def test_prompt_test_invalid_type(self, tmp_path: Path) -> None:
        """Error for unsupported --type value."""
        cfg = self._config_with_prompts(tmp_path)

        result = runner.invoke(app, [
            "config", "prompt", "test",
            "--type", "invalid",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert result.exit_code == 1, result.output
        assert "不支持的类型" in result.output

    def test_prompt_test_url_fetch_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Adapter fetch error is handled gracefully."""
        from unittest.mock import MagicMock

        cfg = self._config_with_prompts(tmp_path, prompts={"title": "Custom: {content}"})

        from web_clip_helper import adapter as adapter_mod
        from web_clip_helper.adapter import AdapterError

        mock_adapter_instance = MagicMock()
        mock_adapter_instance.fetch.side_effect = AdapterError("Connection refused")
        mock_adapter_cls = MagicMock(return_value=mock_adapter_instance)
        monkeypatch.setattr(adapter_mod, "route_url", lambda url: mock_adapter_cls)

        result = runner.invoke(app, [
            "config", "prompt", "test",
            "--type", "title",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert result.exit_code == 1, result.output
        assert "内容获取失败" in result.output
