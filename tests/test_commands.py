"""Tests for list / get / search / tags CLI commands and ClipIndex methods."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from web_clip_helper.config import Config
from web_clip_helper.index import ClipIndex


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_db(tmp_path: Path) -> ClipIndex:
    """Return a ClipIndex backed by a temp database."""
    db_path = tmp_path / "test.db"
    return ClipIndex(db_path)


@pytest.fixture()
def populated_db(tmp_path: Path) -> ClipIndex:
    """Return a ClipIndex with several sample clips inserted."""
    idx = ClipIndex(tmp_path / "clips.db")
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
    return idx


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


# ── ClipIndex method tests ───────────────────────────────────────────


class TestQueryByTag:
    def test_returns_matching_clips(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips_by_tag("python")
        assert len(results) == 2
        titles = {r["title"] for r in results}
        assert "Python Guide" in titles
        assert "FastAPI GitHub Repo" in titles

    def test_returns_empty_for_unknown_tag(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips_by_tag("nonexistent")
        assert results == []

    def test_tag_filter_on_empty_db(self, tmp_db: ClipIndex) -> None:
        results = tmp_db.query_clips_by_tag("anything")
        assert results == []


class TestQueryClipsPagination:
    """Pagination tests for ClipIndex.query_clips and query_clips_by_tag."""

    def test_query_clips_limit(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips(limit=2)
        assert len(results) == 2

    def test_query_clips_offset(self, populated_db: ClipIndex) -> None:
        all_results = populated_db.query_clips()
        offset_results = populated_db.query_clips(offset=1)
        assert len(offset_results) == len(all_results) - 1

    def test_query_clips_limit_and_offset(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips(limit=1, offset=1)
        assert len(results) == 1

    def test_query_clips_offset_beyond_results(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips(offset=100)
        assert results == []

    def test_query_clips_limit_zero(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips(limit=0)
        assert results == []

    def test_query_clips_with_filter_and_limit(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips(filters={"category": "tech"}, limit=1)
        all_tech = populated_db.query_clips(filters={"category": "tech"})
        assert len(results) == 1
        assert len(results) <= len(all_tech)

    def test_query_clips_by_tag_limit(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips_by_tag("python", limit=1)
        assert len(results) == 1

    def test_query_clips_by_tag_offset(self, populated_db: ClipIndex) -> None:
        all_results = populated_db.query_clips_by_tag("python")
        offset_results = populated_db.query_clips_by_tag("python", offset=1)
        assert len(offset_results) == len(all_results) - 1

    def test_query_clips_by_tag_limit_and_offset(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips_by_tag("python", limit=1, offset=0)
        assert len(results) == 1

    def test_query_clips_by_tag_offset_beyond_results(self, populated_db: ClipIndex) -> None:
        results = populated_db.query_clips_by_tag("python", offset=100)
        assert results == []

    def test_query_clips_no_pagination(self, populated_db: ClipIndex) -> None:
        """Without limit/offset, returns all results (backward compat)."""
        results = populated_db.query_clips()
        assert len(results) == 3

    def test_query_clips_by_tag_no_pagination(self, populated_db: ClipIndex) -> None:
        """Without limit/offset, returns all results (backward compat)."""
        results = populated_db.query_clips_by_tag("python")
        assert len(results) == 2


class TestSearchClips:
    def test_search_by_title(self, populated_db: ClipIndex) -> None:
        results = populated_db.search_clips("Python")
        assert len(results) == 1
        assert results[0]["title"] == "Python Guide"

    def test_search_by_url(self, populated_db: ClipIndex) -> None:
        results = populated_db.search_clips("fastapi")
        assert len(results) == 1
        assert "fastapi" in results[0]["url"]

    def test_search_case_insensitive(self, populated_db: ClipIndex) -> None:
        results = populated_db.search_clips("REACT")
        assert len(results) == 1
        assert results[0]["title"] == "React Tutorial"

    def test_search_no_match(self, populated_db: ClipIndex) -> None:
        results = populated_db.search_clips("nonexistent-keyword-xyz")
        assert results == []

    def test_search_empty_keyword(self, populated_db: ClipIndex) -> None:
        # Empty keyword matches everything via LIKE '%%'
        results = populated_db.search_clips("")
        assert len(results) == 3


class TestListTags:
    def test_returns_tags_with_counts(self, populated_db: ClipIndex) -> None:
        tags = populated_db.list_tags()
        tag_map = {t["tag"]: t["count"] for t in tags}
        assert tag_map["python"] == 2
        assert tag_map["guide"] == 1
        assert tag_map["react"] == 1
        assert tag_map["fastapi"] == 1

    def test_sorted_by_count_desc(self, populated_db: ClipIndex) -> None:
        tags = populated_db.list_tags()
        counts = [t["count"] for t in tags]
        assert counts == sorted(counts, reverse=True)

    def test_empty_db(self, tmp_db: ClipIndex) -> None:
        tags = tmp_db.list_tags()
        assert tags == []


class TestDeleteClip:
    def test_delete_existing(self, populated_db: ClipIndex) -> None:
        all_clips = populated_db.query_clips()
        clip_id = all_clips[0]["id"]
        assert populated_db.delete_clip(clip_id) is True
        assert populated_db.get_clip(clip_id) is None

    def test_delete_nonexistent(self, tmp_db: ClipIndex) -> None:
        assert tmp_db.delete_clip(99999) is False


# ── CLI integration tests ────────────────────────────────────────────


class TestCLIList:
    def test_list_all(self, cli_config: Path, run_sdk_cli) -> None:
        # Populate the DB
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://a.com", "title": "A",
            "source_type": "web", "folder_path": "/a", "markdown_path": "/a.md",
        })
        idx.save_clip({
            "url": "https://b.com", "title": "B",
            "source_type": "web", "folder_path": "/b", "markdown_path": "/b.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["list"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 2

    def test_list_by_tag(self, cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://a.com", "title": "A",
            "source_type": "web", "tags": ["python"],
            "folder_path": "/a", "markdown_path": "/a.md",
        })
        idx.save_clip({
            "url": "https://b.com", "title": "B",
            "source_type": "web", "tags": ["java"],
            "folder_path": "/b", "markdown_path": "/b.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["list", "--tag", "python"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["title"] == "A"

    def test_list_empty_db(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["list"])
        results = [e for e in envelopes if e["type"] == "result"]
        # Empty DB now emits a count:0 result line (R037)
        assert len(results) == 1
        assert results[0]["data"].get("count") == 0
        assert results[0]["data"].get("_total_count") == 0

    def test_list_combined_filters(self, cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://a.com", "title": "A",
            "source_type": "web", "category": "tech",
            "folder_path": "/a", "markdown_path": "/a.md",
        })
        idx.save_clip({
            "url": "https://b.com", "title": "B",
            "source_type": "github", "category": "code",
            "folder_path": "/b", "markdown_path": "/b.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["list", "--source-type", "web", "--category", "tech"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["title"] == "A"

    def test_list_with_limit(self, cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(cli_config)
        for i in range(5):
            idx.save_clip({
                "url": f"https://example.com/{i}", "title": f"Clip {i}",
                "source_type": "web", "folder_path": f"/{i}", "markdown_path": f"/{i}.md",
            })
        idx.close()

        code, envelopes = run_sdk_cli(["list", "--limit", "2"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 2

    def test_list_with_offset(self, cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(cli_config)
        for i in range(5):
            idx.save_clip({
                "url": f"https://example.com/{i}", "title": f"Clip {i}",
                "source_type": "web", "folder_path": f"/{i}", "markdown_path": f"/{i}.md",
            })
        idx.close()

        code, envelopes = run_sdk_cli(["list", "--offset", "3"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 2

    def test_list_with_limit_and_offset(self, cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(cli_config)
        for i in range(5):
            idx.save_clip({
                "url": f"https://example.com/{i}", "title": f"Clip {i}",
                "source_type": "web", "folder_path": f"/{i}", "markdown_path": f"/{i}.md",
            })
        idx.close()

        code, envelopes = run_sdk_cli(["list", "--limit", "2", "--offset", "1"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 2

    def test_list_offset_beyond_results(self, cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://a.com", "title": "A",
            "source_type": "web", "folder_path": "/a", "markdown_path": "/a.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["list", "--offset", "100"])
        results = [e for e in envelopes if e["type"] == "result"]
        # Offset beyond results now emits a count:0 result line (R037)
        assert len(results) == 1
        assert results[0]["data"].get("count") == 0

    def test_list_limit_with_tag_filter(self, cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://a.com", "title": "A",
            "source_type": "web", "tags": ["python"],
            "folder_path": "/a", "markdown_path": "/a.md",
        })
        idx.save_clip({
            "url": "https://b.com", "title": "B",
            "source_type": "web", "tags": ["python"],
            "folder_path": "/b", "markdown_path": "/b.md",
        })
        idx.save_clip({
            "url": "https://c.com", "title": "C",
            "source_type": "web", "tags": ["java"],
            "folder_path": "/c", "markdown_path": "/c.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["list", "--tag", "python", "--limit", "1"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1

    def test_list_invalid_limit(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["list", "--limit", "0"])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert "Invalid limit" in errors[0]["message"]

    def test_list_invalid_offset(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["list", "--offset", "-1"])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert "Invalid offset" in errors[0]["message"]


class TestCLIGet:
    def test_get_existing(self, cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(cli_config)
        cid = idx.save_clip({
            "url": "https://example.com", "title": "Test",
            "source_type": "web", "folder_path": "/x", "markdown_path": "/x.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["get", str(cid)])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        data = results[0]["data"]
        assert data["id"] == cid
        assert data["title"] == "Test"

    def test_get_nonexistent(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["get", "99999"])
        errors = [e for e in envelopes if e["type"] == "error"]
        assert len(errors) == 1
        assert "not found" in errors[0]["message"]


class TestCLISearch:
    def test_search_with_results(self, cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/python", "title": "Python Intro",
            "source_type": "web", "folder_path": "/p", "markdown_path": "/p.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "python"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["title"] == "Python Intro"

    def test_search_no_results(self, cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com", "title": "Test",
            "source_type": "web", "folder_path": "/x", "markdown_path": "/x.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["search", "nonexistent-keyword"])
        results = [e for e in envelopes if e["type"] == "result"]
        # No matches now emit a count:0 result line (R037)
        assert len(results) == 1
        assert results[0]["data"].get("count") == 0
        assert results[0]["data"].get("_total_count") == 0


class TestCLITags:
    def test_tags_with_data(self, cli_config: Path, run_sdk_cli) -> None:
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://a.com", "title": "A",
            "source_type": "web", "tags": ["python", "web"],
            "folder_path": "/a", "markdown_path": "/a.md",
        })
        idx.save_clip({
            "url": "https://b.com", "title": "B",
            "source_type": "web", "tags": ["python"],
            "folder_path": "/b", "markdown_path": "/b.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["tags"])
        results = [e for e in envelopes if e["type"] == "result"]
        tag_map = {r["data"]["tag"]: r["data"]["count"] for r in results}
        assert tag_map["python"] == 2
        assert tag_map["web"] == 1

    def test_tags_empty_db(self, cli_config: Path, run_sdk_cli) -> None:
        code, envelopes = run_sdk_cli(["tags"])
        results = [e for e in envelopes if e["type"] == "result"]
        # Empty DB now emits a count:0 result line (R037)
        assert len(results) == 1
        assert results[0]["data"].get("count") == 0


# ── Refresh tests ───────────────────────────────────────────────────────


class TestRefreshIndex:
    """Tests for ClipIndex refresh-related methods."""

    def test_get_refreshable_empty_db(self, tmp_db: ClipIndex) -> None:
        """No clips at all → empty list."""
        assert tmp_db.get_refreshable_clips() == []

    def test_no_dynamic_clips(self, tmp_db: ClipIndex) -> None:
        """Non-dynamic clips should never be returned."""
        tmp_db.save_clip({
            "url": "https://example.com",
            "title": "Static",
            "source_type": "web",
            "is_dynamic": 0,
            "folder_path": "/clips/static",
            "markdown_path": "/clips/static/s.md",
        })
        assert tmp_db.get_refreshable_clips() == []

    def test_dynamic_never_refreshed(self, tmp_db: ClipIndex) -> None:
        """Dynamic clip with no last_refreshed_at → is refreshable."""
        tmp_db.save_clip({
            "url": "https://example.com/live",
            "title": "Live",
            "source_type": "web",
            "is_dynamic": 1,
            "refresh_interval_days": 7,
            "last_refreshed_at": "",
            "folder_path": "/clips/live",
            "markdown_path": "/clips/live/live.md",
        })
        results = tmp_db.get_refreshable_clips()
        assert len(results) == 1
        assert results[0]["title"] == "Live"

    def test_dynamic_expired(self, tmp_db: ClipIndex) -> None:
        """Dynamic clip refreshed long ago → is refreshable."""
        old_time = (datetime.now() - timedelta(days=30)).isoformat()
        tmp_db.save_clip({
            "url": "https://example.com/old",
            "title": "Old Live",
            "source_type": "web",
            "is_dynamic": 1,
            "refresh_interval_days": 7,
            "last_refreshed_at": old_time,
            "folder_path": "/clips/old",
            "markdown_path": "/clips/old/old.md",
        })
        results = tmp_db.get_refreshable_clips()
        assert len(results) == 1

    def test_dynamic_not_yet_expired(self, tmp_db: ClipIndex) -> None:
        """Dynamic clip refreshed recently → NOT refreshable."""
        tmp_db.save_clip({
            "url": "https://example.com/recent",
            "title": "Recent",
            "source_type": "web",
            "is_dynamic": 1,
            "refresh_interval_days": 7,
            "last_refreshed_at": datetime.now().isoformat(),
            "folder_path": "/clips/recent",
            "markdown_path": "/clips/recent/recent.md",
        })
        results = tmp_db.get_refreshable_clips()
        assert results == []

    def test_mark_refreshed(self, tmp_db: ClipIndex) -> None:
        """mark_refreshed should set last_refreshed_at to now."""
        cid = tmp_db.save_clip({
            "url": "https://example.com/mr",
            "title": "Mark Test",
            "source_type": "web",
            "is_dynamic": 1,
            "folder_path": "/clips/mr",
            "markdown_path": "/clips/mr/mr.md",
        })
        assert tmp_db.mark_refreshed(cid) is True
        clip = tmp_db.get_clip(cid)
        assert clip is not None
        assert clip["last_refreshed_at"] is not None
        assert clip["last_refreshed_at"] != ""

    def test_mark_refreshed_nonexistent(self, tmp_db: ClipIndex) -> None:
        """mark_refreshed on non-existent ID returns False."""
        assert tmp_db.mark_refreshed(99999) is False

    def test_is_expired_none(self) -> None:
        """None last_refreshed_at means expired."""
        from web_clip_helper.index import ClipIndex
        assert ClipIndex._is_expired(None, 7) is True

    def test_is_expired_empty_string(self) -> None:
        """Empty string last_refreshed_at means expired."""
        from web_clip_helper.index import ClipIndex
        assert ClipIndex._is_expired("", 7) is True

    def test_is_expired_recent(self) -> None:
        """Recently refreshed → not expired."""
        from web_clip_helper.index import ClipIndex
        assert ClipIndex._is_expired(datetime.now().isoformat(), 7) is False

    def test_is_expired_old(self) -> None:
        """Old timestamp → expired."""
        from web_clip_helper.index import ClipIndex
        old = (datetime.now() - timedelta(days=30)).isoformat()
        assert ClipIndex._is_expired(old, 7) is True


class TestCLIRefresh:
    """CLI integration tests for the refresh command."""

    def test_refresh_no_dynamic_clips(self, cli_config: Path, monkeypatch: pytest.MonkeyPatch, run_sdk_cli) -> None:
        """No dynamic clips → report nothing to refresh."""
        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com",
            "title": "Static",
            "source_type": "web",
            "is_dynamic": 0,
            "folder_path": "/clips/static",
            "markdown_path": "/clips/static/s.md",
        })
        idx.close()

        code, envelopes = run_sdk_cli(["refresh"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["refreshed"] == 0
        assert results[0]["data"]["message"] == "No clips due for refresh"

    def test_refresh_with_expired_dynamic(
        self, cli_config: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_sdk_cli
    ) -> None:
        """Expired dynamic clip → clip_url is called, record updated."""
        from web_clip_helper.models import ClipResult

        old_time = (datetime.now() - timedelta(days=30)).isoformat()

        idx = ClipIndex(cli_config)
        cid = idx.save_clip({
            "url": "https://example.com/live",
            "title": "Live Page",
            "source_type": "web",
            "is_dynamic": 1,
            "refresh_interval_days": 7,
            "last_refreshed_at": old_time,
            "folder_path": str(tmp_path / "live"),
            "markdown_path": str(tmp_path / "live" / "live.md"),
        })
        idx.close()

        # Create the old folder structure so cleanup can run
        old_folder = tmp_path / "live"
        old_folder.mkdir(parents=True, exist_ok=True)
        (old_folder / "live.md").write_text("old content", encoding="utf-8")
        (old_folder / "images").mkdir(exist_ok=True)

        new_folder = tmp_path / "new-live"
        new_folder.mkdir(parents=True, exist_ok=True)
        new_md = new_folder / "new-live.md"
        new_md.write_text("new content", encoding="utf-8")

        mock_result = ClipResult(
            folder_path=new_folder,
            markdown_path=new_md,
            image_count=0,
            record_id=cid,
        )

        with patch("web_clip_helper.pipeline.clip_url", return_value=mock_result) as mock_clip:
            code, envelopes = run_sdk_cli(["refresh"])
            mock_clip.assert_called_once()

        errors = [e for e in envelopes if e["type"] == "error"]
        assert errors == [], f"Unexpected errors: {errors}"

        results = [e for e in envelopes if e["type"] == "result" and "refreshed" in e.get("data", {})]
        assert len(results) == 1
        assert results[0]["data"]["refreshed"] == 1
        assert results[0]["data"]["failed"] == 0

    def test_refresh_failure_continues(
        self, cli_config: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, run_sdk_cli
    ) -> None:
        """If clip_url returns None for one clip, continue and report failure."""
        from web_clip_helper.models import ClipResult

        old_time = (datetime.now() - timedelta(days=30)).isoformat()

        idx = ClipIndex(cli_config)
        cid1 = idx.save_clip({
            "url": "https://example.com/fail",
            "title": "Fail Page",
            "source_type": "web",
            "is_dynamic": 1,
            "refresh_interval_days": 7,
            "last_refreshed_at": old_time,
            "folder_path": str(tmp_path / "fail"),
            "markdown_path": str(tmp_path / "fail" / "fail.md"),
        })
        cid2 = idx.save_clip({
            "url": "https://example.com/ok",
            "title": "OK Page",
            "source_type": "web",
            "is_dynamic": 1,
            "refresh_interval_days": 7,
            "last_refreshed_at": old_time,
            "folder_path": str(tmp_path / "ok"),
            "markdown_path": str(tmp_path / "ok" / "ok.md"),
        })
        idx.close()

        # Create folders
        for name in ("fail", "ok"):
            d = tmp_path / name
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{name}.md").write_text("old", encoding="utf-8")

        ok_folder = tmp_path / "new-ok"
        ok_folder.mkdir(parents=True, exist_ok=True)
        ok_md = ok_folder / "new-ok.md"
        ok_md.write_text("new", encoding="utf-8")

        mock_ok = ClipResult(
            folder_path=ok_folder,
            markdown_path=ok_md,
            image_count=0,
            record_id=cid2,
        )

        call_count = 0

        def side_effect(url, config):
            nonlocal call_count
            call_count += 1
            if "fail" in url:
                return None
            return mock_ok

        with patch("web_clip_helper.pipeline.clip_url", side_effect=side_effect):
            code, envelopes = run_sdk_cli(["refresh"])

        results = [e for e in envelopes if e["type"] == "result" and "refreshed" in e.get("data", {})]
        assert len(results) == 1
        assert results[0]["data"]["refreshed"] == 1
        assert results[0]["data"]["failed"] == 1

    def test_refresh_non_dynamic_not_selected(self, cli_config: Path, monkeypatch: pytest.MonkeyPatch, run_sdk_cli) -> None:
        """Non-dynamic clips should not be selected for refresh."""

        idx = ClipIndex(cli_config)
        idx.save_clip({
            "url": "https://example.com/static",
            "title": "Static Page",
            "source_type": "web",
            "is_dynamic": 0,
            "folder_path": "/clips/static",
            "markdown_path": "/clips/static/s.md",
        })
        idx.close()

        with patch("web_clip_helper.pipeline.clip_url") as mock_clip:
            code, envelopes = run_sdk_cli(["refresh"])
            mock_clip.assert_not_called()

        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert results[0]["data"]["message"] == "No clips due for refresh"


# ── Feedback tests ──────────────────────────────────────────────────────

# ── Version tests ─────────────────────────────────────────────────────


class TestCLIVersion:
    """CLI integration tests for the version command."""

    def test_version_outputs_valid_jsonl(self, run_sdk_cli) -> None:
        """version command output is valid JSONL."""
        code, envelopes = run_sdk_cli(["version"])
        assert len(envelopes) >= 1

    def test_version_contains_version_field(self, run_sdk_cli) -> None:
        """Result JSONL contains a non-empty version field."""
        code, envelopes = run_sdk_cli(["version"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1
        assert "version" in results[0]["data"]
        assert results[0]["data"]["version"] != ""

    def test_version_type_is_result(self, run_sdk_cli) -> None:
        """Result message type is 'result'."""
        code, envelopes = run_sdk_cli(["version"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert len(results) == 1

    def test_version_matches_package_version(self, run_sdk_cli) -> None:
        """Reported version matches web_clip_helper.__version__."""
        from web_clip_helper import __version__

        code, envelopes = run_sdk_cli(["version"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert results[0]["data"]["version"] == __version__

    def test_version_stage_is_version(self, run_sdk_cli) -> None:
        """Result stage is 'version'."""
        code, envelopes = run_sdk_cli(["version"])
        results = [e for e in envelopes if e["type"] == "result"]
        assert results[0]["data"]["stage"] == "version"
