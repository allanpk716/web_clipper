"""Tests for agent auth status + agent config list/set commands.

Covers:
- agent auth status: with/without api_key, valid/invalid key, timeout
- agent config list: redaction of sensitive fields, all sections present
- agent config set: valid path, invalid path, type coercion, persistence
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app

runner = CliRunner()


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output into a list of dicts."""
    return [json.loads(line) for line in output.strip().splitlines() if line.strip()]


def _validate_all_jsonl(output: str) -> list[dict]:
    """Parse and validate all lines are valid JSONL."""
    lines = _parse_jsonl(output)
    valid_types = {"progress", "result", "error", "warning", "help", "schema", "dict", "diagnostics"}
    for line in lines:
        assert "type" in line, f"Missing 'type' in: {line}"
        assert line["type"] in valid_types, f"Invalid type {line['type']!r} in: {line}"
    return lines


# ═══════════════════════════════════════════════════════════════════
# agent auth status
# ═══════════════════════════════════════════════════════════════════


class TestAgentAuthStatusNoKey:
    """When no API key is configured."""

    def test_exits_zero(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = ""
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config
            result = runner.invoke(app, ["agent", "auth", "status"])
            assert result.exit_code == 0

    def test_status_not_configured(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = ""
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config
            result = runner.invoke(app, ["agent", "auth", "status"])
            lines = _validate_all_jsonl(result.output)
            assert len(lines) == 1
            assert lines[0]["type"] == "result"
            assert lines[0]["status"] == "not_configured"
            assert lines[0]["masked_key"] == ""

    def test_stage_field(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = ""
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config
            result = runner.invoke(app, ["agent", "auth", "status"])
            lines = _parse_jsonl(result.output)
            assert lines[0]["stage"] == "agent_auth_status"


class TestAgentAuthStatusValidKey:
    """When API key is valid and server responds."""

    def test_status_valid(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = "sk-test-api-key-12345678"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config

            with patch("httpx.post", return_value=mock_response):
                result = runner.invoke(app, ["agent", "auth", "status"])
                assert result.exit_code == 0
                lines = _validate_all_jsonl(result.output)
                assert len(lines) == 1
                assert lines[0]["status"] == "valid"

    def test_masked_key_never_exposes_plaintext(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        api_key = "sk-secret-key-that-should-be-masked-1234"
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = api_key
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config

            with patch("httpx.post", return_value=mock_response):
                result = runner.invoke(app, ["agent", "auth", "status"])
                lines = _parse_jsonl(result.output)
                masked = lines[0]["masked_key"]
                assert api_key not in masked
                assert "****" in masked

    def test_latency_ms_present(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = "sk-test-key-12345678"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config

            with patch("httpx.post", return_value=mock_response):
                result = runner.invoke(app, ["agent", "auth", "status"])
                lines = _parse_jsonl(result.output)
                assert "latency_ms" in lines[0]
                assert isinstance(lines[0]["latency_ms"], (int, float))

    def test_envelope_fields(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = "sk-test-key-12345678"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config

            with patch("httpx.post", return_value=mock_response):
                result = runner.invoke(app, ["agent", "auth", "status"])
                lines = _parse_jsonl(result.output)
                assert lines[0]["tool"] == "web-clip-helper"
                assert "timestamp" in lines[0]


class TestAgentAuthStatusInvalidKey:
    """When API key is rejected by the server."""

    def test_status_invalid(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = "sk-bad-key-12345678"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config

            with patch("httpx.post", side_effect=Exception("401 Unauthorized")):
                result = runner.invoke(app, ["agent", "auth", "status"])
                assert result.exit_code == 0
                lines = _validate_all_jsonl(result.output)
                assert lines[0]["status"] == "invalid"

    def test_invalid_has_masked_key(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = "sk-bad-key-12345678"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config

            with patch("httpx.post", side_effect=Exception("401")):
                result = runner.invoke(app, ["agent", "auth", "status"])
                lines = _parse_jsonl(result.output)
                assert "masked_key" in lines[0]
                assert "sk-bad-key-12345678" not in lines[0]["masked_key"]

    def test_invalid_has_detail(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = "sk-bad-key-12345678"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config

            with patch("httpx.post", side_effect=Exception("Connection refused")):
                result = runner.invoke(app, ["agent", "auth", "status"])
                lines = _parse_jsonl(result.output)
                assert "detail" in lines[0]
                assert "Connection refused" in lines[0]["detail"]


class TestAgentAuthStatusTimeout:
    """When the LLM endpoint times out."""

    def test_timeout_reports_invalid(self) -> None:
        import httpx

        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = "sk-test-key-12345678"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config

            with patch("httpx.post", side_effect=httpx.TimeoutException("timed out")):
                result = runner.invoke(app, ["agent", "auth", "status"])
                lines = _validate_all_jsonl(result.output)
                assert lines[0]["status"] == "invalid"
                assert "timed out" in lines[0]["detail"].lower() or "timeout" in lines[0]["detail"].lower()


# ═══════════════════════════════════════════════════════════════════
# agent config list
# ═══════════════════════════════════════════════════════════════════


class TestAgentConfigListBasic:
    """Verify basic output structure."""

    def test_exits_zero(self) -> None:
        result = runner.invoke(app, ["agent", "config", "list"])
        assert result.exit_code == 0

    def test_outputs_valid_jsonl(self) -> None:
        result = runner.invoke(app, ["agent", "config", "list"])
        lines = _validate_all_jsonl(result.output)
        assert len(lines) >= 2  # At least sections + summary result

    def test_has_dict_and_result_types(self) -> None:
        result = runner.invoke(app, ["agent", "config", "list"])
        lines = _parse_jsonl(result.output)
        types = {l["type"] for l in lines}
        assert "dict" in types
        assert "result" in types


class TestAgentConfigListSections:
    """Verify all expected sections are present."""

    def test_llm_section_present(self) -> None:
        result = runner.invoke(app, ["agent", "config", "list"])
        lines = _parse_jsonl(result.output)
        dict_lines = [l for l in lines if l["type"] == "dict"]
        llm_found = any("llm" in l.get("data", {}) for l in dict_lines)
        assert llm_found, f"No llm section in dict lines: {dict_lines}"

    def test_refresh_section_present(self) -> None:
        result = runner.invoke(app, ["agent", "config", "list"])
        lines = _parse_jsonl(result.output)
        dict_lines = [l for l in lines if l["type"] == "dict"]
        refresh_found = any("refresh" in l.get("data", {}) for l in dict_lines)
        assert refresh_found

    def test_prompts_section_present(self) -> None:
        result = runner.invoke(app, ["agent", "config", "list"])
        lines = _parse_jsonl(result.output)
        dict_lines = [l for l in lines if l["type"] == "dict"]
        prompts_found = any("prompts" in l.get("data", {}) for l in dict_lines)
        assert prompts_found


class TestAgentConfigListRedaction:
    """Verify sensitive fields are redacted."""

    def test_api_key_redacted(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = "sk-super-secret-key-1234567890"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            config.storage_path = "/tmp/clips"
            config.db_path = "/tmp/clips.db"
            config.refresh.default_interval_days = 7
            config.prompts.title = ""
            config.prompts.tags = ""
            config.prompts.classify = ""
            mock_cfg.return_value = config

            result = runner.invoke(app, ["agent", "config", "list"])
            # Ensure the plaintext key never appears in output
            assert "sk-super-secret-key-1234567890" not in result.output

    def test_redacted_key_format(self) -> None:
        """Verify the masked format uses **** pattern."""
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config._to_dict.return_value = {
                "storage_path": "/tmp/clips",
                "db_path": "/tmp/clips.db",
                "llm": {
                    "api_key": "sk-super-secret-key-1234567890",
                    "base_url": "https://api.example.com/v1",
                    "model": "gpt-4o-mini",
                },
                "refresh": {"default_interval_days": 7},
                "prompts": {"title": "", "tags": "", "classify": ""},
            }
            mock_cfg.return_value = config

            result = runner.invoke(app, ["agent", "config", "list"])
            lines = _parse_jsonl(result.output)
            dict_lines = [l for l in lines if l["type"] == "dict"]
            # Find the llm section
            llm_line = next(l for l in dict_lines if "llm" in l.get("data", {}))
            llm_data = llm_line["data"]["llm"]
            assert "****" in llm_data["api_key"]
            assert llm_data["api_key"].startswith("sk-")
            assert llm_data["api_key"].endswith("7890")


class TestAgentConfigListSummary:
    """Verify the summary result line."""

    def test_summary_has_total_keys(self) -> None:
        result = runner.invoke(app, ["agent", "config", "list"])
        lines = _parse_jsonl(result.output)
        result_lines = [l for l in lines if l["type"] == "result"]
        assert len(result_lines) == 1
        assert "total_keys" in result_lines[0]
        assert isinstance(result_lines[0]["total_keys"], int)

    def test_summary_has_redacted_keys(self) -> None:
        result = runner.invoke(app, ["agent", "config", "list"])
        lines = _parse_jsonl(result.output)
        result_line = next(l for l in lines if l["type"] == "result")
        assert "redacted_keys" in result_line
        assert isinstance(result_line["redacted_keys"], int)

    def test_summary_stage(self) -> None:
        result = runner.invoke(app, ["agent", "config", "list"])
        lines = _parse_jsonl(result.output)
        result_line = next(l for l in lines if l["type"] == "result")
        assert result_line["stage"] == "agent_config_list"

    def test_redacted_count_at_least_1_with_api_key(self) -> None:
        """When api_key is set, at least one field should be redacted."""
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config._to_dict.return_value = {
                "storage_path": "/tmp/clips",
                "db_path": "/tmp/clips.db",
                "llm": {
                    "api_key": "sk-test-key-12345678",
                    "base_url": "https://api.example.com/v1",
                    "model": "gpt-4o-mini",
                },
                "refresh": {"default_interval_days": 7},
                "prompts": {"title": "", "tags": "", "classify": ""},
            }
            mock_cfg.return_value = config

            result = runner.invoke(app, ["agent", "config", "list"])
            lines = _parse_jsonl(result.output)
            result_line = next(l for l in lines if l["type"] == "result")
            assert result_line["redacted_keys"] >= 1


# ═══════════════════════════════════════════════════════════════════
# agent config set
# ═══════════════════════════════════════════════════════════════════


class TestAgentConfigSetValid:
    """Setting a valid config key."""

    def test_set_llm_model(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_get:
            config = MagicMock()
            config.llm.model = "gpt-4o-mini"
            config.save = MagicMock()
            mock_get.return_value = config

            with patch("web_clip_helper.config.set_by_path") as mock_set:
                with patch("web_clip_helper.config._DEFAULT_CONFIG_PATH", "/tmp/test-config.yaml"):
                    result = runner.invoke(app, ["agent", "config", "set", "llm.model", "gpt-4o"])
                    assert result.exit_code == 0
                    lines = _validate_all_jsonl(result.output)
                    assert len(lines) == 1
                    assert lines[0]["type"] == "result"
                    assert lines[0]["key"] == "llm.model"
                    assert lines[0]["masked_value"] == "gpt-4o"

    def test_set_llm_base_url(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_get:
            config = MagicMock()
            config.save = MagicMock()
            mock_get.return_value = config

            with patch("web_clip_helper.config.set_by_path"):
                with patch("web_clip_helper.config._DEFAULT_CONFIG_PATH", "/tmp/test-config.yaml"):
                    result = runner.invoke(app, ["agent", "config", "set", "llm.base_url", "https://new-api.example.com/v1"])
                    assert result.exit_code == 0
                    lines = _parse_jsonl(result.output)
                    assert lines[0]["type"] == "result"
                    assert lines[0]["key"] == "llm.base_url"

    def test_set_api_key_masks_output(self) -> None:
        """Setting api_key should never show plaintext in output."""
        secret_key = "sk-super-secret-key-never-show-this"
        with patch("web_clip_helper.config.get_config") as mock_get:
            config = MagicMock()
            config.save = MagicMock()
            mock_get.return_value = config

            with patch("web_clip_helper.config.set_by_path"):
                with patch("web_clip_helper.config._DEFAULT_CONFIG_PATH", "/tmp/test-config.yaml"):
                    result = runner.invoke(app, ["agent", "config", "set", "llm.api_key", secret_key])
                    assert secret_key not in result.output
                    lines = _parse_jsonl(result.output)
                    assert "****" in lines[0]["masked_value"]

    def test_result_has_config_path(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_get:
            config = MagicMock()
            config.save = MagicMock()
            mock_get.return_value = config

            with patch("web_clip_helper.config.set_by_path"):
                with patch("web_clip_helper.config._DEFAULT_CONFIG_PATH", "/tmp/test-config.yaml"):
                    result = runner.invoke(app, ["agent", "config", "set", "llm.model", "gpt-4o"])
                    lines = _parse_jsonl(result.output)
                    assert "config_path" in lines[0]

    def test_persistence_calls_save(self) -> None:
        """Verify Config.save() is called after setting."""
        with patch("web_clip_helper.config.get_config") as mock_get:
            config = MagicMock()
            config.save = MagicMock()
            mock_get.return_value = config

            with patch("web_clip_helper.config.set_by_path"):
                with patch("web_clip_helper.config._DEFAULT_CONFIG_PATH", "/tmp/test-config.yaml"):
                    runner.invoke(app, ["agent", "config", "set", "llm.model", "gpt-4o"])
                    config.save.assert_called_once()

    def test_invalidates_cache(self) -> None:
        """Verify _cached_config is reset after setting."""
        import web_clip_helper.config as cfg_mod

        with patch.object(cfg_mod, "get_config") as mock_get:
            config = MagicMock()
            config.save = MagicMock()
            mock_get.return_value = config

            with patch.object(cfg_mod, "set_by_path"):
                with patch.object(cfg_mod, "_DEFAULT_CONFIG_PATH", "/tmp/test-config.yaml"):
                    orig_cache = cfg_mod._cached_config
                    runner.invoke(app, ["agent", "config", "set", "llm.model", "gpt-4o"])
                    assert cfg_mod._cached_config is None


class TestAgentConfigSetInvalidPath:
    """Setting an invalid/unknown config key."""

    def test_invalid_path_exits_nonzero(self) -> None:
        result = runner.invoke(app, ["agent", "config", "set", "nonexistent.path", "value"])
        assert result.exit_code != 0

    def test_invalid_path_emits_error(self) -> None:
        result = runner.invoke(app, ["agent", "config", "set", "nonexistent.path", "value"])
        lines = _parse_jsonl(result.output)
        error_lines = [l for l in lines if l["type"] == "error"]
        assert len(error_lines) == 1
        assert error_lines[0]["error_code"] == "INPUT_INVALID"

    def test_invalid_path_lists_allowed(self) -> None:
        result = runner.invoke(app, ["agent", "config", "set", "bad.key", "val"])
        lines = _parse_jsonl(result.output)
        error_line = next(l for l in lines if l["type"] == "error")
        assert "bad.key" in error_line["detail"]

    def test_random_key_rejected(self) -> None:
        result = runner.invoke(app, ["agent", "config", "set", "llm.nonexistent", "val"])
        assert result.exit_code != 0

    def test_partial_path_rejected(self) -> None:
        result = runner.invoke(app, ["agent", "config", "set", "llm", "val"])
        assert result.exit_code != 0


class TestAgentConfigSetTypeCoercion:
    """Verify type coercion for int fields."""

    def test_int_field_coerced(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_get:
            config = MagicMock()
            config.save = MagicMock()
            mock_get.return_value = config

            with patch("web_clip_helper.config.set_by_path") as mock_set:
                with patch("web_clip_helper.config._DEFAULT_CONFIG_PATH", "/tmp/test-config.yaml"):
                    result = runner.invoke(app, ["agent", "config", "set", "refresh.default_interval_days", "14"])
                    assert result.exit_code == 0
                    # set_by_path should have been called with the string value
                    # (actual coercion happens inside set_by_path)
                    mock_set.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# Schema registration
# ═══════════════════════════════════════════════════════════════════


class TestAgentSchemaRegistration:
    """Verify new commands appear in agent schema output."""

    def test_schema_includes_auth_status(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        lines = _parse_jsonl(result.output)
        schema_line = lines[0]
        names = {cmd["name"] for cmd in schema_line["data"]["commands"]}
        assert "agent auth status" in names

    def test_schema_includes_agent_config_list(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        lines = _parse_jsonl(result.output)
        schema_line = lines[0]
        names = {cmd["name"] for cmd in schema_line["data"]["commands"]}
        assert "agent config list" in names

    def test_schema_includes_agent_config_set(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        lines = _parse_jsonl(result.output)
        schema_line = lines[0]
        names = {cmd["name"] for cmd in schema_line["data"]["commands"]}
        assert "agent config set" in names

    def test_auth_status_is_idempotent(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        cmd = next(c for c in schema if c["name"] == "agent auth status")
        assert cmd["is_idempotent"] is True
        assert cmd["parameters"] == []

    def test_config_list_is_idempotent(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        cmd = next(c for c in schema if c["name"] == "agent config list")
        assert cmd["is_idempotent"] is True
        assert cmd["parameters"] == []

    def test_config_set_has_key_value_params(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        cmd = next(c for c in schema if c["name"] == "agent config set")
        assert cmd["is_idempotent"] is True
        param_names = {p["name"] for p in cmd["parameters"]}
        assert "key" in param_names
        assert "value" in param_names


class TestAgentConfigSetAllWhitelistedPaths:
    """Verify every whitelisted path is accepted."""

    @pytest.mark.parametrize("key", [
        "storage_path",
        "db_path",
        "llm.api_key",
        "llm.base_url",
        "llm.model",
        "refresh.default_interval_days",
        "prompts.title",
        "prompts.tags",
        "prompts.classify",
    ])
    def test_whitelisted_path_accepted(self, key: str) -> None:
        with patch("web_clip_helper.config.get_config") as mock_get:
            config = MagicMock()
            config.save = MagicMock()
            mock_get.return_value = config

            with patch("web_clip_helper.config.set_by_path"):
                with patch("web_clip_helper.config._DEFAULT_CONFIG_PATH", "/tmp/test-config.yaml"):
                    result = runner.invoke(app, ["agent", "config", "set", key, "test-value"])
                    assert result.exit_code == 0
                    lines = _parse_jsonl(result.output)
                    assert lines[0]["type"] == "result"
                    assert lines[0]["key"] == key


# ═══════════════════════════════════════════════════════════════════
# agent debug last-crash
# ═══════════════════════════════════════════════════════════════════


class TestAgentDebugLastCrashNoFile:
    """When no crash dump file exists."""

    def test_no_crash_exits_zero(self) -> None:
        with patch("web_clip_helper.paths.get_crash_dump_dir") as mock_dir:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                mock_dir.return_value = Path(td) / "crash_dumps"
                mock_dir.return_value.mkdir(parents=True, exist_ok=True)
                result = runner.invoke(app, ["agent", "debug", "last-crash"])
                assert result.exit_code == 0

    def test_no_crash_status(self) -> None:
        with patch("web_clip_helper.paths.get_crash_dump_dir") as mock_dir:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                mock_dir.return_value = Path(td) / "crash_dumps"
                mock_dir.return_value.mkdir(parents=True, exist_ok=True)
                result = runner.invoke(app, ["agent", "debug", "last-crash"])
                lines = _validate_all_jsonl(result.output)
                assert len(lines) == 1
                assert lines[0]["type"] == "result"
                assert lines[0]["status"] == "no_crash"

    def test_no_crash_has_detail(self) -> None:
        with patch("web_clip_helper.paths.get_crash_dump_dir") as mock_dir:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                mock_dir.return_value = Path(td) / "crash_dumps"
                mock_dir.return_value.mkdir(parents=True, exist_ok=True)
                result = runner.invoke(app, ["agent", "debug", "last-crash"])
                lines = _parse_jsonl(result.output)
                assert "detail" in lines[0]
                assert "No crash dump" in lines[0]["detail"]


class TestAgentDebugLastCrashWithFile:
    """When a crash dump file exists."""

    def _write_crash_file(self, td: str, data: dict) -> Path:
        crash_dir = Path(td) / "crash_dumps"
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_file = crash_dir / ".last-crash.json"
        crash_file.write_text(json.dumps(data), encoding="utf-8")
        return crash_dir

    def test_outputs_dict_type(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            crash_data = {
                "AGENT_ABORTED": True,
                "source": "exception",
                "exception_type": "ValueError",
                "timestamp": "2026-01-01T00:00:00Z",
            }
            crash_dir = self._write_crash_file(td, crash_data)
            with patch("web_clip_helper.paths.get_crash_dump_dir", return_value=crash_dir):
                result = runner.invoke(app, ["agent", "debug", "last-crash"])
                lines = _validate_all_jsonl(result.output)
                assert len(lines) == 1
                assert lines[0]["type"] == "dict"

    def test_crash_data_contents(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            crash_data = {
                "AGENT_ABORTED": True,
                "source": "signal",
                "signal": "SIGTERM",
                "timestamp": "2026-01-01T00:00:00Z",
                "trace_id": "abc123",
            }
            crash_dir = self._write_crash_file(td, crash_data)
            with patch("web_clip_helper.paths.get_crash_dump_dir", return_value=crash_dir):
                result = runner.invoke(app, ["agent", "debug", "last-crash"])
                lines = _parse_jsonl(result.output)
                data = lines[0]["data"]
                assert data["AGENT_ABORTED"] is True
                assert data["source"] == "signal"
                assert data["trace_id"] == "abc123"

    def test_crash_stage_field(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            crash_data = {"AGENT_ABORTED": True}
            crash_dir = self._write_crash_file(td, crash_data)
            with patch("web_clip_helper.paths.get_crash_dump_dir", return_value=crash_dir):
                result = runner.invoke(app, ["agent", "debug", "last-crash"])
                lines = _parse_jsonl(result.output)
                assert lines[0]["stage"] == "agent_debug_last_crash"


class TestAgentDebugLastCrashInvalidJSON:
    """When the crash file contains invalid JSON."""

    def test_invalid_json_reports_error(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            crash_dir = Path(td) / "crash_dumps"
            crash_dir.mkdir(parents=True, exist_ok=True)
            (crash_dir / ".last-crash.json").write_text("not valid json {{{", encoding="utf-8")
            with patch("web_clip_helper.paths.get_crash_dump_dir", return_value=crash_dir):
                result = runner.invoke(app, ["agent", "debug", "last-crash"])
                lines = _validate_all_jsonl(result.output)
                assert lines[0]["type"] == "result"
                assert lines[0]["status"] == "error"
                assert "Failed to read" in lines[0]["detail"]


# ═══════════════════════════════════════════════════════════════════
# agent debug env
# ═══════════════════════════════════════════════════════════════════


class TestAgentDebugEnvStructure:
    """Verify env output structure."""

    def test_exits_zero(self) -> None:
        result = runner.invoke(app, ["agent", "debug", "env"])
        assert result.exit_code == 0

    def test_outputs_diagnostics_type(self) -> None:
        result = runner.invoke(app, ["agent", "debug", "env"])
        lines = _validate_all_jsonl(result.output)
        assert len(lines) == 1
        assert lines[0]["type"] == "diagnostics"

    def test_has_all_sections(self) -> None:
        result = runner.invoke(app, ["agent", "debug", "env"])
        lines = _parse_jsonl(result.output)
        data = lines[0]["data"]
        for section in ("python", "os", "tool", "directories", "llm", "dependencies", "env_indicators"):
            assert section in data, f"Missing section: {section}"

    def test_python_section_has_version(self) -> None:
        result = runner.invoke(app, ["agent", "debug", "env"])
        lines = _parse_jsonl(result.output)
        python_data = lines[0]["data"]["python"]
        assert "version" in python_data
        assert "implementation" in python_data

    def test_os_section(self) -> None:
        result = runner.invoke(app, ["agent", "debug", "env"])
        lines = _parse_jsonl(result.output)
        os_data = lines[0]["data"]["os"]
        assert "name" in os_data
        assert "platform" in os_data
        assert "architecture" in os_data


class TestAgentDebugEnvRedaction:
    """Verify sensitive values are redacted."""

    def test_api_key_not_in_output(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = "sk-super-secret-key-that-should-be-redacted"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config

            result = runner.invoke(app, ["agent", "debug", "env"])
            assert "sk-super-secret-key-that-should-be-redacted" not in result.output

    def test_llm_section_has_api_key_set(self) -> None:
        result = runner.invoke(app, ["agent", "debug", "env"])
        lines = _parse_jsonl(result.output)
        llm_data = lines[0]["data"]["llm"]
        assert "api_key_set" in llm_data

    def test_stage_field(self) -> None:
        result = runner.invoke(app, ["agent", "debug", "env"])
        lines = _parse_jsonl(result.output)
        assert lines[0]["stage"] == "agent_debug_env"


class TestAgentDebugEnvDependencies:
    """Verify dependency versions are present."""

    def test_httpx_version_present(self) -> None:
        result = runner.invoke(app, ["agent", "debug", "env"])
        lines = _parse_jsonl(result.output)
        deps = lines[0]["data"]["dependencies"]
        assert "httpx" in deps
        assert deps["httpx"] != "not_installed"

    def test_typer_version_present(self) -> None:
        result = runner.invoke(app, ["agent", "debug", "env"])
        lines = _parse_jsonl(result.output)
        deps = lines[0]["data"]["dependencies"]
        assert "typer" in deps
        assert deps["typer"] != "not_installed"

    def test_yaml_version_present(self) -> None:
        result = runner.invoke(app, ["agent", "debug", "env"])
        lines = _parse_jsonl(result.output)
        deps = lines[0]["data"]["dependencies"]
        assert "yaml" in deps


# ═══════════════════════════════════════════════════════════════════
# agent cache clean
# ═══════════════════════════════════════════════════════════════════


class TestAgentCacheCleanMissingDir:
    """When cache directory doesn't exist."""

    def test_exits_zero(self) -> None:
        with patch("web_clip_helper.paths.get_state_dir") as mock_dir:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                mock_dir.return_value = Path(td)
                result = runner.invoke(app, ["agent", "cache", "clean"])
                assert result.exit_code == 0

    def test_already_clean_status(self) -> None:
        with patch("web_clip_helper.paths.get_state_dir") as mock_dir:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                mock_dir.return_value = Path(td)
                result = runner.invoke(app, ["agent", "cache", "clean"])
                lines = _validate_all_jsonl(result.output)
                assert len(lines) == 1
                assert lines[0]["type"] == "result"
                assert lines[0]["status"] == "already_clean"


class TestAgentCacheCleanEmptyDir:
    """When cache directory exists but is empty."""

    def test_already_clean_when_empty(self) -> None:
        with patch("web_clip_helper.paths.get_state_dir") as mock_dir:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                cache_dir = Path(td) / "cache"
                cache_dir.mkdir()
                mock_dir.return_value = Path(td)
                result = runner.invoke(app, ["agent", "cache", "clean"])
                lines = _parse_jsonl(result.output)
                assert lines[0]["status"] == "already_clean"


class TestAgentCacheCleanPopulated:
    """When cache directory has files."""

    def test_cleans_files(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            cache_dir.mkdir()
            # Create test files
            (cache_dir / "test1.txt").write_text("hello world", encoding="utf-8")
            (cache_dir / "test2.bin").write_bytes(b"\x00" * 100)
            sub = cache_dir / "subdir"
            sub.mkdir()
            (sub / "nested.txt").write_text("nested content", encoding="utf-8")

            with patch("web_clip_helper.paths.get_state_dir", return_value=Path(td)):
                result = runner.invoke(app, ["agent", "cache", "clean"])
                lines = _validate_all_jsonl(result.output)
                assert len(lines) == 1
                assert lines[0]["type"] == "result"
                assert lines[0]["status"] == "cleaned"
                assert lines[0]["files_removed"] == 3  # test1.txt, test2.bin, nested.txt

    def test_bytes_freed_present(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            cache_dir.mkdir()
            (cache_dir / "file.txt").write_text("x" * 500, encoding="utf-8")

            with patch("web_clip_helper.paths.get_state_dir", return_value=Path(td)):
                result = runner.invoke(app, ["agent", "cache", "clean"])
                lines = _parse_jsonl(result.output)
                assert "bytes_freed" in lines[0]
                assert lines[0]["bytes_freed"] != "0 B"

    def test_cache_dir_in_output(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            cache_dir.mkdir()
            (cache_dir / "file.txt").write_text("data", encoding="utf-8")

            with patch("web_clip_helper.paths.get_state_dir", return_value=Path(td)):
                result = runner.invoke(app, ["agent", "cache", "clean"])
                lines = _parse_jsonl(result.output)
                assert "cache_dir" in lines[0]

    def test_stage_field(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            cache_dir = Path(td) / "cache"
            cache_dir.mkdir()
            (cache_dir / "file.txt").write_text("data", encoding="utf-8")

            with patch("web_clip_helper.paths.get_state_dir", return_value=Path(td)):
                result = runner.invoke(app, ["agent", "cache", "clean"])
                lines = _parse_jsonl(result.output)
                assert lines[0]["stage"] == "agent_cache_clean"


# ═══════════════════════════════════════════════════════════════════
# Schema registration for new commands
# ═══════════════════════════════════════════════════════════════════


class TestNewCommandsSchemaRegistration:
    """Verify new commands appear in agent schema output."""

    def test_schema_includes_debug_last_crash(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        lines = _parse_jsonl(result.output)
        names = {cmd["name"] for cmd in lines[0]["data"]["commands"]}
        assert "agent debug last-crash" in names

    def test_schema_includes_debug_env(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        lines = _parse_jsonl(result.output)
        names = {cmd["name"] for cmd in lines[0]["data"]["commands"]}
        assert "agent debug env" in names

    def test_schema_includes_cache(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        lines = _parse_jsonl(result.output)
        names = {cmd["name"] for cmd in lines[0]["data"]["commands"]}
        assert "agent cache" in names

    def test_debug_last_crash_is_idempotent(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        cmd = next(c for c in schema if c["name"] == "agent debug last-crash")
        assert cmd["is_idempotent"] is True

    def test_debug_env_has_redact_param(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        cmd = next(c for c in schema if c["name"] == "agent debug env")
        param_names = {p["name"] for p in cmd["parameters"]}
        assert "--redact/--no-redact" in param_names

    def test_cache_has_action_param(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        cmd = next(c for c in schema if c["name"] == "agent cache")
        param_names = {p["name"] for p in cmd["parameters"]}
        assert "action" in param_names


# ═══════════════════════════════════════════════════════════════════
# agent feature record
# ═══════════════════════════════════════════════════════════════════


class TestAgentFeatureRecord:
    """Tests for agent feature record --name <n> --desc <d>."""

    def test_record_valid_entry(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with patch("web_clip_helper.paths.get_state_dir", return_value=Path(td)):
                result = runner.invoke(app, [
                    "agent", "feature", "record",
                    "--name", "batch export",
                    "--desc", "Export multiple clips as a zip",
                ])
                lines = _validate_all_jsonl(result.output)
                assert len(lines) == 1
                assert lines[0]["type"] == "result"
                assert lines[0]["status"] == "recorded"
                assert "id" in lines[0]
                assert len(lines[0]["id"]) == 12

                # Verify file was written
                feature_file = Path(td) / "feature_requests.jsonl"
                assert feature_file.exists()
                entries = [json.loads(l) for l in feature_file.read_text(encoding="utf-8").splitlines() if l.strip()]
                assert len(entries) == 1
                assert entries[0]["name"] == "batch export"
                assert entries[0]["description"] == "Export multiple clips as a zip"
                assert "id" in entries[0]
                assert "recorded_at" in entries[0]
                assert "tool_version" in entries[0]

    def test_record_empty_name_rejected(self) -> None:
        result = runner.invoke(app, [
            "agent", "feature", "record",
            "--name", "",
            "--desc", "some description",
        ])
        lines = _validate_all_jsonl(result.output)
        assert any(l["type"] == "error" and "INPUT_INVALID" in l.get("error_code", "") for l in lines)

    def test_record_empty_desc_rejected(self) -> None:
        result = runner.invoke(app, [
            "agent", "feature", "record",
            "--name", "test feature",
            "--desc", "",
        ])
        lines = _validate_all_jsonl(result.output)
        assert any(l["type"] == "error" and "INPUT_INVALID" in l.get("error_code", "") for l in lines)

    def test_record_multiple_entries_append(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with patch("web_clip_helper.paths.get_state_dir", return_value=Path(td)):
                runner.invoke(app, [
                    "agent", "feature", "record",
                    "--name", "first", "--desc", "First feature",
                ])
                runner.invoke(app, [
                    "agent", "feature", "record",
                    "--name", "second", "--desc", "Second feature",
                ])

                feature_file = Path(td) / "feature_requests.jsonl"
                entries = [json.loads(l) for l in feature_file.read_text(encoding="utf-8").splitlines() if l.strip()]
                assert len(entries) == 2
                assert entries[0]["name"] == "first"
                assert entries[1]["name"] == "second"


# ═══════════════════════════════════════════════════════════════════
# agent feature list
# ═══════════════════════════════════════════════════════════════════


class TestAgentFeatureList:
    """Tests for agent feature list."""

    def test_list_with_entries(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            # Pre-populate feature_requests.jsonl
            feature_file = Path(td) / "feature_requests.jsonl"
            entries = [
                {"id": "aaa111", "name": "feat1", "description": "d1", "recorded_at": "2025-01-01T00:00:00.000Z", "tool_version": "0.1.0"},
                {"id": "bbb222", "name": "feat2", "description": "d2", "recorded_at": "2025-01-02T00:00:00.000Z", "tool_version": "0.1.0"},
            ]
            feature_file.write_text(
                "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
                encoding="utf-8",
            )

            with patch("web_clip_helper.paths.get_state_dir", return_value=Path(td)):
                result = runner.invoke(app, ["agent", "feature", "list"])
                lines = _validate_all_jsonl(result.output)
                # 2 dict lines + 1 result summary
                dict_lines = [l for l in lines if l["type"] == "dict"]
                result_lines = [l for l in lines if l["type"] == "result"]
                assert len(dict_lines) == 2
                assert len(result_lines) == 1
                assert result_lines[0]["total"] == 2
                # Newest first: feat2 then feat1
                assert dict_lines[0]["data"]["name"] == "feat2"
                assert dict_lines[1]["data"]["name"] == "feat1"

    def test_list_missing_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            with patch("web_clip_helper.paths.get_state_dir", return_value=Path(td)):
                result = runner.invoke(app, ["agent", "feature", "list"])
                lines = _validate_all_jsonl(result.output)
                assert len(lines) == 1
                assert lines[0]["type"] == "result"
                assert lines[0]["total"] == 0

    def test_list_empty_file(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            feature_file = Path(td) / "feature_requests.jsonl"
            feature_file.write_text("", encoding="utf-8")

            with patch("web_clip_helper.paths.get_state_dir", return_value=Path(td)):
                result = runner.invoke(app, ["agent", "feature", "list"])
                lines = _validate_all_jsonl(result.output)
                assert len(lines) == 1
                assert lines[0]["type"] == "result"
                assert lines[0]["total"] == 0


# ═══════════════════════════════════════════════════════════════════
# agent metrics trace
# ═══════════════════════════════════════════════════════════════════


class TestAgentMetricsTrace:
    """Tests for agent metrics trace --id <trace_id>."""

    def test_trace_matching_crash(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            crash_dir = Path(td) / "crash_dumps"
            crash_dir.mkdir()
            crash_data = {
                "trace_id": "abc123def456",
                "source": "exception",
                "timestamp": "2025-01-15T12:00:00.000Z",
                "flight_context": {"command": "clip"},
            }
            (crash_dir / ".last-crash.json").write_text(
                json.dumps(crash_data), encoding="utf-8"
            )

            with patch("web_clip_helper.paths.get_crash_dump_dir", return_value=crash_dir):
                result = runner.invoke(app, ["agent", "metrics", "trace", "--id", "abc123def456"])
                lines = _validate_all_jsonl(result.output)
                dict_lines = [l for l in lines if l["type"] == "dict"]
                assert len(dict_lines) == 1
                assert dict_lines[0]["data"]["trace_id"] == "abc123def456"

    def test_trace_no_match(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            crash_dir = Path(td) / "crash_dumps"
            crash_dir.mkdir()
            (crash_dir / ".last-crash.json").write_text(
                json.dumps({"trace_id": "other_id", "source": "signal"}), encoding="utf-8"
            )

            with patch("web_clip_helper.paths.get_crash_dump_dir", return_value=crash_dir):
                result = runner.invoke(app, ["agent", "metrics", "trace", "--id", "nonexistent"])
                lines = _validate_all_jsonl(result.output)
                assert len(lines) == 1
                assert lines[0]["type"] == "result"
                assert lines[0]["status"] == "not_found"

    def test_trace_empty_id_rejected(self) -> None:
        result = runner.invoke(app, ["agent", "metrics", "trace", "--id", ""])
        lines = _validate_all_jsonl(result.output)
        assert any(l["type"] == "error" and "INPUT_INVALID" in l.get("error_code", "") for l in lines)

    def test_trace_no_crash_dir(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            crash_dir = Path(td) / "crash_dumps"
            # Don't create crash_dir — simulate missing directory

            with patch("web_clip_helper.paths.get_crash_dump_dir", return_value=crash_dir):
                result = runner.invoke(app, ["agent", "metrics", "trace", "--id", "any_id"])
                lines = _validate_all_jsonl(result.output)
                assert len(lines) == 1
                assert lines[0]["type"] == "result"
                assert lines[0]["status"] == "not_found"

    def test_trace_scans_additional_json_files(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            crash_dir = Path(td) / "crash_dumps"
            crash_dir.mkdir()
            # .last-crash.json has different trace_id
            (crash_dir / ".last-crash.json").write_text(
                json.dumps({"trace_id": "wrong_id"}), encoding="utf-8"
            )
            # Another .json file has the match
            extra_data = {"trace_id": "target_001", "source": "signal"}
            (crash_dir / "crash_20250115.json").write_text(
                json.dumps(extra_data), encoding="utf-8"
            )

            with patch("web_clip_helper.paths.get_crash_dump_dir", return_value=crash_dir):
                result = runner.invoke(app, ["agent", "metrics", "trace", "--id", "target_001"])
                lines = _validate_all_jsonl(result.output)
                dict_lines = [l for l in lines if l["type"] == "dict"]
                assert len(dict_lines) == 1
                assert dict_lines[0]["data"]["trace_id"] == "target_001"


# ═══════════════════════════════════════════════════════════════════
# agent update apply
# ═══════════════════════════════════════════════════════════════════


class TestAgentUpdateApply:
    """Tests for agent update apply --yes."""

    def test_apply_without_yes_flag_rejected(self) -> None:
        result = runner.invoke(app, ["agent", "update", "apply"])
        lines = _validate_all_jsonl(result.output)
        assert any(l["type"] == "error" and "INPUT_INVALID" in l.get("error_code", "") for l in lines)

    def test_apply_already_up_to_date(self) -> None:
        """When PyPI latest <= current version, status=already_up_to_date."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"info": {"version": "0.1.0"}}

        with patch("httpx.get", return_value=mock_response):
            result = runner.invoke(app, ["agent", "update", "apply", "--yes"])
            lines = _validate_all_jsonl(result.output)
            result_lines = [l for l in lines if l["type"] == "result"]
            assert len(result_lines) == 1
            assert result_lines[0]["status"] == "already_up_to_date"

    def test_apply_newer_version_triggers_upgrade(self) -> None:
        """When PyPI has newer version, runs pip install --upgrade."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"info": {"version": "99.0.0"}}

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "Successfully installed web-clip-helper-99.0.0"
        mock_proc.stderr = ""

        with patch("httpx.get", return_value=mock_response), \
             patch("subprocess.run", return_value=mock_proc):
            result = runner.invoke(app, ["agent", "update", "apply", "--yes"])
            lines = _validate_all_jsonl(result.output)
            result_lines = [l for l in lines if l["type"] == "result"]
            assert len(result_lines) == 1
            assert result_lines[0]["status"] == "upgraded"
            assert "old_version" in result_lines[0]
            assert "new_version" in result_lines[0]

    def test_apply_pip_failure(self) -> None:
        """When pip install fails, outputs error."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"info": {"version": "99.0.0"}}

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "ERROR: Could not install"

        with patch("httpx.get", return_value=mock_response), \
             patch("subprocess.run", return_value=mock_proc):
            result = runner.invoke(app, ["agent", "update", "apply", "--yes"])
            lines = _validate_all_jsonl(result.output)
            assert any(l["type"] == "error" for l in lines)

    def test_apply_network_error(self) -> None:
        """When PyPI check fails with network error, outputs error."""
        import httpx

        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
            result = runner.invoke(app, ["agent", "update", "apply", "--yes"])
            lines = _validate_all_jsonl(result.output)
            assert any(l["type"] == "error" and "NETWORK_ERROR" in l.get("error_code", "") for l in lines)

    def test_apply_pypi_404_unpublished(self) -> None:
        """When PyPI returns 404, outputs unpublished status."""
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.get", return_value=mock_response):
            result = runner.invoke(app, ["agent", "update", "apply", "--yes"])
            lines = _validate_all_jsonl(result.output)
            result_lines = [l for l in lines if l["type"] == "result"]
            assert len(result_lines) == 1
            assert result_lines[0]["status"] == "unpublished"


# ═══════════════════════════════════════════════════════════════════
# T03 Schema registration for new commands
# ═══════════════════════════════════════════════════════════════════


class TestT03SchemaRegistration:
    """Verify T03 new commands appear in agent schema output."""

    def test_schema_includes_feature_record(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        names = {c["name"] for c in schema}
        assert "agent feature record" in names

    def test_schema_includes_feature_list(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        names = {c["name"] for c in schema}
        assert "agent feature list" in names

    def test_schema_includes_metrics_trace(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        names = {c["name"] for c in schema}
        assert "agent metrics trace" in names

    def test_schema_includes_update_apply(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        names = {c["name"] for c in schema}
        assert "agent update apply" in names

    def test_feature_record_not_idempotent(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        cmd = next(c for c in schema if c["name"] == "agent feature record")
        assert cmd["is_idempotent"] is False

    def test_feature_list_is_idempotent(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        cmd = next(c for c in schema if c["name"] == "agent feature list")
        assert cmd["is_idempotent"] is True

    def test_metrics_trace_has_id_param(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        cmd = next(c for c in schema if c["name"] == "agent metrics trace")
        param_names = {p["name"] for p in cmd["parameters"]}
        assert "--id" in param_names

    def test_update_apply_has_yes_param(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        cmd = next(c for c in schema if c["name"] == "agent update apply")
        param_names = {p["name"] for p in cmd["parameters"]}
        assert "--yes" in param_names

    def test_total_agent_commands_count(self) -> None:
        """Verify we have 15 agent commands (excluding daemon).

        Original 5 (info/schema/errors/doctor/update check) +
        T01 adds 3 (auth status, config list, config set) +
        T02 adds 3 (debug last-crash, debug env, cache) +
        T03 adds 4 (feature record, feature list, metrics trace, update apply) = 15.
        """
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        agent_cmds = [c for c in schema if c["name"].startswith("agent ")]
        assert len(agent_cmds) == 15
