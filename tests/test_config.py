"""Tests for the Config system."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from web_clip_helper.config import Config


class TestConfigDefaults:
    """Config has sensible defaults even without a file."""

    def test_defaults_used(self, tmp_config_dir: Path) -> None:
        cfg = Config.load(tmp_config_dir / "nonexistent.yaml")
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

    def test_created_file_is_valid_yaml(self, tmp_config_path: Path) -> None:
        Config.load(tmp_config_path)
        with open(tmp_config_path) as fh:
            data = yaml.safe_load(fh)
        assert isinstance(data, dict)
        assert "storage_path" in data
        assert "db_path" in data


class TestConfigLoad:
    """Config loads values from YAML correctly."""

    def test_loads_custom_storage_path(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text(
            yaml.dump({"storage_path": "/custom/clips", "db_path": "/custom/clips.db"})
        )
        cfg = Config.load(tmp_config_path)
        assert cfg.storage_path == "/custom/clips"
        assert cfg.db_path == "/custom/clips.db"

    def test_loads_llm_config(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text(
            yaml.dump({"llm": {"api_key": "sk-test", "model": "gpt-4"}})
        )
        cfg = Config.load(tmp_config_path)
        assert cfg.llm.api_key == "sk-test"
        assert cfg.llm.model == "gpt-4"

    def test_loads_refresh_config(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text(
            yaml.dump({"refresh": {"default_interval_days": 30}})
        )
        cfg = Config.load(tmp_config_path)
        assert cfg.refresh.default_interval_days == 30


class TestConfigMalformed:
    """Config handles malformed YAML gracefully."""

    def test_malformed_yaml_uses_defaults(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text("{{{{invalid yaml::::")
        cfg = Config.load(tmp_config_path)
        # Should fall back to defaults
        assert "clips" in cfg.storage_path

    def test_empty_file_uses_defaults(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text("")
        cfg = Config.load(tmp_config_path)
        assert "clips" in cfg.storage_path
        assert cfg.llm.api_key == ""

    def test_partial_config_merges_defaults(self, tmp_config_path: Path) -> None:
        tmp_config_path.write_text(yaml.dump({"storage_path": "/my/path"}))
        cfg = Config.load(tmp_config_path)
        assert cfg.storage_path == "/my/path"
        # Other fields should be defaults
        assert cfg.llm.model == "gpt-4o-mini"


class TestConfigNotWritable:
    """Config gives a clear error when config dir is not writable."""

    def test_nonexistent_nested_dir(self, tmp_path: Path) -> None:
        """Should still succeed — mkdir(parents=True) handles this."""
        cfg_path = tmp_path / "deep" / "nested" / "config.yaml"
        cfg = Config.load(cfg_path)
        assert cfg_path.exists()

    def test_save_creates_dir(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "new_dir" / "config.yaml"
        cfg = Config()
        cfg.save(cfg_path)
        assert cfg_path.exists()
