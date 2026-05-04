"""Configuration system — loads from the XDG config directory.

Auto-creates the config directory and a default config file on first access.
If the YAML file is malformed or missing keys, sensible defaults are used.

Environment variables ``WEB_CLIP_LLM_API_KEY``, ``WEB_CLIP_LLM_BASE_URL``,
and ``WEB_CLIP_LLM_MODEL`` override the corresponding ``llm`` fields when
set.  Each override is logged at info level so operators can diagnose why the
effective config differs from the file content.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from web_clip_helper.paths import (
    get_config_dir,
    get_data_dir,
    migrate_legacy_data,
)

logger = logging.getLogger(__name__)

__all__ = ["Config", "PromptConfig", "get_config", "get_by_path", "set_by_path", "_mask_api_key"]

_DEFAULT_CONFIG_PATH = get_config_dir() / "config.yaml"


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
class PromptConfig:
    """Prompt template settings (placeholder consumed by S02+)."""

    title: str = ""
    tags: str = ""
    classify: str = ""


@dataclass
class Config:
    """Root configuration object."""

    storage_path: str = ""
    db_path: str = ""
    llm: LLMConfig = field(default_factory=LLMConfig)
    refresh: RefreshConfig = field(default_factory=RefreshConfig)
    prompts: PromptConfig = field(default_factory=PromptConfig)

    def __post_init__(self) -> None:
        """Fill empty paths with XDG defaults (computed lazily)."""
        if not self.storage_path:
            self.storage_path = str(get_data_dir() / "clips")
        if not self.db_path:
            self.db_path = str(get_data_dir() / "clips.db")

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
        # Environment variable overrides for LLM settings (take precedence over YAML)
        _apply_env_overrides(config)
        # Ensure config dir + default file exist
        config._ensure_config_file(config_path)
        return config

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> "Config":
        """Construct a Config from a dict, applying defaults for missing keys."""
        llm_raw = raw.get("llm", {}) or {}
        refresh_raw = raw.get("refresh", {}) or {}
        prompts_raw = raw.get("prompts", {}) or {}
        return cls(
            storage_path=raw.get("storage_path", ""),
            db_path=raw.get("db_path", ""),
            llm=LLMConfig(
                api_key=llm_raw.get("api_key", ""),
                base_url=llm_raw.get("base_url", "https://api.openai.com/v1"),
                model=llm_raw.get("model", "gpt-4o-mini"),
            ),
            refresh=RefreshConfig(
                default_interval_days=refresh_raw.get("default_interval_days", 7),
            ),
            prompts=PromptConfig(
                title=prompts_raw.get("title", ""),
                tags=prompts_raw.get("tags", ""),
                classify=prompts_raw.get("classify", ""),
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
            "prompts": {
                "title": self.prompts.title,
                "tags": self.prompts.tags,
                "classify": self.prompts.classify,
            },
        }


# ── Module-level singleton ──────────────────────────────────────────

_cached_config: Config | None = None


def get_config(path: Path | str | None = None) -> Config:
    """Return a cached Config instance (loaded once, then reused).

    On first call, triggers legacy data migration if needed.
    """
    global _cached_config
    if _cached_config is None:
        try:
            from web_clip_helper.output import jsonl_emit_progress

            migrate_legacy_data(jsonl_emit_progress=jsonl_emit_progress)
        except Exception:
            # Non-fatal: migration failure shouldn't block startup
            migrate_legacy_data()
        _cached_config = Config.load(path)
    return _cached_config


# ── Environment variable overrides ──────────────────────────────────

_ENV_OVERRIDES: dict[str, tuple[str, str]] = {
    "WEB_CLIP_LLM_API_KEY": ("llm", "api_key"),
    "WEB_CLIP_LLM_BASE_URL": ("llm", "base_url"),
    "WEB_CLIP_LLM_MODEL": ("llm", "model"),
}


def _apply_env_overrides(config: Config) -> None:
    """Override Config LLM fields from environment variables when set."""
    for env_var, (section, field_name) in _ENV_OVERRIDES.items():
        value = os.environ.get(env_var)
        if value is not None:
            setattr(getattr(config, section), field_name, value)
            logger.info(
                "Config override from env: %s → %s.%s",
                env_var,
                section,
                field_name,
            )


# ── Dot-path helpers ────────────────────────────────────────────────


def get_by_path(obj: Any, dotpath: str) -> Any:
    """Retrieve a value from *obj* using a dot-separated path like ``llm.api_key``.

    Raises :class:`KeyError` with a clear message if the path is invalid.
    """
    parts = dotpath.split(".")
    current = obj
    traversed: list[str] = []
    for part in parts:
        traversed.append(part)
        if not hasattr(current, part):
            raise KeyError(
                f"Config path '{'.'.join(traversed)}' does not exist. "
                f"Available fields: {[f.name for f in fields(current)]}"
            )
        current = getattr(current, part)
    return current


def set_by_path(obj: Any, dotpath: str, value: str) -> None:
    """Set a value on *obj* using a dot-separated path, coercing type.

    *value* is always a string (from CLI); it is coerced to the target
    field's declared type (``str`` → ``str``, ``int`` → ``int``).

    Raises :class:`KeyError` if the path is invalid.
    """
    parts = dotpath.split(".")
    if len(parts) < 1:
        raise KeyError("Empty dot-path")

    # Navigate to parent
    parent = obj
    traversed: list[str] = []
    for part in parts[:-1]:
        traversed.append(part)
        if not hasattr(parent, part):
            raise KeyError(
                f"Config path '{'.'.join(traversed)}' does not exist. "
                f"Available fields: {[f.name for f in fields(parent)]}"
            )
        parent = getattr(parent, part)

    leaf = parts[-1]
    if not hasattr(parent, leaf):
        raise KeyError(
            f"Config path '{dotpath}' does not exist. "
            f"Available fields: {[f.name for f in fields(parent)]}"
        )

    # Coerce value to the target field's type
    target_field = next(f for f in fields(parent) if f.name == leaf)
    expected_type = target_field.type
    if expected_type is int or expected_type == "int":
        coerced: Any = int(value)
    else:
        coerced = value

    setattr(parent, leaf, coerced)


# ── Masking utility ─────────────────────────────────────────────────


def _mask_api_key(value: str) -> str:
    """Mask an API key for safe display.

    - Empty string → empty string
    - ≤ 8 characters → ``****``
    - Otherwise → first 3 chars + ``****`` + last 4 chars (e.g. ``sk-****1234``)
    """
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"
