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
