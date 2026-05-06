"""Configuration system — loads from the SDK sandbox data directory.

Auto-creates the data directory and a default config file on first access.
If the JSON file is malformed or missing keys, sensible defaults are used.

Environment variables ``WEB_CLIP_LLM_API_KEY``, ``WEB_CLIP_LLM_BASE_URL``,
and ``WEB_CLIP_LLM_MODEL`` override the corresponding ``llm`` fields when
set.  Each override is logged at info level so operators can diagnose why the
effective config differs from the file content.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from agentsdk import ConfigManager, Sandbox
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

__all__ = ["Config", "LLMConfig", "PromptConfig", "get_config", "get_by_path", "set_by_path", "_mask_api_key"]

_sandbox = Sandbox("web-clip-helper")
_DEFAULT_CONFIG_PATH = Path(_sandbox.data_dir) / "config.json"


# ── Pydantic models ────────────────────────────────────────────────


class LLMConfig(BaseModel):
    """LLM connection settings (used by S03+)."""

    model_config = {"frozen": False}

    api_key: str = Field(default="", json_schema_extra={"sensitive": True, "config": True})
    base_url: str = Field(default="https://api.openai.com/v1", json_schema_extra={"config": True})
    model: str = Field(default="gpt-4o-mini", json_schema_extra={"config": True})


class RefreshConfig(BaseModel):
    """Refresh polling settings."""

    model_config = {"frozen": False}

    default_interval_days: int = Field(default=7, json_schema_extra={"config": True})


class PromptConfig(BaseModel):
    """Prompt template settings (placeholder consumed by S02+)."""

    model_config = {"frozen": False}

    title: str = Field(default="", json_schema_extra={"config": True})
    tags: str = Field(default="", json_schema_extra={"config": True})
    classify: str = Field(default="", json_schema_extra={"config": True})


class Config(BaseModel):
    """Root configuration object."""

    model_config = {"frozen": False}

    storage_path: str = Field(default="", json_schema_extra={"config": True})
    db_path: str = Field(default="", json_schema_extra={"config": True})
    llm: LLMConfig = Field(default_factory=LLMConfig)
    refresh: RefreshConfig = Field(default_factory=RefreshConfig)
    prompts: PromptConfig = Field(default_factory=PromptConfig)

    @model_validator(mode="after")
    def _fill_sandbox_defaults(self) -> "Config":
        """Fill empty paths with SDK sandbox defaults."""
        data_dir = Path(_sandbox.data_dir)
        if not self.storage_path:
            object.__setattr__(self, "storage_path", str(data_dir / "clips"))
        if not self.db_path:
            object.__setattr__(self, "db_path", str(data_dir / "clips.db"))
        return self

    # ── ConfigManager instance ────────────────────────────────────

    _cm: ConfigManager | None = None

    @classmethod
    def _get_cm(cls, path: Path | None) -> ConfigManager:
        """Get or create a ConfigManager for the given path."""
        return ConfigManager(cls, str(path))

    # ── Load / save ──────────────────────────────────────────────

    @classmethod
    def load(cls, path: Path | str | None = None) -> "Config":
        """Load config from *path* (default: ``~/.web-clip-helper/data/config.json``).

        Auto-creates the config directory and writes defaults on first run.
        Malformed JSON is silently ignored (defaults used instead).
        """
        config_path = Path(path) if path is not None else _DEFAULT_CONFIG_PATH
        raw: dict[str, Any] = {}

        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as fh:
                    loaded = json.loads(fh.read())
                if isinstance(loaded, dict):
                    raw = loaded
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Fall back to defaults — don't crash on malformed JSON
                pass

        config = cls.model_validate(raw)
        # Environment variable overrides for LLM settings (take precedence over file)
        _apply_env_overrides(config)
        # Ensure config dir + default file exist
        config._ensure_config_file(config_path)
        return config

    def _ensure_config_file(self, path: Path) -> None:
        """Create config directory and default config file if they don't exist."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                self.save(path)
        except OSError as exc:
            raise OSError(
                f"Cannot create config directory {path.parent}: {exc}. "
                f"Please create it manually or set appropriate permissions."
            ) from exc

    def save(self, path: Path | str | None = None) -> None:
        """Persist current config to JSON at *path*."""
        config_path = Path(path) if path is not None else _DEFAULT_CONFIG_PATH
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = self._to_dict()
        payload = json.dumps(data, indent=2, ensure_ascii=False)
        with open(config_path, "w", encoding="utf-8") as fh:
            fh.write(payload)

    def _to_dict(self) -> dict[str, Any]:
        """Return a plain dict representation (backward compat for CLI callers)."""
        return self.model_dump()


# ── Module-level singleton ──────────────────────────────────────────

_cached_config: Config | None = None


def get_config(path: Path | str | None = None) -> Config:
    """Return a cached Config instance (loaded once, then reused).

    On first call, tries to run YAML→JSON migration if the migration
    module is available (T02). Non-fatal if migration module doesn't exist yet.
    """
    global _cached_config
    if _cached_config is None:
        try:
            from web_clip_helper.migration import run_migration

            run_migration()
        except ImportError:
            # T02 not complete yet — skip migration
            pass
        except Exception:
            # Non-fatal: migration failure shouldn't block startup
            logger.warning("Config migration failed, continuing with current config")
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
            available = list(type(current).model_fields.keys()) if hasattr(type(current), "model_fields") else []
            raise KeyError(
                f"Config path '{'.'.join(traversed)}' does not exist. "
                f"Available fields: {available}"
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
            available = list(type(parent).model_fields.keys()) if hasattr(type(parent), "model_fields") else []
            raise KeyError(
                f"Config path '{'.'.join(traversed)}' does not exist. "
                f"Available fields: {available}"
            )
        parent = getattr(parent, part)

    leaf = parts[-1]
    if not hasattr(parent, leaf):
        available = list(type(parent).model_fields.keys()) if hasattr(type(parent), "model_fields") else []
        raise KeyError(
            f"Config path '{dotpath}' does not exist. "
            f"Available fields: {available}"
        )

    # Coerce value to the target field's type
    field_info = type(parent).model_fields[leaf]
    annotation = field_info.annotation
    coerced: Any
    if annotation is int or annotation == "int":
        coerced = int(value)
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
