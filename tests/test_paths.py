"""Tests for the paths module — XDG directory getters."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from web_clip_helper.paths import (
    APP_NAME,
    get_config_dir,
    get_crash_dump_dir,
    get_data_dir,
    get_reports_dir,
    get_state_dir,
)


class TestDirectoryGetters:
    """Test that each getter returns a Path and creates the directory."""

    def test_get_config_dir_returns_path(self, tmp_path: Path) -> None:
        with patch("web_clip_helper.paths.user_config_dir", return_value=str(tmp_path / "cfg")):
            result = get_config_dir()
            assert isinstance(result, Path)
            assert result.exists()

    def test_get_data_dir_returns_path(self, tmp_path: Path) -> None:
        with patch("web_clip_helper.paths.user_data_dir", return_value=str(tmp_path / "data")):
            result = get_data_dir()
            assert isinstance(result, Path)
            assert result.exists()

    def test_get_state_dir_returns_path(self, tmp_path: Path) -> None:
        with patch("web_clip_helper.paths.user_state_dir", return_value=str(tmp_path / "state")):
            result = get_state_dir()
            assert isinstance(result, Path)
            assert result.exists()

    def test_get_crash_dump_dir_under_state(self, tmp_path: Path) -> None:
        with patch("web_clip_helper.paths.user_state_dir", return_value=str(tmp_path / "state")):
            result = get_crash_dump_dir()
            assert result.name == "crash_dumps"
            assert result.exists()

    def test_get_reports_dir_under_data(self, tmp_path: Path) -> None:
        with patch("web_clip_helper.paths.user_data_dir", return_value=str(tmp_path / "data")):
            result = get_reports_dir()
            assert result.name == "reports"
            assert result.exists()

    def test_get_config_dir_idempotent(self, tmp_path: Path) -> None:
        """Calling twice returns the same path without error."""
        with patch("web_clip_helper.paths.user_config_dir", return_value=str(tmp_path / "cfg")):
            first = get_config_dir()
            second = get_config_dir()
            assert first == second


class TestDirectoryAutoCreate:
    """Verify that directories are auto-created when they don't exist."""

    def test_config_dir_created(self, tmp_path: Path) -> None:
        target = tmp_path / "new_cfg"
        assert not target.exists()
        with patch("web_clip_helper.paths.user_config_dir", return_value=str(target)):
            get_config_dir()
            assert target.exists()

    def test_data_dir_created(self, tmp_path: Path) -> None:
        target = tmp_path / "new_data"
        assert not target.exists()
        with patch("web_clip_helper.paths.user_data_dir", return_value=str(target)):
            get_data_dir()
            assert target.exists()

    def test_state_dir_created(self, tmp_path: Path) -> None:
        target = tmp_path / "new_state"
        assert not target.exists()
        with patch("web_clip_helper.paths.user_state_dir", return_value=str(target)):
            get_state_dir()
            assert target.exists()

    def test_crash_dump_creates_parent(self, tmp_path: Path) -> None:
        state = tmp_path / "state"
        with patch("web_clip_helper.paths.user_state_dir", return_value=str(state)):
            crash_dir = get_crash_dump_dir()
            assert crash_dir.exists()

    def test_reports_creates_parent(self, tmp_path: Path) -> None:
        data = tmp_path / "data"
        with patch("web_clip_helper.paths.user_data_dir", return_value=str(data)):
            reports_dir = get_reports_dir()
            assert reports_dir.exists()


class TestAppConstants:
    """Verify module constants."""

    def test_app_name(self) -> None:
        assert APP_NAME == "web-clip-helper"

    def test_legacy_dir(self) -> None:
        from web_clip_helper.paths import LEGACY_DIR

        assert str(LEGACY_DIR).endswith(".web-clip-helper")
