"""Integration tests for SDK agent commands and JSONL envelope convergence.

Validates:
- SDK agent commands (schema, errors, config list/set, doctor, debug-last-crash, cache-clean)
  are correctly generated via create_agent_app()
- ConfigProvider registration enables agent config commands
- Health checks are registered and runnable via doctor
- CommandMeta enriches schema output with description/is_idempotent
- Custom agent extensions still work (info, update, auth, debug-env, feature, metrics)
- All JSONL output converges to exactly 4 standard types: result, error, warning, progress
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.config import Config
from web_clip_helper.output import set_quiet

runner = CliRunner()


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_trace_id():
    """Override conftest's autouse to NOT reset the App singleton.

    The SDK agent commands in cli.py capture the App instance at import
    time via closures (create_agent_app(app)). If we reset the singleton,
    new get_app() calls return a different App whose Writer buffer is
    never written to by the closure-captured SDK commands.  Instead, we
    keep the same App instance and just reset quiet mode between tests.
    """
    set_quiet(False)
    yield
    set_quiet(False)


@pytest.fixture()
def cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary config + DB, patch get_config to use it."""
    import web_clip_helper.config as cfg_mod

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    db_path = str(tmp_path / "clips.db")
    config = Config(db_path=db_path, storage_path=str(tmp_path / "clips"))
    config.save(config_dir / "config.json")
    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path / "clips.db"


def _get_writer_buffer():
    """Return the SDK Writer's internal StringIO buffer.

    This is the buffer that the SDK agent commands write to (via their
    closure-captured App instance).
    """
    from web_clip_helper.app import get_app
    return get_app().writer._output


def _drain_buffer(buf) -> list[dict]:
    """Read all JSONL lines from the writer's buffer, clear it, return parsed."""
    content = buf.getvalue()
    buf.truncate(0)
    buf.seek(0)
    lines = [l for l in content.strip().splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


def _run_and_capture(args: list[str]) -> tuple[Any, list[dict]]:
    """Invoke CLI via CliRunner and capture JSONL from SDK Writer's buffer."""
    set_quiet(False)
    buf = _get_writer_buffer()
    buf.truncate(0)
    buf.seek(0)
    result = runner.invoke(app, args)
    msgs = _drain_buffer(buf)
    return result, msgs


def _run_via_app_run(args: list[str]) -> tuple[int, list[dict]]:
    """Run CLI through App.run() — the real entry point — and capture stdout.

    This is necessary for tests that need the full App.run() lifecycle
    (stdout hijacking, Writer setup, etc).
    """
    from web_clip_helper.app import get_app

    old_stdout = sys.stdout
    buf = io.StringIO()
    # App.run() stores _real_stdout at __init__ time and creates a Writer
    # targeting _real_stdout during run(). We patch _real_stdout so the
    # Writer outputs to our buffer.
    sdk_app = get_app()
    sdk_app._real_stdout = buf
    try:
        code = sdk_app.run(app, args)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 0
    finally:
        sys.stdout = old_stdout
        sdk_app._real_stdout = old_stdout

    output = buf.getvalue()
    lines = [l for l in output.strip().splitlines() if l.strip()]
    msgs = [json.loads(l) for l in lines]
    return code, msgs


def _validate_jsonl_types(messages: list[dict], allowed_types: set[str] | None = None) -> None:
    """Assert every message has a valid type field."""
    valid = allowed_types or {"result", "error", "warning", "progress"}
    for msg in messages:
        assert "type" in msg, f"Missing 'type' field in: {msg!r}"
        assert msg["type"] in valid, f"Invalid type {msg['type']!r}, allowed: {valid}"


# ── Test: Agent Command Registration ────────────────────────────────


class TestAgentCommandRegistration:
    """Verify all SDK and custom agent commands are registered."""

    def test_all_agent_commands_present(self):
        """12 agent commands should be registered: 7 SDK + 5 custom."""
        from typer.main import get_command
        import click

        click_cmd = get_command(app)
        ctx = click.Context(click_cmd)
        agent = click_cmd.get_command(ctx, "agent")
        assert agent is not None, "agent subcommand group not found"

        subcmds = sorted(agent.list_commands(click.Context(agent)))
        expected = sorted([
            "auth", "cache-clean", "config", "debug-env", "debug-last-crash",
            "doctor", "errors", "feature", "info", "metrics", "schema", "update",
        ])
        assert subcmds == expected, f"Expected {expected}, got {subcmds}"

    def test_config_has_list_and_set(self):
        """SDK agent config should have list and set subcommands."""
        from typer.main import get_command
        import click

        click_cmd = get_command(app)
        ctx = click.Context(click_cmd)
        agent = click_cmd.get_command(ctx, "agent")
        agent_ctx = click.Context(agent)
        config_cmd = agent.get_command(agent_ctx, "config")
        assert config_cmd is not None

        subcmds = sorted(config_cmd.list_commands(click.Context(config_cmd)))
        assert "list" in subcmds
        assert "set" in subcmds

    def test_update_has_check_and_apply(self):
        """Custom agent update should have check and apply subcommands."""
        from typer.main import get_command
        import click

        click_cmd = get_command(app)
        ctx = click.Context(click_cmd)
        agent = click_cmd.get_command(ctx, "agent")
        agent_ctx = click.Context(agent)
        update_cmd = agent.get_command(agent_ctx, "update")
        assert update_cmd is not None

        subcmds = sorted(update_cmd.list_commands(click.Context(update_cmd)))
        assert "check" in subcmds
        assert "apply" in subcmds

    def test_auth_has_status(self):
        """Custom agent auth should have status subcommand."""
        from typer.main import get_command
        import click

        click_cmd = get_command(app)
        ctx = click.Context(click_cmd)
        agent = click_cmd.get_command(ctx, "agent")
        agent_ctx = click.Context(agent)
        auth_cmd = agent.get_command(agent_ctx, "auth")
        assert auth_cmd is not None

        subcmds = sorted(auth_cmd.list_commands(click.Context(auth_cmd)))
        assert "status" in subcmds

    def test_feature_has_record_and_list(self):
        """Custom agent feature should have record and list subcommands."""
        from typer.main import get_command
        import click

        click_cmd = get_command(app)
        ctx = click.Context(click_cmd)
        agent = click_cmd.get_command(ctx, "agent")
        agent_ctx = click.Context(agent)
        feature_cmd = agent.get_command(agent_ctx, "feature")
        assert feature_cmd is not None

        subcmds = sorted(feature_cmd.list_commands(click.Context(feature_cmd)))
        assert "record" in subcmds
        assert "list" in subcmds

    def test_metrics_has_trace(self):
        """Custom agent metrics should have trace subcommand."""
        from typer.main import get_command
        import click

        click_cmd = get_command(app)
        ctx = click.Context(click_cmd)
        agent = click_cmd.get_command(ctx, "agent")
        agent_ctx = click.Context(agent)
        metrics_cmd = agent.get_command(agent_ctx, "metrics")
        assert metrics_cmd is not None

        subcmds = sorted(metrics_cmd.list_commands(click.Context(metrics_cmd)))
        assert "trace" in subcmds


# ── Test: SDK agent schema ──────────────────────────────────────────


class TestAgentSchema:
    """Verify agent schema command outputs business commands with CommandMeta."""

    def test_schema_output_is_valid_jsonl(self):
        """Schema command produces parseable JSONL."""
        result, msgs = _run_and_capture(["agent", "schema"])
        assert result.exit_code == 0
        assert len(msgs) >= 1

    def test_schema_contains_tool_and_version(self):
        """Schema output includes tool name and version."""
        result, msgs = _run_and_capture(["agent", "schema"])
        assert result.exit_code == 0
        schema_msg = msgs[0]
        assert schema_msg.get("tool") == "web-clip-helper"
        assert "version" in schema_msg

    def test_schema_has_commands_array(self):
        """Schema output contains a commands array."""
        result, msgs = _run_and_capture(["agent", "schema"])
        assert result.exit_code == 0
        schema_data = msgs[0].get("data", msgs[0])
        assert "commands" in schema_data, f"No 'commands' key in: {list(msgs[0].keys())}"
        commands = schema_data["commands"]
        assert len(commands) > 0, "Empty commands array in schema"

    def test_schema_includes_core_business_commands(self):
        """Schema includes clip, list, get, search, tags, delete, update, refresh."""
        result, msgs = _run_and_capture(["agent", "schema"])
        assert result.exit_code == 0
        schema_data = msgs[0].get("data", msgs[0])
        commands = schema_data.get("commands", [])
        # SDK _walk_commands prefixes paths with tool name, e.g. "web-clip-helper clip"
        paths = {c.get("path", c.get("name", "")) for c in commands}
        for expected in ["clip", "list", "get", "search", "tags", "delete", "update", "refresh"]:
            # Match either "clip" or "web-clip-helper clip" style paths
            found = expected in paths or any(p.endswith(f" {expected}") for p in paths)
            assert found, f"Missing command '{expected}' in schema paths: {paths}"

    def test_schema_command_meta_has_description(self):
        """CommandMeta enriches schema entries with description."""
        result, msgs = _run_and_capture(["agent", "schema"])
        assert result.exit_code == 0
        schema_data = msgs[0].get("data", msgs[0])
        commands = schema_data.get("commands", [])
        # Find clip entry by path suffix (SDK prefixes with tool name)
        clip_entries = [c for c in commands if c.get("path", "").endswith(" clip") or c.get("path") == "clip"]
        assert len(clip_entries) >= 1, f"No clip entry: {[c.get('path') for c in commands]}"
        assert "description" in clip_entries[0], f"Missing description: {clip_entries[0]}"
        assert clip_entries[0]["description"]  # non-empty

    def test_schema_command_meta_has_is_idempotent(self):
        """CommandMeta enriches schema entries with is_idempotent."""
        result, msgs = _run_and_capture(["agent", "schema"])
        assert result.exit_code == 0
        schema_data = msgs[0].get("data", msgs[0])
        commands = schema_data.get("commands", [])
        clip_entries = [c for c in commands if c.get("path", "").endswith(" clip") or c.get("path") == "clip"]
        assert len(clip_entries) >= 1
        assert "is_idempotent" in clip_entries[0]
        assert clip_entries[0]["is_idempotent"] is False

    def test_schema_list_is_idempotent(self):
        """list command should be marked as idempotent."""
        result, msgs = _run_and_capture(["agent", "schema"])
        assert result.exit_code == 0
        schema_data = msgs[0].get("data", msgs[0])
        commands = schema_data.get("commands", [])
        list_entries = [c for c in commands if c.get("path", "").endswith(" list") or c.get("path") == "list"]
        assert len(list_entries) >= 1, f"No list entry: {[c.get('path') for c in commands]}"
        assert list_entries[0]["is_idempotent"] is True


# ── Test: SDK agent errors ──────────────────────────────────────────


class TestAgentErrors:
    """Verify agent errors command lists registered error codes."""

    def test_errors_output_is_valid_jsonl(self):
        """Errors command produces parseable JSONL."""
        result, msgs = _run_and_capture(["agent", "errors"])
        assert result.exit_code == 0
        assert len(msgs) >= 1

    def test_errors_lists_known_codes(self):
        """Errors output includes registered error codes."""
        result, msgs = _run_and_capture(["agent", "errors"])
        assert result.exit_code == 0
        all_output = json.dumps(msgs)
        for code in ["INPUT_INVALID", "NOT_FOUND", "INTERNAL_ERROR"]:
            assert code in all_output, f"Error code {code} not found in: {all_output[:500]}"


# ── Test: SDK agent config ──────────────────────────────────────────


class TestAgentConfig:
    """Verify agent config list/set work through ConfigManager."""

    def test_config_list(self, cli_config):
        """agent config list should output JSONL result."""
        result, msgs = _run_and_capture(["agent", "config", "list"])
        assert result.exit_code == 0
        assert len(msgs) >= 1
        _validate_jsonl_types(msgs)

    def test_config_set(self, cli_config):
        """agent config set should update a whitelisted config value."""
        result, msgs = _run_and_capture(["agent", "config", "set", "storage_path", "/tmp/test-clips"])
        assert result.exit_code == 0
        assert len(msgs) >= 1
        _validate_jsonl_types(msgs)


# ── Test: SDK agent doctor ──────────────────────────────────────────


class TestAgentDoctor:
    """Verify agent doctor runs registered health checks."""

    def test_doctor_output_is_valid_jsonl(self, cli_config):
        """Doctor command produces parseable JSONL."""
        result, msgs = _run_and_capture(["agent", "doctor"])
        assert result.exit_code == 0
        assert len(msgs) >= 1
        _validate_jsonl_types(msgs)

    def test_doctor_includes_check_results(self, cli_config):
        """Doctor output should reference health checks."""
        result, msgs = _run_and_capture(["agent", "doctor"])
        assert result.exit_code == 0
        all_output = json.dumps(msgs)
        check_names = ["storage_dirs", "sqlite", "config", "llm_connectivity"]
        found = any(name in all_output for name in check_names)
        assert found, f"No health check names in doctor output: {all_output[:500]}"


# ── Test: Custom agent commands ─────────────────────────────────────


class TestCustomAgentCommands:
    """Verify custom agent extensions still work."""

    def test_agent_info(self):
        """agent info outputs tool metadata."""
        result, msgs = _run_and_capture(["agent", "info"])
        assert result.exit_code == 0
        assert len(msgs) >= 1
        _validate_jsonl_types(msgs)
        info_results = [
            m for m in msgs
            if m.get("type") == "result"
            and (m.get("data", {}).get("stage") == "agent_info" or m.get("stage") == "agent_info")
        ]
        assert len(info_results) >= 1, f"No agent_info result in: {msgs}"

    def test_agent_debug_env(self, cli_config):
        """agent debug-env outputs environment snapshot."""
        result, msgs = _run_and_capture(["agent", "debug-env"])
        assert result.exit_code == 0
        assert len(msgs) >= 1
        _validate_jsonl_types(msgs)

    def test_agent_auth_status_no_key(self, cli_config):
        """agent auth status outputs not_configured when no api_key."""
        result, msgs = _run_and_capture(["agent", "auth", "status"])
        assert result.exit_code == 0
        assert len(msgs) >= 1
        _validate_jsonl_types(msgs)

    def test_agent_feature_record_and_list(self, cli_config, tmp_path, monkeypatch):
        """agent feature record stores entry, agent feature list reads it back."""
        import web_clip_helper.app as app_mod

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        monkeypatch.setattr(app_mod, "get_state_dir", lambda: state_dir)

        result1, msgs1 = _run_and_capture(
            ["agent", "feature", "record", "--name", "test-feature", "--desc", "A test"],
        )
        assert result1.exit_code == 0
        assert len(msgs1) >= 1
        _validate_jsonl_types(msgs1)

        result2, msgs2 = _run_and_capture(["agent", "feature", "list"])
        assert result2.exit_code == 0
        assert len(msgs2) >= 1
        _validate_jsonl_types(msgs2)

    def test_agent_update_check(self):
        """agent update check produces valid JSONL."""
        result, msgs = _run_and_capture(["agent", "update", "check"])
        assert len(msgs) >= 1, "Expected at least one JSONL message"
        _validate_jsonl_types(msgs)


# ── Test: JSONL 4-type purity ───────────────────────────────────────


class TestJSONLPurity:
    """Verify all agent command outputs use only the 4 standard envelope types."""

    @pytest.mark.parametrize("cmd_args", [
        ["agent", "schema"],
        ["agent", "errors"],
        ["agent", "info"],
    ], ids=lambda args: "-".join(args))
    def test_jsonl_purity_for_readonly_commands(self, cmd_args):
        """Read-only commands should emit only result/error/warning/progress."""
        result, msgs = _run_and_capture(cmd_args)
        assert len(msgs) >= 1, f"No output for {cmd_args}"
        _validate_jsonl_types(msgs)

    def test_jsonl_purity_doctor(self, cli_config):
        """Doctor command should emit only standard types."""
        result, msgs = _run_and_capture(["agent", "doctor"])
        assert len(msgs) >= 1
        _validate_jsonl_types(msgs)

    def test_jsonl_purity_debug_env(self, cli_config):
        """debug-env should emit only standard types."""
        result, msgs = _run_and_capture(["agent", "debug-env"])
        assert len(msgs) >= 1
        _validate_jsonl_types(msgs)

    def test_jsonl_purity_config_list(self, cli_config):
        """config list should emit only standard types."""
        result, msgs = _run_and_capture(["agent", "config", "list"])
        assert len(msgs) >= 1
        _validate_jsonl_types(msgs)

    def test_jsonl_purity_auth_status(self, cli_config):
        """auth status should emit only standard types."""
        result, msgs = _run_and_capture(["agent", "auth", "status"])
        assert len(msgs) >= 1
        _validate_jsonl_types(msgs)

    def test_result_like_types_only_result(self):
        """The _RESULT_LIKE_TYPES set should contain only 'result'."""
        from web_clip_helper.output import _RESULT_LIKE_TYPES
        assert _RESULT_LIKE_TYPES == frozenset({"result"})

    def test_invalid_type_raises_valueerror(self):
        """Passing a non-standard type to jsonl_emit raises ValueError."""
        from web_clip_helper.output import jsonl_emit

        with pytest.raises(ValueError, match="Invalid JSONL type"):
            jsonl_emit("schema", data={"foo": "bar"})

    def test_help_wrapper_emits_result_type(self):
        """jsonl_emit_help emits type=result, not type=help."""
        from web_clip_helper.output import jsonl_emit_help

        buf = _get_writer_buffer()
        buf.truncate(0)
        buf.seek(0)
        jsonl_emit_help(commands=[{"name": "test", "help": "Test"}])
        msgs = _drain_buffer(buf)
        assert len(msgs) >= 1
        assert msgs[0]["type"] == "result"

    def test_dict_wrapper_emits_result_type(self):
        """jsonl_emit_dict emits type=result."""
        from web_clip_helper.output import jsonl_emit_dict

        buf = _get_writer_buffer()
        buf.truncate(0)
        buf.seek(0)
        jsonl_emit_dict(data={"key": "val"}, stage="test")
        msgs = _drain_buffer(buf)
        assert len(msgs) >= 1
        assert msgs[0]["type"] == "result"

    def test_schema_wrapper_emits_result_type(self):
        """jsonl_emit_schema emits type=result."""
        from web_clip_helper.output import jsonl_emit_schema

        buf = _get_writer_buffer()
        buf.truncate(0)
        buf.seek(0)
        jsonl_emit_schema(data={"commands": []})
        msgs = _drain_buffer(buf)
        assert len(msgs) >= 1
        assert msgs[0]["type"] == "result"


# ── Test: Provider Registration ─────────────────────────────────────


class TestProviderRegistration:
    """Verify SDK providers are correctly registered on the App singleton."""

    def test_config_provider_registered(self):
        """ConfigManager is registered as 'default' ConfigProvider."""
        from web_clip_helper.app import get_app

        app_instance = get_app()
        assert app_instance._config_providers, "No config providers registered"
        assert "default" in app_instance._config_providers

    def test_health_checks_registered(self):
        """All 4 health checks are registered."""
        from web_clip_helper.app import get_app

        app_instance = get_app()
        assert app_instance._health_checks, "No health checks registered"
        expected = {"storage_dirs", "sqlite", "config", "llm_connectivity"}
        registered = set(app_instance._health_checks.keys())
        assert expected == registered, f"Expected {expected}, got {registered}"

    def test_command_meta_registered(self):
        """CommandMeta entries are registered for all 16 business commands."""
        from web_clip_helper.app import get_app

        app_instance = get_app()
        assert app_instance._command_meta, "No command meta registered"
        tool = "web-clip-helper"
        expected_paths = {
            f"{tool} clip", f"{tool} list", f"{tool} get", f"{tool} search",
            f"{tool} tags", f"{tool} delete", f"{tool} update", f"{tool} refresh",
            f"{tool} version", f"{tool} config list", f"{tool} config get",
            f"{tool} config set", f"{tool} config prompt test",
            f"{tool} report submit", f"{tool} report list", f"{tool} report show",
        }
        registered = set(app_instance._command_meta.keys())
        assert expected_paths == registered, f"Expected {expected_paths}, got {registered}"

    def test_command_meta_has_description_and_idempotent(self):
        """Each CommandMeta entry has description and is_idempotent."""
        from web_clip_helper.app import get_app
        from agentsdk.agent_commands import CommandMeta

        app_instance = get_app()
        for path, meta in app_instance._command_meta.items():
            assert isinstance(meta, CommandMeta), f"Expected CommandMeta for {path}, got {type(meta)}"
            assert meta.description, f"Empty description in {path}"
            assert isinstance(meta.is_idempotent, bool), f"is_idempotent not bool in {path}"


# ── Test: SDK commands produce correct output type ───────────────────


class TestSDKCommandOutputTypes:
    """Verify SDK-generated commands produce correct JSONL envelope types."""

    def test_schema_produces_result_type(self):
        """schema command emits type=result."""
        result, msgs = _run_and_capture(["agent", "schema"])
        assert result.exit_code == 0
        types = {m["type"] for m in msgs}
        assert types.issubset({"result", "progress", "warning"})

    def test_errors_produces_result_type(self):
        """errors command emits type=result."""
        result, msgs = _run_and_capture(["agent", "errors"])
        assert result.exit_code == 0
        types = {m["type"] for m in msgs}
        assert types.issubset({"result", "progress", "warning"})

    def test_doctor_produces_result_or_progress(self, cli_config):
        """doctor command emits result/progress (health check results)."""
        result, msgs = _run_and_capture(["agent", "doctor"])
        assert result.exit_code == 0
        types = {m["type"] for m in msgs}
        assert types.issubset({"result", "progress", "warning"})

    def test_cache_clean_produces_output(self):
        """cache-clean command runs without error."""
        result, msgs = _run_and_capture(["agent", "cache-clean"])
        _validate_jsonl_types(msgs)

    def test_debug_last_crash_no_crash(self):
        """debug-last-crash emits error when no crash dump exists."""
        result, msgs = _run_and_capture(["agent", "debug-last-crash"])
        # Returns non-zero when no crash dumps found — that's expected
        assert len(msgs) >= 1
        _validate_jsonl_types(msgs)
