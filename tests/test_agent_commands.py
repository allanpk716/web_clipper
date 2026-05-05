"""Tests for agent auth status, config list/set, debug, cache, feature, metrics, and update commands.

Covers:
- agent auth status: with/without api_key, valid/invalid key, timeout
- agent config list: redaction of sensitive fields, all sections present
- agent config set: valid paths (whitelisted), invalid paths, persistence
- agent debug-last-crash: no crash file, crash file present, invalid JSON
- agent debug-env: structure, sections, redaction, dependencies
- agent cache-clean: missing dir, empty dir, populated dir
- agent feature record: valid entry, empty name/desc rejected, append
- agent feature list: with entries, missing file, empty file
- agent metrics trace: matching crash, no match, empty id, scan extra files
- agent update apply: without --yes, already up-to-date, newer version, pip failure
- Schema registration for all commands
"""

from __future__ import annotations

import json
import os
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


# ── Helpers ─────────────────────────────────────────────────────


def _run_and_capture(args: list[str], run_sdk_cli=None) -> tuple[int, list[dict]]:
    """Invoke CLI and capture SDK Writer JSONL output.
    
    If run_sdk_cli fixture is available, uses it for proper SDK output capture.
    Otherwise falls back to CliRunner + Writer buffer drain.
    """
    set_quiet(False)
    if run_sdk_cli is not None:
        return run_sdk_cli(args)
    # Fallback: drain writer buffer
    from web_clip_helper.app import get_app
    buf = get_app().writer._output
    buf.truncate(0)
    buf.seek(0)
    result = runner.invoke(app, args)
    content = buf.getvalue()
    buf.truncate(0)
    buf.seek(0)
    lines = [l for l in content.strip().splitlines() if l.strip()]
    msgs = [json.loads(l) for l in lines]
    return result.exit_code, msgs


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
            code, envelopes = _run_and_capture(["agent", "auth", "status"])
            assert code == 0

    def test_status_not_configured(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = ""
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config
            code, envelopes = _run_and_capture(["agent", "auth", "status"])
            assert len(envelopes) == 1
            assert envelopes[0]["type"] == "result"
            data = envelopes[0]["data"]
            assert data["status"] == "not_configured"
            assert data["masked_key"] == ""

    def test_stage_field(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = ""
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config
            code, envelopes = _run_and_capture(["agent", "auth", "status"])
            assert envelopes[0]["data"]["stage"] == "agent_auth_status"


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
                code, envelopes = _run_and_capture(["agent", "auth", "status"])
                assert code == 0
                assert len(envelopes) == 1
                assert envelopes[0]["data"]["status"] == "valid"

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
                code, envelopes = _run_and_capture(["agent", "auth", "status"])
                masked = envelopes[0]["data"]["masked_key"]
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
                code, envelopes = _run_and_capture(["agent", "auth", "status"])
                data = envelopes[0]["data"]
                assert "latency_ms" in data
                assert isinstance(data["latency_ms"], (int, float))

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
                code, envelopes = _run_and_capture(["agent", "auth", "status"])
                assert envelopes[0]["tool"] == "web-clip-helper"
                assert "timestamp" in envelopes[0]


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
                code, envelopes = _run_and_capture(["agent", "auth", "status"])
                assert code == 0
                assert len(envelopes) == 1
                assert envelopes[0]["data"]["status"] == "invalid"

    def test_invalid_has_masked_key(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = "sk-bad-key-12345678"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config

            with patch("httpx.post", side_effect=Exception("401")):
                code, envelopes = _run_and_capture(["agent", "auth", "status"])
                data = envelopes[0]["data"]
                assert "masked_key" in data
                assert "sk-bad-key-12345678" not in data["masked_key"]

    def test_invalid_has_detail(self) -> None:
        with patch("web_clip_helper.config.get_config") as mock_cfg:
            config = MagicMock()
            config.llm.api_key = "sk-bad-key-12345678"
            config.llm.base_url = "https://api.example.com/v1"
            config.llm.model = "gpt-4o-mini"
            mock_cfg.return_value = config

            with patch("httpx.post", side_effect=Exception("Connection refused")):
                code, envelopes = _run_and_capture(["agent", "auth", "status"])
                data = envelopes[0]["data"]
                assert "detail" in data
                assert "Connection refused" in data["detail"]


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
                code, envelopes = _run_and_capture(["agent", "auth", "status"])
                data = envelopes[0]["data"]
                assert data["status"] == "invalid"
                detail = data.get("detail", "").lower()
                assert "timed out" in detail or "timeout" in detail


# ═══════════════════════════════════════════════════════════════════
# agent config list
# ═══════════════════════════════════════════════════════════════════


class TestAgentConfigListBasic:
    """Verify basic output structure."""

    def test_exits_zero(self) -> None:
        code, envelopes = _run_and_capture(["agent", "config", "list"])
        assert code == 0

    def test_outputs_result_envelope(self) -> None:
        code, envelopes = _run_and_capture(["agent", "config", "list"])
        result_envs = [e for e in envelopes if e["type"] == "result"]
        assert len(result_envs) >= 1

    def test_has_config_in_data(self) -> None:
        code, envelopes = _run_and_capture(["agent", "config", "list"])
        result_env = next(e for e in envelopes if e["type"] == "result")
        assert "config" in result_env["data"]


class TestAgentConfigListSections:
    """Verify all expected sections are present in config data."""

    def test_llm_section_present(self) -> None:
        code, envelopes = _run_and_capture(["agent", "config", "list"])
        result_env = next(e for e in envelopes if e["type"] == "result")
        assert "llm" in result_env["data"]["config"]

    def test_refresh_section_present(self) -> None:
        code, envelopes = _run_and_capture(["agent", "config", "list"])
        result_env = next(e for e in envelopes if e["type"] == "result")
        assert "refresh" in result_env["data"]["config"]

    def test_prompts_section_present(self) -> None:
        code, envelopes = _run_and_capture(["agent", "config", "list"])
        result_env = next(e for e in envelopes if e["type"] == "result")
        assert "prompts" in result_env["data"]["config"]


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

            code, envelopes = _run_and_capture(["agent", "config", "list"])
            # Verify no plaintext key in the JSON output
            output_str = json.dumps(envelopes)
            assert "sk-super-secret-key-1234567890" not in output_str


# ═══════════════════════════════════════════════════════════════════
# agent config set
# ═══════════════════════════════════════════════════════════════════


class TestAgentConfigSetValid:
    """Setting a valid (whitelisted) config key."""

    def test_set_storage_path(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with patch("web_clip_helper.app.get_config_dir", return_value=Path(td)):
                code, envelopes = _run_and_capture(["agent", "config", "set", "storage_path", str(Path(td) / "clips")])
                assert code == 0
                assert any(e["type"] == "result" for e in envelopes)

    def test_set_db_path(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with patch("web_clip_helper.app.get_config_dir", return_value=Path(td)):
                code, envelopes = _run_and_capture(["agent", "config", "set", "db_path", str(Path(td) / "clips.db")])
                assert code == 0
                assert any(e["type"] == "result" for e in envelopes)


class TestAgentConfigSetInvalidPath:
    """Setting an invalid/unknown config key."""

    def test_invalid_path_exits_nonzero(self) -> None:
        code, envelopes = _run_and_capture(["agent", "config", "set", "nonexistent.path", "value"])
        assert code != 0

    def test_invalid_path_emits_error(self) -> None:
        code, envelopes = _run_and_capture(["agent", "config", "set", "nonexistent.path", "value"])
        error_envs = [e for e in envelopes if e["type"] == "error"]
        assert len(error_envs) == 1
        assert error_envs[0]["error_code"] == "INPUT_INVALID"

    def test_invalid_path_mentions_field(self) -> None:
        code, envelopes = _run_and_capture(["agent", "config", "set", "bad.key", "val"])
        error_env = next(e for e in envelopes if e["type"] == "error")
        assert "bad.key" in error_env["message"]

    def test_random_key_rejected(self) -> None:
        code, envelopes = _run_and_capture(["agent", "config", "set", "llm.nonexistent", "val"])
        assert code != 0

    def test_partial_path_rejected(self) -> None:
        code, envelopes = _run_and_capture(["agent", "config", "set", "llm", "val"])
        assert code != 0


class TestAgentConfigSetAllWhitelistedPaths:
    """Verify every whitelisted path is accepted."""

    @pytest.mark.parametrize("key", [
        "storage_path",
        "db_path",
    ])
    def test_whitelisted_path_accepted(self, key: str) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with patch("web_clip_helper.app.get_config_dir", return_value=Path(td)):
                code, envelopes = _run_and_capture(["agent", "config", "set", key, str(Path(td) / "test")])
                assert code == 0
                assert any(e["type"] == "result" for e in envelopes)


# ═══════════════════════════════════════════════════════════════════
# agent debug-last-crash
# ═══════════════════════════════════════════════════════════════════


class TestAgentDebugLastCrashNoFile:
    """When no crash dump file exists.

    Uses the real sandbox crash_dumps dir because SDK command closures
    capture app.sandbox at import time — patching get_crash_dumps_dir
    has no effect. We move any existing .json files aside and restore
    them after.
    """

    @pytest.fixture(autouse=True)
    def _ensure_no_crash_files(self):
        from web_clip_helper.app import get_crash_dumps_dir
        crash_dir = get_crash_dumps_dir()
        crash_dir.mkdir(parents=True, exist_ok=True)
        # Move existing .json files aside
        json_files = list(crash_dir.glob("*.json"))
        held = []
        for f in json_files:
            backup = f.with_suffix(".json.bak")
            f.rename(backup)
            held.append((f, backup))
        yield
        # Restore
        for orig, backup in held:
            if backup.exists():
                backup.rename(orig)

    def test_no_crash_exits_error(self, run_sdk_cli) -> None:
        """No crash files returns NOT_FOUND error (exit >= 1)."""
        code, envelopes = _run_and_capture(["agent", "debug-last-crash"], run_sdk_cli)
        assert code >= 1

    def test_no_crash_is_not_found(self, run_sdk_cli) -> None:
        """No crash files returns NOT_FOUND error_code in JSONL."""
        code, envelopes = _run_and_capture(["agent", "debug-last-crash"], run_sdk_cli)
        assert any(e["type"] == "error" and e.get("error_code") == "NOT_FOUND" for e in envelopes)


class TestAgentDebugLastCrashWithFile:
    """When a crash dump file exists."""

    def _write_crash_file(self, td: str, data: dict) -> Path:
        crash_dir = Path(td) / "crash_dumps"
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_file = crash_dir / ".last-crash.json"
        crash_file.write_text(json.dumps(data), encoding="utf-8")
        return crash_dir

    def test_outputs_dict_type(self) -> None:
        """Verify debug-last-crash reads and outputs crash data.

        Note: Uses real sandbox path because SDK command closures capture
        the App's sandbox at creation time. We write to the real crash_dumps
        dir and clean up after.
        """
        from web_clip_helper.app import get_crash_dumps_dir
        crash_dir = get_crash_dumps_dir()
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_file = crash_dir / f"test-crash-{id(self)}.json"
        try:
            crash_data = {
                "AGENT_ABORTED": True,
                "source": "exception",
                "exception_type": "ValueError",
                "timestamp": "2026-01-01T00:00:00Z",
            }
            crash_file.write_text(json.dumps(crash_data), encoding="utf-8")
            code, envelopes = _run_and_capture(["agent", "debug-last-crash"])
            assert code == 0, f"Exit code {code}, envelopes: {envelopes}"
            assert len(envelopes) == 1
            assert envelopes[0]["type"] == "result"
            assert envelopes[0]["data"]["crash"]["AGENT_ABORTED"] is True
        finally:
            crash_file.unlink(missing_ok=True)

    def test_crash_data_contents(self) -> None:
        from web_clip_helper.app import get_crash_dumps_dir
        crash_dir = get_crash_dumps_dir()
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_file = crash_dir / f"test-crash-content-{id(self)}.json"
        try:
            crash_data = {
                "AGENT_ABORTED": True,
                "source": "signal",
                "signal": "SIGTERM",
                "timestamp": "2026-01-01T00:00:00Z",
                "trace_id": "abc123",
            }
            crash_file.write_text(json.dumps(crash_data), encoding="utf-8")
            code, envelopes = _run_and_capture(["agent", "debug-last-crash"])
            assert code == 0, f"Exit code {code}"
            data = envelopes[0]["data"]["crash"]
            assert data["AGENT_ABORTED"] is True
            assert data["source"] == "signal"
            assert data["trace_id"] == "abc123"
        finally:
            crash_file.unlink(missing_ok=True)

    def test_crash_stage_field(self) -> None:
        from web_clip_helper.app import get_crash_dumps_dir
        crash_dir = get_crash_dumps_dir()
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_file = crash_dir / f"test-crash-stage-{id(self)}.json"
        try:
            crash_data = {"AGENT_ABORTED": True}
            crash_file.write_text(json.dumps(crash_data), encoding="utf-8")
            code, envelopes = _run_and_capture(["agent", "debug-last-crash"])
            assert code == 0
            # SDK wraps crash data in data.crash with file name
            assert "crash" in envelopes[0]["data"]
            assert "file" in envelopes[0]["data"]
        finally:
            crash_file.unlink(missing_ok=True)


class TestAgentDebugLastCrashInvalidJSON:
    """When the crash file contains invalid JSON."""

    def test_invalid_json_reports_result(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            crash_dir = Path(td) / "crash_dumps"
            crash_dir.mkdir(parents=True, exist_ok=True)
            (crash_dir / ".last-crash.json").write_text("not valid json {{{", encoding="utf-8")
            with patch("web_clip_helper.app.get_crash_dumps_dir", return_value=crash_dir):
                code, envelopes = _run_and_capture(["agent", "debug-last-crash"])
                assert len(envelopes) == 1
                # The command should still produce a valid envelope (error or result)
                assert envelopes[0]["type"] in ("result", "error")


# ═══════════════════════════════════════════════════════════════════
# agent debug-env
# ═══════════════════════════════════════════════════════════════════


class TestAgentDebugEnvStructure:
    """Verify debug-env output structure."""

    def test_exits_zero(self) -> None:
        code, envelopes = _run_and_capture(["agent", "debug-env"])
        assert code == 0

    def test_outputs_result_envelope(self) -> None:
        code, envelopes = _run_and_capture(["agent", "debug-env"])
        assert len(envelopes) == 1
        assert envelopes[0]["type"] == "result"

    def test_has_all_sections(self) -> None:
        code, envelopes = _run_and_capture(["agent", "debug-env"])
        # Data is nested: envelope.data.data (wrapper with stage + inner data)
        inner_data = envelopes[0]["data"]["data"]
        for section in ("python", "os", "tool", "directories", "llm", "dependencies", "env_indicators"):
            assert section in inner_data, f"Missing section: {section}"

    def test_python_section_has_version(self) -> None:
        code, envelopes = _run_and_capture(["agent", "debug-env"])
        python_data = envelopes[0]["data"]["data"]["python"]
        assert "version" in python_data
        assert "implementation" in python_data

    def test_os_section(self) -> None:
        code, envelopes = _run_and_capture(["agent", "debug-env"])
        os_data = envelopes[0]["data"]["data"]["os"]
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

            code, envelopes = _run_and_capture(["agent", "debug-env"])
            output_str = json.dumps(envelopes)
            assert "sk-super-secret-key-that-should-be-redacted" not in output_str

    def test_llm_section_has_api_key_set(self) -> None:
        code, envelopes = _run_and_capture(["agent", "debug-env"])
        llm_data = envelopes[0]["data"]["data"]["llm"]
        assert "api_key_set" in llm_data

    def test_stage_field(self) -> None:
        code, envelopes = _run_and_capture(["agent", "debug-env"])
        assert envelopes[0]["data"]["stage"] == "agent_debug_env"


class TestAgentDebugEnvDependencies:
    """Verify dependency versions are present."""

    def test_httpx_version_present(self) -> None:
        code, envelopes = _run_and_capture(["agent", "debug-env"])
        deps = envelopes[0]["data"]["data"]["dependencies"]
        assert "httpx" in deps
        assert deps["httpx"] != "not_installed"

    def test_typer_version_present(self) -> None:
        code, envelopes = _run_and_capture(["agent", "debug-env"])
        deps = envelopes[0]["data"]["data"]["dependencies"]
        assert "typer" in deps
        assert deps["typer"] != "not_installed"

    def test_yaml_version_present(self) -> None:
        code, envelopes = _run_and_capture(["agent", "debug-env"])
        deps = envelopes[0]["data"]["data"]["dependencies"]
        assert "yaml" in deps


# ═══════════════════════════════════════════════════════════════════
# agent cache-clean
# ═══════════════════════════════════════════════════════════════════


class TestAgentCacheCleanMissingDir:
    """When cache directory doesn't exist."""

    def test_exits_zero(self) -> None:
        with patch("web_clip_helper.app.get_state_dir") as mock_dir:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                mock_dir.return_value = Path(td)
                code, envelopes = _run_and_capture(["agent", "cache-clean"])
                assert code == 0

    def test_already_clean_status(self) -> None:
        with patch("web_clip_helper.app.get_state_dir") as mock_dir:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                mock_dir.return_value = Path(td)
                code, envelopes = _run_and_capture(["agent", "cache-clean"])
                assert len(envelopes) == 1
                assert envelopes[0]["type"] == "result"
                assert envelopes[0]["data"]["cleaned"] == 0


class TestAgentCacheCleanEmptyDir:
    """When cache directory exists but is empty."""

    def test_already_clean_when_empty(self) -> None:
        with patch("web_clip_helper.app.get_state_dir") as mock_dir:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                cache_dir = Path(td) / "cache"
                cache_dir.mkdir()
                mock_dir.return_value = Path(td)
                code, envelopes = _run_and_capture(["agent", "cache-clean"])
                assert envelopes[0]["data"]["cleaned"] == 0


class TestAgentCacheCleanPopulated:
    """When cache directory has files."""

    def test_cleans_files(self) -> None:
        """Cache clean removes files from the SDK sandbox cache dir.

        Uses the real sandbox path because SDK command closures capture
        the App's sandbox at creation time.
        """
        from web_clip_helper.app import get_sandbox
        cache_dir = Path(get_sandbox().cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        # Clean up any existing files first
        for f in cache_dir.iterdir():
            if f.is_file():
                f.unlink()
        (cache_dir / "test1.txt").write_text("hello world", encoding="utf-8")
        (cache_dir / "test2.bin").write_bytes(b"\x00" * 100)
        sub = cache_dir / "subdir"
        sub.mkdir(exist_ok=True)
        (sub / "nested.txt").write_text("nested content", encoding="utf-8")

        code, envelopes = _run_and_capture(["agent", "cache-clean"])
        assert len(envelopes) == 1
        assert envelopes[0]["type"] == "result"
        data = envelopes[0]["data"]
        assert data["cleaned"] >= 1, f"Expected >=1 cleaned, got {data['cleaned']}"

    def test_stage_field(self) -> None:
        from web_clip_helper.app import get_sandbox
        cache_dir = Path(get_sandbox().cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "file.txt").write_text("data", encoding="utf-8")

        code, envelopes = _run_and_capture(["agent", "cache-clean"])
        # SDK cache-clean emits cleaned count
        assert envelopes[0]["data"].get("cleaned") >= 1


# ═══════════════════════════════════════════════════════════════════
# agent feature record
# ═══════════════════════════════════════════════════════════════════


class TestAgentFeatureRecord:
    """Tests for agent feature record --name <n> --desc <d>."""

    def test_record_valid_entry(self) -> None:
        """Record a feature request.

        Uses real sandbox because SDK command closures capture the App's
        sandbox at creation time.
        """
        from web_clip_helper.app import get_state_dir
        state_dir = get_state_dir()
        feature_file = state_dir / "feature_requests.jsonl"
        # Clear pre-existing entries for clean test
        if feature_file.exists():
            backup = feature_file.read_text(encoding="utf-8")
        else:
            backup = ""
        feature_file.unlink(missing_ok=True)

        try:
            code, envelopes = _run_and_capture([
                "agent", "feature", "record",
                "--name", "batch export",
                "--desc", "Export multiple clips as a zip",
            ])
            assert len(envelopes) == 1
            assert envelopes[0]["type"] == "result"
            data = envelopes[0]["data"]
            assert data["status"] == "recorded"
            assert "id" in data

            # Verify file was written
            assert feature_file.exists()
            entries = [json.loads(l) for l in feature_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            assert len(entries) >= 1
            latest = entries[-1]
            assert latest["name"] == "batch export"
            assert latest["description"] == "Export multiple clips as a zip"
        finally:
            # Restore original content
            if backup:
                feature_file.write_text(backup, encoding="utf-8")

    def test_record_empty_name_rejected(self) -> None:
        code, envelopes = _run_and_capture([
            "agent", "feature", "record",
            "--name", "",
            "--desc", "some description",
        ])
        assert any(e["type"] == "error" and e.get("error_code") == "INPUT_INVALID" for e in envelopes)

    def test_record_empty_desc_rejected(self) -> None:
        code, envelopes = _run_and_capture([
            "agent", "feature", "record",
            "--name", "test feature",
            "--desc", "",
        ])
        assert any(e["type"] == "error" and e.get("error_code") == "INPUT_INVALID" for e in envelopes)

    def test_record_multiple_entries_append(self) -> None:
        from web_clip_helper.app import get_state_dir
        state_dir = get_state_dir()
        feature_file = state_dir / "feature_requests.jsonl"
        if feature_file.exists():
            backup = feature_file.read_text(encoding="utf-8")
        else:
            backup = ""
        feature_file.unlink(missing_ok=True)

        try:
            _run_and_capture(["agent", "feature", "record", "--name", "first", "--desc", "First feature"])
            _run_and_capture(["agent", "feature", "record", "--name", "second", "--desc", "Second feature"])

            entries = [json.loads(l) for l in feature_file.read_text(encoding="utf-8").splitlines() if l.strip()]
            assert len(entries) == 2
            assert entries[0]["name"] == "first"
            assert entries[1]["name"] == "second"
        finally:
            if backup:
                feature_file.write_text(backup, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════
# agent feature list
# ═══════════════════════════════════════════════════════════════════


class TestAgentFeatureList:
    """Tests for agent feature list."""

    def test_list_with_entries(self) -> None:
        from web_clip_helper.app import get_state_dir
        state_dir = get_state_dir()
        feature_file = state_dir / "feature_requests.jsonl"
        if feature_file.exists():
            backup = feature_file.read_text(encoding="utf-8")
        else:
            backup = ""

        try:
            entries = [
                {"id": "aaa111", "name": "feat1", "description": "d1", "recorded_at": "2025-01-01T00:00:00.000Z", "tool_version": "0.1.0"},
                {"id": "bbb222", "name": "feat2", "description": "d2", "recorded_at": "2025-01-02T00:00:00.000Z", "tool_version": "0.1.0"},
            ]
            feature_file.write_text(
                "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
                encoding="utf-8",
            )

            code, envelopes = _run_and_capture(["agent", "feature", "list"])
            result_envs = [e for e in envelopes if e["type"] == "result"]
            assert len(result_envs) >= 1
            # The last result envelope should have the total
            last_result = result_envs[-1]
            assert last_result["data"]["total"] == 2
        finally:
            if backup:
                feature_file.write_text(backup, encoding="utf-8")

    def test_list_missing_file(self) -> None:
        from web_clip_helper.app import get_state_dir
        state_dir = get_state_dir()
        feature_file = state_dir / "feature_requests.jsonl"
        if feature_file.exists():
            backup = feature_file.read_text(encoding="utf-8")
        else:
            backup = ""
        feature_file.unlink(missing_ok=True)

        try:
            code, envelopes = _run_and_capture(["agent", "feature", "list"])
            assert len(envelopes) == 1
            assert envelopes[0]["data"]["total"] == 0
        finally:
            if backup:
                feature_file.write_text(backup, encoding="utf-8")

    def test_list_empty_file(self) -> None:
        from web_clip_helper.app import get_state_dir
        state_dir = get_state_dir()
        feature_file = state_dir / "feature_requests.jsonl"
        if feature_file.exists():
            backup = feature_file.read_text(encoding="utf-8")
        else:
            backup = ""

        try:
            feature_file.write_text("", encoding="utf-8")
            code, envelopes = _run_and_capture(["agent", "feature", "list"])
            assert len(envelopes) == 1
            assert envelopes[0]["data"]["total"] == 0
        finally:
            if backup:
                feature_file.write_text(backup, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════
# agent metrics trace
# ═══════════════════════════════════════════════════════════════════


class TestAgentMetricsTrace:
    """Tests for agent metrics trace --id <trace_id>."""

    def test_trace_matching_crash(self) -> None:
        from web_clip_helper.app import get_crash_dumps_dir
        crash_dir = get_crash_dumps_dir()
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_file = crash_dir / f"trace-test-{id(self)}.json"
        try:
            crash_data = {
                "trace_id": "abc123def456",
                "source": "exception",
                "timestamp": "2025-01-15T12:00:00.000Z",
                "flight_context": {"command": "clip"},
            }
            crash_file.write_text(json.dumps(crash_data), encoding="utf-8")

            code, envelopes = _run_and_capture(["agent", "metrics", "trace", "--id", "abc123def456"])
            result_envs = [e for e in envelopes if e["type"] == "result"]
            assert len(result_envs) == 1
            assert result_envs[0]["data"]["data"]["trace_id"] == "abc123def456"
        finally:
            crash_file.unlink(missing_ok=True)

    def test_trace_no_match(self) -> None:
        from web_clip_helper.app import get_crash_dumps_dir
        crash_dir = get_crash_dumps_dir()
        crash_dir.mkdir(parents=True, exist_ok=True)
        crash_file = crash_dir / f"no-match-{id(self)}.json"
        try:
            crash_file.write_text(
                json.dumps({"trace_id": "other_id", "source": "signal"}), encoding="utf-8"
            )

            code, envelopes = _run_and_capture(["agent", "metrics", "trace", "--id", "nonexistent"])
            assert len(envelopes) == 1
            assert envelopes[0]["data"]["status"] == "not_found"
        finally:
            crash_file.unlink(missing_ok=True)

    def test_trace_empty_id_rejected(self) -> None:
        code, envelopes = _run_and_capture(["agent", "metrics", "trace", "--id", ""])
        assert any(e["type"] == "error" and e.get("error_code") == "INPUT_INVALID" for e in envelopes)

    def test_trace_no_crash_dir(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            crash_dir = Path(td) / "crash_dumps"

            with patch("web_clip_helper.app.get_crash_dumps_dir", return_value=crash_dir):
                code, envelopes = _run_and_capture(["agent", "metrics", "trace", "--id", "any_id"])
                assert len(envelopes) == 1
                assert envelopes[0]["data"]["status"] == "not_found"

    def test_trace_scans_additional_json_files(self) -> None:
        from web_clip_helper.app import get_crash_dumps_dir
        crash_dir = get_crash_dumps_dir()
        crash_dir.mkdir(parents=True, exist_ok=True)
        wrong_file = crash_dir / f"wrong-{id(self)}.json"
        target_file = crash_dir / f"target-{id(self)}.json"
        try:
            wrong_file.write_text(
                json.dumps({"trace_id": "wrong_id"}), encoding="utf-8"
            )
            target_file.write_text(
                json.dumps({"trace_id": "target_001", "source": "signal"}), encoding="utf-8"
            )

            code, envelopes = _run_and_capture(["agent", "metrics", "trace", "--id", "target_001"])
            result_envs = [e for e in envelopes if e["type"] == "result"]
            assert len(result_envs) == 1
            assert result_envs[0]["data"]["data"]["trace_id"] == "target_001"
        finally:
            wrong_file.unlink(missing_ok=True)
            target_file.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════
# agent update apply
# ═══════════════════════════════════════════════════════════════════


class TestAgentUpdateApply:
    """Tests for agent update apply --yes."""

    def test_apply_without_yes_flag_rejected(self) -> None:
        code, envelopes = _run_and_capture(["agent", "update", "apply"])
        assert any(e["type"] == "error" and e.get("error_code") == "INPUT_INVALID" for e in envelopes)

    def test_apply_already_up_to_date(self) -> None:
        """When PyPI latest <= current version, status=already_up_to_date."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"info": {"version": "0.1.0"}}

        with patch("httpx.get", return_value=mock_response):
            code, envelopes = _run_and_capture(["agent", "update", "apply", "--yes"])
            result_envs = [e for e in envelopes if e["type"] == "result"]
            assert len(result_envs) == 1
            assert result_envs[0]["data"]["status"] == "already_up_to_date"

    def test_apply_newer_version_triggers_upgrade(self) -> None:
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
            code, envelopes = _run_and_capture(["agent", "update", "apply", "--yes"])
            result_envs = [e for e in envelopes if e["type"] == "result"]
            assert len(result_envs) == 1
            assert result_envs[0]["data"]["status"] == "upgraded"
            assert "old_version" in result_envs[0]["data"]
            assert "new_version" in result_envs[0]["data"]

    def test_apply_pip_failure(self) -> None:
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
            code, envelopes = _run_and_capture(["agent", "update", "apply", "--yes"])
            assert any(e["type"] == "error" for e in envelopes)

    def test_apply_network_error(self) -> None:
        import httpx

        with patch("httpx.get", side_effect=httpx.TimeoutException("timeout")):
            code, envelopes = _run_and_capture(["agent", "update", "apply", "--yes"])
            assert any(e["type"] == "error" and e.get("error_code") == "NETWORK_ERROR" for e in envelopes)

    def test_apply_pypi_404_unpublished(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.get", return_value=mock_response):
            code, envelopes = _run_and_capture(["agent", "update", "apply", "--yes"])
            result_envs = [e for e in envelopes if e["type"] == "result"]
            assert len(result_envs) == 1
            assert result_envs[0]["data"]["status"] == "unpublished"


# ═══════════════════════════════════════════════════════════════════
# Schema registration
# ═══════════════════════════════════════════════════════════════════


class TestAgentSchemaRegistration:
    """Verify commands appear in agent schema output."""

    def _get_schema(self) -> list[dict]:
        code, envelopes = _run_and_capture(["agent", "schema"])
        schema_line = next(e for e in envelopes if e["type"] == "result")
        return schema_line["data"]["commands"]

    def _get_paths(self) -> set[str]:
        return {cmd.get("path", "") for cmd in self._get_schema()}

    def test_schema_includes_auth_status(self) -> None:
        paths = self._get_paths()
        assert any("agent" in p and "auth" in p and "status" in p for p in paths), f"agent auth status not in {paths}"

    def test_schema_includes_agent_config_list(self) -> None:
        paths = self._get_paths()
        assert any("agent" in p and "config" in p and "list" in p for p in paths), f"agent config list not in {paths}"

    def test_schema_includes_agent_config_set(self) -> None:
        paths = self._get_paths()
        assert any("agent" in p and "config" in p and "set" in p for p in paths), f"agent config set not in {paths}"

    def test_auth_status_has_no_flags(self) -> None:
        cmds = self._get_schema()
        cmd = next(c for c in cmds if "agent" in c.get("path", "") and "auth" in c.get("path", "") and "status" in c.get("path", ""))
        assert cmd.get("flags", []) == [] or "flags" not in cmd

    def test_config_list_present_in_schema(self) -> None:
        cmds = self._get_schema()
        config_list_cmds = [c for c in cmds if "agent" in c.get("path", "") and "config" in c.get("path", "") and "list" in c.get("path", "")]
        assert len(config_list_cmds) >= 1, f"agent config list not found in schema"

    def test_config_set_present_in_schema(self) -> None:
        cmds = self._get_schema()
        config_set_cmds = [c for c in cmds if "agent" in c.get("path", "") and "config" in c.get("path", "") and "set" in c.get("path", "")]
        assert len(config_set_cmds) >= 1, f"agent config set not found in schema"


class TestNewCommandsSchemaRegistration:
    """Verify new commands appear in agent schema output."""

    def _get_schema(self) -> list[dict]:
        code, envelopes = _run_and_capture(["agent", "schema"])
        schema_line = next(e for e in envelopes if e["type"] == "result")
        return schema_line["data"]["commands"]

    def _get_paths(self) -> set[str]:
        return {cmd.get("path", "") for cmd in self._get_schema()}

    def test_schema_includes_debug_last_crash(self) -> None:
        paths = self._get_paths()
        assert any("debug-last-crash" in p for p in paths), f"debug-last-crash not in {paths}"

    def test_schema_includes_debug_env(self) -> None:
        paths = self._get_paths()
        assert any("debug-env" in p for p in paths), f"debug-env not in {paths}"

    def test_schema_includes_cache(self) -> None:
        paths = self._get_paths()
        assert any("cache-clean" in p for p in paths), f"cache-clean not in {paths}"

    def test_debug_last_crash_has_no_flags(self) -> None:
        cmds = self._get_schema()
        cmd = next(c for c in cmds if "debug-last-crash" in c.get("path", ""))
        assert cmd.get("flags", []) == [] or "flags" not in cmd

    def test_debug_env_has_redact_flag(self) -> None:
        cmds = self._get_schema()
        cmd = next(c for c in cmds if "debug-env" in c.get("path", ""))
        flag_names = {f.get("name") for f in cmd.get("flags", [])}
        assert "redact" in flag_names

    def test_cache_clean_has_no_flags(self) -> None:
        cmds = self._get_schema()
        cmd = next(c for c in cmds if "cache-clean" in c.get("path", ""))
        assert cmd.get("flags", []) == [] or "flags" not in cmd


class TestT03SchemaRegistration:
    """Verify T03 new commands appear in agent schema output."""

    def _get_schema(self) -> list[dict]:
        code, envelopes = _run_and_capture(["agent", "schema"])
        schema_line = next(e for e in envelopes if e["type"] == "result")
        return schema_line["data"]["commands"]

    def _get_paths(self) -> set[str]:
        return {cmd.get("path", "") for cmd in self._get_schema()}

    def test_schema_includes_feature_record(self) -> None:
        paths = self._get_paths()
        assert any("feature" in p and "record" in p for p in paths), f"feature record not in {paths}"

    def test_schema_includes_feature_list(self) -> None:
        paths = self._get_paths()
        assert any("feature" in p and "list" in p for p in paths), f"feature list not in {paths}"

    def test_schema_includes_metrics_trace(self) -> None:
        paths = self._get_paths()
        assert any("metrics" in p and "trace" in p for p in paths), f"metrics trace not in {paths}"

    def test_schema_includes_update_apply(self) -> None:
        paths = self._get_paths()
        assert any("update" in p and "apply" in p for p in paths), f"update apply not in {paths}"

    def test_feature_record_has_name_flag(self) -> None:
        cmds = self._get_schema()
        cmd = next(c for c in cmds if "feature" in c.get("path", "") and "record" in c.get("path", ""))
        flag_names = {f.get("name") for f in cmd.get("flags", [])}
        assert "name" in flag_names

    def test_feature_list_has_no_flags(self) -> None:
        cmds = self._get_schema()
        cmd = next(c for c in cmds if "feature" in c.get("path", "") and "list" in c.get("path", ""))
        assert cmd.get("flags", []) == [] or "flags" not in cmd

    def test_metrics_trace_has_id_flag(self) -> None:
        cmds = self._get_schema()
        cmd = next(c for c in cmds if "metrics" in c.get("path", "") and "trace" in c.get("path", ""))
        flag_names = {f.get("name") for f in cmd.get("flags", [])}
        assert "id" in flag_names

    def test_update_apply_has_yes_flag(self) -> None:
        cmds = self._get_schema()
        cmd = next(c for c in cmds if "update" in c.get("path", "") and "apply" in c.get("path", ""))
        flag_names = {f.get("name") for f in cmd.get("flags", [])}
        assert "yes" in flag_names

    def test_agent_commands_count(self) -> None:
        """Verify agent commands exist in the schema output."""
        cmds = self._get_schema()
        # Count commands whose path contains 'agent'
        agent_cmds = [c for c in cmds if "agent" in c.get("path", "")]
        # Should have multiple agent commands
        assert len(agent_cmds) >= 5, f"Expected >= 5 agent commands, got {len(agent_cmds)}: {agent_cmds}"
