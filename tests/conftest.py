"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def tmp_config_dir(tmp_path: Path) -> Path:
    """Return a temporary directory suitable for config files."""
    d = tmp_path / "cfg"
    d.mkdir()
    return d


@pytest.fixture()
def tmp_config_path(tmp_config_dir: Path) -> Path:
    """Return a path to a temporary config.yaml."""
    return tmp_config_dir / "config.yaml"
