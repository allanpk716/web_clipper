"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _reset_trace_id():
    """Reset SDK Writer trace_id and quiet mode between tests to prevent state leakage."""
    from web_clip_helper.app import get_app, _app as _app_mod

    # Reset the singleton so each test gets a fresh App/Writer.
    import web_clip_helper.app as _app_module
    _app_module._app = None
    yield
    _app_module._app = None


@pytest.fixture()
def tmp_config_dir(tmp_path: Path) -> Path:
    """Return a temporary directory suitable for config files."""
    d = tmp_path / "cfg"
    d.mkdir()
    return d


@pytest.fixture()
def tmp_config_path(tmp_config_dir: Path) -> Path:
    """Return a path to a temporary config.json."""
    return tmp_config_dir / "config.json"
