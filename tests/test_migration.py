"""Tests for XDG → SDK Sandbox migration."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from web_clip_helper.migration import (
    _MARKER_OK,
    _MARKER_PARTIAL,
    _copy_item,
    _copy_tree,
    _deep_merge,
    _migrate_config,
    _migrate_data,
    _read_marker,
    _write_marker,
    run_migration,
)


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture()
def fake_sandbox(tmp_path: Path):
    """Create a fake Sandbox-like object using tmp_path."""

    class FakeSandbox:
        def __init__(self, base: Path):
            self.base_dir = base
            self.data_dir = base / "data"
            self.cache_dir = base / "cache"
            self.crash_dumps_dir = base / "crash_dumps"
            self.locks_dir = base / "locks"
            # Ensure directories exist
            for d in (self.data_dir, self.cache_dir, self.crash_dumps_dir, self.locks_dir):
                d.mkdir(parents=True, exist_ok=True)

    return FakeSandbox(tmp_path / "sandbox")


@pytest.fixture()
def xdg_dirs(tmp_path: Path):
    """Patch platformdirs to return tmp_path subdirs."""
    config_dir = tmp_path / "xdg_config"
    data_dir = tmp_path / "xdg_data"
    state_dir = tmp_path / "xdg_state"
    patches = [
        patch("web_clip_helper.migration.user_config_dir", return_value=str(config_dir)),
        patch("web_clip_helper.migration.user_data_dir", return_value=str(data_dir)),
        patch("web_clip_helper.migration.user_state_dir", return_value=str(state_dir)),
    ]
    for p in patches:
        p.start()
    yield config_dir, data_dir, state_dir
    for p in patches:
        p.stop()


# ── Helper tests ───────────────────────────────────────────────────


class TestDeepMerge:
    def test_flat(self) -> None:
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_override(self) -> None:
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested(self) -> None:
        base = {"llm": {"api_key": "", "model": "gpt-4o-mini"}}
        override = {"llm": {"api_key": "sk-test"}}
        assert _deep_merge(base, override) == {
            "llm": {"api_key": "sk-test", "model": "gpt-4o-mini"}
        }

    def test_does_not_mutate_base(self) -> None:
        base = {"a": {"b": 1}}
        _deep_merge(base, {"a": {"c": 2}})
        assert "c" not in base["a"]


class TestCopyItem:
    def test_copies_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "file.txt"
        src.parent.mkdir()
        src.write_text("hello", encoding="utf-8")
        dst = tmp_path / "dst" / "file.txt"
        assert _copy_item(src, dst) is True
        assert dst.read_text(encoding="utf-8") == "hello"

    def test_missing_source_is_ok(self, tmp_path: Path) -> None:
        dst = tmp_path / "dst" / "file.txt"
        assert _copy_item(tmp_path / "nonexistent", dst) is True

    def test_permission_error(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "file.txt"
        src.parent.mkdir()
        src.write_text("hello", encoding="utf-8")
        dst = tmp_path / "dst" / "file.txt"
        with patch("web_clip_helper.migration.shutil.copy2", side_effect=PermissionError("locked")):
            assert _copy_item(src, dst) is False


class TestCopyTree:
    def test_copies_tree(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "clips"
        src.mkdir(parents=True)
        (src / "clip1.md").write_text("# Clip", encoding="utf-8")
        sub = src / "sub"
        sub.mkdir()
        (sub / "clip2.md").write_text("# Clip2", encoding="utf-8")

        dst = tmp_path / "dst" / "clips"
        assert _copy_tree(src, dst) is True
        assert (dst / "clip1.md").read_text(encoding="utf-8") == "# Clip"
        assert (dst / "sub" / "clip2.md").read_text(encoding="utf-8") == "# Clip2"

    def test_missing_source_is_ok(self, tmp_path: Path) -> None:
        assert _copy_tree(tmp_path / "nonexistent", tmp_path / "dst") is True

    def test_merges_into_existing(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "clips"
        src.mkdir(parents=True)
        (src / "new.md").write_text("new", encoding="utf-8")

        dst = tmp_path / "dst" / "clips"
        dst.mkdir(parents=True)
        (dst / "existing.md").write_text("existing", encoding="utf-8")

        assert _copy_tree(src, dst) is True
        assert (dst / "existing.md").read_text(encoding="utf-8") == "existing"
        assert (dst / "new.md").read_text(encoding="utf-8") == "new"


# ── Marker tests ───────────────────────────────────────────────────


class TestMarker:
    def test_read_missing(self, tmp_path: Path) -> None:
        assert _read_marker(tmp_path) is None

    def test_write_and_read(self, tmp_path: Path) -> None:
        _write_marker(tmp_path, "ok")
        assert _read_marker(tmp_path) == "ok"

    def test_write_partial(self, tmp_path: Path) -> None:
        _write_marker(tmp_path, "partial")
        assert _read_marker(tmp_path) == "partial"


# ── Config migration tests ─────────────────────────────────────────


class TestMigrateConfig:
    def test_yaml_to_json(self, tmp_path: Path) -> None:
        xdg_config = tmp_path / "xdg_config"
        xdg_config.mkdir()
        sandbox_base = tmp_path / "sandbox"
        sandbox_base.mkdir()

        yaml_content = "llm:\n  api_key: sk-test\n  model: gpt-4o\n"
        (xdg_config / "config.yaml").write_text(yaml_content, encoding="utf-8")

        assert _migrate_config(xdg_config, sandbox_base) is True

        dst = sandbox_base / "config.json"
        assert dst.exists()
        data = json.loads(dst.read_text(encoding="utf-8"))
        assert data["llm"]["api_key"] == "sk-test"
        assert data["llm"]["model"] == "gpt-4o"
        # Defaults preserved
        assert data["llm"]["base_url"] == "https://api.openai.com/v1"

    def test_no_yaml_skips(self, tmp_path: Path) -> None:
        xdg_config = tmp_path / "xdg_config"
        xdg_config.mkdir()
        sandbox_base = tmp_path / "sandbox"
        sandbox_base.mkdir()

        assert _migrate_config(xdg_config, sandbox_base) is True
        assert not (sandbox_base / "config.json").exists()

    def test_corrupt_yaml_uses_defaults(self, tmp_path: Path) -> None:
        xdg_config = tmp_path / "xdg_config"
        xdg_config.mkdir()
        sandbox_base = tmp_path / "sandbox"
        sandbox_base.mkdir()

        (xdg_config / "config.yaml").write_text("{{{invalid yaml", encoding="utf-8")

        assert _migrate_config(xdg_config, sandbox_base) is True

        dst = sandbox_base / "config.json"
        assert dst.exists()
        data = json.loads(dst.read_text(encoding="utf-8"))
        assert data["llm"]["model"] == "gpt-4o-mini"  # default

    def test_existing_config_json_not_overwritten(self, tmp_path: Path) -> None:
        xdg_config = tmp_path / "xdg_config"
        xdg_config.mkdir()
        sandbox_base = tmp_path / "sandbox"
        sandbox_base.mkdir()

        (xdg_config / "config.yaml").write_text("llm:\n  api_key: sk-new\n", encoding="utf-8")
        existing = {"llm": {"api_key": "sk-kept"}}
        (sandbox_base / "config.json").write_text(
            json.dumps(existing) + "\n", encoding="utf-8"
        )

        assert _migrate_config(xdg_config, sandbox_base) is True

        data = json.loads((sandbox_base / "config.json").read_text(encoding="utf-8"))
        assert data["llm"]["api_key"] == "sk-kept"


# ── Data migration tests ───────────────────────────────────────────


class TestMigrateData:
    def test_copies_all_items(self, tmp_path: Path, fake_sandbox) -> None:
        xdg_data = tmp_path / "xdg_data"
        xdg_state = tmp_path / "xdg_state"
        xdg_data.mkdir()
        xdg_state.mkdir()

        (xdg_data / "clips.db").write_bytes(b"db-data")
        clips = xdg_data / "clips"
        clips.mkdir()
        (clips / "clip1.md").write_text("# Clip1", encoding="utf-8")
        reports = xdg_data / "reports"
        reports.mkdir()
        (reports / "report1.md").write_text("# Report", encoding="utf-8")
        crash = xdg_state / "crash_dumps"
        crash.mkdir()
        (crash / "dump.json").write_text("{}", encoding="utf-8")

        results = _migrate_data(xdg_data, xdg_state, fake_sandbox)

        assert results == {
            "clips.db": True,
            "clips/": True,
            "reports/": True,
            "crash_dumps/": True,
        }
        assert (fake_sandbox.data_dir / "clips.db").read_bytes() == b"db-data"
        assert (fake_sandbox.data_dir / "clips" / "clip1.md").exists()
        assert (fake_sandbox.data_dir / "reports" / "report1.md").exists()
        assert (fake_sandbox.crash_dumps_dir / "dump.json").exists()

    def test_locked_db_skips(self, tmp_path: Path, fake_sandbox) -> None:
        xdg_data = tmp_path / "xdg_data"
        xdg_state = tmp_path / "xdg_state"
        xdg_data.mkdir()
        xdg_state.mkdir()

        (xdg_data / "clips.db").write_bytes(b"locked-db")

        with patch(
            "web_clip_helper.migration.shutil.copy2",
            side_effect=PermissionError("database is locked"),
        ):
            results = _migrate_data(xdg_data, xdg_state, fake_sandbox)

        assert results["clips.db"] is False
        # Other items should still succeed
        assert results["clips/"] is True
        assert results["reports/"] is True

    def test_no_data_still_ok(self, tmp_path: Path, fake_sandbox) -> None:
        xdg_data = tmp_path / "xdg_data"
        xdg_state = tmp_path / "xdg_state"
        xdg_data.mkdir()
        xdg_state.mkdir()

        results = _migrate_data(xdg_data, xdg_state, fake_sandbox)
        assert all(results.values())


# ── Full migration integration tests ───────────────────────────────


class TestRunMigration:
    def test_full_migration(self, tmp_path: Path, fake_sandbox, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs

        # Create legacy XDG data
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.yaml").write_text(
            "llm:\n  api_key: sk-migrate\n", encoding="utf-8"
        )
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "clips.db").write_bytes(b"old-db")
        clips = data_dir / "clips"
        clips.mkdir()
        (clips / "old_clip.md").write_text("# Old", encoding="utf-8")
        state_dir.mkdir(parents=True, exist_ok=True)
        crash = state_dir / "crash_dumps"
        crash.mkdir()
        (crash / "crash.json").write_text("{}", encoding="utf-8")

        assert run_migration(fake_sandbox) is True

        # Config migrated
        cfg = json.loads(
            (fake_sandbox.base_dir / "config.json").read_text(encoding="utf-8")
        )
        assert cfg["llm"]["api_key"] == "sk-migrate"

        # Data migrated
        assert (fake_sandbox.data_dir / "clips.db").read_bytes() == b"old-db"
        assert (fake_sandbox.data_dir / "clips" / "old_clip.md").exists()
        assert (fake_sandbox.crash_dumps_dir / "crash.json").exists()

        # Marker written
        assert _read_marker(fake_sandbox.base_dir) == _MARKER_OK

    def test_idempotent_skips(self, tmp_path: Path, fake_sandbox, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs

        # Create legacy data
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.yaml").write_text("llm:\n  api_key: sk-1\n", encoding="utf-8")
        data_dir.mkdir(parents=True, exist_ok=True)

        # Run once
        assert run_migration(fake_sandbox) is True

        # Modify the source YAML (should NOT be re-migrated)
        (config_dir / "config.yaml").write_text("llm:\n  api_key: sk-2\n", encoding="utf-8")

        # Run again — should skip
        assert run_migration(fake_sandbox) is True
        cfg = json.loads(
            (fake_sandbox.base_dir / "config.json").read_text(encoding="utf-8")
        )
        assert cfg["llm"]["api_key"] == "sk-1"  # unchanged

    def test_no_legacy_data(self, tmp_path: Path, fake_sandbox, xdg_dirs) -> None:
        # No XDG dirs created at all
        assert run_migration(fake_sandbox) is True
        assert _read_marker(fake_sandbox.base_dir) == _MARKER_OK

    def test_partial_migration(self, tmp_path: Path, fake_sandbox, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs

        # Create legacy data with a locked DB
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.yaml").write_text("key: val\n", encoding="utf-8")
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "clips.db").write_bytes(b"locked")
        state_dir.mkdir(parents=True, exist_ok=True)

        with patch(
            "web_clip_helper.migration.shutil.copy2",
            side_effect=PermissionError("locked"),
        ):
            result = run_migration(fake_sandbox)

        # Should fail because clips.db can't be copied
        assert result is False
        assert _read_marker(fake_sandbox.base_dir) == _MARKER_PARTIAL

    def test_partial_retries(self, tmp_path: Path, fake_sandbox, xdg_dirs) -> None:
        """After a partial migration, a re-run should retry failed items."""
        config_dir, data_dir, state_dir = xdg_dirs

        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.yaml").write_text("key: val\n", encoding="utf-8")
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "clips.db").write_bytes(b"retry-db")
        state_dir.mkdir(parents=True, exist_ok=True)

        # First run: clips.db is locked
        with patch(
            "web_clip_helper.migration.shutil.copy2",
            side_effect=PermissionError("locked"),
        ):
            result = run_migration(fake_sandbox)
        assert result is False
        assert _read_marker(fake_sandbox.base_dir) == _MARKER_PARTIAL

        # Second run: copy succeeds (patch removed)
        # Remove partial marker so run_migration doesn't see "partial" and skip
        # Actually, current implementation treats partial as needing re-run only if marker is not "ok"
        # But we wrote "partial" — current code only skips on "ok". Let's verify.
        result = run_migration(fake_sandbox)
        assert result is True
        assert (fake_sandbox.data_dir / "clips.db").read_bytes() == b"retry-db"
        assert _read_marker(fake_sandbox.base_dir) == _MARKER_OK

    def test_corrupt_yaml(self, tmp_path: Path, fake_sandbox, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs

        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.yaml").write_text("{{{bad yaml", encoding="utf-8")
        data_dir.mkdir(parents=True, exist_ok=True)

        assert run_migration(fake_sandbox) is True
        cfg = json.loads(
            (fake_sandbox.base_dir / "config.json").read_text(encoding="utf-8")
        )
        assert cfg["llm"]["model"] == "gpt-4o-mini"  # defaults used
