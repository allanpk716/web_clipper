"""Documentation validation tests for the import command.

Ensures AGENT_INSTRUCTION.md, README.md, agent schema, and agent errors
all correctly describe the import command and its behavior.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper import __version__

ROOT = Path(__file__).resolve().parent.parent
AGENT_DOC = ROOT / "AGENT_INSTRUCTION.md"
README = ROOT / "README.md"

runner = CliRunner()


def _run(*args: str) -> str:
    return runner.invoke(app, args).output


def _parse(output: str) -> list[dict]:
    return [json.loads(l) for l in output.strip().splitlines() if l.strip()]


# ── Agent Schema ──────────────────────────────────────────────────────


class TestAgentSchema:
    def test_schema_includes_import(self) -> None:
        msgs = _parse(_run("agent", "schema"))
        schema_msg = [m for m in msgs if m.get("type") == "schema"][0]
        commands = schema_msg.get("data", {}).get("commands", schema_msg.get("commands", []))
        names = [c["name"] for c in commands]
        assert "import" in names

    def test_import_schema_has_required_params(self) -> None:
        msgs = _parse(_run("agent", "schema"))
        schema_msg = [m for m in msgs if m.get("type") == "schema"][0]
        commands = schema_msg.get("data", {}).get("commands", schema_msg.get("commands", []))
        import_cmd = [c for c in commands if c["name"] == "import"][0]
        param_names = [p["name"] for p in import_cmd["parameters"]]
        assert "source_dir" in param_names
        assert "--copy" in param_names
        assert "--source-type" in param_names
        assert "--dry-run" in param_names

    def test_import_schema_source_dir_required(self) -> None:
        msgs = _parse(_run("agent", "schema"))
        schema_msg = [m for m in msgs if m.get("type") == "schema"][0]
        commands = schema_msg.get("data", {}).get("commands", schema_msg.get("commands", []))
        import_cmd = [c for c in commands if c["name"] == "import"][0]
        source_dir = [p for p in import_cmd["parameters"] if p["name"] == "source_dir"][0]
        assert source_dir["required"] is True

    def test_import_is_idempotent(self) -> None:
        msgs = _parse(_run("agent", "schema"))
        schema_msg = [m for m in msgs if m.get("type") == "schema"][0]
        commands = schema_msg.get("data", {}).get("commands", schema_msg.get("commands", []))
        import_cmd = [c for c in commands if c["name"] == "import"][0]
        assert import_cmd["is_idempotent"] is True


# ── Agent Errors ──────────────────────────────────────────────────────


class TestAgentErrors:
    def test_errors_include_import_error(self) -> None:
        lines = _parse(_run("agent", "errors"))
        codes = [m.get("data", {}).get("error_code", "") for m in lines]
        assert "IMPORT_ERROR" in codes

    def test_errors_include_import_scan_error(self) -> None:
        lines = _parse(_run("agent", "errors"))
        codes = [m.get("data", {}).get("error_code", "") for m in lines]
        assert "IMPORT_SCAN_ERROR" in codes


# ── Help output ──────────────────────────────────────────────────────


class TestHelpOutput:
    def test_help_lists_import(self) -> None:
        msgs = _parse(_run("--help"))
        help_msg = [m for m in msgs if m.get("type") == "help"][0]
        names = [c["name"] for c in help_msg["commands"]]
        assert "import" in names

    def test_import_help_has_params(self) -> None:
        msgs = _parse(_run("import", "--help"))
        help_msg = [m for m in msgs if m.get("type") == "help"][0]
        assert "SOURCE_DIR" in str(help_msg)
        assert "--copy" in str(help_msg)
        assert "--source-type" in str(help_msg)
        assert "--dry-run" in str(help_msg)


# ── AGENT_INSTRUCTION.md ─────────────────────────────────────────────


class TestAgentInstructionDoc:
    def test_agent_doc_mentions_import(self) -> None:
        content = AGENT_DOC.read_text(encoding="utf-8")
        assert "import" in content.lower()

    def test_agent_doc_has_import_sop(self) -> None:
        content = AGENT_DOC.read_text(encoding="utf-8")
        assert "Step 3.5" in content or "import /path" in content

    def test_agent_doc_import_in_command_table(self) -> None:
        content = AGENT_DOC.read_text(encoding="utf-8")
        assert "import <dir>" in content or "`import`" in content

    def test_agent_doc_import_error_codes(self) -> None:
        content = AGENT_DOC.read_text(encoding="utf-8")
        assert "IMPORT_ERROR" in content or "IMPORT_SCAN_ERROR" in content


# ── README.md ────────────────────────────────────────────────────────


class TestReadmeDoc:
    def test_readme_mentions_import(self) -> None:
        content = README.read_text(encoding="utf-8")
        assert "import" in content.lower()

    def test_readme_has_import_section(self) -> None:
        content = README.read_text(encoding="utf-8")
        assert "### import" in content or "## import" in content

    def test_readme_import_example(self) -> None:
        content = README.read_text(encoding="utf-8")
        assert "web-clip-helper import" in content

    def test_readme_import_error_codes(self) -> None:
        content = README.read_text(encoding="utf-8")
        assert "IMPORT_ERROR" in content or "IMPORT_SCAN_ERROR" in content or "INPUT_INVALID" in content
