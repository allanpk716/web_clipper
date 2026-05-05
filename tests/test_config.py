"""Tests for the Config system."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from web_clip_helper.config import (
    Config,
    PromptConfig,
    _mask_api_key,
    get_by_path,
    set_by_path,
)


class TestConfigDefaults:
    """Config has sensible defaults even without a file."""

    def test_defaults_used(self, tmp_config_dir: Path) -> None:
        cfg = Config.load(tmp_config_dir / "nonexistent.json")
        assert "clips" in cfg.storage_path
        assert "clips.db" in cfg.db_path
        assert cfg.llm.api_key == ""
        assert cfg.llm.base_url == "https://api.openai.com/v1"
        assert cfg.llm.model == "gpt-4o-mini"
        assert cfg.refresh.default_interval_days == 7


class TestConfigAutoCreate:
    """Config auto-creates its directory and default file."""

    def test_creates_config_file(self, tmp_config_path: Path) -> None:
        assert not tmp_config_path.exists()
        Config.load(tmp_config_path)
        assert tmp_config_path.exists()

    def test_created_file_is_valid_json(self, tmp_config_path: Path) -> None:
        Config.load(tmp_config_path)
        with open(tmp_config_path) as fh:
            data = json.loads(fh.read())
        assert isinstance(data, dict)
        assert "storage_path" in data
        assert "db_path" in data


class TestConfigLoad:
    """Config loads values from JSON correctly."""

    def test_loads_custom_storage_path(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text(
            json.dumps({"storage_path": "/custom/clips", "db_path": "/custom/clips.db"})
        )
        cfg = Config.load(tmp_config_path)
        assert cfg.storage_path == "/custom/clips"
        assert cfg.db_path == "/custom/clips.db"

    def test_loads_llm_config(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text(
            json.dumps({"llm": {"api_key": "sk-test", "model": "gpt-4"}})
        )
        cfg = Config.load(tmp_config_path)
        assert cfg.llm.api_key == "sk-test"
        assert cfg.llm.model == "gpt-4"

    def test_loads_refresh_config(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text(
            json.dumps({"refresh": {"default_interval_days": 30}})
        )
        cfg = Config.load(tmp_config_path)
        assert cfg.refresh.default_interval_days == 30


class TestConfigMalformed:
    """Config handles malformed JSON gracefully."""

    def test_malformed_json_uses_defaults(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text("{{{{invalid json::::")
        cfg = Config.load(tmp_config_path)
        # Should fall back to defaults
        assert "clips" in cfg.storage_path

    def test_empty_file_uses_defaults(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text("")
        cfg = Config.load(tmp_config_path)
        assert "clips" in cfg.storage_path
        assert cfg.llm.api_key == ""

    def test_partial_config_merges_defaults(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text(json.dumps({"storage_path": "/my/path"}))
        cfg = Config.load(tmp_config_path)
        assert cfg.storage_path == "/my/path"
        # Other fields should be defaults
        assert cfg.llm.model == "gpt-4o-mini"


class TestConfigNotWritable:
    """Config gives a clear error when config dir is not writable."""

    def test_nonexistent_nested_dir(self, tmp_path: Path) -> None:
        """Should still succeed — mkdir(parents=True) handles this."""
        cfg_path = tmp_path / "deep" / "nested" / "config.json"
        cfg = Config.load(cfg_path)
        assert cfg_path.exists()

    def test_save_creates_dir(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "new_dir" / "config.json"
        cfg = Config()
        cfg.save(cfg_path)
        assert cfg_path.exists()


# ── Environment variable override tests ─────────────────────────────


class TestEnvVarOverride:
    """Environment variables override file values for LLM settings."""

    def test_api_key_override(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text(
            json.dumps({"llm": {"api_key": "from-file"}})
        )
        os.environ["WEB_CLIP_LLM_API_KEY"] = "from-env"
        try:
            cfg = Config.load(tmp_config_path)
            assert cfg.llm.api_key == "from-env"
        finally:
            del os.environ["WEB_CLIP_LLM_API_KEY"]

    def test_base_url_override(self, tmp_config_path: Path) -> None:
        os.environ["WEB_CLIP_LLM_BASE_URL"] = "https://custom.api/v1"
        try:
            cfg = Config.load(tmp_config_path)
            assert cfg.llm.base_url == "https://custom.api/v1"
        finally:
            del os.environ["WEB_CLIP_LLM_BASE_URL"]

    def test_model_override(self, tmp_config_path: Path) -> None:
        os.environ["WEB_CLIP_LLM_MODEL"] = "gpt-4"
        try:
            cfg = Config.load(tmp_config_path)
            assert cfg.llm.model == "gpt-4"
        finally:
            del os.environ["WEB_CLIP_LLM_MODEL"]

    def test_no_override_when_env_not_set(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text(
            json.dumps({"llm": {"api_key": "file-value"}})
        )
        # Ensure env vars are not set
        for var in ("WEB_CLIP_LLM_API_KEY", "WEB_CLIP_LLM_BASE_URL", "WEB_CLIP_LLM_MODEL"):
            os.environ.pop(var, None)
        cfg = Config.load(tmp_config_path)
        assert cfg.llm.api_key == "file-value"


# ── Dot-path get/set tests ──────────────────────────────────────────


class TestDotPathGet:
    """get_by_path navigates Pydantic model fields with dot-separated paths."""

    def test_top_level_field(self) -> None:
        cfg = Config()
        assert get_by_path(cfg, "storage_path") == cfg.storage_path

    def test_nested_llm_field(self) -> None:
        cfg = Config()
        assert get_by_path(cfg, "llm.api_key") == cfg.llm.api_key
        assert get_by_path(cfg, "llm.model") == cfg.llm.model

    def test_nested_refresh_field(self) -> None:
        cfg = Config()
        assert get_by_path(cfg, "refresh.default_interval_days") == 7

    def test_prompts_field(self) -> None:
        cfg = Config(prompts=PromptConfig(title="test-title"))
        assert get_by_path(cfg, "prompts.title") == "test-title"

    def test_invalid_path_raises_key_error(self) -> None:
        cfg = Config()
        with pytest.raises(KeyError, match="does not exist"):
            get_by_path(cfg, "llm.nonexistent")

    def test_invalid_top_level_raises_key_error(self) -> None:
        cfg = Config()
        with pytest.raises(KeyError, match="does not exist"):
            get_by_path(cfg, "nonexistent")


class TestDotPathSet:
    """set_by_path modifies Config in-place with type coercion."""

    def test_set_string_field(self) -> None:
        cfg = Config()
        set_by_path(cfg, "llm.api_key", "sk-new-key")
        assert cfg.llm.api_key == "sk-new-key"

    def test_set_int_field_coerces(self) -> None:
        cfg = Config()
        set_by_path(cfg, "refresh.default_interval_days", "30")
        assert cfg.refresh.default_interval_days == 30
        assert isinstance(cfg.refresh.default_interval_days, int)

    def test_set_top_level_field(self) -> None:
        cfg = Config()
        set_by_path(cfg, "storage_path", "/new/path")
        assert cfg.storage_path == "/new/path"

    def test_set_invalid_path_raises_key_error(self) -> None:
        cfg = Config()
        with pytest.raises(KeyError, match="does not exist"):
            set_by_path(cfg, "llm.nonexistent", "value")


# ── Masking utility tests ───────────────────────────────────────────


class TestMaskApiKey:
    """_mask_api_key masks API keys for safe display."""

    def test_empty_string(self) -> None:
        assert _mask_api_key("") == ""

    def test_short_string(self) -> None:
        # ≤ 8 chars → all masked
        assert _mask_api_key("short") == "****"

    def test_exactly_8_chars(self) -> None:
        assert _mask_api_key("12345678") == "****"

    def test_long_string(self) -> None:
        assert _mask_api_key("sk-abcdefgh1234") == "sk-****1234"

    def test_typical_sk_key(self) -> None:
        assert _mask_api_key("sk-proj-abc123XYZ789def") == "sk-****9def"


# ── PromptConfig round-trip tests ───────────────────────────────────


class TestPromptConfig:
    """PromptConfig round-trips through load/save."""

    def test_prompts_default_empty(self, tmp_config_path: Path) -> None:
        cfg = Config.load(tmp_config_path)
        assert cfg.prompts.title == ""
        assert cfg.prompts.tags == ""
        assert cfg.prompts.classify == ""

    def test_prompts_loaded_from_json(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text(
            json.dumps({
                "prompts": {"title": "summarize", "tags": "extract", "classify": "categorize"}
            })
        )
        cfg = Config.load(tmp_config_path)
        assert cfg.prompts.title == "summarize"
        assert cfg.prompts.tags == "extract"
        assert cfg.prompts.classify == "categorize"

    def test_prompts_round_trip(self, tmp_config_path: Path) -> None:
        cfg = Config(prompts=PromptConfig(title="my-title", tags="t1,t2", classify="cat"))
        cfg.save(tmp_config_path)

        loaded = Config.load(tmp_config_path)
        assert loaded.prompts.title == "my-title"
        assert loaded.prompts.tags == "t1,t2"
        assert loaded.prompts.classify == "cat"

    def test_prompts_in_to_dict(self) -> None:
        cfg = Config(prompts=PromptConfig(title="hello"))
        d = cfg._to_dict()
        assert "prompts" in d
        assert d["prompts"]["title"] == "hello"
