"""CLI entry point — Typer application with JSONL output.

All user-facing output goes through ``output.jsonl_emit`` — no bare ``print()`` calls.
"""

from __future__ import annotations

import sys
from typing import Optional

import typer

from web_clip_helper.output import jsonl_emit_error, jsonl_emit_help, jsonl_emit_progress, jsonl_emit_result

# Trigger adapter auto-discovery registration
import web_clip_helper.adapters._registry  # noqa: F401

__all__ = ["app", "config_app"]

app = typer.Typer(
    name="web-clip-helper",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
)

# Description of sub-commands shown in JSONL help output.
_COMMAND_HELP = [
    {"name": "clip", "help": "Clip a URL or raw text into Markdown + storage"},
    {"name": "list", "help": "List clipped items"},
    {"name": "get", "help": "Get a clipped item by ID"},
    {"name": "search", "help": "Search clipped items by keyword"},
    {"name": "tags", "help": "List or manage tags"},
    {"name": "refresh", "help": "Refresh dynamic clipped items"},
    {"name": "feedback", "help": "Submit feedback on clipping quality"},
    {"name": "config", "help": "Manage configuration (list/get/set + prompt test)"},
]


@app.callback()
def main(
    help_flag: bool = typer.Option(False, "--help", "-h", is_flag=True, is_eager=True),
) -> None:
    """web-clip-helper — LLM Agent-oriented web clipping tool.

    All output (including --help) is JSONL so agents can parse it easily.
    """
    if help_flag:
        jsonl_emit_help(
            commands=_COMMAND_HELP,
            description="LLM Agent-oriented web clipping CLI tool",
        )
        raise typer.Exit(0)


# ── config sub-application ──────────────────────────────────────────

config_app = typer.Typer(
    name="config",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
    help="Manage configuration",
)


@config_app.callback()
def config_main() -> None:
    """Configuration management commands."""
    pass


@config_app.command(name="list")
def config_list(
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Path to config file"),
) -> None:
    """List all configuration values (api_key is masked)."""
    import web_clip_helper.config as cfg_mod

    try:
        config = cfg_mod.Config.load(path)
        data = config._to_dict()
        _emit_config_items(data, parent="")
    except Exception as exc:
        jsonl_emit_error(stage="config", detail=f"Failed to list config: {exc}")
        raise typer.Exit(1)


def _emit_config_items(data: dict, parent: str) -> None:
    """Recursively emit config key=value pairs as JSONL result lines."""
    for key, value in data.items():
        full_key = f"{parent}.{key}" if parent else key
        if isinstance(value, dict):
            _emit_config_items(value, full_key)
        else:
            from web_clip_helper.config import _mask_api_key

            display_value = _mask_api_key(str(value)) if full_key == "llm.api_key" else str(value)
            jsonl_emit_result(stage="config", key=full_key, value=display_value)


@config_app.command(name="get")
def config_get(
    key: str = typer.Argument(..., help="Config key in dot-path notation (e.g. llm.api_key)"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Path to config file"),
) -> None:
    """Get a single configuration value by dot-path key."""
    from web_clip_helper.config import Config, _mask_api_key, get_by_path

    try:
        config = Config.load(path)
        value = get_by_path(config, key)
        display_value = _mask_api_key(str(value)) if key == "llm.api_key" else str(value)
        jsonl_emit_result(stage="config", key=key, value=display_value)
    except KeyError as exc:
        jsonl_emit_error(stage="config", detail=str(exc))
        raise typer.Exit(1)
    except Exception as exc:
        jsonl_emit_error(stage="config", detail=f"Failed to get config: {exc}")
        raise typer.Exit(1)


@config_app.command(name="set")
def config_set(
    key: str = typer.Argument(..., help="Config key in dot-path notation (e.g. llm.api_key)"),
    value: str = typer.Argument(..., help="Value to set"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Path to config file"),
) -> None:
    """Set a configuration value by dot-path key and save to file."""
    import web_clip_helper.config as cfg_mod

    try:
        config = cfg_mod.Config.load(path)
        cfg_mod.set_by_path(config, key, value)
        save_path = path or str(cfg_mod._DEFAULT_CONFIG_PATH)
        config.save(save_path)
        # Invalidate module-level cache so subsequent commands see the new value
        cfg_mod._cached_config = None
        jsonl_emit_result(stage="config", key=key, value=value, message="Config updated")
    except KeyError as exc:
        jsonl_emit_error(stage="config", detail=str(exc))
        raise typer.Exit(1)
    except Exception as exc:
        jsonl_emit_error(stage="config", detail=f"Failed to set config: {exc}")
        raise typer.Exit(1)


# ── config prompt sub-application ────────────────────────────────

prompt_app = typer.Typer(
    name="prompt",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
    help="Prompt template testing",
)


@prompt_app.command(name="test")
def prompt_test(
    type: str = typer.Option(..., "--type", "-t", help="Prompt type: title | tags | classify"),
    url: str = typer.Option(..., "--url", "-u", help="URL to fetch content from"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Path to config file"),
) -> None:
    """Compare built-in and custom prompt results side-by-side."""
    import sys as _sys

    # Windows GBK encoding fix (MEM043/MEM047)
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    if type not in ("title", "tags", "classify"):
        print(f"错误: 不支持的类型 '{type}'，请使用 title, tags, 或 classify")
        raise typer.Exit(1)

    from web_clip_helper.config import Config
    from web_clip_helper.llm import LLMClient

    try:
        config = Config.load(path)
    except Exception as exc:
        print(f"[加载配置失败: {exc}]")
        raise typer.Exit(1)

    # Check if custom prompt is set for the requested type
    custom_template = getattr(config.prompts, type, "")
    if not custom_template or not custom_template.strip():
        print(f"未设置自定义提示词，请先用 config set prompts.{type} 设置")
        raise typer.Exit(1)

    # Route URL and fetch content via adapter
    try:
        from web_clip_helper.adapter import route_url
        adapter_cls = route_url(url)
        adapter = adapter_cls()
        raw_content = adapter.fetch(url)
    except ValueError as exc:
        print(f"[URL 路由失败: {exc}]")
        raise typer.Exit(1)
    except Exception as exc:
        print(f"[内容获取失败: {exc}]")
        raise typer.Exit(1)

    content_md = raw_content.content_md
    source_type = raw_content.source_type

    # Create two LLMClient instances: built-in (no prompts) and custom (with prompts)
    from web_clip_helper.config import PromptConfig

    built_in_client = LLMClient(config.llm)
    custom_client = LLMClient(config.llm, prompts=config.prompts)

    # Call the appropriate method on both clients
    method_map = {
        "title": "generate_title",
        "tags": "extract_tags",
        "classify": "classify_content",
    }
    method_name = method_map[type]

    no_api_key = not config.llm.api_key or not config.llm.api_key.strip()

    def _safe_call(client: LLMClient, label: str) -> str:
        try:
            if no_api_key:
                return "[未配置 API Key]"
            if type == "title":
                result = getattr(client, method_name)(content_md, source_type, url=url)
            else:
                result = getattr(client, method_name)(content_md, source_type)
            if isinstance(result, list):
                return ", ".join(result) if result else "(空)"
            return str(result) if result else "(空)"
        except Exception as exc:
            return f"[调用失败: {exc}]"

    built_in_result = _safe_call(built_in_client, "内置")
    custom_result = _safe_call(custom_client, "自定义")

    # Print human-readable side-by-side comparison
    separator = "─" * 40
    print(f"提示词对比测试 — {type}")
    print(f"URL: {url}")
    print(separator)
    print("【内置提示词结果】")
    print(built_in_result)
    print()
    print("【自定义提示词结果】")
    print(custom_result)
    print(separator)


# Register prompt sub-app on config_app
config_app.add_typer(prompt_app, name="prompt", help="Prompt template testing")

# Register config sub-app on main app
app.add_typer(config_app, name="config", help="Manage configuration")


@app.command()
def clip(
    url: Optional[str] = typer.Argument(None, help="URL to clip"),
    text: Optional[str] = typer.Option(None, "--text", "-t", help="Clip raw text instead of URL"),
) -> None:
    """Clip a URL or raw text into Markdown + storage."""
    if not url and not text:
        jsonl_emit_error(stage="clip", detail="Either a URL or text must be provided")
        raise typer.Exit(1)

    from web_clip_helper.config import get_config
    from web_clip_helper.pipeline import clip_text, clip_url

    config = get_config()

    try:
        if url:
            result = clip_url(url, config)
        else:
            result = clip_text(text or "", config)

        if result is None:
            raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        jsonl_emit_error(stage="clip", detail=f"Unexpected error: {exc}")
        raise typer.Exit(1)


def _get_index():
    """Helper: load config and return a ClipIndex (caller must close)."""
    from web_clip_helper.config import get_config
    from web_clip_helper.index import ClipIndex

    config = get_config()
    return ClipIndex(config.db_path)


@app.command(name="list")
def list_clips(
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category"),
    source_type: Optional[str] = typer.Option(None, "--source-type", "-s", help="Filter by source type"),
) -> None:
    """List clipped items with optional filters. Output is JSONL."""
    idx = _get_index()
    try:
        if tag:
            results = idx.query_clips_by_tag(tag)
        else:
            filters: dict = {}
            if category:
                filters["category"] = category
            if source_type:
                filters["source_type"] = source_type
            results = idx.query_clips(filters or None)

        jsonl_emit_progress(stage="list", message="Query completed", count=len(results))
        for clip in results:
            jsonl_emit_result(stage="list", **clip)
    except Exception as exc:
        jsonl_emit_error(stage="list", detail=f"Query failed: {exc}")
        raise typer.Exit(1)
    finally:
        idx.close()


@app.command(name="get")
def get_clip(
    clip_id: int = typer.Argument(..., help="Clip ID to retrieve"),
) -> None:
    """Get a single clipped item by ID. Output is JSONL."""
    idx = _get_index()
    try:
        record = idx.get_clip(clip_id)
        if record is None:
            jsonl_emit_error(stage="get", detail=f"Clip {clip_id} not found")
            raise typer.Exit(1)
        jsonl_emit_result(stage="get", **record)
    except typer.Exit:
        raise
    except Exception as exc:
        jsonl_emit_error(stage="get", detail=f"Query failed: {exc}")
        raise typer.Exit(1)
    finally:
        idx.close()


@app.command(name="search")
def search_clips(
    keyword: str = typer.Argument(..., help="Search keyword for title/URL"),
) -> None:
    """Search clipped items by keyword in title and URL. Output is JSONL."""
    idx = _get_index()
    try:
        results = idx.search_clips(keyword)
        jsonl_emit_progress(stage="search", message="Search completed", count=len(results))
        for clip in results:
            jsonl_emit_result(stage="search", **clip)
    except Exception as exc:
        jsonl_emit_error(stage="search", detail=f"Search failed: {exc}")
        raise typer.Exit(1)
    finally:
        idx.close()


@app.command(name="tags")
def list_tags() -> None:
    """List all unique tags with usage counts. Output is JSONL."""
    idx = _get_index()
    try:
        tag_list = idx.list_tags()
        jsonl_emit_progress(stage="tags", message="Tags retrieved", count=len(tag_list))
        for entry in tag_list:
            jsonl_emit_result(stage="tags", **entry)
    except Exception as exc:
        jsonl_emit_error(stage="tags", detail=f"Failed to list tags: {exc}")
        raise typer.Exit(1)
    finally:
        idx.close()


@app.command(name="feedback")
def feedback(
    description: str = typer.Argument(..., help="Problem description"),
    feedback_type: str = typer.Option("bug", "--type", help="Feedback type: bug | feature | other"),
) -> None:
    """Generate a feedback file with environment info. Output is JSONL."""
    import platform
    from datetime import datetime
    from pathlib import Path

    from web_clip_helper import __version__
    from web_clip_helper.config import get_config

    if feedback_type not in ("bug", "feature", "other"):
        jsonl_emit_error(stage="feedback", detail=f"Invalid feedback type: {feedback_type}. Must be bug, feature, or other.")
        raise typer.Exit(1)

    config = get_config()

    # Try to get clip count (non-fatal)
    clip_count_str: str = "N/A"
    try:
        from web_clip_helper.index import ClipIndex
        idx = ClipIndex(config.db_path)
        clip_count_str = str(len(idx.query_clips()))
        idx.close()
    except Exception:
        pass

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filename_ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    content = (
        f"# Feedback: {feedback_type}\n"
        f"\n"
        f"## \u95ee\u9898\u63cf\u8ff0\n"
        f"{description}\n"
        f"\n"
        f"## \u73af\u5883\u4fe1\u606f\n"
        f"- Python: {sys.version}\n"
        f"- OS: {platform.platform()}\n"
        f"- web-clip-helper \u7248\u672c: {__version__}\n"
        f"- \u914d\u7f6e\u8def\u5f84: {config.storage_path}\n"
        f"- \u6570\u636e\u5e93: {config.db_path}\n"
        f"- \u526a\u85cf\u6570\u91cf: {clip_count_str}\n"
        f"\n"
        f"## \u751f\u6210\u65f6\u95f4\n"
        f"{timestamp}\n"
    )

    feedback_dir = Path.home() / ".web-clip-helper" / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    filename = f"feedback_{feedback_type}_{filename_ts}.md"
    file_path = feedback_dir / filename

    try:
        file_path.write_text(content, encoding="utf-8")
        jsonl_emit_result(
            stage="feedback",
            file=str(file_path),
            feedback_type=feedback_type,
            message=f"Feedback file generated: {file_path}",
        )
    except Exception as exc:
        jsonl_emit_error(stage="feedback", detail=f"Failed to write feedback file: {exc}")
        raise typer.Exit(1)


@app.command(name="refresh")
def refresh_clips() -> None:
    """Refresh dynamic clipped items that are due for re-clip. Output is JSONL."""
    from web_clip_helper.config import get_config
    from web_clip_helper.index import ClipIndex
    from web_clip_helper.pipeline import clip_url

    config = get_config()
    idx = ClipIndex(config.db_path)
    try:
        refreshable = idx.get_refreshable_clips()

        if not refreshable:
            jsonl_emit_result(stage="refresh", refreshed=0, failed=0, message="No clips due for refresh")
            return

        jsonl_emit_progress(stage="refresh", message=f"Found {len(refreshable)} clips to refresh", count=len(refreshable))

        refreshed_count = 0
        failed_count = 0

        for clip in refreshable:
            clip_id = clip["id"]
            url = clip.get("url", "")
            jsonl_emit_progress(
                stage="refresh",
                message=f"Refreshing clip #{clip_id}: {url}",
                clip_id=clip_id,
            )

            try:
                result = clip_url(url, config)
                if result is None:
                    failed_count += 1
                    jsonl_emit_error(
                        stage="refresh",
                        detail=f"Failed to refresh clip #{clip_id}: clip_url returned None",
                        clip_id=clip_id,
                    )
                    continue

                # Remove old folder contents (markdown + images)
                folder_path = clip.get("folder_path", "")
                if folder_path:
                    from pathlib import Path
                    folder = Path(folder_path)
                    if folder.exists():
                        for child in folder.iterdir():
                            if child.is_file():
                                child.unlink()
                            elif child.is_dir():
                                import shutil
                                shutil.rmtree(child, ignore_errors=True)

                # Update the clip record with new paths
                idx.update_clip(clip_id, {
                    "folder_path": str(result.folder_path),
                    "markdown_path": str(result.markdown_path),
                    "image_count": result.image_count,
                    "title": clip.get("title", ""),  # keep original title unless we want to update
                })

                # Mark as refreshed
                idx.mark_refreshed(clip_id)
                refreshed_count += 1

                jsonl_emit_progress(
                    stage="refresh",
                    message=f"Clip #{clip_id} refreshed successfully",
                    clip_id=clip_id,
                )

            except Exception as exc:
                failed_count += 1
                jsonl_emit_error(
                    stage="refresh",
                    detail=f"Error refreshing clip #{clip_id}: {exc}",
                    clip_id=clip_id,
                )

        jsonl_emit_result(
            stage="refresh",
            refreshed=refreshed_count,
            failed=failed_count,
            message=f"Refresh complete: {refreshed_count} refreshed, {failed_count} failed",
        )

    except Exception as exc:
        jsonl_emit_error(stage="refresh", detail=f"Refresh command failed: {exc}")
        raise typer.Exit(1)
    finally:
        idx.close()
