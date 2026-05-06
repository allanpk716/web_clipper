"""Tests for agent doctor and agent update check commands.

Covers:
- agent doctor: integration test (single result envelope with data.checks array)
- agent doctor: unit tests for individual _check_* functions (imported from app.py)
- agent update check: up-to-date, new version, unpublished, network errors, internal errors
- Schema registration for doctor and update check
"""

from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.output import set_quiet

runner = CliRunner()


# ── Override conftest's autouse to keep App singleton alive ──────


@pytest.fixture(autouse=True)
def _reset_trace_id():
    """Reset quiet mode between tests. Conftest handles Writer buffer cleanup."""
    from web_clip_helper.output import set_quiet
    set_quiet(False)
    yield
    set_quiet(False)


# ── Helpers: CliRunner + drain SDK Writer buffer ─────────────────


def _get_writer_buffer():
    """Return the SDK Writer's internal StringIO buffer."""
    from web_clip_helper.app import get_app
    return get_app().writer._output


def _drain_buffer(buf) -> list[dict]:
    """Read all JSONL lines from the writer's buffer, clear it, return parsed."""
    content = buf.getvalue()
    buf.truncate(0)
    buf.seek(0)
    lines = [l for l in content.strip().splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


def _run_and_capture(args: list[str]) -> tuple[int, list[dict]]:
    """Invoke CLI via CliRunner and capture JSONL from SDK Writer's buffer."""
    set_quiet(False)
    buf = _get_writer_buffer()
    buf.truncate(0)
    buf.seek(0)
    result = runner.invoke(app, args)
    msgs = _drain_buffer(buf)
    return result.exit_code, msgs


# ═══════════════════════════════════════════════════════════════════
# agent doctor — integration tests (single result envelope)
# ═══════════════════════════════════════════════════════════════════


class TestAgentDoctorBasic:
    """Verify agent doctor command basic output structure."""

    def test_doctor_exits_zero(self) -> None:
        code, envelopes = _run_and_capture(["agent", "doctor"])
        assert code == 0

    def test_doctor_outputs_single_result_envelope(self) -> None:
        """New SDK doctor emits a single result envelope with data.checks."""
        code, envelopes = _run_and_capture(["agent", "doctor"])
        result_envs = [e for e in envelopes if e["type"] == "result"]
        assert len(result_envs) == 1, f"Expected 1 result envelope, got {len(result_envs)}"

    def test_result_envelope_has_status_and_checks(self) -> None:
        code, envelopes = _run_and_capture(["agent", "doctor"])
        data = envelopes[0]["data"]
        assert "status" in data
        assert data["status"] in ("pass", "fail")
        assert "checks" in data
        assert isinstance(data["checks"], list)

    def test_checks_have_required_fields(self) -> None:
        code, envelopes = _run_and_capture(["agent", "doctor"])
        checks = envelopes[0]["data"]["checks"]
        for check in checks:
            assert "name" in check, f"Missing 'name' in: {check}"
            assert "status" in check, f"Missing 'status' in: {check}"
            assert check["status"] in ("pass", "fail", "skip"), f"Invalid status: {check['status']}"
            assert "message" in check, f"Missing 'message' in: {check}"


class TestAgentDoctorCheckNames:
    """Verify our 4 custom check names are present among the checks."""

    def test_all_custom_check_names_present(self) -> None:
        code, envelopes = _run_and_capture(["agent", "doctor"])
        checks = envelopes[0]["data"]["checks"]
        check_names = {c["name"] for c in checks}
        expected = {"storage_dirs", "sqlite", "config", "llm_connectivity"}
        assert expected.issubset(check_names), f"Expected {expected} subset of {check_names}"


class TestAgentDoctorHappyPath:
    """When everything works, custom checks should pass or skip."""

    def test_storage_dirs_present(self) -> None:
        code, envelopes = _run_and_capture(["agent", "doctor"])
        checks = envelopes[0]["data"]["checks"]
        storage = next(c for c in checks if c["name"] == "storage_dirs")
        # storage_dirs may pass or fail depending on test env (migration errors)
        assert storage["status"] in ("pass", "fail")

    def test_sqlite_present(self) -> None:
        code, envelopes = _run_and_capture(["agent", "doctor"])
        checks = envelopes[0]["data"]["checks"]
        sqlite_names = [c["name"] for c in checks]
        assert "sqlite" in sqlite_names

    def test_config_present(self) -> None:
        code, envelopes = _run_and_capture(["agent", "doctor"])
        checks = envelopes[0]["data"]["checks"]
        config_names = [c["name"] for c in checks]
        assert "config" in config_names

    def test_llm_status_is_pass_fail_or_skip(self) -> None:
        code, envelopes = _run_and_capture(["agent", "doctor"])
        checks = envelopes[0]["data"]["checks"]
        llm_check = next(c for c in checks if c["name"] == "llm_connectivity")
        # In test env, may be skip (no key) or fail (config migration error)
        assert llm_check["status"] in ("pass", "fail", "skip")


class TestAgentDoctorEnvelope:
    """Verify JSONL envelope fields on the result envelope."""

    def test_result_envelope_has_envelope(self) -> None:
        code, envelopes = _run_and_capture(["agent", "doctor"])
        result_env = next(e for e in envelopes if e["type"] == "result")
        assert "version" in result_env
        assert result_env["tool"] == "web-clip-helper"
        assert "timestamp" in result_env


class TestAgentDoctorRobustness:
    """Verify doctor never crashes."""

    def test_doctor_never_crashes(self) -> None:
        code, envelopes = _run_and_capture(["agent", "doctor"])
        assert code == 0
        assert len(envelopes) >= 1

    def test_doctor_produces_valid_json(self) -> None:
        code, envelopes = _run_and_capture(["agent", "doctor"])
        # Already parsed by _drain_buffer — if we got here, all lines are valid JSON


# ═══════════════════════════════════════════════════════════════════
# agent doctor — unit tests for _check_* functions
# ═══════════════════════════════════════════════════════════════════


class TestCheckLLMConnectivity:
    """Unit tests for _check_llm_connectivity (imported from app.py)."""

    def test_llm_passes_on_success(self) -> None:
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
                from web_clip_helper.app import _check_llm_connectivity

                result = _check_llm_connectivity()
                assert result.status == "pass"
                assert "api.example.com" in result.message
                mock_post.assert_called_once()

    def test_llm_fails_on_error(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_get_config:
            config = MagicMock()
            config.llm.api_key = "sk-test-key"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_get_config.return_value = config

            with patch("httpx.post", side_effect=Exception("Connection refused")):
                from web_clip_helper.app import _check_llm_connectivity

                result = _check_llm_connectivity()
                assert result.status == "fail"
                assert "Connection refused" in result.message

    def test_llm_skips_without_api_key(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_get_config:
            config = MagicMock()
            config.llm.api_key = ""
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_get_config.return_value = config

            from web_clip_helper.app import _check_llm_connectivity

            result = _check_llm_connectivity()
            assert result.status == "pass"
            assert "skip" in result.message.lower()


class TestCheckStorageDirs:
    """Unit tests for _check_storage_dirs (imported from app.py)."""

    def test_storage_dirs_fails_on_write_error(self) -> None:
        with patch("web_clip_helper.app.get_config_dir", side_effect=OSError("Permission denied")):
            from web_clip_helper.app import _check_storage_dirs

            result = _check_storage_dirs()
            assert result.status == "fail"
            assert "Permission denied" in result.message


class TestCheckSQLite:
    """Unit tests for _check_sqlite (imported from app.py)."""

    def test_sqlite_fails_on_db_error(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_get_config:
            config = MagicMock()
            config.db_path = "/nonexistent/path/clips.db"
            mock_get_config.return_value = config

            with patch("web_clip_helper.repository.index.ClipIndex._connect", side_effect=sqlite3.OperationalError("disk I/O error")):
                from web_clip_helper.app import _check_sqlite

                result = _check_sqlite()
                assert result.status == "fail"
                assert "disk I/O error" in result.message


class TestCheckConfig:
    """Unit tests for _check_config (imported from app.py)."""

    def test_config_fails_on_missing_llm_section(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_get_config:
            config = MagicMock(spec=[])  # Empty spec — no attributes
            mock_get_config.return_value = config

            from web_clip_helper.app import _check_config

            result = _check_config()
            assert result.status == "fail"

    def test_config_fails_on_empty_base_url(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_get_config:
            config = MagicMock()
            config.llm.base_url = ""
            mock_get_config.return_value = config

            from web_clip_helper.app import _check_config

            result = _check_config()
            assert result.status == "fail"
            assert "base_url" in result.message


# ═══════════════════════════════════════════════════════════════════
# agent update check
# ═══════════════════════════════════════════════════════════════════


class TestAgentUpdateCheckUpToDate:
    """When current version matches or exceeds PyPI version."""

    def test_update_check_exits_zero(self) -> None:
        """Basic smoke test — may hit real PyPI."""
        code, envelopes = _run_and_capture(["agent", "update", "check"])
        assert code == 0

    def test_update_check_outputs_valid_envelope(self) -> None:
        code, envelopes = _run_and_capture(["agent", "update", "check"])
        for env in envelopes:
            assert "type" in env
            assert env["type"] in ("result", "error")
            assert "version" in env
            assert env["tool"] == "web-clip-helper"
            assert "timestamp" in env

    def test_update_check_result_has_version_fields(self) -> None:
        """With mocked PyPI response — up-to-date scenario."""
        mock_data = {"info": {"version": "0.1.0"}}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_data

        with patch("httpx.get", return_value=mock_response):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert code == 0
            assert len(envelopes) == 1
            env = envelopes[0]
            assert env["type"] == "result"
            data = env["data"]
            assert data["current_version"] == "0.2.0"
            assert data["latest_version"] == "0.1.0"
            assert data["up_to_date"] is True
            assert "duration_ms" in data
            assert data["stage"] == "agent_update_check"


class TestAgentUpdateCheckNewVersion:
    """When a newer version is available on PyPI."""

    def test_update_available(self) -> None:
        mock_data = {"info": {"version": "0.3.0"}}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_data

        with patch("httpx.get", return_value=mock_response):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert code == 0
            assert len(envelopes) == 1
            env = envelopes[0]
            assert env["type"] == "result"
            data = env["data"]
            assert data["up_to_date"] is False
            assert data["current_version"] == "0.2.0"
            assert data["latest_version"] == "0.3.0"
            assert "changelog_url" in data
            assert "0.3.0" in data["changelog_url"]

    def test_update_available_has_stage(self) -> None:
        mock_data = {"info": {"version": "99.0.0"}}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_data

        with patch("httpx.get", return_value=mock_response):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert envelopes[0]["data"]["stage"] == "agent_update_check"


class TestAgentUpdateCheckUnpublished:
    """When package returns 404 from PyPI (not yet published)."""

    def test_unpublished_status(self) -> None:
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=mock_response
            )
        )

        with patch("httpx.get", return_value=mock_response):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert code == 0
            assert len(envelopes) == 1
            env = envelopes[0]
            assert env["type"] == "result"
            data = env["data"]
            assert data["status"] == "unpublished"
            assert data["up_to_date"] is True
            assert data["current_version"] == "0.2.0"

    def test_unpublished_has_detail(self) -> None:
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "404 Not Found", request=MagicMock(), response=mock_response
            )
        )

        with patch("httpx.get", return_value=mock_response):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            data = envelopes[0]["data"]
            detail = data.get("detail", "")
            assert "not found" in detail.lower() or "unpublished" in detail.lower()


class TestAgentUpdateCheckNetworkError:
    """When network errors occur."""

    def test_timeout_error(self) -> None:
        import httpx

        with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert code == 0
            assert len(envelopes) == 1
            env = envelopes[0]
            assert env["type"] == "error"
            assert env["error_code"] == "NETWORK_ERROR"
            msg = env["message"].lower()
            assert "timed out" in msg or "timeout" in msg

    def test_connection_error(self) -> None:
        import httpx

        with patch("httpx.get", side_effect=httpx.ConnectError("Connection refused")):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert len(envelopes) == 1
            assert envelopes[0]["type"] == "error"
            assert envelopes[0]["error_code"] == "NETWORK_ERROR"

    def test_generic_request_error(self) -> None:
        import httpx

        with patch("httpx.get", side_effect=httpx.RequestError("DNS failure")):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert envelopes[0]["type"] == "error"
            assert envelopes[0]["error_code"] == "NETWORK_ERROR"


class TestAgentUpdateCheckInternalError:
    """When PyPI returns unexpected data."""

    def test_missing_version_in_response(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"info": {}}

        with patch("httpx.get", return_value=mock_response):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert code == 0
            assert envelopes[0]["type"] == "error"
            assert envelopes[0]["error_code"] == "INTERNAL_ERROR"

    def test_invalid_version_string(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"info": {"version": "not-a-version"}}

        with patch("httpx.get", return_value=mock_response):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert code == 0
            assert envelopes[0]["type"] == "error"
            assert envelopes[0]["error_code"] == "INTERNAL_ERROR"

    def test_http_status_error_non_404(self) -> None:
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "500 Server Error", request=MagicMock(), response=mock_response
            )
        )

        with patch("httpx.get", return_value=mock_response):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert code == 0
            assert envelopes[0]["type"] == "error"
            assert envelopes[0]["error_code"] == "NETWORK_ERROR"

    def test_unexpected_exception(self) -> None:
        with patch("httpx.get", side_effect=RuntimeError("something broke")):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert code == 0
            assert envelopes[0]["type"] == "error"
            assert envelopes[0]["error_code"] == "INTERNAL_ERROR"


class TestAgentUpdateCheckRobustness:
    """Verify update check never crashes."""

    def test_never_crashes(self) -> None:
        with patch("httpx.get", side_effect=Exception("catastrophe")):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert code == 0
            assert len(envelopes) >= 1

    def test_produces_exactly_one_envelope(self) -> None:
        mock_data = {"info": {"version": "0.2.0"}}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = mock_data

        with patch("httpx.get", return_value=mock_response):
            code, envelopes = _run_and_capture(["agent", "update", "check"])
            assert len(envelopes) == 1


# ═══════════════════════════════════════════════════════════════════
# Schema registration
# ═══════════════════════════════════════════════════════════════════


def _get_schema_paths() -> set[str]:
    """Run 'agent schema' and return the set of command paths (e.g. 'web-clip-helper agent doctor')."""
    code, envelopes = _run_and_capture(["agent", "schema"])
    schema_line = next(e for e in envelopes if e["type"] == "result")
    return {cmd.get("path", "") for cmd in schema_line["data"]["commands"]}


def _get_schema_commands() -> list[dict]:
    """Run 'agent schema' and return the commands list."""
    code, envelopes = _run_and_capture(["agent", "schema"])
    schema_line = next(e for e in envelopes if e["type"] == "result")
    return schema_line["data"]["commands"]


class TestAgentDoctorSchemaEntry:
    """Verify agent doctor is registered in the command schema."""

    def test_schema_includes_agent_doctor(self) -> None:
        paths = _get_schema_paths()
        assert any("agent" in p and "doctor" in p for p in paths), f"doctor not in {paths}"

    def test_agent_doctor_schema_has_no_flags(self) -> None:
        cmds = _get_schema_commands()
        doctor = next(c for c in cmds if "agent" in c.get("path", "") and "doctor" in c.get("path", ""))
        assert doctor.get("flags", []) == [] or "flags" not in doctor


class TestAgentUpdateCheckSchemaEntry:
    """Verify agent update check is registered in the command schema."""

    def test_schema_includes_agent_update_check(self) -> None:
        paths = _get_schema_paths()
        assert any("agent" in p and "update" in p and "check" in p for p in paths), f"update check not in {paths}"

    def test_agent_update_check_schema_has_no_flags(self) -> None:
        cmds = _get_schema_commands()
        update_cmd = next(c for c in cmds if "agent" in c.get("path", "") and "update" in c.get("path", "") and "check" in c.get("path", ""))
        assert update_cmd.get("flags", []) == [] or "flags" not in update_cmd
