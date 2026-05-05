"""Tests for refresh command: preserve original tags/category/title + --re-enrich option."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from web_clip_helper.config import Config, LLMConfig
from web_clip_helper.index import ClipIndex
from web_clip_helper.models import ClipResult


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
    config.save(tmp_path / "config.json")

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

    def test_preserves_tags(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
        """Original tags are kept after refresh."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["python", "guide"], category="tech", title="My Guide")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            code, envelopes = run_sdk_cli(["refresh"])

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["tags"] == ["python", "guide"], f"Tags should be preserved, got {record['tags']}"

    def test_preserves_category(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
        """Original category is kept after refresh."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["tag1"], category="science", title="Science Article")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            code, envelopes = run_sdk_cli(["refresh"])

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["category"] == "science", f"Category should be preserved, got {record['category']}"

    def test_preserves_title(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
        """Original title is kept after refresh."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="c", title="My Original Title")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            code, envelopes = run_sdk_cli(["refresh"])

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["title"] == "My Original Title", f"Title should be preserved, got {record['title']}"

    def test_preserves_empty_tags(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
        """Empty tags list is preserved (not replaced with LLM output)."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=[], category="", title="No Tags")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            code, envelopes = run_sdk_cli(["refresh"])

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["tags"] == [], f"Empty tags should be preserved, got {record['tags']}"

    def test_preserves_empty_category(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
        """Empty category string is preserved."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="", title="No Category")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            code, envelopes = run_sdk_cli(["refresh"])

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["category"] == "", f"Empty category should be preserved, got '{record['category']}'"


# ── Tests: --re-enrich mode regenerates tags/category ──────────────────


class TestReEnrich:
    """refresh --re-enrich should regenerate tags/category via LLM."""

    def test_re_enrich_updates_tags(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
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
            code, envelopes = run_sdk_cli(["refresh", "--re-enrich"])

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["tags"] == ["new-tag-1", "new-tag-2"], f"Tags should be regenerated, got {record['tags']}"

    def test_re_enrich_updates_category(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
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
            code, envelopes = run_sdk_cli(["refresh", "--re-enrich"])

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["category"] == "technology", f"Category should be regenerated, got {record['category']}"

    def test_re_enrich_preserves_title(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
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
            code, envelopes = run_sdk_cli(["refresh", "--re-enrich"])

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["title"] == "Keep This Title", f"Title should still be preserved under --re-enrich, got {record['title']}"

    def test_re_enrich_llm_failure_keeps_original(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
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
            code, envelopes = run_sdk_cli(["refresh", "--re-enrich"])

        idx = ClipIndex(cli_env["db_path"])
        record = idx.get_clip(clip_id)
        idx.close()

        assert record is not None
        assert record["tags"] == ["original"], "Tags should be preserved on LLM failure"
        assert record["category"] == "original-cat", "Category should be preserved on LLM failure"


# ── Tests: JSONL output via SDK Envelopes ─────────────────────────────


class TestJsonlOutput:
    """Verify refresh JSONL output via SDK envelopes.

    The SDK Writer wraps output in envelopes with version/tool/type/timestamp.
    Result data is inside envelope.data.
    """

    def test_default_mode_emits_result(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
        """Default refresh emits result envelopes."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="c")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            code, envelopes = run_sdk_cli(["refresh"])

        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) >= 1, "Should have at least one result envelope"
        # Result data should contain refresh info
        data = results[-1]["data"]
        assert "stage" in data, f"Result data should include stage, got keys: {data.keys()}"

    def test_re_enrich_mode_emits_result(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
        """--re-enrich mode emits result envelopes."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="c")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        mock_llm_client = MagicMock()
        mock_llm_client.extract_tags.return_value = ["new"]
        mock_llm_client.classify_content.return_value = "new"

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result), \
             patch("web_clip_helper.llm.LLMClient", return_value=mock_llm_client):
            code, envelopes = run_sdk_cli(["refresh", "--re-enrich"])

        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) >= 1, "Should have at least one result envelope"

    def test_result_envelope_has_data(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
        """Final result envelope includes data payload."""
        idx = ClipIndex(cli_env["db_path"])
        clip_id = _make_dynamic_clip(idx, cli_env["storage_path"], tags=["t"], category="c")
        idx.close()

        fake_result = _fake_clip_result(cli_env["storage_path"], clip_id)

        with patch("web_clip_helper.pipeline.clip_url", return_value=fake_result):
            code, envelopes = run_sdk_cli(["refresh"])

        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) > 0, "Should have at least one result envelope"
        last_result = results[-1]
        assert "data" in last_result, f"Result envelope should include data, got keys: {last_result.keys()}"

    def test_no_refreshable_clips(self, tmp_path: Path, cli_env: dict, run_sdk_cli) -> None:
        """When no clips are refreshable, emits clean result."""
        # No clips inserted → nothing to refresh
        code, envelopes = run_sdk_cli(["refresh"])
        results = [e for e in envelopes if e["type"] == "result"]
        # Should emit a result indicating 0 refreshed
        assert len(results) >= 1
        data = results[-1]["data"]
        assert data.get("refreshed") == 0
