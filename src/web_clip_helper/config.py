"""Configuration system — loads from ``~/.web-clip-helper/config.yaml``.

Auto-creates the config directory and a default config file on first access.
If the YAML file is malformed or missing keys, sensible defaults are used.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

__all__ = ["Config", "get_config"]

_DEFAULT_CONFIG_DIR = Path.home() / ".web-clip-helper"
_DEFAULT_CONFIG_PATH = _DEFAULT_CONFIG_DIR / "config.yaml"


@dataclass
class LLMConfig:
    """LLM connection settings (used by S03+)."""

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"


@dataclass
class RefreshConfig:
    """Refresh polling settings."""

    default_interval_days: int = 7


@dataclass
class Config:
    """Root configuration object."""

    storage_path: str = str(_DEFAULT_CONFIG_DIR / "clips")
    db_path: str = str(_DEFAULT_CONFIG_DIR / "clips.db")
    llm: LLMConfig = field(default_factory=LLMConfig)
    refresh: RefreshConfig = field(default_factory=RefreshConfig)

    # ── Load / save ─────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        """Load config from *path* (default: ``~/.web-clip-helper/config.yaml``).

        Auto-creates the config directory and writes defaults on first run.
        Malformed YAML is silently ignored (defaults used instead).
        """
        config_path = Path(path) if path is not None else _DEFAULT_CONFIG_PATH
        raw: dict[str, Any] = {}

        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as fh:
                    loaded = yaml.safe_load(fh)
                if isinstance(loaded, dict):
                    raw = loaded
            except yaml.YAMLError:
                # Fall back to defaults — don't crash on malformed YAML
                pass

        config = cls._from_dict(raw)
        # Ensure config dir + default file exist
        config._ensure_config_file(config_path)
        return config

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> "Config":
        """Construct a Config from a dict, applying defaults for missing keys."""
        llm_raw = raw.get("llm", {}) or {}
        refresh_raw = raw.get("refresh", {}) or {}
        return cls(
            storage_path=raw.get("storage_path", str(_DEFAULT_CONFIG_DIR / "clips")),
            db_path=raw.get("db_path", str(_DEFAULT_CONFIG_DIR / "clips.db")),
            llm=LLMConfig(
                api_key=llm_raw.get("api_key", ""),
                base_url=llm_raw.get("base_url", "https://api.openai.com/v1"),
                model=llm_raw.get("model", "gpt-4o-mini"),
            ),
            refresh=RefreshConfig(
                default_interval_days=refresh_raw.get("default_interval_days", 7),
            ),
        )

    def _ensure_config_file(self, path: Path) -> None:
        """Create config directory and default config file if they don't exist."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                self.save(path)
        except OSError as exc:
            # Config dir not writable — raise with a clear message
            raise OSError(
                f"Cannot create config directory {path.parent}: {exc}. "
                f"Please create it manually or set appropriate permissions."
            ) from exc

    def save(self, path: Path | str | None = None) -> None:
        """Persist current config to YAML at *path*."""
        config_path = Path(path) if path is not None else _DEFAULT_CONFIG_PATH
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = self._to_dict()
        with open(config_path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, allow_unicode=True)

    def _to_dict(self) -> dict[str, Any]:
        return {
            "storage_path": self.storage_path,
            "db_path": self.db_path,
            "llm": {
                "api_key": self.llm.api_key,
                "base_url": self.llm.base_url,
                "model": self.llm.model,
            },
            "refresh": {
                "default_interval_days": self.refresh.default_interval_days,
            },
        }


# ── Module-level singleton ──────────────────────────────────────────

_cached_config: Config | None = None


def get_config(path: Path | str | None = None) -> Config:
    """Return a cached Config instance (loaded once, then reused)."""
    global _cached_config
    if _cached_config is None:
        _cached_config = Config.load(path)
    return _cached_config
