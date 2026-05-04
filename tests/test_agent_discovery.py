"""Tests for agent namespace discovery commands (info, schema, errors) and new JSONL types."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from web_clip_helper.agent_schema import get_commands_schema
from web_clip_helper.cli import app
from web_clip_helper.error_codes import ErrorCode, EXIT_CODE_MAP
from web_clip_helper.output import _VALID_TYPES


runner = CliRunner()


# ── JSONL type whitelist ──────────────────────────────────────────


class TestValidTypes:
    """Verify that the new JSONL type values are in the whitelist."""

    def test_schema_type_allowed(self) -> None:
        assert "schema" in _VALID_TYPES

    def test_dict_type_allowed(self) -> None:
        assert "dict" in _VALID_TYPES

    def test_diagnostics_type_allowed(self) -> None:
        assert "diagnostics" in _VALID_TYPES

    def test_existing_types_preserved(self) -> None:
        for t in ("progress", "result", "error", "warning", "help"):
            assert t in _VALID_TYPES


# ── agent info ────────────────────────────────────────────────────


class TestAgentInfo:
    """Verify agent info command output structure."""

    def test_info_exits_zero(self) -> None:
        result = runner.invoke(app, ["agent", "info"])
        assert result.exit_code == 0

    def test_info_outputs_valid_jsonl(self) -> None:
        result = runner.invoke(app, ["agent", "info"])
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        assert len(lines) >= 1
        data = json.loads(lines[0])
        assert data["type"] == "result"

    def test_info_contains_required_fields(self) -> None:
        result = runner.invoke(app, ["agent", "info"])
        data = json.loads(result.output.strip().splitlines()[0])
        assert data["name"] == "web-clip-helper"
        assert "version" in data
        assert isinstance(data["version"], str) and len(data["version"]) > 0
        assert "description" in data
        assert "docs" in data

    def test_info_version_matches_package(self) -> None:
        from web_clip_helper import __version__

        result = runner.invoke(app, ["agent", "info"])
        data = json.loads(result.output.strip().splitlines()[0])
        assert data["version"] == __version__

    def test_info_includes_envelope_fields(self) -> None:
        result = runner.invoke(app, ["agent", "info"])
        data = json.loads(result.output.strip().splitlines()[0])
        assert "version" in data  # envelope version
        assert data["tool"] == "web-clip-helper"
        assert "timestamp" in data
        assert "trace_id" in data


# ── agent errors ──────────────────────────────────────────────────


class TestAgentErrors:
    """Verify agent errors command output structure."""

    def test_errors_exits_zero(self) -> None:
        result = runner.invoke(app, ["agent", "errors"])
        assert result.exit_code == 0

    def test_errors_outputs_all_codes(self) -> None:
        result = runner.invoke(app, ["agent", "errors"])
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        # Should have one JSONL line per error code
        all_codes = ErrorCode.all_codes()
        assert len(lines) == len(all_codes)

    def test_errors_each_line_is_dict_type(self) -> None:
        result = runner.invoke(app, ["agent", "errors"])
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        for line in lines:
            data = json.loads(line)
            assert data["type"] == "dict"

    def test_errors_contains_required_fields_per_code(self) -> None:
        result = runner.invoke(app, ["agent", "errors"])
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        for line in lines:
            data = json.loads(line)
            payload = data["data"]
            assert "error_code" in payload
            assert "exit_code" in payload
            assert "description" in payload
            assert "guidance" in payload

    def test_errors_exit_codes_match_map(self) -> None:
        result = runner.invoke(app, ["agent", "errors"])
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        for line in lines:
            data = json.loads(line)
            payload = data["data"]
            expected_exit = EXIT_CODE_MAP.get(payload["error_code"], 1)
            assert payload["exit_code"] == expected_exit

    def test_errors_guidance_non_empty(self) -> None:
        result = runner.invoke(app, ["agent", "errors"])
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        for line in lines:
            data = json.loads(line)
            payload = data["data"]
            assert len(payload["guidance"]) > 0

    def test_errors_covers_all_known_codes(self) -> None:
        result = runner.invoke(app, ["agent", "errors"])
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        output_codes = set()
        for line in lines:
            data = json.loads(line)
            output_codes.add(data["data"]["error_code"])
        expected_codes = set(ErrorCode.all_codes().keys())
        assert output_codes == expected_codes


# ── ErrorCode.guidance() ──────────────────────────────────────────


class TestErrorCodeGuidance:
    """Verify ErrorCode.guidance() returns meaningful text."""

    def test_guidance_for_known_code(self) -> None:
        g = ErrorCode.guidance("INPUT_INVALID")
        assert isinstance(g, str) and len(g) > 0

    def test_guidance_for_unknown_code(self) -> None:
        g = ErrorCode.guidance("NONEXISTENT_CODE")
        assert isinstance(g, str) and len(g) > 0

    def test_all_codes_have_guidance(self) -> None:
        for code in ErrorCode.all_codes():
            g = ErrorCode.guidance(code)
            assert len(g) > 0, f"Missing guidance for {code}"

    def test_describe_backward_compatible(self) -> None:
        """Ensure describe() still works as before."""
        desc = ErrorCode.describe("INPUT_INVALID")
        assert desc == "Invalid or missing input argument"

    def test_all_codes_backward_compatible(self) -> None:
        """Ensure all_codes() still returns code → description dict."""
        codes = ErrorCode.all_codes()
        assert isinstance(codes, dict)
        assert "INPUT_INVALID" in codes
        assert len(codes) >= 12


# ── agent schema ──────────────────────────────────────────────────


class TestAgentSchema:
    """Verify agent schema command output structure."""

    def test_schema_exits_zero(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        assert result.exit_code == 0

    def test_schema_outputs_valid_jsonl(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        lines = [l for l in result.output.strip().splitlines() if l.strip()]
        assert len(lines) >= 1
        data = json.loads(lines[0])
        assert data["type"] == "schema"

    def test_schema_contains_commands_array(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        assert "data" in data
        assert "commands" in data["data"]
        assert isinstance(data["data"]["commands"], list)

    def test_schema_each_command_has_required_fields(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        for cmd in data["data"]["commands"]:
            assert "name" in cmd, f"Missing 'name' in command: {cmd}"
            assert "description" in cmd, f"Missing 'description' in command: {cmd}"
            assert "is_idempotent" in cmd, f"Missing 'is_idempotent' in command: {cmd}"
            assert isinstance(cmd["is_idempotent"], bool), f"is_idempotent not bool in {cmd['name']}"
            assert "parameters" in cmd, f"Missing 'parameters' in command: {cmd}"
            assert isinstance(cmd["parameters"], list), f"parameters not list in {cmd['name']}"

    def test_schema_each_parameter_has_required_fields(self) -> None:
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        for cmd in data["data"]["commands"]:
            for param in cmd["parameters"]:
                assert "name" in param, f"Missing 'name' in param of {cmd['name']}: {param}"
                assert "type" in param, f"Missing 'type' in param of {cmd['name']}: {param}"
                assert "required" in param, f"Missing 'required' in param of {cmd['name']}: {param}"
                assert isinstance(param["required"], bool), f"required not bool in {cmd['name']}.{param['name']}"
                assert "description" in param, f"Missing 'description' in param of {cmd['name']}: {param}"

    def test_schema_covers_core_commands(self) -> None:
        """Verify all core business commands are present."""
        core_commands = {"clip", "list", "get", "search", "tags", "delete", "update", "refresh", "version"}
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        names = {cmd["name"] for cmd in data["data"]["commands"]}
        missing = core_commands - names
        assert not missing, f"Missing core commands: {missing}"

    def test_schema_covers_config_commands(self) -> None:
        """Verify config sub-commands are present."""
        config_commands = {"config list", "config get", "config set", "config prompt test"}
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        names = {cmd["name"] for cmd in data["data"]["commands"]}
        missing = config_commands - names
        assert not missing, f"Missing config commands: {missing}"

    def test_schema_covers_report_commands(self) -> None:
        """Verify report sub-commands are present."""
        report_commands = {"report submit", "report list", "report show"}
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        names = {cmd["name"] for cmd in data["data"]["commands"]}
        missing = report_commands - names
        assert not missing, f"Missing report commands: {missing}"

    def test_schema_covers_agent_commands(self) -> None:
        """Verify agent sub-commands are present."""
        agent_commands = {"agent info", "agent schema", "agent errors"}
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        names = {cmd["name"] for cmd in data["data"]["commands"]}
        missing = agent_commands - names
        assert not missing, f"Missing agent commands: {missing}"

    def test_schema_clip_is_not_idempotent(self) -> None:
        """Clip is intentionally non-idempotent (duplicate detection)."""
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        clip_cmd = next(c for c in data["data"]["commands"] if c["name"] == "clip")
        assert clip_cmd["is_idempotent"] is False

    def test_schema_report_submit_is_not_idempotent(self) -> None:
        """Report submit creates a new file each time."""
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        submit_cmd = next(c for c in data["data"]["commands"] if c["name"] == "report submit")
        assert submit_cmd["is_idempotent"] is False

    def test_schema_read_commands_are_idempotent(self) -> None:
        """Read-only commands should be marked idempotent."""
        read_commands = {"list", "get", "search", "tags", "version", "report list", "report show"}
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        for cmd in data["data"]["commands"]:
            if cmd["name"] in read_commands:
                assert cmd["is_idempotent"] is True, f"{cmd['name']} should be idempotent"

    def test_schema_includes_envelope_fields(self) -> None:
        """Verify JSONL envelope fields are present."""
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        assert data["tool"] == "web-clip-helper"
        assert "timestamp" in data
        assert "trace_id" in data

    def test_schema_has_stage_field(self) -> None:
        """Verify stage field identifies the command."""
        result = runner.invoke(app, ["agent", "schema"])
        data = json.loads(result.output.strip().splitlines()[0])
        assert data.get("stage") == "agent_schema"


# ── get_commands_schema (unit tests) ──────────────────────────────


class TestGetCommandsSchema:
    """Unit tests for the schema data builder."""

    def test_returns_list(self) -> None:
        schema = get_commands_schema()
        assert isinstance(schema, list)

    def test_all_entries_have_names(self) -> None:
        schema = get_commands_schema()
        for cmd in schema:
            assert isinstance(cmd["name"], str) and len(cmd["name"]) > 0

    def test_all_descriptions_non_empty(self) -> None:
        schema = get_commands_schema()
        for cmd in schema:
            assert isinstance(cmd["description"], str) and len(cmd["description"]) > 0

    def test_at_least_18_commands(self) -> None:
        """Verify comprehensive coverage of all business commands."""
        schema = get_commands_schema()
        assert len(schema) >= 18

    def test_no_duplicate_names(self) -> None:
        schema = get_commands_schema()
        names = [cmd["name"] for cmd in schema]
        assert len(names) == len(set(names)), f"Duplicate command names: {names}"

    def test_optional_default_field_type(self) -> None:
        """When present, default field should have a sensible type."""
        schema = get_commands_schema()
        for cmd in schema:
            for param in cmd["parameters"]:
                if "default" in param:
                    assert isinstance(param["default"], (str, int, bool, type(None))), \
                        f"Unexpected default type in {cmd['name']}.{param['name']}: {type(param['default'])}"
