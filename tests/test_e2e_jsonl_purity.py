"""E2E JSONL purity test — every CLI command exercised through success and error paths.

Validates the Agent consumption contract: every CLI command in every scenario
produces pure JSONL on stdout (each line is valid JSON with a ``type`` field in
{progress, result, error, warning} — help is type=result).

Uses ``run_sdk_cli`` fixture (in-process via SDK App.run()) for most tests.
Help tests use subprocess since Click's built-in help for leaf commands
writes to sys.stdout (the _FakeStream) rather than the SDK Writer.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from tests.conftest import _parse_envelopes, _unwrap_data, _unwrap_error_message
from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex
from web_clip_helper.models import ClipResult


# ── Shared helpers ──────────────────────────────────────────────────


def _validate_all_jsonl(output: str) -> list[dict]:
    """Parse every non-empty line as JSON, assert ``type`` is valid envelope type.

    Returns the list of parsed objects so callers can make further assertions.
    """
    valid_types = {"progress", "result", "error", "warning"}
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


def _run_subprocess(*args: str) -> tuple[int, str, str]:
    """Run CLI via subprocess and return (exit_code, stdout, stderr)."""
    r = subprocess.run(
        [sys.executable, "-m", "web_clip_helper.cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return r.returncode, r.stdout, r.stderr


# ── Fixtures ────────────────────────────────────────────────────────


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
    config.save(config_dir / "config.json")
    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path / "clips.db"


@pytest.fixture()
def populated_cli_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """cli_config with three sample clips pre-inserted."""
    db_path = tmp_path / "clips.db"
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    config = Config(db_path=str(db_path), storage_path=str(tmp_path / "clips"))
    config.save(config_dir / "config.json")

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
    """Redirect get_reports_dir to tmp_path/reports for report commands."""
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr("web_clip_helper.cli.get_reports_dir", lambda: reports_dir)
    return tmp_path


# ═══════════════════════════════════════════════════════════════════
#  TestSuccessScenarios
# ═══════════════════════════════════════════════════════════════════


class TestSuccessScenarios:
    """Every command with valid inputs produces pure JSONL on stdout."""

    # ── version ──────────────────────────────────────────────────

    def test_version(self, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["version"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert "version" in data
        assert data["stage"] == "version"

    # ── list (empty DB) ──────────────────────────────────────────

    def test_list_empty_db(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["list"])
        assert code == 0
        progress = [e for e in envelopes if e["type"] == "progress"]
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(progress) == 1
        # Empty DB → result with empty data list or no result
        assert len(results) <= 1

    # ── list --tag python (populated DB) ─────────────────────────

    def test_list_with_tag_filter(self, populated_cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["list", "--tag", "python"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        # Each result envelope contains a single clip record in data
        data_list = [_unwrap_data(r) for r in results]
        titles = {d.get("title") for d in data_list}
        assert "Python Guide" in titles

    # ── get existing ID ──────────────────────────────────────────

    def test_get_existing(self, populated_cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(populated_cli_config)
        cid = idx.save_clip({
            "url": "https://example.com/e2e",
            "title": "E2E Get Test",
            "source_type": "web",
            "folder_path": "/e2e",
            "markdown_path": "/e2e/test.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["get", str(cid)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["id"] == cid
        assert data["title"] == "E2E Get Test"

    # ── search keyword ───────────────────────────────────────────

    def test_search_keyword(self, populated_cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["search", "Python"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) >= 1
        data_list = [_unwrap_data(r) for r in results]
        assert any(d.get("title") == "Python Guide" for d in data_list)

    # ── tags ─────────────────────────────────────────────────────

    def test_tags(self, populated_cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["tags"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) >= 1
        # Tags result contains tag data
        data_list = [_unwrap_data(r) for r in results]
        # Find the python tag entry
        python_entries = [d for d in data_list if d.get("tag") == "python"]
        assert len(python_entries) >= 1
        assert python_entries[0]["count"] == 2

    # ── update --dynamic existing ID ─────────────────────────────

    def test_update_dynamic(self, populated_cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(populated_cli_config)
        cid = idx.save_clip({
            "url": "https://example.com/update-me",
            "title": "To Update",
            "source_type": "web",
            "folder_path": "/update",
            "markdown_path": "/update/test.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["update", str(cid), "--dynamic"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["id"] == cid
        assert data["is_dynamic"] == 1

    # ── refresh (no refreshable clips) ───────────────────────────

    def test_refresh_no_dynamic_clips(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["refresh"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["refreshed"] == 0

    # ── config list ──────────────────────────────────────────────

    def test_config_list(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "list"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) >= 1
        data_list = [_unwrap_data(r) for r in results]
        keys = {d["key"] for d in data_list}
        assert "db_path" in keys

    # ── config get llm.api_key ───────────────────────────────────

    def test_config_get_api_key(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "get", "llm.api_key"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["key"] == "llm.api_key"
        # Value should be masked or empty
        val = data["value"]
        assert val == "" or "****" in val

    # ── config set llm.base_url ──────────────────────────────────

    def test_config_set(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "set", "llm.base_url", "https://test.example.com"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["key"] == "llm.base_url"
        assert data["value"] == "https://test.example.com"

    # ── report submit ────────────────────────────────────────────

    def test_report_submit(self, cli_config: Path, tmp_home: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["report", "submit", "--type", "bug", "test issue"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["report_type"] == "bug"
        assert "file" in data
        assert Path(data["file"]).exists()

    # ── report list ──────────────────────────────────────────────

    def test_report_list(self, cli_config: Path, tmp_home: Path, run_sdk_cli) -> None:
        # Pre-create a report file
        reports_dir = tmp_home / "reports"
        reports_dir.mkdir(parents=True)
        (reports_dir / "report_bug_20260501_100000.md").write_text("# test", encoding="utf-8")

        code, envelopes = run_sdk_cli(["report", "list"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert len(data["reports"]) >= 1

    # ── report show <id> ─────────────────────────────────────────

    def test_report_show(self, cli_config: Path, tmp_home: Path, run_sdk_cli) -> None:
        reports_dir = tmp_home / "reports"
        reports_dir.mkdir(parents=True)
        content = "# Feedback: bug\n\nTest content for show"
        (reports_dir / "report_bug_20260501_100000.md").write_text(content, encoding="utf-8")

        code, envelopes = run_sdk_cli(["report", "show", "report_bug_20260501_100000"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["report_id"] == "report_bug_20260501_100000"
        assert "Test content for show" in data["content"]

    # ── clip --text (mock pipeline) ──────────────────────────────

    def test_clip_text(self, cli_config: Path, tmp_path: Path, run_sdk_cli) -> None:
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
            code, envelopes = run_sdk_cli(["clip", "--text", "hello world"])

        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) >= 1

    # ── delete existing ID ───────────────────────────────────────

    def test_delete_existing(self, populated_cli_config: Path, run_sdk_cli) -> None:
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

        code, envelopes = run_sdk_cli(["delete", str(cid)])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = _unwrap_data(results[0])
        assert data["id"] == cid


# ═══════════════════════════════════════════════════════════════════
#  TestErrorScenarios
# ═══════════════════════════════════════════════════════════════════


class TestErrorScenarios:
    """Every command with invalid/missing inputs produces JSONL error output."""

    # ── search (no keyword) ──────────────────────────────────────

    def test_search_no_keyword(self, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["search"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── get (no ID) ──────────────────────────────────────────────

    def test_get_no_id(self, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["get"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── get nonexistent ID ───────────────────────────────────────

    def test_get_nonexistent_id(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["get", "99999"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "NOT_FOUND"

    # ── delete (no ID) ───────────────────────────────────────────

    def test_delete_no_id(self, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["delete"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── update (no options) ──────────────────────────────────────

    def test_update_no_options(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["update", "1"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"
        stage, detail = _unwrap_error_message(errors[0])
        assert "At least one option" in detail

    # ── update --interval 0 ──────────────────────────────────────

    def test_update_interval_zero(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["update", "1", "--interval", "0"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"
        stage, detail = _unwrap_error_message(errors[0])
        assert "interval" in detail.lower()

    # ── clip (no URL/text) ───────────────────────────────────────

    def test_clip_no_input(self, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["clip"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── clip --badopt ────────────────────────────────────────────

    def test_clip_bad_option(self, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["clip", "--badopt"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── config (no subcommand) ───────────────────────────────────

    def test_config_no_subcommand(self, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1

    # ── config get (no key) ──────────────────────────────────────

    def test_config_get_no_key(self, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["config", "get"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"

    # ── report submit --type invalid ─────────────────────────────

    def test_report_submit_invalid_type(self, cli_config: Path, tmp_home: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["report", "submit", "--type", "invalid", "desc"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "INPUT_INVALID"
        stage, detail = _unwrap_error_message(errors[0])
        assert "Invalid report type" in detail

    # ── report show nonexistent ──────────────────────────────────

    def test_report_show_nonexistent(self, cli_config: Path, tmp_home: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["report", "show", "nonexistent_report"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "NOT_FOUND"

    # ── report (no subcommand) ───────────────────────────────────

    def test_report_no_subcommand(self, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["report"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1

    # ── get nonexistent ID — verify error detail mentions clip ───

    def test_get_nonexistent_mentions_not_found(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["get", "99999"])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "NOT_FOUND"
        stage, detail = _unwrap_error_message(errors[0])
        assert "not found" in detail.lower()

    # ── delete nonexistent ID ────────────────────────────────────

    def test_delete_nonexistent_id(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["delete", "99999"])
        assert code != 0
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "NOT_FOUND"


# ═══════════════════════════════════════════════════════════════════
#  TestCrossCommandWorkflow
# ═══════════════════════════════════════════════════════════════════


class TestCrossCommandWorkflow:
    """Full clip → list → get → search → update → delete → verify-404 lifecycle."""

    def test_full_clip_lifecycle(self, cli_config: Path, tmp_path: Path, run_sdk_cli) -> None:
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
            return ClipResult(
                folder_path=clip_folder,
                markdown_path=clip_md,
                image_count=0,
                record_id=cid,
            )

        with patch("web_clip_helper.pipeline.clip_text", side_effect=_mock_clip_text) as mock_clip:
            clip_code, clip_envelopes = run_sdk_cli(["clip", "--text", "E2E test content"])
        mock_clip.assert_called_once()
        assert clip_code == 0
        clip_id = captured_clip_id[0]

        # ── Step 2: list → verify clip appears ───────────────────
        list_code, list_envelopes = run_sdk_cli(["list"])
        assert list_code == 0
        list_results = [e for e in list_envelopes if e["type"] == "result"]
        list_ids = {_unwrap_data(r).get("id") for r in list_results}
        assert clip_id in list_ids, f"Clip {clip_id} not found in list results: {list_ids}"

        # ── Step 3: get <id> → verify full details ───────────────
        get_code, get_envelopes = run_sdk_cli(["get", str(clip_id)])
        assert get_code == 0
        get_results = [e for e in get_envelopes if e["type"] == "result"]
        assert len(get_results) == 1
        assert _unwrap_data(get_results[0])["id"] == clip_id

        # ── Step 4: search 'E2E test' → verify found ─────────────
        search_code, search_envelopes = run_sdk_cli(["search", "E2E test"])
        assert search_code == 0
        search_results = [e for e in search_envelopes if e["type"] == "result"]
        search_ids = {_unwrap_data(r).get("id") for r in search_results}
        assert clip_id in search_ids, f"Clip {clip_id} not found in search results"

        # ── Step 5: update <id> --dynamic → verify update ────────
        update_code, update_envelopes = run_sdk_cli(["update", str(clip_id), "--dynamic"])
        assert update_code == 0
        update_results = [e for e in update_envelopes if e["type"] == "result"]
        assert len(update_results) == 1
        data = _unwrap_data(update_results[0])
        assert data["id"] == clip_id
        assert data["is_dynamic"] == 1

        # ── Step 6: delete <id> → verify delete result ───────────
        del_folder = populated_cli_config.parent / "del" if False else clip_folder
        delete_code, delete_envelopes = run_sdk_cli(["delete", str(clip_id)])
        assert delete_code == 0
        delete_results = [e for e in delete_envelopes if e["type"] == "result"]
        assert len(delete_results) == 1
        assert _unwrap_data(delete_results[0])["id"] == clip_id

        # ── Step 7: get <id> → verify NOT_FOUND ──────────────────
        get_again_code, get_again_envelopes = run_sdk_cli(["get", str(clip_id)])
        assert get_again_code != 0
        errors = [e for e in get_again_envelopes if e["type"] == "error"]
        assert len(errors) >= 1
        assert errors[0].get("error_code") == "NOT_FOUND"


# ═══════════════════════════════════════════════════════════════════
#  TestHelpAndQuiet
# ═══════════════════════════════════════════════════════════════════


class TestHelpAndQuiet:
    """--help and --quiet produce correct JSONL output."""

    # ── root --help ──────────────────────────────────────────────

    def test_root_help(self, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["--help"])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) >= 1
        data = _unwrap_data(results[0])
        assert "description" in data
        cmd_names = [c["name"] for c in data["commands"]]
        assert "clip" in cmd_names
        assert "list" in cmd_names

    # ── no subcommand (same as root help) ────────────────────────

    def test_no_subcommand(self, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli([])
        assert code == 0
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) >= 1

    # ── each leaf command --help ─────────────────────────────────
    # Note: leaf --help is handled by Click's built-in help renderer
    # which writes to sys.stdout (the _FakeStream inside App.run()),
    # not the SDK Writer. Use subprocess for these.

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
        code, stdout, stderr = _run_subprocess(subcmd, "--help")
        assert code == 0, f"Exit code {code}: {stderr}"
        msgs = _validate_all_jsonl(stdout)
        results = [m for m in msgs if m["type"] == "result"]
        assert len(results) >= 1

    # ── --quiet list → no progress lines ─────────────────────────

    def test_quiet_list_no_progress(self, populated_cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["--quiet", "list"])
        assert code == 0
        types = [e["type"] for e in envelopes]
        assert "progress" not in types
        assert "result" in types

    # ── --quiet tags → no progress lines ─────────────────────────

    def test_quiet_tags_no_progress(self, populated_cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["--quiet", "tags"])
        assert code == 0
        types = [e["type"] for e in envelopes]
        assert "progress" not in types
        assert "result" in types
