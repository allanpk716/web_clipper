"""Tests for refresh command: preserve original tags/category/title + --re-enrich option."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from web_clip_helper.cli import app
from web_clip_helper.config import Config, LLMConfig
from web_clip_helper.index import ClipIndex
from web_clip_helper.models import ClipResult

runner = CliRunner()


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Create a temp config + DB, patch get_config to use it."""
    import web_clip_helper.config as cfg_mod

    db_path = str(tmp_path / "clips.db")
    storage_path = tmp_path / "clips"
    storage_path.mkdir()

    config = Config(
        storage_path=str(storage_path),
        db_path=db_path,
        llm=LLMConfig(api_key="test-key", base_url="https://api.test.com", model="test-model"),
    )
    config.save(tmp_path / "config.yaml")

    # Patch the module-level singleton so get_config() returns our config
    monkeypatch.setattr(cfg_mod, "_cached_config", config)

    return {"db_path": db_path, "storage_path": str(storage_path)}


def _make_dynamic_clip(idx: ClipIndex, storage_path: str, tags: list[str] | None = None, category: str = "", title: str = "Original Title") -> int:
    """Insert a dynamic clip that is due for refresh."""
    folder = Path(storage_path) / "test-clip"
    folder.mkdir(exist_ok=True)
    md_path = folder / "article.md"
    md_path.write_text("# Original content\n\nSome content here.", encoding="utf-8")

    clip_id = idx.save_clip({
        "url": "https://example.com/test-article",
        "title": title,
        "source_type": "web",
        "category": category,
        "tags": tags if tags is not None else ["original-tag"],
        "folder_path": str(folder),
        "markdown_path": str(md_path),
        "is_dynamic": 1,
        "refresh_interval_days": 7,
    })
    return clip_id


def _fake_clip_result(storage_path: str, clip_id: int) -> ClipResult:
    """Create a fake ClipResult simulating a successful re-clip."""
    new_folder = Path(storage_path) / f"refreshed-clip-{clip_id}"
    new_folder.mkdir(exist_ok=True)
    new_md = new_folder / "refreshed.md"
    new_md.write_text("# Refreshed content\n\nNew content after refresh.", encoding="utf-8")
    return ClipResult(
        folder_path=new_folder,
        markdown_path=new_md,
        image_count=2,
        record_id=clip_id,
    )


# ── Tests: Default mode preserves tags/category/title ─────────────────


class TestDefaultPreserve:
    """refresh without --re-enrich should preserve original metadata."""

    def test_preserves_tags(self, tmp_path: Path, cli_env: dict) -> None:
        """Original tags are kept after refresh."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["python", "guide"], category="tech", title="My Guide")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            result = runner.invoke(app, ["refresh"])

        assert result.exit_code == 0

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["tags"] == ["python", "guide"], f"Tags should be preserved, got {record['tags']}"

    def test_preserves_category(self, tmp_path: Path, cli_env: dict) -> None:
        """Original category is kept after refresh."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["tag1"], category="science", title="Science Article")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            result = runner.invoke(app, ["refresh"])

        assert result.exit_code == 0

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["category"] == "science", f"Category should be preserved, got {record['category']}"

    def test_preserves_title(self, tmp_path: Path, cli_env: dict) -> None:
        """Original title is kept after refresh."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="c", title="My Original Title")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            result = runner.invoke(app, ["refresh"])

        assert result.exit_code == 0

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["title"] == "My Original Title", f"Title should be preserved, got {record['title']}"

    def test_preserves_empty_tags(self, tmp_path: Path, cli_env: dict) -> None:
        """Empty tags list is preserved (not replaced with LLM output)."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=[], category="", title="No Tags")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            result = runner.invoke(app, ["refresh"])

        assert result.exit_code == 0

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["tags"] == [], f"Empty tags should be preserved, got {record['tags']}"

    def test_preserves_empty_category(self, tmp_path: Path, cli_env: dict) -> None:
        """Empty category string is preserved."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="", title="No Category")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            result = runner.invoke(app, ["refresh"])

        assert result.exit_code == 0

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["category"] == "", f"Empty category should be preserved, got '{record['category']}'"


# ── Tests: --re-enrich mode regenerates tags/category ──────────────────


class TestReEnrich:
    """refresh --re-enrich should regenerate tags/category via LLM."""

    def test_re_enrich_updates_tags(self, tmp_path: Path, cli_env: dict) -> None:
        """--re-enrich regenerates tags via LLM."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["old-tag"], category="old-cat", title="Re-Enrich Me")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        mock_llm_client = MagicMock()
        mock_llm_client.extract_tags.return_value = ["new-tag-1", "new-tag-2"]
        mock_llm_client.classify_content.return_value = "new-category"

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result), \
             patch("web_clip_helper.llm.LLMClient", return_value=mock_llm_client):
            result = runner.invoke(app, ["refresh", "--re-enrich"])

        assert result.exit_code == 0

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["tags"] == ["new-tag-1", "new-tag-2"], f"Tags should be regenerated, got {record['tags']}"

    def test_re_enrich_updates_category(self, tmp_path: Path, cli_env: dict) -> None:
        """--re-enrich regenerates category via LLM."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="old-cat", title="Re-Enrich Cat")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        mock_llm_client = MagicMock()
        mock_llm_client.extract_tags.return_value = ["updated-tag"]
        mock_llm_client.classify_content.return_value = "technology"

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result), \
             patch("web_clip_helper.llm.LLMClient", return_value=mock_llm_client):
            result = runner.invoke(app, ["refresh", "--re-enrich"])

        assert result.exit_code == 0

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["category"] == "technology", f"Category should be regenerated, got {record['category']}"

    def test_re_enrich_preserves_title(self, tmp_path: Path, cli_env: dict) -> None:
        """--re-enrich should still preserve the original title."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="c", title="Keep This Title")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        mock_llm_client = MagicMock()
        mock_llm_client.extract_tags.return_value = ["new"]
        mock_llm_client.classify_content.return_value = "new-cat"

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result), \
             patch("web_clip_helper.llm.LLMClient", return_value=mock_llm_client):
            result = runner.invoke(app, ["refresh", "--re-enrich"])

        assert result.exit_code == 0

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["title"] == "Keep This Title", f"Title should still be preserved under --re-enrich, got {record['title']}"

    def test_re_enrich_llm_failure_keeps_original(self, tmp_path: Path, cli_env: dict) -> None:
        """If LLM fails during --re-enrich, original tags/category are kept."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["original"], category="original-cat", title="Fallback Test")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        mock_llm_client = MagicMock()
        mock_llm_client.extract_tags.side_effect = RuntimeError("LLM unavailable")
        mock_llm_client.classify_content.return_value = "should-not-appear"

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result), \
             patch("web_clip_helper.llm.LLMClient", return_value=mock_llm_client):
            result = runner.invoke(app, ["refresh", "--re-enrich"])

        assert result.exit_code == 0

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["tags"] == ["original"], "Tags should be preserved on LLM failure"
        assert record["category"] == "original-cat", "Category should be preserved on LLM failure"


# ── Tests: JSONL output includes re_enrich flag ──────────────────────


class TestJsonlOutput:
    """JSONL progress/result lines should include re_enrich field."""

    def test_default_mode_no_re_enrich_flag(self, tmp_path: Path, cli_env: dict) -> None:
        """Default refresh emits re_enrich=false in progress."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="c")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            result = runner.invoke(app, ["refresh"])

        assert result.exit_code == 0
        # Parse JSONL output — at least one progress line should have re_enrich=false
        lines = [json.loads(l) for l in result.output.strip().split("\n") if l.strip()]
        progress_lines = [l for l in lines if l.get("type") == "progress"]
        assert any(l.get("re_enrich") is False for l in progress_lines), "Should emit re_enrich=false in default mode"

    def test_re_enrich_flag_in_jsonl(self, tmp_path: Path, cli_env: dict) -> None:
        """--re-enrich mode emits re_enrich=true in progress."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="c")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        mock_llm_client = MagicMock()
        mock_llm_client.extract_tags.return_value = ["new"]
        mock_llm_client.classify_content.return_value = "new"

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result), \
             patch("web_clip_helper.llm.LLMClient", return_value=mock_llm_client):
            result = runner.invoke(app, ["refresh", "--re-enrich"])

        assert result.exit_code == 0
        lines = [json.loads(l) for l in result.output.strip().split("\n") if l.strip()]
        progress_lines = [l for l in lines if l.get("type") == "progress"]
        assert any(l.get("re_enrich") is True for l in progress_lines), "Should emit re_enrich=true in --re-enrich mode"

    def test_result_line_includes_re_enrich(self, tmp_path: Path, cli_env: dict) -> None:
        """Final result line includes re_enrich field."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="c")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            result = runner.invoke(app, ["refresh"])

        assert result.exit_code == 0
        lines = [json.loads(l) for l in result.output.strip().split("\n") if l.strip()]
        result_lines = [l for l in lines if l.get("type") == "result"]
        assert len(result_lines) > 0, "Should have at least one result line"
        last_result = result_lines[-1]
        assert "re_enrich" in last_result, f"Result line should include re_enrich, got keys: {last_result.keys()}"
        assert last_result["re_enrich"] is False

    def test_no_refreshable_clips(self, tmp_path: Path, cli_env: dict) -> None:
        """When no clips are refreshable, emits clean result."""
        # No clips inserted → nothing to refresh
        result = runner.invoke(app, ["refresh"])
        assert result.exit_code == 0
        lines = [json.loads(l) for l in result.output.strip().split("\n") if l.strip()]
        result_lines = [l for l in lines if l.get("type") == "result"]
        assert any(l.get("refreshed") == 0 for l in result_lines)
