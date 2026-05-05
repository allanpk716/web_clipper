"""Tests for the update CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex


# ── Fixtures ──────────────────────────────────────────────────────────


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


def _insert_clip(db_path: Path, **overrides) -> int:
    """Insert a clip into the DB and return its ID."""
    idx = ClipIndex(db_path)
    defaults = {
        "url": "https://example.com",
        "title": "Test Clip",
        "source_type": "web",
        "category": "article",
        "tags": json.dumps(["default"]),
        "folder_path": "/clips/test",
        "markdown_path": "/clips/test/test.md",
    }
    defaults.update(overrides)
    cid = idx.save_clip(defaults)
    idx.close()
    return cid


# ── Tests: --title ────────────────────────────────────────────────────


class TestUpdateTitle:
    def test_set_title(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --title 'New Title' updates the title."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--title", "New Title"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["id"] == cid
        assert results[0]["data"]["title"] == "New Title"

        # Verify in DB
        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["title"] == "New Title"

    def test_set_title_empty_string(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --title '' sets title to empty string."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--title", ""])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["title"] == ""

        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["title"] == ""

    def test_set_title_unicode(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --title with unicode characters."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--title", "中文标题 🎉"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["title"] == "中文标题 🎉"

        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["title"] == "中文标题 🎉"


# ── Tests: --tags ─────────────────────────────────────────────────────


class TestUpdateTags:
    def test_set_tags(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --tags '[\"a\",\"b\"]' updates tags."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--tags", '["a","b"]'])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["tags"] == ["a", "b"]

        # Verify in DB
        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["tags"] == ["a", "b"]

    def test_set_tags_empty_array(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --tags '[]' clears tags."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--tags", "[]"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["tags"] == []

        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["tags"] == []

    def test_set_tags_single(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --tags '[\"only\"]' sets single tag."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--tags", '["only"]'])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["tags"] == ["only"]

    def test_tags_invalid_json(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --tags 'not-json' → error."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--tags", "not-json"])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert "invalid tags json" in errors[0]["message"].lower()

    def test_tags_not_array(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --tags '\"single\"' → error (not an array)."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--tags", '"single"'])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert "must be a json array" in errors[0]["message"].lower()

    def test_tags_non_string_element(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --tags '[1,2]' → error (elements not strings)."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--tags", "[1,2]"])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert "not a string" in errors[0]["message"].lower()


# ── Tests: --category ─────────────────────────────────────────────────


class TestUpdateCategory:
    def test_set_category(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --category 'blog' updates category."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--category", "blog"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["category"] == "blog"

        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["category"] == "blog"

    def test_set_category_empty(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --category '' clears category."""
        cid = _insert_clip(cli_config, category="tech")
        code, envelopes = run_sdk_cli(["update", str(cid), "--category", ""])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["category"] == ""

        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["category"] == ""


# ── Tests: existing dynamic/interval (preserved) ─────────────────────


class TestUpdateDynamic:
    def test_set_dynamic(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --dynamic sets is_dynamic=1."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--dynamic"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["id"] == cid
        assert results[0]["data"]["is_dynamic"] == 1

        # Verify in DB
        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["is_dynamic"] == 1

    def test_set_no_dynamic(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --no-dynamic sets is_dynamic=0."""
        cid = _insert_clip(cli_config, is_dynamic=1)
        code, envelopes = run_sdk_cli(["update", str(cid), "--no-dynamic"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["is_dynamic"] == 0

        # Verify in DB
        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["is_dynamic"] == 0


class TestUpdateInterval:
    def test_set_interval(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --interval 3 sets refresh_interval_days=3."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--interval", "3"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["refresh_interval_days"] == 3

        # Verify in DB
        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["refresh_interval_days"] == 3

    def test_set_interval_minimum(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --interval 1 (minimum valid value) succeeds."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--interval", "1"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["refresh_interval_days"] == 1


# ── Tests: combinations ───────────────────────────────────────────────


class TestUpdateBoth:
    def test_set_dynamic_and_interval(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --dynamic --interval 7 sets both fields."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--dynamic", "--interval", "7"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["is_dynamic"] == 1
        assert results[0]["data"]["refresh_interval_days"] == 7

        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["is_dynamic"] == 1
        assert clip["refresh_interval_days"] == 7

    def test_set_title_and_tags(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --title X --tags '[\"a\"]' sets both."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--title", "New", "--tags", '["a"]'])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["title"] == "New"
        assert results[0]["data"]["tags"] == ["a"]

        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["title"] == "New"
        assert clip["tags"] == ["a"]

    def test_set_title_tags_category(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --title --tags --category sets all three."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--title", "T", "--tags", '["x"]', "--category", "news"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["title"] == "T"
        assert results[0]["data"]["tags"] == ["x"]
        assert results[0]["data"]["category"] == "news"

        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["title"] == "T"
        assert clip["tags"] == ["x"]
        assert clip["category"] == "news"

    def test_set_all_options(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> with all options at once."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli([
            "update", str(cid),
            "--title", "Full Update",
            "--tags", '["tag1","tag2"]',
            "--category", "docs",
            "--dynamic",
            "--interval", "14",
        ])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        r = results[0]["data"]
        assert r["title"] == "Full Update"
        assert r["tags"] == ["tag1", "tag2"]
        assert r["category"] == "docs"
        assert r["is_dynamic"] == 1
        assert r["refresh_interval_days"] == 14

        # Verify all in DB
        idx = ClipIndex(cli_config)
        clip = idx.get_clip(cid)
        idx.close()
        assert clip["title"] == "Full Update"
        assert clip["tags"] == ["tag1", "tag2"]
        assert clip["category"] == "docs"
        assert clip["is_dynamic"] == 1
        assert clip["refresh_interval_days"] == 14


# ── Tests: error cases ───────────────────────────────────────────────


class TestUpdateErrors:
    def test_no_options(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> with no options → error + exit 1."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid)])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert "at least one option" in errors[0]["message"].lower()

    def test_nonexistent_id(self, cli_config: Path, run_sdk_cli) -> None:
        """update 999 --dynamic with non-existent ID → error + exit 1."""
        code, envelopes = run_sdk_cli(["update", "999", "--dynamic"])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert "not found" in errors[0]["message"]

    def test_interval_zero(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --interval 0 → error + exit 1."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--interval", "0"])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert "invalid interval" in errors[0]["message"].lower()

    def test_interval_negative(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --interval -1 → error + exit 1."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--interval", "-1"])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert "invalid interval" in errors[0]["message"].lower()

    def test_title_only_is_valid(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --title 'X' is valid (no dynamic/interval needed)."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--title", "Just Title"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["title"] == "Just Title"

    def test_tags_only_is_valid(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --tags '[\"x\"]' is valid (no dynamic/interval needed)."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--tags", '["x"]'])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["tags"] == ["x"]

    def test_category_only_is_valid(self, cli_config: Path, run_sdk_cli) -> None:
        """update <id> --category 'docs' is valid (no dynamic/interval needed)."""
        cid = _insert_clip(cli_config)
        code, envelopes = run_sdk_cli(["update", str(cid), "--category", "docs"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["category"] == "docs"
