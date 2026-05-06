"""Tests for pagination metadata (_total_count, _limit, _offset) in list/search result lines."""

from __future__ import annotations

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

    # Patch the module-level singleton
    monkeypatch.setattr(cfg_mod, "_cached_config", config)
    return tmp_path / "clips.db"


class TestListPaginationMetadata:
    """Verify list command result envelopes include pagination metadata."""

    def test_list_pagination_with_limit_offset(self, cli_config: Path, run_sdk_cli) -> None:
        """list --limit 1 --offset 0 should include _total_count=3, _limit=1, _offset=0."""
        idx = ClipIndex(cli_config)
        for i in range(3):
            idx.save_clip({
                "url": f"https://example.com/{i}",
                "title": f"Clip {i}",
                "source_type": "web",
                "folder_path": f"/{i}",
                "markdown_path": f"/{i}.md",
            })
        idx.close()

        code, envelopes = run_sdk_cli(["list", "--limit", "1", "--offset", "0"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1

        data = results[0]["data"]
        assert data["_total_count"] == 3
        assert data["_limit"] == 1
        assert data["_offset"] == 0

    def test_list_pagination_no_limit_offset(self, cli_config: Path, run_sdk_cli) -> None:
        """list without --limit/--offset should have _limit=None, _offset=0."""
        idx = ClipIndex(cli_config)
        for i in range(3):
            idx.save_clip({
                "url": f"https://example.com/{i}",
                "title": f"Clip {i}",
                "source_type": "web",
                "folder_path": f"/{i}",
                "markdown_path": f"/{i}.md",
            })
        idx.close()

        code, envelopes = run_sdk_cli(["list"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 3

        for env in results:
            data = env["data"]
            assert data["_total_count"] == 3
            assert data["_limit"] is None
            assert data["_offset"] == 0

    def test_list_pagination_with_tag_filter(self, cli_config: Path, run_sdk_cli) -> None:
        """list --tag with limit should reflect total matching count."""
        idx = ClipIndex(cli_config)
        for i in range(3):
            idx.save_clip({
                "url": f"https://example.com/{i}",
                "title": f"Clip {i}",
                "source_type": "web",
                "tags": ["python"],
                "folder_path": f"/{i}",
                "markdown_path": f"/{i}.md",
            })
        idx.save_clip({
            "url": "https://example.com/other",
            "title": "Other",
            "source_type": "web",
            "tags": ["java"],
            "folder_path": "/other",
            "markdown_path": "/other.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["list", "--tag", "python", "--limit", "1"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1

        data = results[0]["data"]
        assert data["_total_count"] == 3  # 3 python-tagged clips total
        assert data["_limit"] == 1

    def test_list_pagination_total_count_reflects_all_matching(self, cli_config: Path, run_sdk_cli) -> None:
        """_total_count should reflect total matching rows, not just returned rows."""
        idx = ClipIndex(cli_config)
        for i in range(5):
            idx.save_clip({
                "url": f"https://example.com/{i}",
                "title": f"Clip {i}",
                "source_type": "web",
                "folder_path": f"/{i}",
                "markdown_path": f"/{i}.md",
            })
        idx.close()

        code, envelopes = run_sdk_cli(["list", "--limit", "2", "--offset", "1"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 2

        for env in results:
            data = env["data"]
            assert data["_total_count"] == 5
            assert data["_limit"] == 2
            assert data["_offset"] == 1


class TestSearchPaginationMetadata:
    """Verify search command result envelopes include pagination metadata."""

    def test_search_pagination_metadata(self, cli_config: Path, run_sdk_cli) -> None:
        """search should include _total_count, _limit=None, _offset=0."""
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/python-intro",
            "title": "Python Intro",
            "source_type": "web",
            "folder_path": "/p",
            "markdown_path": "/p.md",
        })
        idx.save_clip({
            "url": "https://example.com/python-guide",
            "title": "Python Guide",
            "source_type": "web",
            "folder_path": "/g",
            "markdown_path": "/g.md",
        })
        idx.save_clip({
            "url": "https://example.com/react-tutorial",
            "title": "React Tutorial",
            "source_type": "web",
            "folder_path": "/r",
            "markdown_path": "/r.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "Python"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 2

        for env in results:
            data = env["data"]
            assert data["_total_count"] == 2
            assert data["_limit"] is None
            assert data["_offset"] == 0

    def test_search_pagination_total_count_matches_results(self, cli_config: Path, run_sdk_cli) -> None:
        """_total_count for search equals len(results) since search has no pagination."""
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/alpha",
            "title": "Alpha Beta",
            "source_type": "web",
            "folder_path": "/a",
            "markdown_path": "/a.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "Alpha"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1

        data = results[0]["data"]
        assert data["_total_count"] == 1
