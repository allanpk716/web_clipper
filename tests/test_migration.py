"""Tests for data migration from legacy ~/.web-clip-helper/ to XDG directories."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from web_clip_helper.paths import (
    LEGACY_DIR,
    get_config_dir,
    get_data_dir,
    get_state_dir,
    get_migration_marker,
    migrate_legacy_data,
)


@pytest.fixture()
def xdg_dirs(tmp_path: Path):
    """Patch XDG directories to use tmp_path."""
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    state_dir = tmp_path / "state"

    patches = [
        patch("web_clip_helper.paths.user_config_dir", return_value=str(config_dir)),
        patch("web_clip_helper.paths.user_data_dir", return_value=str(data_dir)),
        patch("web_clip_helper.paths.user_state_dir", return_value=str(state_dir)),
    ]
    for p in patches:
        p.start()
    yield config_dir, data_dir, state_dir
    for p in patches:
        p.stop()


@pytest.fixture()
def legacy_home(tmp_path: Path):
    """Create a fake legacy ~/.web-clip-helper/ with sample data."""
    legacy = tmp_path / "legacy"
    # Patch LEGACY_DIR to point here
    with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
        with patch("web_clip_helper.paths.get_migration_marker", return_value=legacy / ".migrated"):
            yield legacy


class TestMigrationIdempotency:
    """Migration should be idempotent and safe to run multiple times."""

    def test_no_legacy_dir_no_error(self, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs
        # Patch LEGACY_DIR to a nonexistent path
        with patch("web_clip_helper.paths.LEGACY_DIR", Path("/nonexistent/legacy")):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=Path("/nonexistent/legacy/.migrated")):
                result = migrate_legacy_data()
        assert result is True

    def test_marker_exists_skips_migration(self, tmp_path: Path, xdg_dirs) -> None:
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        marker = legacy / ".migrated"
        marker.write_text("ok", encoding="utf-8")

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()
        assert result is True
        # No files copied since marker already exists


class TestMigrationHappyPath:
    """Successful migration copies all legacy data."""

    def test_copies_config_yaml(self, tmp_path: Path, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / "config.yaml").write_text("storage_path: /old/path\n", encoding="utf-8")
        marker = legacy / ".migrated"

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()

        assert result is True
        assert (config_dir / "config.yaml").exists()
        assert (config_dir / "config.yaml").read_text(encoding="utf-8") == "storage_path: /old/path\n"

    def test_copies_clips_db(self, tmp_path: Path, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / "clips.db").write_bytes(b"fake-sqlite-data")
        marker = legacy / ".migrated"

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()

        assert result is True
        assert (data_dir / "clips.db").exists()
        assert (data_dir / "clips.db").read_bytes() == b"fake-sqlite-data"

    def test_copies_clips_directory(self, tmp_path: Path, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        clips = legacy / "clips"
        clips.mkdir()
        (clips / "2026-01-01_test.md").write_text("# Test", encoding="utf-8")
        marker = legacy / ".migrated"

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()

        assert result is True
        assert (data_dir / "clips" / "2026-01-01_test.md").exists()

    def test_copies_reports_directory(self, tmp_path: Path, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        reports = legacy / "reports"
        reports.mkdir()
        (reports / "report_bug_20260101.md").write_text("# Bug", encoding="utf-8")
        marker = legacy / ".migrated"

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()

        assert result is True
        assert (data_dir / "reports" / "report_bug_20260101.md").exists()

    def test_copies_crash_dumps_directory(self, tmp_path: Path, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        crash = legacy / "crash_dumps"
        crash.mkdir()
        (crash / ".last-crash.json").write_text('{"test": true}', encoding="utf-8")
        marker = legacy / ".migrated"

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()

        assert result is True
        assert (state_dir / "crash_dumps" / ".last-crash.json").exists()

    def test_writes_migration_marker(self, tmp_path: Path, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        marker = legacy / ".migrated"

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()

        assert result is True
        assert marker.exists()
        assert marker.read_text(encoding="utf-8") == "ok"

    def test_full_migration_all_items(self, tmp_path: Path, xdg_dirs) -> None:
        """Migrate all item types at once."""
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()

        # Create all legacy items
        (legacy / "config.yaml").write_text("key: value\n", encoding="utf-8")
        (legacy / "clips.db").write_bytes(b"db-data")
        clips = legacy / "clips"
        clips.mkdir()
        (clips / "clip1.md").write_text("# Clip 1", encoding="utf-8")
        reports = legacy / "reports"
        reports.mkdir()
        (reports / "report1.md").write_text("# Report", encoding="utf-8")
        crash = legacy / "crash_dumps"
        crash.mkdir()
        (crash / "dump1.json").write_text("{}", encoding="utf-8")
        marker = legacy / ".migrated"

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()

        assert result is True
        assert (config_dir / "config.yaml").exists()
        assert (data_dir / "clips.db").exists()
        assert (data_dir / "clips" / "clip1.md").exists()
        assert (data_dir / "reports" / "report1.md").exists()
        assert (state_dir / "crash_dumps" / "dump1.json").exists()
        assert marker.exists()


class TestMigrationPartialData:
    """Migration handles partial legacy data gracefully."""

    def test_only_config_yaml(self, tmp_path: Path, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / "config.yaml").write_text("key: val\n", encoding="utf-8")
        marker = legacy / ".migrated"

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()

        assert result is True
        assert (config_dir / "config.yaml").exists()
        assert not (data_dir / "clips.db").exists()  # was not in legacy

    def test_empty_legacy_dir(self, tmp_path: Path, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        marker = legacy / ".migrated"

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()

        assert result is True
        assert marker.exists()

    def test_missing_optional_items_ok(self, tmp_path: Path, xdg_dirs) -> None:
        """If clips/ or reports/ don't exist, migration still succeeds."""
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / "config.yaml").write_text("key: val\n", encoding="utf-8")
        # No clips/, no reports/, no crash_dumps/
        marker = legacy / ".migrated"

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()

        assert result is True


class TestMigrationFailure:
    """Migration failure is non-fatal and returns False."""

    def test_write_failure_returns_false(self, tmp_path: Path, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / "config.yaml").write_text("key: val\n", encoding="utf-8")
        marker = legacy / ".migrated"

        # Make config_dir unwritable by patching mkdir to raise
        original_mkdir = Path.mkdir

        def failing_mkdir(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            if "config" in str(self) and str(self).endswith("config"):
                raise OSError("Permission denied")
            return original_mkdir(self, *args, **kwargs)

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                with patch.object(Path, "mkdir", failing_mkdir):
                    result = migrate_legacy_data()

        assert result is False

    def test_preserves_legacy_data_on_failure(self, tmp_path: Path, xdg_dirs) -> None:
        """Legacy data is NOT deleted when migration fails (copy, not move)."""
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / "config.yaml").write_text("original\n", encoding="utf-8")
        marker = legacy / ".migrated"

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                with patch.object(Path, "mkdir", side_effect=OSError("fail")):
                    result = migrate_legacy_data()

        assert result is False
        # Legacy file still exists
        assert (legacy / "config.yaml").read_text(encoding="utf-8") == "original\n"


class TestMigrationMarker:
    """Migration marker prevents re-migration."""

    def test_marker_prevents_rerun(self, tmp_path: Path, xdg_dirs) -> None:
        config_dir, data_dir, state_dir = xdg_dirs
        legacy = tmp_path / "legacy"
        legacy.mkdir()
        (legacy / "config.yaml").write_text("old\n", encoding="utf-8")
        marker = legacy / ".migrated"
        marker.write_text("ok", encoding="utf-8")

        with patch("web_clip_helper.paths.LEGACY_DIR", legacy):
            with patch("web_clip_helper.paths.get_migration_marker", return_value=marker):
                result = migrate_legacy_data()

        assert result is True
        # Config was NOT copied (marker was already present)
        assert not (config_dir / "config.yaml").exists()
