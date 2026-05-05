"""Integration tests for the ``config`` CLI subcommands.

Tests use ``run_sdk_cli`` fixture for simple config list/get/set commands
and subprocess for complex ``config prompt test`` commands that need
Click's pager/progress features.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from unittest.mock import MagicMock

from tests.conftest import _parse_envelopes, _unwrap_data, _unwrap_error_message


# ── Helpers ─────────────────────────────────────────────────────────


def _write_config(path: Path, data: dict) -> None:
    """Write a JSON config dict to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _config_with_prompts(tmp_path: Path, api_key: str = "sk-test-key", prompts: dict | None = None) -> Path:
    """Helper: create a config file with custom prompts."""
    p = tmp_path / "config.json"
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


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Return a path to a temporary config.json with some data."""
    p = tmp_path / "config.json"
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

    def test_list_returns_envelopes_with_masked_api_key(self, config_file: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "list", "--path", str(config_file)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        # Each config key is a separate result envelope
        api_key_entries = [d for d in (_unwrap_data(r) for r in results) if d.get("key") == "llm.api_key"]
        assert len(api_key_entries) == 1
        assert "sk-****" in api_key_entries[0]["value"]
        assert "secret" not in api_key_entries[0]["value"]

    def test_list_shows_all_fields(self, config_file: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "list", "--path", str(config_file)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        data_list = [_unwrap_data(r) for r in results]
        keys = {d["key"] for d in data_list}
        # Must cover all config fields
        assert "llm.api_key" in keys
        assert "llm.base_url" in keys
        assert "llm.model" in keys
        assert "refresh.default_interval_days" in keys
        assert "prompts.title" in keys
        assert "prompts.tags" in keys
        assert "prompts.classify" in keys

    def test_list_with_defaults(self, tmp_path: Path, run_sdk_cli) -> None:
        """Config list on a fresh (auto-created) config shows defaults."""
        fresh = tmp_path / "subdir" / "config.json"
        code, envelopes = run_sdk_cli(["config", "list", "--path", str(fresh)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        data_list = [_unwrap_data(r) for r in results]
        model_entries = [d for d in data_list if d.get("key") == "llm.model"]
        assert len(model_entries) == 1
        assert model_entries[0]["value"] == "gpt-4o-mini"

    def test_list_path_option(self, config_file: Path, run_sdk_cli) -> None:
        """--path routes to the specified file."""
        code, envelopes = run_sdk_cli(["config", "list", "--path", str(config_file)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        data_list = [_unwrap_data(r) for r in results]
        model_entries = [d for d in data_list if d.get("key") == "llm.model"]
        assert model_entries[0]["value"] == "gpt-4"


# ── config get ──────────────────────────────────────────────────────


class TestConfigGet:
    """Tests for ``config get <key>``."""

    def test_get_masked_api_key(self, config_file: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "get", "llm.api_key", "--path", str(config_file)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["key"] == "llm.api_key"
        assert "sk-****" in data["value"]
        # Raw secret must NOT appear
        assert "secret" not in data["value"]

    def test_get_plaintext_value(self, config_file: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "get", "llm.model", "--path", str(config_file)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["key"] == "llm.model"
        assert data["value"] == "gpt-4"

    def test_get_nonexistent_key_returns_error(self, config_file: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "get", "nonexistent.key", "--path", str(config_file)])
        assert code == 2  # CONFIG_ERROR → semantic exit code 2
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "CONFIG_ERROR"
        stage, detail = _unwrap_error_message(errors[0])
        assert "config" == stage

    def test_get_nested_field(self, config_file: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "get", "refresh.default_interval_days", "--path", str(config_file)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        data = _unwrap_data(results[0])
        assert data["value"] == "14"

    def test_get_path_option(self, config_file: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "get", "llm.base_url", "--path", str(config_file)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        data = _unwrap_data(results[0])
        assert data["value"] == "https://api.example.com/v1"


# ── config set ──────────────────────────────────────────────────────


class TestConfigSet:
    """Tests for ``config set <key> <value>``."""

    def test_set_string_persists(self, config_file: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "set", "llm.model", "gpt-4", "--path", str(config_file)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["key"] == "llm.model"
        assert data["value"] == "gpt-4"
        assert data.get("message") == "Config updated"

        # Verify persisted to file
        with open(config_file, encoding="utf-8") as fh:
            saved = json.loads(fh.read())
        assert saved["llm"]["model"] == "gpt-4"

    def test_set_api_key_shows_raw_confirmation(self, config_file: Path, run_sdk_cli) -> None:
        """config set for api_key echoes the raw value as user confirmation."""
        code, envelopes = run_sdk_cli(["config", "set", "llm.api_key", "sk-newkey123", "--path", str(config_file)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        data = _unwrap_data(results[0])
        # Confirmation shows raw value (user intentionally set it)
        assert data["value"] == "sk-newkey123"

        # Verify persisted
        with open(config_file, encoding="utf-8") as fh:
            saved = json.loads(fh.read())
        assert saved["llm"]["api_key"] == "sk-newkey123"

    def test_set_int_coercion(self, config_file: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "set", "refresh.default_interval_days", "14", "--path", str(config_file)])
        assert code == 0

        # Load from file and verify type coercion
        from web_clip_helper.config import Config

        loaded = Config.load(config_file)
        assert loaded.refresh.default_interval_days == 14

    def test_set_then_load_returns_updated(self, config_file: Path, run_sdk_cli) -> None:
        """After config set, loading from the same file returns the updated value."""
        run_sdk_cli(["config", "set", "llm.model", "claude-3", "--path", str(config_file)])

        from web_clip_helper.config import Config

        loaded = Config.load(config_file)
        assert loaded.llm.model == "claude-3"

    def test_set_nonexistent_key_returns_error(self, config_file: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "set", "nonexistent.key", "val", "--path", str(config_file)])
        assert code == 2  # CONFIG_ERROR → semantic exit code 2
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "CONFIG_ERROR"

    def test_set_path_option(self, tmp_path: Path, run_sdk_cli) -> None:
        """config set --path writes to the specified file."""
        cfg = tmp_path / "custom.json"
        _write_config(cfg, {"llm": {"model": "gpt-4o-mini"}})
        code, envelopes = run_sdk_cli(["config", "set", "llm.model", "gpt-4", "--path", str(cfg)])
        assert code == 0

        from web_clip_helper.config import Config

        loaded = Config.load(cfg)
        assert loaded.llm.model == "gpt-4"

    def test_set_invalid_int_returns_error(self, config_file: Path, run_sdk_cli) -> None:
        """Setting an int field to a non-int value should error."""
        code, envelopes = run_sdk_cli(["config", "set", "refresh.default_interval_days", "not-a-number", "--path", str(config_file)])
        assert code == 2  # CONFIG_ERROR → semantic exit code 2


# ── config prompt test ────────────────────────────────────────────


class TestConfigPromptTest:
    """Tests for ``config prompt test`` command — SDK Envelope output."""

    def test_prompt_test_with_custom_title(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_sdk_cli) -> None:
        """SDK Envelope result shows both built-in and custom results for title."""
        cfg = _config_with_prompts(tmp_path, prompts={"title": "Custom: {content}"})

        from web_clip_helper import adapter as adapter_mod

        mock_raw = MagicMock()
        mock_raw.content_md = "Test article content about Python."
        mock_raw.source_type = "web"
        mock_adapter_cls = MagicMock(return_value=MagicMock(fetch=MagicMock(return_value=mock_raw)))
        monkeypatch.setattr(adapter_mod, "route_url", lambda url: mock_adapter_cls)

        from web_clip_helper.llm import LLMClient

        def _mock_chat(self_llm, user_prompt: str):
            if "Custom:" in user_prompt:
                return "Custom Title Result"
            return "Built-in Title Result"

        monkeypatch.setattr(LLMClient, "_chat", _mock_chat)

        code, envelopes = run_sdk_cli([
            "config", "prompt", "test",
            "--type", "title",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["prompt_type"] == "title"
        assert data["url"] == "https://example.com"
        assert data["built_in"] == "Built-in Title Result"
        assert data["custom"] == "Custom Title Result"

    def test_prompt_test_with_custom_tags(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_sdk_cli) -> None:
        """SDK Envelope result shows both built-in and custom results for tags."""
        cfg = _config_with_prompts(tmp_path, prompts={"tags": "Tag: {content}"})

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

        code, envelopes = run_sdk_cli([
            "config", "prompt", "test",
            "--type", "tags",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["prompt_type"] == "tags"
        assert "built-in-tag" in data["built_in"]
        assert "custom-tag" in data["custom"]

    def test_prompt_test_with_custom_classify(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_sdk_cli) -> None:
        """SDK Envelope result shows both built-in and custom results for classify."""
        cfg = _config_with_prompts(tmp_path, prompts={"classify": "Classify: {content}"})

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

        code, envelopes = run_sdk_cli([
            "config", "prompt", "test",
            "--type", "classify",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["prompt_type"] == "classify"
        assert data["built_in"] == "技术"
        assert data["custom"] == "自定义类别"

    def test_prompt_test_no_custom_prompt(self, tmp_path: Path, run_sdk_cli) -> None:
        """When custom prompt for the given type is empty, JSONL error is emitted."""
        cfg = _config_with_prompts(tmp_path, prompts={"tags": "some tags template"})

        code, envelopes = run_sdk_cli([
            "config", "prompt", "test",
            "--type", "title",  # title has no custom prompt set
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert code == 2  # NO_CUSTOM_PROMPT → semantic exit code 2
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "NO_CUSTOM_PROMPT"
        stage, detail = _unwrap_error_message(errors[0])
        assert "prompts.title" in detail

    def test_prompt_test_no_api_key(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_sdk_cli) -> None:
        """When api_key is empty, SDK Envelope result includes [未配置 API Key] in built_in."""
        cfg = _config_with_prompts(tmp_path, api_key="", prompts={"title": "Custom: {content}"})

        from web_clip_helper import adapter as adapter_mod

        mock_raw = MagicMock()
        mock_raw.content_md = "Test content."
        mock_raw.source_type = "web"
        mock_adapter_cls = MagicMock(return_value=MagicMock(fetch=MagicMock(return_value=mock_raw)))
        monkeypatch.setattr(adapter_mod, "route_url", lambda url: mock_adapter_cls)

        code, envelopes = run_sdk_cli([
            "config", "prompt", "test",
            "--type", "title",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["built_in"] == "[未配置 API Key]"

    def test_prompt_test_invalid_type(self, tmp_path: Path, run_sdk_cli) -> None:
        """Error JSONL for unsupported --type value."""
        cfg = _config_with_prompts(tmp_path)

        code, envelopes = run_sdk_cli([
            "config", "prompt", "test",
            "--type", "invalid",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert code == 2  # INVALID_TYPE → semantic exit code 2
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "INVALID_TYPE"

    def test_prompt_test_url_fetch_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_sdk_cli) -> None:
        """Adapter fetch error emits JSONL error."""
        cfg = _config_with_prompts(tmp_path, prompts={"title": "Custom: {content}"})

        from web_clip_helper import adapter as adapter_mod
        from web_clip_helper.adapter import AdapterError

        mock_adapter_instance = MagicMock()
        mock_adapter_instance.fetch.side_effect = AdapterError("Connection refused")
        mock_adapter_cls = MagicMock(return_value=mock_adapter_instance)
        monkeypatch.setattr(adapter_mod, "route_url", lambda url: mock_adapter_cls)

        code, envelopes = run_sdk_cli([
            "config", "prompt", "test",
            "--type", "title",
            "--url", "https://example.com",
            "--path", str(cfg),
        ])

        assert code == 4  # FETCH_ERROR → semantic exit code 4
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "FETCH_ERROR"
