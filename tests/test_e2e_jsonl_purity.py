"""E2E JSONL purity test — every CLI command exercised through success and error paths.

Validates the Agent consumption contract: every CLI command in every scenario
produces pure JSONL on stdout (each line is valid JSON with a ``type`` field in
{progress, result, error, warning, help}).

Uses CliRunner (in-process) for speed.  The companion
``test_typer_exception_interception.py`` covers the subprocess path.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex
from web_clip_helper.models import ClipResult
from web_clip_helper.output import set_quiet

runner = CliRunner()


# ── Shared helpers ──────────────────────────────────────────────────


def _validate_all_jsonl(output: str) -> list[dict]:
    """Parse every non-empty line as JSON, assert ``type`` is valid.

    Returns the list of parsed objects so callers can make further assertions.
    """
    valid_types = {"progress", "result", "error", "warning", "help"}
    clean = re.sub(r"\x1b\[[0-9;]*m", "", output)
    lines = [l for l in clean.splitlines() if l.strip()]
    assert lines, "Expected JSONL output but got empty stdout"
    parsed: list[dict] = []
    for line in lines:
        obj = json.loads(line)  # raises on non-JSON
        assert "type" in obj, f"Missing 'type' field in JSONL line: {line!r}"
        assert obj["type"] in valid_types, (
            f"Invalid type {obj['type']!r} in line: {line!r}"
        )
        parsed.append(obj)
    return parsed


def _run(args: list[str]) -> Any:
    """Invoke CLI via CliRunner, resetting _quiet_mode around the call."""
    set_quiet(False)
    return runner.invoke(app, args)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_quiet_mode():
    """Ensure _quiet_mode is reset before and after every test."""
    set_quiet(False)
    yield
    set_quiet(False)


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
    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path / "clips.db"


@pytest.fixture()
def populated_cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """cli_config with three sample clips pre-inserted."""
    db_path = tmp_path / "clips.db"
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config = Config(db_path=str(db_path), storage_path=str(tmp_path / "clips"))
    config.save(config_dir / "config.yaml")

    import web_clip_helper.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "_cached_config", config)

    idx = ClipIndex(db_path)
    idx.save_clip({
        "url": "https://example.com/python-guide",
        "title": "Python Guide",
        "source_type": "web",
        "category": "tech",
        "tags": ["python", "guide"],
        "folder_path": "/clips/python-guide",
        "markdown_path": "/clips/python-guide/guide.md",
    })
    idx.save_clip({
        "url": "https://example.com/react-tutorial",
        "title": "React Tutorial",
        "source_type": "web",
        "category": "tech",
        "tags": ["react", "javascript"],
        "folder_path": "/clips/react-tutorial",
        "markdown_path": "/clips/react-tutorial/tutorial.md",
    })
    idx.save_clip({
        "url": "https://github.com/fastapi/fastapi",
        "title": "FastAPI GitHub Repo",
        "source_type": "github",
        "category": "code",
        "tags": ["python", "fastapi", "api"],
        "folder_path": "/clips/fastapi",
        "markdown_path": "/clips/fastapi/readme.md",
    })
    idx.close()
    return db_path


@pytest.fixture()
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect Path.home() to tmp_path for report commands."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


# ═══════════════════════════════════════════════════════════════════
#  TestSuccessScenarios
# ═══════════════════════════════════════════════════════════════════


class TestSuccessScenarios:
    """Every command with valid inputs produces pure JSONL on stdout."""

    # ── version ──────────────────────────────────────────────────

    def test_version(self) -> None:
        result = _run(["version"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) == 1
        assert "version" in results[0]
        assert results[0]["stage"] == "version"

    # ── list (empty DB) ──────────────────────────────────────────

    def test_list_empty_db(self, cli_config: Path) -> None:
        result = _run(["list"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        progress = [m for m in msgs if m["type"] == "progress"]
        results = [m for m in msgs if m["type"] == "result"]
        assert len(progress) == 1
        assert len(results) == 0  # empty DB

    # ── list --tag python (populated DB) ─────────────────────────

    def test_list_with_tag_filter(self, populated_cli_config: Path) -> None:
        result = _run(["list", "--tag", "python"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) == 2
        titles = {r["title"] for r in results}
        assert "Python Guide" in titles

    # ── get existing ID ──────────────────────────────────────────

    def test_get_existing(self, populated_cli_config: Path) -> None:
        idx = ClipIndex(populated_cli_config)
        cid = idx.save_clip({
            "url": "https://example.com/e2e",
            "title": "E2E Get Test",
            "source_type": "web",
            "folder_path": "/e2e",
            "markdown_path": "/e2e/test.md",
        })
        idx.close()

        result = _run(["get", str(cid)])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["id"] == cid
        assert results[0]["title"] == "E2E Get Test"

    # ── search keyword ───────────────────────────────────────────

    def test_search_keyword(self, populated_cli_config: Path) -> None:
        result = _run(["search", "Python"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) >= 1
        assert any(r["title"] == "Python Guide" for r in results)

    # ── tags ─────────────────────────────────────────────────────

    def test_tags(self, populated_cli_config: Path) -> None:
        result = _run(["tags"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) >= 1
        tag_map = {r["tag"]: r["count"] for r in results}
        assert tag_map["python"] == 2

    # ── update --dynamic existing ID ─────────────────────────────

    def test_update_dynamic(self, populated_cli_config: Path) -> None:
        idx = ClipIndex(populated_cli_config)
        cid = idx.save_clip({
            "url": "https://example.com/update-me",
            "title": "To Update",
            "source_type": "web",
            "folder_path": "/update",
            "markdown_path": "/update/test.md",
        })
        idx.close()

        result = _run(["update", str(cid), "--dynamic"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["id"] == cid
        assert results[0]["is_dynamic"] == 1

    # ── refresh (no refreshable clips) ───────────────────────────

    def test_refresh_no_dynamic_clips(self, cli_config: Path) -> None:
        result = _run(["refresh"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["refreshed"] == 0

    # ── config list ──────────────────────────────────────────────

    def test_config_list(self, cli_config: Path) -> None:
        result = _run(["config", "list"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) >= 1
        keys = {r["key"] for r in results}
        assert "db_path" in keys

    # ── config get llm.api_key ───────────────────────────────────

    def test_config_get_api_key(self, cli_config: Path) -> None:
        result = _run(["config", "get", "llm.api_key"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["key"] == "llm.api_key"
        # Value should be masked
        assert results[0]["value"] == "" or "***" in results[0]["value"] or results[0]["value"] == ""

    # ── config set llm.base_url ──────────────────────────────────

    def test_config_set(self, cli_config: Path) -> None:
        result = _run(["config", "set", "llm.base_url", "https://test.example.com"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["key"] == "llm.base_url"
        assert results[0]["value"] == "https://test.example.com"

    # ── report submit ────────────────────────────────────────────

    def test_report_submit(self, cli_config: Path, tmp_home: Path) -> None:
        result = _run(["report", "submit", "--type", "bug", "test issue"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["report_type"] == "bug"
        assert "file" in results[0]
        assert Path(results[0]["file"]).exists()

    # ── report list ──────────────────────────────────────────────

    def test_report_list(self, cli_config: Path, tmp_home: Path) -> None:
        # Pre-create a report file
        reports_dir = tmp_home / ".web-clip-helper" / "reports"
        reports_dir.mkdir(parents=True)
        (reports_dir / "report_bug_20260501_100000.md").write_text("# test", encoding="utf-8")

        result = _run(["report", "list"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) == 1
        assert len(results[0]["reports"]) >= 1

    # ── report show <id> ─────────────────────────────────────────

    def test_report_show(self, cli_config: Path, tmp_home: Path) -> None:
        reports_dir = tmp_home / ".web-clip-helper" / "reports"
        reports_dir.mkdir(parents=True)
        content = "# Feedback: bug\n\nTest content for show"
        (reports_dir / "report_bug_20260501_100000.md").write_text(content, encoding="utf-8")

        result = _run(["report", "show", "report_bug_20260501_100000"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["report_id"] == "report_bug_20260501_100000"
        assert "Test content for show" in results[0]["content"]

    # ── clip --text (mock pipeline) ──────────────────────────────

    def test_clip_text(self, cli_config: Path, tmp_path: Path) -> None:
        folder = tmp_path / "clip_out"
        folder.mkdir()
        md_path = folder / "clip.md"
        md_path.write_text("hello world content", encoding="utf-8")

        mock_result = ClipResult(
            folder_path=folder,
            markdown_path=md_path,
            image_count=0,
            record_id=1,
        )

        def _mock_clip_text(text: str, config: Any) -> ClipResult:
            """Simulate the real clip_text pipeline's JSONL emissions."""
            from web_clip_helper.output import jsonl_emit_progress, jsonl_emit_result
            jsonl_emit_progress(message="Starting clip for raw text", percent=0, stage="clip")
            jsonl_emit_result(
                stage="clip",
                id=1,
                title="hello world",
                source_type="text",
                folder=str(folder),
            )
            return mock_result

        with patch("web_clip_helper.pipeline.clip_text", side_effect=_mock_clip_text):
            result = _run(["clip", "--text", "hello world"])

        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) >= 1

    # ── delete existing ID ───────────────────────────────────────

    def test_delete_existing(self, populated_cli_config: Path) -> None:
        idx = ClipIndex(populated_cli_config)
        cid = idx.save_clip({
            "url": "https://example.com/to-delete",
            "title": "Delete Me",
            "source_type": "web",
            "folder_path": str(populated_cli_config.parent / "del"),
            "markdown_path": "/del/test.md",
        })
        idx.close()

        # Create the folder so delete can clean up
        del_folder = populated_cli_config.parent / "del"
        del_folder.mkdir(parents=True, exist_ok=True)

        result = _run(["delete", str(cid)])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) == 1
        assert results[0]["id"] == cid


# ═══════════════════════════════════════════════════════════════════
#  TestErrorScenarios
# ═══════════════════════════════════════════════════════════════════


class TestErrorScenarios:
    """Every command with invalid/missing inputs produces JSONL error output."""

    # ── search (no keyword) ──────────────────────────────────────

    def test_search_no_keyword(self) -> None:
        result = _run(["search"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── get (no ID) ──────────────────────────────────────────────

    def test_get_no_id(self) -> None:
        result = _run(["get"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── get nonexistent ID ───────────────────────────────────────

    def test_get_nonexistent_id(self, cli_config: Path) -> None:
        result = _run(["get", "99999"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "NOT_FOUND"

    # ── delete (no ID) ───────────────────────────────────────────

    def test_delete_no_id(self) -> None:
        result = _run(["delete"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── update (no options) ──────────────────────────────────────

    def test_update_no_options(self, cli_config: Path) -> None:
        result = _run(["update", "1"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"
        assert "At least one option" in errors[0]["detail"]

    # ── update --interval 0 ──────────────────────────────────────

    def test_update_interval_zero(self, cli_config: Path) -> None:
        result = _run(["update", "1", "--interval", "0"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"
        assert "interval" in errors[0]["detail"].lower()

    # ── clip (no URL/text) ───────────────────────────────────────

    def test_clip_no_input(self) -> None:
        result = _run(["clip"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── clip --badopt ────────────────────────────────────────────

    def test_clip_bad_option(self) -> None:
        result = _run(["clip", "--badopt"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── config (no subcommand) ───────────────────────────────────

    def test_config_no_subcommand(self) -> None:
        result = _run(["config"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1

    # ── config get (no key) ──────────────────────────────────────

    def test_config_get_no_key(self) -> None:
        result = _run(["config", "get"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── report submit --type invalid ─────────────────────────────

    def test_report_submit_invalid_type(self, cli_config: Path, tmp_home: Path) -> None:
        result = _run(["report", "submit", "--type", "invalid", "desc"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"
        assert "Invalid report type" in errors[0]["detail"]

    # ── report show nonexistent ──────────────────────────────────

    def test_report_show_nonexistent(self, cli_config: Path, tmp_home: Path) -> None:
        result = _run(["report", "show", "nonexistent_report"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "NOT_FOUND"

    # ── report (no subcommand) ───────────────────────────────────

    def test_report_no_subcommand(self) -> None:
        result = _run(["report"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1

    # ── get nonexistent ID — verify error detail mentions clip ───

    def test_get_nonexistent_mentions_not_found(self, cli_config: Path) -> None:
        result = _run(["get", "99999"])
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "NOT_FOUND"
        assert "not found" in errors[0]["detail"].lower()

    # ── delete nonexistent ID ────────────────────────────────────

    def test_delete_nonexistent_id(self, cli_config: Path) -> None:
        result = _run(["delete", "99999"])
        assert result.exit_code != 0
        msgs = _validate_all_jsonl(result.output)
        errors = [m for m in msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "NOT_FOUND"


# ═══════════════════════════════════════════════════════════════════
#  TestCrossCommandWorkflow
# ═══════════════════════════════════════════════════════════════════


class TestCrossCommandWorkflow:
    """Full clip → list → get → search → update → delete → verify-404 lifecycle."""

    def test_full_clip_lifecycle(self, cli_config: Path, tmp_path: Path) -> None:
        """Exercise clip → list → get → search → update → delete → get-404."""

        # ── Step 1: clip --text ──────────────────────────────────
        clip_folder = tmp_path / "lifecycle_clip"
        clip_folder.mkdir()
        clip_md = clip_folder / "content.md"
        clip_md.write_text("E2E test content for lifecycle", encoding="utf-8")

        mock_result = ClipResult(
            folder_path=clip_folder,
            markdown_path=clip_md,
            image_count=0,
            record_id=None,
        )

        captured_clip_id: list[int] = []

        def _mock_clip_text(text: str, config: Any) -> ClipResult:
            """Simulate the real clip_text pipeline's JSONL emissions."""
            from web_clip_helper.output import jsonl_emit_progress, jsonl_emit_result
            jsonl_emit_progress(message="Starting clip for raw text", percent=0, stage="clip")
            # Insert a real record into the DB so list/get/search/find it
            from web_clip_helper.config import get_config
            cfg = get_config()
            idx = ClipIndex(cfg.db_path)
            cid = idx.save_clip({
                "url": "",
                "title": "E2E test content",
                "source_type": "text",
                "tags": [],
                "folder_path": str(clip_folder),
                "markdown_path": str(clip_md),
            })
            idx.close()
            captured_clip_id.append(cid)
            jsonl_emit_result(
                stage="clip",
                id=cid,
                title="E2E test content",
                source_type="text",
                folder=str(clip_folder),
            )
            # Update the mock result with the real ID
            return ClipResult(
                folder_path=clip_folder,
                markdown_path=clip_md,
                image_count=0,
                record_id=cid,
            )

        with patch("web_clip_helper.pipeline.clip_text", side_effect=_mock_clip_text) as mock_clip:
            clip_result = _run(["clip", "--text", "E2E test content"])
        mock_clip.assert_called_once()
        assert clip_result.exit_code == 0
        clip_msgs = _validate_all_jsonl(clip_result.output)

        # Extract the clip ID from the result
        clip_results = [m for m in clip_msgs if m["type"] == "result"]
        assert len(clip_results) >= 1
        clip_id = captured_clip_id[0]

        # ── Step 2: list → verify clip appears ───────────────────
        list_result = _run(["list"])
        assert list_result.exit_code == 0
        list_msgs = _validate_all_jsonl(list_result.output)
        list_results = [m for m in list_msgs if m["type"] == "result"]
        list_ids = {r["id"] for r in list_results}
        assert clip_id in list_ids, f"Clip {clip_id} not found in list results: {list_ids}"

        # ── Step 3: get <id> → verify full details ───────────────
        get_result = _run(["get", str(clip_id)])
        assert get_result.exit_code == 0
        get_msgs = _validate_all_jsonl(get_result.output)
        get_results = [m for m in get_msgs if m["type"] == "result"]
        assert len(get_results) == 1
        assert get_results[0]["id"] == clip_id

        # ── Step 4: search 'E2E test' → verify found ─────────────
        search_result = _run(["search", "E2E test"])
        assert search_result.exit_code == 0
        search_msgs = _validate_all_jsonl(search_result.output)
        search_results = [m for m in search_msgs if m["type"] == "result"]
        search_ids = {r["id"] for r in search_results}
        assert clip_id in search_ids, f"Clip {clip_id} not found in search results"

        # ── Step 5: update <id> --dynamic → verify update ────────
        update_result = _run(["update", str(clip_id), "--dynamic"])
        assert update_result.exit_code == 0
        update_msgs = _validate_all_jsonl(update_result.output)
        update_results = [m for m in update_msgs if m["type"] == "result"]
        assert len(update_results) == 1
        assert update_results[0]["id"] == clip_id
        assert update_results[0]["is_dynamic"] == 1

        # ── Step 6: delete <id> → verify delete result ───────────
        # The folder was created at tmp_path / "lifecycle_clip" so delete can rmtree
        delete_result = _run(["delete", str(clip_id)])
        assert delete_result.exit_code == 0
        delete_msgs = _validate_all_jsonl(delete_result.output)
        delete_results = [m for m in delete_msgs if m["type"] == "result"]
        assert len(delete_results) == 1
        assert delete_results[0]["id"] == clip_id

        # ── Step 7: get <id> → verify NOT_FOUND ──────────────────
        get_again = _run(["get", str(clip_id)])
        assert get_again.exit_code != 0
        get_again_msgs = _validate_all_jsonl(get_again.output)
        errors = [m for m in get_again_msgs if m["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "NOT_FOUND"


# ═══════════════════════════════════════════════════════════════════
#  TestHelpAndQuiet
# ═══════════════════════════════════════════════════════════════════


class TestHelpAndQuiet:
    """--help and --quiet produce correct JSONL output."""

    # ── root --help ──────────────────────────────────────────────

    def test_root_help(self) -> None:
        result = _run(["--help"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        help_msgs = [m for m in msgs if m["type"] == "help"]
        assert len(help_msgs) >= 1
        assert "description" in help_msgs[0]
        cmd_names = [c["name"] for c in help_msgs[0]["commands"]]
        assert "clip" in cmd_names
        assert "list" in cmd_names

    # ── no subcommand (same as root help) ────────────────────────

    def test_no_subcommand(self) -> None:
        result = _run([])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        help_msgs = [m for m in msgs if m["type"] == "help"]
        assert len(help_msgs) >= 1

    # ── each leaf command --help ─────────────────────────────────

    @pytest.mark.parametrize("subcmd", [
        "list",
        "get",
        "search",
        "clip",
        "delete",
        "update",
        "refresh",
        "tags",
        "version",
    ])
    def test_leaf_help_jsonl(self, subcmd: str) -> None:
        result = _run([subcmd, "--help"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        help_msgs = [m for m in msgs if m["type"] == "help"]
        assert len(help_msgs) >= 1
        assert help_msgs[0].get("command") == subcmd

    # ── --quiet list → no progress lines ─────────────────────────

    def test_quiet_list_no_progress(self, populated_cli_config: Path) -> None:
        result = _run(["--quiet", "list"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        types = [m["type"] for m in msgs]
        assert "progress" not in types
        assert "result" in types

    # ── --quiet tags → no progress lines ─────────────────────────

    def test_quiet_tags_no_progress(self, populated_cli_config: Path) -> None:
        result = _run(["--quiet", "tags"])
        assert result.exit_code == 0
        msgs = _validate_all_jsonl(result.output)
        types = [m["type"] for m in msgs]
        assert "progress" not in types
        assert "result" in types
