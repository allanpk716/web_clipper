"""Tests for agent doctor command — health diagnostics.

Covers all 4 checks (storage_dirs, sqlite, config, llm_connectivity)
and the summary result line.
"""

from __future__ import annotations

import httpx
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app

runner = CliRunner()


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output into a list of dicts."""
    return [json.loads(line) for line in output.strip().splitlines() if line.strip()]


# ── agent doctor command integration ──────────────────────────────


class TestAgentDoctorBasic:
    """Verify agent doctor command basic output structure."""

    def test_doctor_exits_zero(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"

    def test_doctor_outputs_5_jsonl_lines(self) -> None:
        """4 diagnostics + 1 summary result."""
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        assert len(lines) == 5, f"Expected 5 lines, got {len(lines)}: {result.output}"

    def test_doctor_has_4_diagnostics_lines(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        diag_lines = [l for l in lines if l["type"] == "diagnostics"]
        assert len(diag_lines) == 4

    def test_doctor_has_1_result_line(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        result_lines = [l for l in lines if l["type"] == "result"]
        assert len(result_lines) == 1

    def test_diagnostics_lines_have_required_fields(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        diag_lines = [l for l in lines if l["type"] == "diagnostics"]
        for line in diag_lines:
            assert "check" in line, f"Missing 'check' in: {line}"
            assert "status" in line, f"Missing 'status' in: {line}"
            assert line["status"] in ("pass", "fail", "skip"), f"Invalid status: {line['status']}"
            assert "detail" in line, f"Missing 'detail' in: {line}"
            assert "duration_ms" in line, f"Missing 'duration_ms' in: {line}"
            assert isinstance(line["duration_ms"], (int, float)), f"duration_ms not numeric: {line}"

    def test_result_line_has_summary_counts(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        result_line = next(l for l in lines if l["type"] == "result")
        assert result_line["total"] == 4
        assert result_line["pass"] + result_line["fail"] + result_line["skip"] == 4
        assert result_line["stage"] == "agent_doctor"

    def test_diagnostics_have_agent_doctor_stage(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        diag_lines = [l for l in lines if l["type"] == "diagnostics"]
        for line in diag_lines:
            assert line["stage"] == "agent_doctor"


class TestAgentDoctorCheckNames:
    """Verify all 4 check names are present."""

    def test_all_check_names_present(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        diag_lines = [l for l in lines if l["type"] == "diagnostics"]
        check_names = {l["check"] for l in diag_lines}
        expected = {"storage_dirs", "sqlite", "config", "llm_connectivity"}
        assert check_names == expected, f"Expected {expected}, got {check_names}"


class TestAgentDoctorHappyPath:
    """When everything works, all checks should pass except LLM (skipped without key)."""

    def test_storage_dirs_passes(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        storage = next(l for l in lines if l["type"] == "diagnostics" and l["check"] == "storage_dirs")
        assert storage["status"] == "pass"

    def test_sqlite_passes(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        sqlite_check = next(l for l in lines if l["type"] == "diagnostics" and l["check"] == "sqlite")
        assert sqlite_check["status"] == "pass"

    def test_config_passes(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        config_check = next(l for l in lines if l["type"] == "diagnostics" and l["check"] == "config")
        assert config_check["status"] == "pass"

    def test_llm_skipped_without_api_key(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        llm_check = next(l for l in lines if l["type"] == "diagnostics" and l["check"] == "llm_connectivity")
        # Without api_key, should be "skip"
        assert llm_check["status"] == "skip"

    def test_summary_counts_match(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        diag_lines = [l for l in lines if l["type"] == "diagnostics"]
        result_line = next(l for l in lines if l["type"] == "result")

        expected_pass = sum(1 for l in diag_lines if l["status"] == "pass")
        expected_fail = sum(1 for l in diag_lines if l["status"] == "fail")
        expected_skip = sum(1 for l in diag_lines if l["status"] == "skip")

        assert result_line["pass"] == expected_pass
        assert result_line["fail"] == expected_fail
        assert result_line["skip"] == expected_skip
        assert result_line["total"] == 4


class TestAgentDoctorLLMConnectivity:
    """Test LLM connectivity check with mocked HTTP responses."""

    def test_llm_passes_on_success(self) -> None:
        """When api_key is set and API responds 200, check should pass."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch("web_clip_helper.config.get_config") as mock_get_config:
            config = MagicMock()
            config.llm.api_key = "sk-test-key"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_get_config.return_value = config

            with patch("httpx.post", return_value=mock_response) as mock_post:
                from web_clip_helper.cli import _check_llm_connectivity

                result = _check_llm_connectivity()
                assert result["status"] == "pass"
                assert "api.example.com" in result["detail"]
                mock_post.assert_called_once()

    def test_llm_fails_on_error(self) -> None:
        """When api_key is set but API returns error, check should fail."""
        with patch("web_clip_helper.config.get_config") as mock_get_config:
            config = MagicMock()
            config.llm.api_key = "sk-test-key"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_get_config.return_value = config

            with patch("httpx.post", side_effect=Exception("Connection refused")):
                from web_clip_helper.cli import _check_llm_connectivity

                result = _check_llm_connectivity()
                assert result["status"] == "fail"
                assert "Connection refused" in result["detail"]

    def test_llm_skips_without_api_key(self) -> None:
        """When api_key is empty, check should skip."""
        with patch("web_clip_helper.config.get_config") as mock_get_config:
            config = MagicMock()
            config.llm.api_key = ""
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_get_config.return_value = config

            from web_clip_helper.cli import _check_llm_connectivity

            result = _check_llm_connectivity()
            assert result["status"] == "skip"


class TestAgentDoctorStorageDirs:
    """Test storage_dirs check with mocked failures."""

    def test_storage_dirs_fails_on_write_error(self) -> None:
        """When directory is not writable, check should fail."""
        with patch("web_clip_helper.cli.get_config_dir") as mock_cfg:
            mock_cfg.side_effect = OSError("Permission denied")

            from web_clip_helper.cli import _check_storage_dirs

            result = _check_storage_dirs()
            assert result["status"] == "fail"
            assert "Permission denied" in result["detail"]


class TestAgentDoctorSQLite:
    """Test SQLite check with mocked failures."""

    def test_sqlite_fails_on_db_error(self) -> None:
        """When SQLite is corrupted, check should fail."""
        with patch("web_clip_helper.config.get_config") as mock_get_config:
            config = MagicMock()
            config.db_path = "/nonexistent/path/clips.db"
            mock_get_config.return_value = config

            with patch("web_clip_helper.index.ClipIndex._connect", side_effect=sqlite3.OperationalError("disk I/O error")):
                from web_clip_helper.cli import _check_sqlite

                result = _check_sqlite()
                assert result["status"] == "fail"
                assert "disk I/O error" in result["detail"]


class TestAgentDoctorConfig:
    """Test config check with mocked failures."""

    def test_config_fails_on_missing_llm_section(self) -> None:
        """When config has no llm section, check should fail."""
        with patch("web_clip_helper.config.get_config") as mock_get_config:
            config = MagicMock(spec=[])  # Empty spec — no attributes
            mock_get_config.return_value = config

            from web_clip_helper.cli import _check_config

            result = _check_config()
            assert result["status"] == "fail"

    def test_config_fails_on_empty_base_url(self) -> None:
        """When llm.base_url is empty, check should fail."""
        with patch("web_clip_helper.config.get_config") as mock_get_config:
            config = MagicMock()
            config.llm.base_url = ""
            mock_get_config.return_value = config

            from web_clip_helper.cli import _check_config

            result = _check_config()
            assert result["status"] == "fail"
            assert "base_url" in result["detail"]


class TestAgentDoctorEnvelope:
    """Verify JSONL envelope fields on diagnostics lines."""

    def test_diagnostics_lines_have_envelope(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        diag_lines = [l for l in lines if l["type"] == "diagnostics"]
        for line in diag_lines:
            assert "version" in line
            assert line["tool"] == "web-clip-helper"
            assert "timestamp" in line

    def test_result_line_has_envelope(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        lines = _parse_jsonl(result.output)
        result_line = next(l for l in lines if l["type"] == "result")
        assert "version" in result_line
        assert result_line["tool"] == "web-clip-helper"
        assert "timestamp" in result_line


class TestAgentDoctorRobustness:
    """Verify doctor never crashes, even when individual checks fail."""

    def test_doctor_never_crashes(self) -> None:
        """Even with broken config, doctor should output valid JSONL."""
        # All checks use get_config() which auto-creates defaults — this should pass
        result = runner.invoke(app, ["agent", "doctor"])
        assert result.exit_code == 0
        lines = _parse_jsonl(result.output)
        assert len(lines) >= 5

    def test_doctor_produces_valid_json(self) -> None:
        result = runner.invoke(app, ["agent", "doctor"])
        for line in result.output.strip().splitlines():
            if line.strip():
                json.loads(line)  # Should not raise


class TestAgentDoctorSchemaEntry:
    """Verify agent doctor is registered in the command schema."""

    def test_schema_includes_agent_doctor(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        names = {cmd["name"] for cmd in schema}
        assert "agent doctor" in names

    def test_agent_doctor_schema_fields(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        doctor = next(c for c in schema if c["name"] == "agent doctor")
        assert doctor["is_idempotent"] is True
        assert doctor["parameters"] == []
        assert "health" in doctor["description"].lower() or "diagnostics" in doctor["description"].lower()


# ── agent update check command ────────────────────────────────────


class TestAgentUpdateCheckUpToDate:
    """When current version matches or exceeds PyPI version."""

    def test_update_check_exits_zero(self) -> None:
        """Basic smoke test — may hit real PyPI."""
        result = runner.invoke(app, ["agent", "update", "check"])
        assert result.exit_code == 0, f"Exit code {result.exit_code}, output: {result.output}"

    def test_update_check_outputs_valid_jsonl(self) -> None:
        result = runner.invoke(app, ["agent", "update", "check"])
        for line in result.output.strip().splitlines():
            if line.strip():
                parsed = json.loads(line)
                assert "type" in parsed
                assert parsed["type"] in ("result", "error")
                assert "version" in parsed
                assert parsed["tool"] == "web-clip-helper"
                assert "timestamp" in parsed

    def test_update_check_result_has_version_fields(self) -> None:
        """With mocked PyPI response — up-to-date scenario."""
        mock_data = {
            "info": {"version": "0.1.0"},  # Older than current 0.2.0
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_data

        with patch("httpx.get", return_value=mock_response):
            result = runner.invoke(app, ["agent", "update", "check"])
            assert result.exit_code == 0
            lines = _parse_jsonl(result.output)
            assert len(lines) == 1
            line = lines[0]
            assert line["type"] == "result"
            assert line["current_version"] == "0.2.0"
            assert line["latest_version"] == "0.1.0"
            assert line["up_to_date"] is True
            assert "duration_ms" in line
            assert line["stage"] == "agent_update_check"


class TestAgentUpdateCheckNewVersion:
    """When a newer version is available on PyPI."""

    def test_update_available(self) -> None:
        mock_data = {
            "info": {"version": "0.3.0"},
        }
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_data

        with patch("httpx.get", return_value=mock_response):
            result = runner.invoke(app, ["agent", "update", "check"])
            assert result.exit_code == 0
            lines = _parse_jsonl(result.output)
            assert len(lines) == 1
            line = lines[0]
            assert line["type"] == "result"
            assert line["up_to_date"] is False
            assert line["current_version"] == "0.2.0"
            assert line["latest_version"] == "0.3.0"
            assert "changelog_url" in line
            assert "0.3.0" in line["changelog_url"]

    def test_update_available_has_stage(self) -> None:
        mock_data = {"info": {"version": "99.0.0"}}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_data

        with patch("httpx.get", return_value=mock_response):
            result = runner.invoke(app, ["agent", "update", "check"])
            lines = _parse_jsonl(result.output)
            assert lines[0]["stage"] == "agent_update_check"


class TestAgentUpdateCheckUnpublished:
    """When package returns 404 from PyPI (not yet published)."""

    def test_unpublished_status(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=mock_response
            )
        )

        with patch("httpx.get", return_value=mock_response):
            result = runner.invoke(app, ["agent", "update", "check"])
            assert result.exit_code == 0
            lines = _parse_jsonl(result.output)
            assert len(lines) == 1
            line = lines[0]
            assert line["type"] == "result"
            assert line["status"] == "unpublished"
            assert line["up_to_date"] is True
            assert line["current_version"] == "0.2.0"

    def test_unpublished_has_detail(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=mock_response
            )
        )

        with patch("httpx.get", return_value=mock_response):
            result = runner.invoke(app, ["agent", "update", "check"])
            lines = _parse_jsonl(result.output)
            assert "not found" in lines[0]["detail"].lower() or "unpublished" in lines[0].get("detail", "").lower()


class TestAgentUpdateCheckNetworkError:
    """When network errors occur."""

    def test_timeout_error(self) -> None:
        with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
            result = runner.invoke(app, ["agent", "update", "check"])
            assert result.exit_code == 0
            lines = _parse_jsonl(result.output)
            assert len(lines) == 1
            line = lines[0]
            assert line["type"] == "error"
            assert line["error_code"] == "NETWORK_ERROR"
            assert "timed out" in line["detail"].lower() or "timeout" in line["detail"].lower()

    def test_connection_error(self) -> None:
        with patch("httpx.get", side_effect=httpx.ConnectError("Connection refused")):
            result = runner.invoke(app, ["agent", "update", "check"])
            assert result.exit_code == 0
            lines = _parse_jsonl(result.output)
            assert len(lines) == 1
            assert lines[0]["type"] == "error"
            assert lines[0]["error_code"] == "NETWORK_ERROR"

    def test_generic_request_error(self) -> None:
        with patch("httpx.get", side_effect=httpx.RequestError("DNS failure")):
            result = runner.invoke(app, ["agent", "update", "check"])
            assert result.exit_code == 0
            lines = _parse_jsonl(result.output)
            assert lines[0]["type"] == "error"
            assert lines[0]["error_code"] == "NETWORK_ERROR"


class TestAgentUpdateCheckInternalError:
    """When PyPI returns unexpected data."""

    def test_missing_version_in_response(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"info": {}}  # No version field

        with patch("httpx.get", return_value=mock_response):
            result = runner.invoke(app, ["agent", "update", "check"])
            assert result.exit_code == 0
            lines = _parse_jsonl(result.output)
            assert lines[0]["type"] == "error"
            assert lines[0]["error_code"] == "INTERNAL_ERROR"

    def test_invalid_version_string(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"info": {"version": "not-a-version"}}

        with patch("httpx.get", return_value=mock_response):
            result = runner.invoke(app, ["agent", "update", "check"])
            assert result.exit_code == 0
            lines = _parse_jsonl(result.output)
            assert lines[0]["type"] == "error"
            assert lines[0]["error_code"] == "INTERNAL_ERROR"

    def test_http_status_error_non_404(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "500 Server Error", request=MagicMock(), response=mock_response
            )
        )

        with patch("httpx.get", return_value=mock_response):
            result = runner.invoke(app, ["agent", "update", "check"])
            assert result.exit_code == 0
            lines = _parse_jsonl(result.output)
            assert lines[0]["type"] == "error"
            assert lines[0]["error_code"] == "NETWORK_ERROR"

    def test_unexpected_exception(self) -> None:
        with patch("httpx.get", side_effect=RuntimeError("something broke")):
            result = runner.invoke(app, ["agent", "update", "check"])
            assert result.exit_code == 0
            lines = _parse_jsonl(result.output)
            assert lines[0]["type"] == "error"
            assert lines[0]["error_code"] == "INTERNAL_ERROR"


class TestAgentUpdateCheckRobustness:
    """Verify update check never crashes."""

    def test_never_crashes(self) -> None:
        """Even with broken everything, should emit valid JSONL."""
        with patch("httpx.get", side_effect=Exception("catastrophe")):
            result = runner.invoke(app, ["agent", "update", "check"])
            assert result.exit_code == 0
            lines = _parse_jsonl(result.output)
            assert len(lines) >= 1
            # All lines should be valid JSON (already parsed by _parse_jsonl)

    def test_produces_exactly_one_jsonl_line(self) -> None:
        """Every scenario should produce exactly 1 JSONL line."""
        mock_data = {"info": {"version": "0.2.0"}}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_data

        with patch("httpx.get", return_value=mock_response):
            result = runner.invoke(app, ["agent", "update", "check"])
            lines = _parse_jsonl(result.output)
            assert len(lines) == 1


class TestAgentUpdateCheckSchemaEntry:
    """Verify agent update check is registered in the command schema."""

    def test_schema_includes_agent_update_check(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        names = {cmd["name"] for cmd in schema}
        assert "agent update check" in names

    def test_agent_update_check_schema_fields(self) -> None:
        from web_clip_helper.agent_schema import get_commands_schema

        schema = get_commands_schema()
        update_cmd = next(c for c in schema if c["name"] == "agent update check")
        assert update_cmd["is_idempotent"] is True
        assert update_cmd["parameters"] == []
        assert "pypi" in update_cmd["description"].lower() or "version" in update_cmd["description"].lower()
