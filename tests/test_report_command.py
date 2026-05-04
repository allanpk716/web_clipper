"""Comprehensive tests for the report subcommand system (submit / list / show).

These tests replace the former TestCLIFeedback tests. They cover all three
report subcommands, edge cases, error codes, and verify that the old
`feedback` command has been fully removed.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app, _COMMAND_HELP
from web_clip_helper.config import Config

runner = CliRunner()


# ── Helpers ───────────────────────────────────────────────────────────


def _run_cli(*args: str) -> str:
    """Run the CLI and return stdout."""
    result = runner.invoke(app, args)
    return result.output


def _parse_jsonl(output: str) -> list[dict]:
    """Parse JSONL output into a list of dicts."""
    return [json.loads(line) for line in output.strip().splitlines() if line.strip()]


def _patch_reports_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Patch get_reports_dir to use tmp_path and return the reports dir."""
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr("web_clip_helper.cli.get_reports_dir", lambda: reports_dir)
    return reports_dir


@pytest.fixture()
def cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary config + DB, patch get_config to use it.

    Returns the DB path so tests can pre-populate data.
    """
    import web_clip_helper.config as cfg_mod

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    db_path = str(tmp_path / "clips.db")
    config = Config(db_path=db_path, storage_path=str(tmp_path / "clips"))
    config.save(config_dir / "config.yaml")

    # Patch the module-level singleton
    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path / "clips.db"


# ── TestReportSubmit ──────────────────────────────────────────────────


class TestReportSubmit:
    """Tests for `report submit`."""

    def test_submit_bug_report(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Submit a bug report → file created, JSONL result with correct fields."""
        reports_dir = _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("report", "submit", "--type", "bug", "Something is broken")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1

        file_path = results[0]["file"]
        assert "report_bug_" in file_path
        assert results[0]["report_type"] == "bug"
        assert results[0]["stage"] == "report_submit"

        content = Path(file_path).read_text(encoding="utf-8")
        assert "# Feedback: bug" in content
        assert "Something is broken" in content
        assert "Python:" in content
        assert "OS:" in content
        assert "web-clip-helper" in content

    def test_submit_feature_report(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Submit a feature report with --type feature."""
        _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("report", "submit", "Add dark mode", "--type", "feature")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["report_type"] == "feature"
        assert "report_feature_" in results[0]["file"]

        content = Path(results[0]["file"]).read_text(encoding="utf-8")
        assert "# Feedback: feature" in content
        assert "Add dark mode" in content

    def test_submit_other_type(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Submit a report with --type other."""
        _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("report", "submit", "General note", "--type", "other")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["report_type"] == "other"
        assert "report_other_" in results[0]["file"]

    def test_submit_invalid_type(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Invalid report type → JSONL error INPUT_INVALID."""
        _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("report", "submit", "Test", "--type", "invalid")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "INPUT_INVALID"
        assert "Invalid report type" in errors[0]["detail"]

    def test_submit_missing_description(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing description argument → JSONL error from _JSONLGroup interception."""
        _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("report", "submit")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) >= 1

    def test_reports_dir_auto_created(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reports directory is auto-created if it doesn't exist."""
        reports_dir = _patch_reports_dir(tmp_path, monkeypatch)
        assert not reports_dir.exists()

        output = _run_cli("report", "submit", "Test description")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert reports_dir.exists()

    def test_filename_format(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Filename follows report_{type}_{YYYYMMDD_HHMMSS}.md pattern."""
        _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("report", "submit", "Check filename")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        filename = Path(results[0]["file"]).name

        assert re.match(r"report_bug_\d{8}_\d{6}\.md", filename), f"Filename format wrong: {filename}"

    def test_file_content_structure(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """File content contains expected sections: header, description, env info, timestamps."""
        _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("report", "submit", "--type", "bug", "Detailed issue")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1

        content = Path(results[0]["file"]).read_text(encoding="utf-8")
        # Header
        assert "# Feedback: bug" in content
        # Description section
        assert "问题描述" in content
        assert "Detailed issue" in content
        # Environment section
        assert "环境信息" in content
        assert "Python:" in content
        assert "OS:" in content
        assert "web-clip-helper 版本:" in content
        assert "配置路径:" in content
        assert "数据库:" in content
        assert "剪藏数量:" in content
        # Timestamp section
        assert "生成时间" in content

    def test_attach_valid_file(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--attach with valid file → content embedded, attached_file in result."""
        _patch_reports_dir(tmp_path, monkeypatch)

        log_file = tmp_path / "clip_log.jsonl"
        log_content = '{"type":"progress","stage":"clip","message":"started"}\n'
        log_file.write_text(log_content, encoding="utf-8")

        output = _run_cli("report", "submit", "Clip failed", "--attach", str(log_file))
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["attached_file"] == str(log_file.resolve())

        content = Path(results[0]["file"]).read_text(encoding="utf-8")
        assert "## 附加日志" in content
        assert "started" in content
        assert str(log_file.resolve()) in content

    def test_attach_nonexistent_file(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--attach with nonexistent file → JSONL error INPUT_INVALID."""
        _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("report", "submit", "Bug", "--attach", "/nonexistent/path/file.jsonl")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "INPUT_INVALID"
        assert "not found" in errors[0]["detail"]

    def test_attach_large_file_truncated(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--attach with large file → truncated with notice."""
        _patch_reports_dir(tmp_path, monkeypatch)

        big_file = tmp_path / "big_log.jsonl"
        big_content = "x" * (101 * 1024)  # 101 KB
        big_file.write_text(big_content, encoding="utf-8")

        output = _run_cli("report", "submit", "Large log", "--attach", str(big_file))
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1

        content = Path(results[0]["file"]).read_text(encoding="utf-8")
        assert "100KB" in content
        assert "截断" in content
        assert "## 附加日志" in content

    def test_write_failure_storage_error(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Write failure → JSONL error STORAGE_ERROR."""
        reports_dir = _patch_reports_dir(tmp_path, monkeypatch)
        reports_dir.mkdir(parents=True)

        original_write_text = Path.write_text

        def failing_write_text(self_path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            # Only fail for .md files in the reports directory
            if str(self_path).startswith(str(reports_dir)) and self_path.suffix == ".md":
                raise OSError("disk full")
            return original_write_text(self_path, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", failing_write_text)

        output = _run_cli("report", "submit", "Test storage failure")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "STORAGE_ERROR"
        assert "Failed to write report file" in errors[0]["detail"]


# ── TestReportList ────────────────────────────────────────────────────


class TestReportList:
    """Tests for `report list`."""

    def test_empty_reports_directory(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty reports directory → JSONL result with empty reports array."""
        reports_dir = _patch_reports_dir(tmp_path, monkeypatch)
        reports_dir.mkdir(parents=True)

        output = _run_cli("report", "list")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["reports"] == []
        assert results[0]["stage"] == "report_list"

    def test_nonexistent_reports_directory(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-existent reports directory → JSONL result with empty reports array."""
        _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("report", "list")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["reports"] == []

    def test_multiple_reports_sorted_newest_first(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multiple reports → sorted newest-first (by filename, which encodes timestamp)."""
        reports_dir = _patch_reports_dir(tmp_path, monkeypatch)
        reports_dir.mkdir(parents=True)

        # Create reports with same type but different timestamps in filenames
        # sorted(glob(...), reverse=True) sorts alphabetically descending
        (reports_dir / "report_bug_20260501_100000.md").write_text("# Feedback: bug\nfirst", encoding="utf-8")
        (reports_dir / "report_bug_20260502_120000.md").write_text("# Feedback: bug\nsecond", encoding="utf-8")
        (reports_dir / "report_bug_20260503_140000.md").write_text("# Feedback: bug\nthird", encoding="utf-8")

        output = _run_cli("report", "list")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        reports = results[0]["reports"]
        assert len(reports) == 3

        # Newest first (reverse alphabetical = newest first since filenames encode timestamps)
        assert "20260503" in reports[0]["id"]
        assert "20260502" in reports[1]["id"]
        assert "20260501" in reports[2]["id"]

    def test_each_entry_has_required_fields(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each list entry has id, report_type, created_at, file fields."""
        reports_dir = _patch_reports_dir(tmp_path, monkeypatch)
        reports_dir.mkdir(parents=True)
        (reports_dir / "report_bug_20260503_100000.md").write_text("# Feedback: bug\ntest", encoding="utf-8")

        output = _run_cli("report", "list")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        reports = results[0]["reports"]
        assert len(reports) == 1

        entry = reports[0]
        assert "id" in entry
        assert "report_type" in entry
        assert "created_at" in entry
        assert "file" in entry
        assert entry["report_type"] == "bug"

    def test_jsonl_purity(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Every line of list output is valid JSON."""
        reports_dir = _patch_reports_dir(tmp_path, monkeypatch)
        reports_dir.mkdir(parents=True)
        (reports_dir / "report_bug_20260503_100000.md").write_text("test", encoding="utf-8")

        output = _run_cli("report", "list")
        lines = [line for line in output.strip().splitlines() if line.strip()]
        for line in lines:
            parsed = json.loads(line)
            assert "type" in parsed

    def test_list_finds_submitted_report(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """report list finds previously submitted reports."""
        _patch_reports_dir(tmp_path, monkeypatch)

        _run_cli("report", "submit", "Test report for list")
        output = _run_cli("report", "list")
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert len(results[0]["reports"]) >= 1


# ── TestReportShow ────────────────────────────────────────────────────


class TestReportShow:
    """Tests for `report show`."""

    def test_show_existing_report(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Existing report → JSONL result with report_id, file, content."""
        _patch_reports_dir(tmp_path, monkeypatch)

        submit_output = _run_cli("report", "submit", "Show test content")
        submit_msgs = _parse_jsonl(submit_output)
        submit_results = [m for m in submit_msgs if m["type"] == "result"]
        report_id = os.path.basename(submit_results[0]["file"]).replace(".md", "")

        output = _run_cli("report", "show", report_id)
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["report_id"] == report_id
        assert results[0]["stage"] == "report_show"
        assert "Show test content" in results[0]["content"]

    def test_show_content_matches_file(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Content from show matches the actual file on disk."""
        _patch_reports_dir(tmp_path, monkeypatch)

        submit_output = _run_cli("report", "submit", "Content verification test")
        submit_msgs = _parse_jsonl(submit_output)
        submit_results = [m for m in submit_msgs if m["type"] == "result"]
        report_id = os.path.basename(submit_results[0]["file"]).replace(".md", "")

        output = _run_cli("report", "show", report_id)
        messages = _parse_jsonl(output)
        results = [m for m in messages if m["type"] == "result"]
        assert len(results) == 1

        # Read file directly and compare
        file_content = Path(results[0]["file"]).read_text(encoding="utf-8")
        assert results[0]["content"] == file_content

    def test_show_nonexistent_report(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-existent report ID → JSONL error with NOT_FOUND."""
        _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("report", "show", "nonexistent_report")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) == 1
        assert errors[0]["error_code"] == "NOT_FOUND"
        assert errors[0]["stage"] == "report_show"
        assert "not found" in errors[0]["detail"]

    def test_show_missing_report_id(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing REPORT_ID argument → JSONL error from _JSONLGroup interception."""
        _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("report", "show")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) >= 1


# ── TestFeedbackRemoved ──────────────────────────────────────────────


class TestFeedbackRemoved:
    """Verify the old `feedback` command has been fully removed."""

    def test_feedback_command_not_found(self, cli_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """`feedback 'test'` → JSONL error (no such command)."""
        _patch_reports_dir(tmp_path, monkeypatch)

        output = _run_cli("feedback", "test")
        messages = _parse_jsonl(output)
        errors = [m for m in messages if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0]["error_code"] == "INPUT_INVALID"

    def test_command_help_does_not_contain_feedback(self) -> None:
        """_COMMAND_HELP does not contain 'feedback'."""
        names = [entry["name"] for entry in _COMMAND_HELP]
        assert "feedback" not in names

    def test_command_help_contains_report(self) -> None:
        """_COMMAND_HELP contains 'report'."""
        names = [entry["name"] for entry in _COMMAND_HELP]
        assert "report" in names
