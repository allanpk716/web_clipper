"""CLI entry point — Typer application with JSONL output.

All user-facing output goes through ``output.jsonl_emit`` — no bare ``print()`` calls.
The :func:`main` function delegates to SDK ``App.run()`` for stdout hijacking,
signal handling, panic recovery, and ``--quiet`` mode.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any, Optional

import click
import typer
from typer.core import TyperGroup

from web_clip_helper.app import get_app, get_reports_dir, get_crash_dumps_dir, get_state_dir, get_data_dir, get_config_dir, flight_update, flight_get, flight_clear
from web_clip_helper.error_codes import exit_code_for
from web_clip_helper.output import jsonl_emit_error, jsonl_emit_help, jsonl_emit_progress, jsonl_emit_result, jsonl_emit_warning, jsonl_emit_dict

# Trigger adapter auto-discovery registration
import web_clip_helper.adapters._registry  # noqa: F401

__all__ = ["app", "config_app", "report_app"]


class _SDKGroup(TyperGroup):
    """Custom TyperGroup that intercepts Click/Typer exceptions and emits JSONL errors.

    Runs commands with standalone_mode=False so that
    click.exceptions.ClickException propagates back to us.  We then
    emit a single JSONL error line with error_code=INPUT_INVALID and
    exit with the correct code.

    All stdout hijacking, signal handling, and panic recovery are
    handled by SDK App.run() — this class is only concerned with
    converting Click exceptions into JSONL errors.
    """

    def main(  # type: ignore[override]
        self,
        args: Any = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        windows_expand_args: bool = True,
        **extra: Any,
    ) -> Any:
        # Always run in non-standalone mode so ClickException and Abort
        # propagate rather than being handled by Click's default renderer.
        try:
            rv = super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )
            # In non-standalone mode, Click returns exit codes (int) instead
            # of raising SystemExit.  SDK App.run() only inspects exceptions,
            # not return values.  Propagate non-zero return values as
            # SystemExit so the SDK can extract the correct exit code.
            if rv is not None and rv != 0:
                raise SystemExit(rv)
            return rv
        except click.exceptions.ClickException as exc:
            # ClickException covers MissingParameter, NoSuchOption, BadParameter,
            # NoArgsIsHelpError, UsageError, etc.
            detail = str(exc.format_message()).strip()
            if not detail:
                detail = "Missing subcommand"
            jsonl_emit_error(
                stage="cli",
                detail=detail,
                error_code="INPUT_INVALID",
            )
            raise SystemExit(exit_code_for("INPUT_INVALID"))
        except click.exceptions.Abort:
            jsonl_emit_error(
                stage="cli",
                detail="Aborted",
                error_code="INPUT_INVALID",
            )
            raise SystemExit(exit_code_for("INPUT_INVALID"))


app = typer.Typer(
    name="web-clip-helper",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
    cls=_SDKGroup,
)

# Description of sub-commands shown in JSONL help output.
_COMMAND_HELP = [
    {"name": "clip", "help": "Clip a URL or raw text into Markdown + storage"},
    {"name": "list", "help": "List clipped items"},
    {"name": "get", "help": "Get a clipped item by ID"},
    {"name": "search", "help": "Search clipped items by keyword"},
    {"name": "tags", "help": "List or manage tags"},
    {"name": "delete", "help": "Delete a clipped item by ID"},
    {"name": "update", "help": "Update clip fields (title, tags, category, dynamic flag, refresh interval)"},
    {"name": "refresh", "help": "Refresh dynamic clipped items"},
    {"name": "report", "help": "Submit and view structured feedback reports"},
    {"name": "config", "help": "Manage configuration (list/get/set + prompt test)"},
    {"name": "version", "help": "Print the current version"},
    {"name": "agent", "help": "Agent reserved namespace — discovery, health, introspection, and runtime management"},
]


@app.callback()
def _cli_callback(
    ctx: typer.Context,
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

    # No subcommand invoked → emit JSONL help and exit cleanly
    if ctx.invoked_subcommand is None:
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
        jsonl_emit_error(stage="config", detail=f"Failed to list config: {exc}", error_code="CONFIG_ERROR")
        raise typer.Exit(exit_code_for("CONFIG_ERROR"))


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
        jsonl_emit_error(stage="config", detail=str(exc), error_code="CONFIG_ERROR")
        raise typer.Exit(exit_code_for("CONFIG_ERROR"))
    except Exception as exc:
        jsonl_emit_error(stage="config", detail=f"Failed to get config: {exc}", error_code="CONFIG_ERROR")
        raise typer.Exit(exit_code_for("CONFIG_ERROR"))


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

        save_path = path or str(get_config_dir() / "config.json")
        config.save(save_path)
        # Invalidate module-level cache so subsequent commands see the new value
        cfg_mod._cached_config = None
        jsonl_emit_result(stage="config", key=key, value=value, message="Config updated")
    except KeyError as exc:
        jsonl_emit_error(stage="config", detail=str(exc), error_code="CONFIG_ERROR")
        raise typer.Exit(exit_code_for("CONFIG_ERROR"))
    except Exception as exc:
        jsonl_emit_error(stage="config", detail=f"Failed to set config: {exc}", error_code="CONFIG_ERROR")
        raise typer.Exit(exit_code_for("CONFIG_ERROR"))


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
    """Compare built-in and custom prompt results as JSONL."""
    import sys as _sys

    # Windows GBK encoding fix (MEM043/MEM047)
    # Guard against _FakeStream (SDK App.run() replaces sys.stdout) which
    # lacks reconfigure.  When running in-process via App.run() the Writer
    # already targets the real stdout, so reconfigure is unnecessary.
    _stdout = _sys.stdout
    if hasattr(_stdout, "reconfigure"):
        _stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    if type not in ("title", "tags", "classify"):
        jsonl_emit_error(stage="prompt_test", detail=f"Unsupported type: {type}", error_code="INVALID_TYPE")
        raise typer.Exit(exit_code_for("INVALID_TYPE"))

    from web_clip_helper.config import Config
    from web_clip_helper.llm import LLMClient

    try:
        config = Config.load(path)
    except Exception as exc:
        jsonl_emit_error(stage="prompt_test", detail=f"Config load failed: {exc}", error_code="CONFIG_ERROR")
        raise typer.Exit(exit_code_for("CONFIG_ERROR"))

    # Check if custom prompt is set for the requested type
    custom_template = getattr(config.prompts, type, "")
    if not custom_template or not custom_template.strip():
        jsonl_emit_error(stage="prompt_test", detail=f"No custom prompt set for prompts.{type}", error_code="NO_CUSTOM_PROMPT")
        raise typer.Exit(exit_code_for("NO_CUSTOM_PROMPT"))

    # Route URL and fetch content via adapter
    try:
        from web_clip_helper.adapter import route_url
        adapter_cls = route_url(url)
        adapter = adapter_cls()
        raw_content = adapter.fetch(url)
    except ValueError as exc:
        jsonl_emit_error(stage="prompt_test", detail=f"URL routing failed: {exc}", error_code="URL_ROUTE_ERROR")
        raise typer.Exit(exit_code_for("URL_ROUTE_ERROR"))
    except Exception as exc:
        jsonl_emit_error(stage="prompt_test", detail=f"Content fetch failed: {exc}", error_code="FETCH_ERROR")
        raise typer.Exit(exit_code_for("FETCH_ERROR"))

    content_md = raw_content.content_md
    source_type = raw_content.source_type

    # Create two LLMClient instances: built-in (no prompts) and custom (with prompts)
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

    jsonl_emit_result(
        stage="prompt_test",
        prompt_type=type,
        url=url,
        built_in=built_in_result,
        custom=custom_result,
    )


# Register prompt sub-app on config_app
config_app.add_typer(prompt_app, name="prompt", help="Prompt template testing")

# Register config sub-app on main app
app.add_typer(config_app, name="config", help="Manage configuration")

# ── Report sub-app ──────────────────────────────────────────────────
report_app = typer.Typer(
    name="report",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
    help="Submit and view structured feedback reports",
)


@report_app.command(name="submit")
def report_submit(
    description: str = typer.Argument(..., help="Problem description"),
    report_type: str = typer.Option("bug", "--type", help="Report type: bug | feature | other"),
    attach: Optional[str] = typer.Option(None, "--attach", help="Attach a file (e.g. JSONL log) to the report"),
) -> None:
    """Submit a structured feedback report. Output is JSONL."""
    import platform
    from datetime import datetime
    from pathlib import Path

    from web_clip_helper import __version__
    from web_clip_helper.config import get_config

    if report_type not in ("bug", "feature", "other"):
        jsonl_emit_error(stage="report_submit", detail=f"Invalid report type: {report_type}. Must be bug, feature, or other.", error_code="INPUT_INVALID")
        raise typer.Exit(exit_code_for("INPUT_INVALID"))

    # Handle --attach option
    attach_content: str | None = None
    attach_path_resolved: str | None = None
    attach_truncated: bool = False
    max_attach_size = 100 * 1024  # 100 KB

    if attach is not None:
        attach_file = Path(attach).expanduser().resolve()
        if not attach_file.is_file():
            jsonl_emit_error(stage="report_submit", detail=f"Attached file not found: {attach}", error_code="INPUT_INVALID")
            raise typer.Exit(exit_code_for("INPUT_INVALID"))

        try:
            raw_bytes = attach_file.read_bytes()
            if len(raw_bytes) > max_attach_size:
                raw_bytes = raw_bytes[:max_attach_size]
                attach_truncated = True
            attach_content = raw_bytes.decode("utf-8", errors="replace")
            attach_path_resolved = str(attach_file)
        except OSError as exc:
            jsonl_emit_error(stage="report_submit", detail=f"Failed to read attached file: {exc}", error_code="INPUT_INVALID")
            raise typer.Exit(exit_code_for("INPUT_INVALID"))

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
        f"# Feedback: {report_type}\n"
        f"\n"
        f"## 问题描述\n"
        f"{description}\n"
        f"\n"
        f"## 环境信息\n"
        f"- Python: {sys.version}\n"
        f"- OS: {platform.platform()}\n"
        f"- web-clip-helper 版本: {__version__}\n"
        f"- 配置路径: {config.storage_path}\n"
        f"- 数据库: {config.db_path}\n"
        f"- 剪藏数量: {clip_count_str}\n"
        f"\n"
        f"## 生成时间\n"
        f"{timestamp}\n"
    )

    # Append attached log section if provided
    if attach_content is not None:
        truncation_notice = ""
        if attach_truncated:
            truncation_notice = "\n> **注意**: 文件超过 100KB，已截断显示。\n"
        content += (
            f"\n## 附加日志\n"
            f"文件: {attach_path_resolved}{truncation_notice}\n"
            f"\n```\n{attach_content}\n```\n"
        )

    reports_dir = get_reports_dir()
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"report_{report_type}_{filename_ts}.md"
    file_path = reports_dir / filename

    try:
        file_path.write_text(content, encoding="utf-8")
        result_kwargs: dict[str, Any] = {
            "stage": "report_submit",
            "file": str(file_path),
            "report_type": report_type,
            "message": f"Report file generated: {file_path}",
        }
        if attach_path_resolved is not None:
            result_kwargs["attached_file"] = attach_path_resolved
        jsonl_emit_result(**result_kwargs)
    except Exception as exc:
        jsonl_emit_error(stage="report_submit", detail=f"Failed to write report file: {exc}", error_code="STORAGE_ERROR")
        raise typer.Exit(exit_code_for("STORAGE_ERROR"))


@report_app.command(name="list")
def report_list() -> None:
    """List all submitted reports. Output is JSONL."""
    from pathlib import Path

    reports_dir = get_reports_dir()

    reports: list[dict[str, str]] = []

    if reports_dir.is_dir():
        md_files = sorted(reports_dir.glob("report_*.md"), reverse=True)
        for md_file in md_files:
            stem = md_file.stem
            # Parse type from stem: report_{type}_{timestamp}
            parts = stem.split("_", 2)
            report_type = parts[1] if len(parts) >= 3 else "unknown"
            # Use mtime as created_at
            created_at = md_file.stat().st_mtime
            reports.append({
                "id": stem,
                "report_type": report_type,
                "created_at": created_at,
                "file": str(md_file),
            })

    jsonl_emit_result(
        stage="report_list",
        reports=reports,
        message=f"Found {len(reports)} report(s)",
    )


@report_app.command(name="show")
def report_show(
    report_id: str = typer.Argument(..., help="Report ID (filename stem, e.g. report_bug_20260503_105540)"),
) -> None:
    """Show a specific report by ID. Output is JSONL."""
    from pathlib import Path

    reports_dir = get_reports_dir()
    file_path = reports_dir / f"{report_id}.md"

    if not file_path.is_file():
        jsonl_emit_error(stage="report_show", detail=f"Report not found: {report_id}", error_code="NOT_FOUND")
        raise typer.Exit(exit_code_for("NOT_FOUND"))

    try:
        content = file_path.read_text(encoding="utf-8")
        jsonl_emit_result(
            stage="report_show",
            report_id=report_id,
            file=str(file_path),
            content=content,
        )
    except Exception as exc:
        jsonl_emit_error(stage="report_show", detail=f"Failed to read report file: {exc}", error_code="STORAGE_ERROR")
        raise typer.Exit(exit_code_for("STORAGE_ERROR"))


# Register report sub-app on main app
app.add_typer(report_app, name="report", help="Submit and view structured feedback reports")


@app.command()
def clip(
    url: Optional[str] = typer.Argument(None, help="URL to clip"),
    text: Optional[str] = typer.Option(None, "--text", "-t", help="Clip raw text instead of URL"),
    no_images: bool = typer.Option(False, "--no-images", help="Skip image downloading entirely"),
    timeout: int = typer.Option(60, "--timeout", help="Wall-clock timeout in seconds for the entire clip operation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview execution plan without performing real IO"),
) -> None:
    """Clip a URL or raw text into Markdown + storage."""
    if not url and not text:
        jsonl_emit_error(stage="clip", detail="Either a URL or text must be provided", error_code="INPUT_INVALID")
        raise typer.Exit(exit_code_for("INPUT_INVALID"))

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

    from web_clip_helper.config import get_config
    from web_clip_helper.pipeline import clip_text, clip_url, plan_clip_text, plan_clip_url

    config = get_config()

    # --dry-run mode: plan-only, no real IO
    if dry_run:
        flight_update(command="clip", url=url, text=text, phase="dry-run")
        try:
            if url:
                plan_clip_url(url, config)
            else:
                plan_clip_text(text or "", config)
        except SystemExit:
            flight_clear()
            raise
        flight_clear()
        return

    flight_update(command="clip", url=url, text=text, phase="starting")

    def _run_clip():
        if url:
            return clip_url(url, config, skip_images=no_images)
        else:
            return clip_text(text or "", config)

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_run_clip)
    try:
        result = future.result(timeout=timeout)
    except FuturesTimeoutError:
        executor.shutdown(wait=False, cancel_futures=True)
        jsonl_emit_error(
            stage="clip",
            detail=f"Clip operation timed out after {timeout}s",
            error_code="TIMEOUT_ERROR",
        )
        raise typer.Exit(exit_code_for("TIMEOUT_ERROR"))

    executor.shutdown(wait=False)
    if result is None:
        last_error_code = flight_get("last_error_code")
        if last_error_code:
            raise typer.Exit(exit_code_for(last_error_code))
        raise typer.Exit(1)
    flight_clear()


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
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Maximum number of results to return"),
    offset: Optional[int] = typer.Option(None, "--offset", help="Number of results to skip"),
) -> None:
    """List clipped items with optional filters and pagination. Output is JSONL."""
    if limit is not None and limit <= 0:
        jsonl_emit_error(stage="list", detail=f"Invalid limit: {limit}. Must be a positive integer", error_code="INPUT_INVALID")
        raise typer.Exit(exit_code_for("INPUT_INVALID"))
    if offset is not None and offset < 0:
        jsonl_emit_error(stage="list", detail=f"Invalid offset: {offset}. Must be a non-negative integer", error_code="INPUT_INVALID")
        raise typer.Exit(exit_code_for("INPUT_INVALID"))

    idx = _get_index()
    try:
        if tag:
            total_results = idx.query_clips_by_tag(tag)
            results = idx.query_clips_by_tag(tag, limit=limit, offset=offset)
        else:
            filters: dict = {}
            if category:
                filters["category"] = category
            if source_type:
                filters["source_type"] = source_type
            total_results = idx.query_clips(filters or None)
            results = idx.query_clips(filters or None, limit=limit, offset=offset)

        jsonl_emit_progress(
            stage="list",
            message="Query completed",
            total_count=len(total_results),
            returned_count=len(results),
        )
        if results:
            for clip in results:
                jsonl_emit_result(
                    stage="list",
                    _total_count=len(total_results),
                    _limit=limit,
                    _offset=offset or 0,
                    **clip,
                )
        else:
            jsonl_emit_result(stage="list", count=0, _total_count=0, _limit=limit, _offset=offset or 0)
    except Exception as exc:
        jsonl_emit_error(stage="list", detail=f"Query failed: {exc}", error_code="INDEX_ERROR")
        raise typer.Exit(exit_code_for("INDEX_ERROR"))
    finally:
        idx.close()


@app.command(name="get")
def get_clip(
    clip_id: int = typer.Argument(..., help="Clip ID to retrieve"),
    content: bool = typer.Option(False, "--content", help="Include markdown body as 'content' field in the result"),
) -> None:
    """Get a single clipped item by ID. Output is JSONL."""
    idx = _get_index()
    try:
        record = idx.get_clip(clip_id)
        if record is None:
            jsonl_emit_error(stage="get", detail=f"Clip {clip_id} not found", error_code="NOT_FOUND")
            raise typer.Exit(exit_code_for("NOT_FOUND"))

        # If --content flag is set, read the markdown file and include it
        if content:
            md_path = record.get("markdown_path", "")
            if md_path:
                try:
                    from pathlib import Path as _Path
                    record["content"] = _Path(md_path).read_text(encoding="utf-8")
                except FileNotFoundError:
                    jsonl_emit_warning(message=f"Markdown file not found: {md_path}", stage="get")
                except UnicodeDecodeError:
                    jsonl_emit_warning(message=f"Markdown file has encoding issues: {md_path}", stage="get")
                except OSError as exc:
                    jsonl_emit_warning(message=f"Failed to read markdown file: {exc}", stage="get")

        jsonl_emit_result(stage="get", **record)
    except typer.Exit:
        raise
    except Exception as exc:
        jsonl_emit_error(stage="get", detail=f"Query failed: {exc}", error_code="INDEX_ERROR")
        raise typer.Exit(exit_code_for("INDEX_ERROR"))
    finally:
        idx.close()


@app.command(name="search")
def search_clips(
    keyword: str = typer.Argument(..., help="Search keyword for title/URL"),
    full: bool = typer.Option(False, "--full", help="Search markdown file content in addition to title/URL"),
) -> None:
    """Search clipped items by keyword in title and URL. Output is JSONL."""
    idx = _get_index()
    try:
        if full:
            results = idx.search_clips_fulltext(keyword)
            mode = "fulltext"
        else:
            results = idx.search_clips(keyword)
            mode = "metadata"
        jsonl_emit_progress(stage="search", message="Search completed", count=len(results), mode=mode)
        if results:
            for clip in results:
                jsonl_emit_result(
                    stage="search",
                    _total_count=len(results),
                    _limit=None,
                    _offset=0,
                    **clip,
                )
        else:
            jsonl_emit_result(stage="search", count=0, _total_count=0, _limit=None, _offset=0)
    except Exception as exc:
        jsonl_emit_error(stage="search", detail=f"Search failed: {exc}", error_code="INDEX_ERROR")
        raise typer.Exit(exit_code_for("INDEX_ERROR"))
    finally:
        idx.close()


@app.command(name="delete")
def delete_clip(
    clip_id: int = typer.Argument(..., help="Clip ID to delete"),
) -> None:
    """Delete a clipped item by ID. Removes record from DB and folder from disk."""
    import shutil
    from pathlib import Path

    idx = _get_index()
    try:
        record = idx.get_clip(clip_id)
        if record is None:
            jsonl_emit_error(stage="delete", detail=f"Clip {clip_id} not found", error_code="NOT_FOUND")
            raise typer.Exit(exit_code_for("NOT_FOUND"))

        folder_path = record.get("folder_path", "")

        # Delete from SQLite
        deleted = idx.delete_clip(clip_id)
        if not deleted:
            jsonl_emit_error(stage="delete", detail=f"Failed to delete clip {clip_id}", error_code="INDEX_ERROR")
            raise typer.Exit(exit_code_for("INDEX_ERROR"))

        # Clean up folder on disk (non-fatal if fails)
        if folder_path:
            folder = Path(folder_path)
            if folder.exists():
                try:
                    shutil.rmtree(folder)
                except Exception as exc:
                    jsonl_emit_warning(message=f"Folder cleanup failed: {exc}", stage="delete")

        jsonl_emit_result(stage="delete", id=clip_id, folder=folder_path, message="Clip deleted")
    except typer.Exit:
        raise
    except Exception as exc:
        jsonl_emit_error(stage="delete", detail=f"Delete failed: {exc}", error_code="INTERNAL_ERROR")
        raise typer.Exit(exit_code_for("INTERNAL_ERROR"))
    finally:
        idx.close()


@app.command(name="tags")
def list_tags() -> None:
    """List all unique tags with usage counts. Output is JSONL."""
    idx = _get_index()
    try:
        tag_list = idx.list_tags()
        jsonl_emit_progress(stage="tags", message="Tags retrieved", count=len(tag_list))
        if tag_list:
            for entry in tag_list:
                jsonl_emit_result(stage="tags", **entry)
        else:
            jsonl_emit_result(stage="tags", count=0)
    except Exception as exc:
        jsonl_emit_error(stage="tags", detail=f"Failed to list tags: {exc}", error_code="INDEX_ERROR")
        raise typer.Exit(exit_code_for("INDEX_ERROR"))
    finally:
        idx.close()


@app.command(name="update")
def update_clip(
    clip_id: int = typer.Argument(..., help="Clip ID to update"),
    dynamic: Optional[bool] = typer.Option(None, "--dynamic/--no-dynamic", help="Set dynamic flag"),
    interval: Optional[int] = typer.Option(None, "--interval", "-i", help="Refresh interval in days"),
    title: Optional[str] = typer.Option(None, "--title", help="New title for the clip"),
    tags: Optional[str] = typer.Option(None, "--tags", help="New tags as JSON array string, e.g. '[\"tag1\",\"tag2\"]'"),
    category: Optional[str] = typer.Option(None, "--category", help="New category for the clip"),
) -> None:
    """Update clip fields (title, tags, category, dynamic flag, refresh interval). Output is JSONL."""
    has_update = any(v is not None for v in [dynamic, interval, title, tags, category])
    if not has_update:
        jsonl_emit_error(stage="update", detail="At least one option (--title, --tags, --category, --dynamic/--no-dynamic, or --interval) is required", error_code="INPUT_INVALID")
        raise typer.Exit(exit_code_for("INPUT_INVALID"))

    if interval is not None and interval <= 0:
        jsonl_emit_error(stage="update", detail=f"Invalid interval: {interval}. Must be a positive integer", error_code="INPUT_INVALID")
        raise typer.Exit(exit_code_for("INPUT_INVALID"))

    # Parse tags JSON array
    parsed_tags: list[str] | None = None
    if tags is not None:
        try:
            parsed_tags = json.loads(tags)
            if not isinstance(parsed_tags, list):
                jsonl_emit_error(stage="update", detail=f"Invalid tags: must be a JSON array, got {type(parsed_tags).__name__}", error_code="INPUT_INVALID")
                raise typer.Exit(exit_code_for("INPUT_INVALID"))
            for i, t in enumerate(parsed_tags):
                if not isinstance(t, str):
                    jsonl_emit_error(stage="update", detail=f"Invalid tags: element at index {i} is not a string ({type(t).__name__})", error_code="INPUT_INVALID")
                    raise typer.Exit(exit_code_for("INPUT_INVALID"))
        except json.JSONDecodeError as exc:
            jsonl_emit_error(stage="update", detail=f"Invalid tags JSON: {exc}", error_code="INPUT_INVALID")
            raise typer.Exit(exit_code_for("INPUT_INVALID"))

    idx = _get_index()
    try:
        record = idx.get_clip(clip_id)
        if record is None:
            jsonl_emit_error(stage="update", detail=f"Clip {clip_id} not found", error_code="NOT_FOUND")
            raise typer.Exit(exit_code_for("NOT_FOUND"))

        updates: dict[str, Any] = {}
        if title is not None:
            updates["title"] = title
        if parsed_tags is not None:
            updates["tags"] = parsed_tags
        if category is not None:
            updates["category"] = category
        if dynamic is not None:
            updates["is_dynamic"] = 1 if dynamic else 0
        if interval is not None:
            updates["refresh_interval_days"] = interval

        idx.update_clip(clip_id, updates)

        # Build result dict with updated field values
        result_data: dict[str, Any] = {"id": clip_id}
        if title is not None:
            result_data["title"] = title
        if parsed_tags is not None:
            result_data["tags"] = parsed_tags
        if category is not None:
            result_data["category"] = category
        if dynamic is not None:
            result_data["is_dynamic"] = 1 if dynamic else 0
        if interval is not None:
            result_data["refresh_interval_days"] = interval

        jsonl_emit_result(stage="update", **result_data)
    except typer.Exit:
        raise
    except Exception as exc:
        jsonl_emit_error(stage="update", detail=f"Update failed: {exc}", error_code="INDEX_ERROR")
        raise typer.Exit(exit_code_for("INDEX_ERROR"))
    finally:
        idx.close()


@app.command(name="refresh")
def refresh_clips(
    re_enrich: bool = typer.Option(False, "--re-enrich", help="Re-run LLM enrichment to regenerate tags/category"),
) -> None:
    """Refresh dynamic clipped items that are due for re-clip. Output is JSONL."""
    from web_clip_helper.config import get_config
    from web_clip_helper.index import ClipIndex
    from web_clip_helper.pipeline import clip_url

    config = get_config()
    flight_update(command="refresh", phase="starting")
    idx = ClipIndex(config.db_path)
    try:
        refreshable = idx.get_refreshable_clips()

        if not refreshable:
            jsonl_emit_result(stage="refresh", refreshed=0, failed=0, message="No clips due for refresh")
            return

        jsonl_emit_progress(
            stage="refresh",
            message=f"Found {len(refreshable)} clips to refresh",
            count=len(refreshable),
            re_enrich=re_enrich,
        )

        refreshed_count = 0
        failed_count = 0

        for clip in refreshable:
            clip_id = clip["id"]
            url = clip.get("url", "")
            # Preserve original metadata
            original_tags = clip.get("tags", [])
            original_category = clip.get("category", "")
            original_title = clip.get("title", "")

            jsonl_emit_progress(
                stage="refresh",
                message=f"Refreshing clip #{clip_id}: {url}",
                clip_id=clip_id,
                re_enrich=re_enrich,
            )

            try:
                result = clip_url(url, config)
                if result is None:
                    failed_count += 1
                    jsonl_emit_error(
                        stage="refresh",
                        detail=f"Failed to refresh clip #{clip_id}: clip_url returned None",
                        clip_id=clip_id,
                        error_code="REFRESH_ERROR",
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

                # Build update dict — always preserve original title, tags, category
                updates: dict[str, Any] = {
                    "folder_path": str(result.folder_path),
                    "markdown_path": str(result.markdown_path),
                    "image_count": result.image_count,
                    "title": original_title,
                    "tags": original_tags,
                    "category": original_category,
                }

                # When --re-enrich is set, run LLM on the new markdown content
                if re_enrich:
                    try:
                        from pathlib import Path as _Path
                        from web_clip_helper.llm import LLMClient

                        new_md = _Path(result.markdown_path).read_text(encoding="utf-8")
                        client = LLMClient(config.llm, prompts=config.prompts)
                        new_tags = client.extract_tags(new_md, clip.get("source_type", "web"))
                        new_category = client.classify_content(new_md, clip.get("source_type", "web"))
                        updates["tags"] = new_tags
                        updates["category"] = new_category
                    except Exception as exc:
                        jsonl_emit_warning(
                            message=f"LLM re-enrichment failed for clip #{clip_id}: {exc}",
                            stage="refresh",
                        )
                        # Keep original tags/category on failure

                idx.update_clip(clip_id, updates)

                # Mark as refreshed
                idx.mark_refreshed(clip_id)
                refreshed_count += 1

                jsonl_emit_progress(
                    stage="refresh",
                    message=f"Clip #{clip_id} refreshed successfully",
                    clip_id=clip_id,
                    re_enrich=re_enrich,
                )

            except Exception as exc:
                failed_count += 1
                jsonl_emit_error(
                    stage="refresh",
                    detail=f"Error refreshing clip #{clip_id}: {exc}",
                    clip_id=clip_id,
                    error_code="REFRESH_ERROR",
                )

        jsonl_emit_result(
            stage="refresh",
            refreshed=refreshed_count,
            failed=failed_count,
            message=f"Refresh complete: {refreshed_count} refreshed, {failed_count} failed",
            re_enrich=re_enrich,
        )
        flight_clear()

    except Exception as exc:
        jsonl_emit_error(stage="refresh", detail=f"Refresh command failed: {exc}", error_code="REFRESH_ERROR")
        raise typer.Exit(exit_code_for("REFRESH_ERROR"))
    finally:
        idx.close()


# ── Agent reserved namespace (SDK + custom extensions) ───────────

_SENSITIVE_KEY_PARTS = {"api_key", "secret", "token", "password"}

# Build SDK agent Typer with standard commands:
#   schema, errors, config list/set, doctor, debug-last-crash, cache-clean
_agent_typer = get_app().agent_commands()


# ── Custom extension: agent info ──────────────────────────────────


@_agent_typer.command(name="info")
def agent_info() -> None:
    """Output tool version, description, and documentation pointers as JSONL."""
    from web_clip_helper import __version__

    jsonl_emit_result(
        stage="agent_info",
        name="web-clip-helper",
        version=__version__,
        description="LLM Agent-oriented web clipping tool",
        docs="https://github.com/your-org/web-clip-helper/blob/main/README.md",
    )


# ── Custom extension: agent update ───────────────────────────────


_agent_update_app = typer.Typer(
    name="update",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
    help="Check for updates",
)


@_agent_update_app.command(name="check")
def agent_update_check() -> None:
    """Check PyPI for a newer version of web-clip-helper.

    Queries the PyPI JSON API and compares the latest release version
    with the currently installed version.  Outputs a single JSONL line:
    - ``type=result`` with ``up_to_date`` / ``current_version`` / ``latest_version``
    - ``type=error`` on network failure (``NETWORK_ERROR``) or unexpected
      responses (``INTERNAL_ERROR``).
    """
    import time

    import httpx
    from packaging.version import Version, InvalidVersion

    from web_clip_helper import __version__

    start = time.monotonic()
    current_version = __version__
    pypi_url = "https://pypi.org/pypi/web-clip-helper/json"

    try:
        resp = httpx.get(pypi_url, timeout=10.0)
        elapsed = (time.monotonic() - start) * 1000

        if resp.status_code == 404:
            jsonl_emit_result(
                stage="agent_update_check",
                current_version=current_version,
                up_to_date=True,
                status="unpublished",
                detail="Package not found on PyPI — may not be published yet",
                duration_ms=round(elapsed, 2),
            )
            return

        resp.raise_for_status()
        data = resp.json()

        info = data.get("info", {})
        latest_str = info.get("version", "")
        if not latest_str:
            jsonl_emit_error(
                stage="agent_update_check",
                detail="PyPI response missing version field",
                error_code="INTERNAL_ERROR",
            )
            return

        try:
            latest_version = Version(latest_str)
            current = Version(current_version)
        except InvalidVersion:
            jsonl_emit_error(
                stage="agent_update_check",
                detail=f"Invalid version string: current={current_version!r}, latest={latest_str!r}",
                error_code="INTERNAL_ERROR",
            )
            return

        if latest_version > current:
            changelog_url = f"https://pypi.org/project/web-clip-helper/{latest_str}/#history"
            jsonl_emit_result(
                stage="agent_update_check",
                current_version=current_version,
                latest_version=latest_str,
                up_to_date=False,
                changelog_url=changelog_url,
                duration_ms=round(elapsed, 2),
            )
        else:
            jsonl_emit_result(
                stage="agent_update_check",
                current_version=current_version,
                latest_version=latest_str,
                up_to_date=True,
                duration_ms=round(elapsed, 2),
            )

    except httpx.TimeoutException:
        elapsed = (time.monotonic() - start) * 1000
        jsonl_emit_error(
            stage="agent_update_check",
            detail=f"PyPI request timed out after {round(elapsed, 0)}ms",
            error_code="NETWORK_ERROR",
        )
    except httpx.HTTPStatusError as exc:
        elapsed = (time.monotonic() - start) * 1000
        jsonl_emit_error(
            stage="agent_update_check",
            detail=f"PyPI returned HTTP {exc.response.status_code}",
            error_code="NETWORK_ERROR",
        )
    except httpx.RequestError as exc:
        elapsed = (time.monotonic() - start) * 1000
        jsonl_emit_error(
            stage="agent_update_check",
            detail=f"Network error: {exc}",
            error_code="NETWORK_ERROR",
        )
    except Exception as exc:
        elapsed = (time.monotonic() - start) * 1000
        jsonl_emit_error(
            stage="agent_update_check",
            detail=f"Unexpected error checking for updates: {exc}",
            error_code="INTERNAL_ERROR",
        )


@_agent_update_app.command(name="apply")
def agent_update_apply(
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm upgrade without interactive prompt"),
) -> None:
    """Trigger an in-place upgrade via pip install --upgrade.

    Requires --yes flag for explicit confirmation.  Before applying,
    runs an update check to confirm a newer version exists.
    If already up-to-date, outputs type=result with status=already_up_to_date.
    On success, outputs type=result with old_version and new_version.
    """
    import subprocess

    from packaging.version import Version

    from web_clip_helper import __version__

    if not yes:
        jsonl_emit_error(
            stage="agent_update_apply",
            detail="--yes flag is required for non-interactive upgrade",
            error_code="INPUT_INVALID",
        )
        raise typer.Exit(exit_code_for("INPUT_INVALID"))

    old_version = __version__

    # Check if a newer version is available first
    import httpx

    pypi_url = "https://pypi.org/pypi/web-clip-helper/json"
    try:
        resp = httpx.get(pypi_url, timeout=10.0)
        if resp.status_code == 404:
            jsonl_emit_result(
                stage="agent_update_apply",
                status="unpublished",
                current_version=old_version,
                detail="Package not found on PyPI",
            )
            return

        resp.raise_for_status()
        data = resp.json()
        latest_str = data.get("info", {}).get("version", "")
        if not latest_str:
            jsonl_emit_error(
                stage="agent_update_apply",
                detail="PyPI response missing version field",
                error_code="INTERNAL_ERROR",
            )
            raise typer.Exit(exit_code_for("INTERNAL_ERROR"))

        try:
            latest_version = Version(latest_str)
            current = Version(old_version)
        except Exception:
            jsonl_emit_error(
                stage="agent_update_apply",
                detail=f"Invalid version string: current={old_version!r}, latest={latest_str!r}",
                error_code="INTERNAL_ERROR",
            )
            raise typer.Exit(exit_code_for("INTERNAL_ERROR"))

        if latest_version <= current:
            jsonl_emit_result(
                stage="agent_update_apply",
                status="already_up_to_date",
                current_version=old_version,
                latest_version=latest_str,
            )
            return

    except httpx.TimeoutException:
        jsonl_emit_error(
            stage="agent_update_apply",
            detail="PyPI request timed out during update check",
            error_code="NETWORK_ERROR",
        )
        raise typer.Exit(exit_code_for("NETWORK_ERROR"))
    except httpx.HTTPStatusError as exc:
        jsonl_emit_error(
            stage="agent_update_apply",
            detail=f"PyPI returned HTTP {exc.response.status_code}",
            error_code="NETWORK_ERROR",
        )
        raise typer.Exit(exit_code_for("NETWORK_ERROR"))
    except httpx.RequestError as exc:
        jsonl_emit_error(
            stage="agent_update_apply",
            detail=f"Network error: {exc}",
            error_code="NETWORK_ERROR",
        )
        raise typer.Exit(exit_code_for("NETWORK_ERROR"))
    except typer.Exit:
        raise
    except Exception as exc:
        if "INPUT_INVALID" in str(exc) or "INTERNAL_ERROR" in str(exc):
            raise
        jsonl_emit_error(
            stage="agent_update_apply",
            detail=f"Unexpected error checking for updates: {exc}",
            error_code="INTERNAL_ERROR",
        )
        raise typer.Exit(exit_code_for("INTERNAL_ERROR"))

    # New version available — proceed with pip install --upgrade
    jsonl_emit_progress(
        stage="agent_update_apply",
        message=f"Upgrading from {old_version} to {latest_str}...",
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "web-clip-helper"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            stderr_detail = proc.stderr.strip() or "pip install failed with no stderr"
            jsonl_emit_error(
                stage="agent_update_apply",
                detail=stderr_detail,
                error_code="INTERNAL_ERROR",
            )
            raise typer.Exit(exit_code_for("INTERNAL_ERROR"))

        # Re-import to get new version (best-effort)
        try:
            import importlib
            import web_clip_helper
            importlib.reload(web_clip_helper)
            new_version = web_clip_helper.__version__
        except Exception:
            new_version = latest_str

        jsonl_emit_result(
            stage="agent_update_apply",
            status="upgraded",
            old_version=old_version,
            new_version=new_version,
        )
    except subprocess.TimeoutExpired:
        jsonl_emit_error(
            stage="agent_update_apply",
            detail="pip install --upgrade timed out after 120s",
            error_code="TIMEOUT_ERROR",
        )
        raise typer.Exit(exit_code_for("TIMEOUT_ERROR"))
    except typer.Exit:
        raise
    except Exception as exc:
        jsonl_emit_error(
            stage="agent_update_apply",
            detail=f"Upgrade failed: {exc}",
            error_code="INTERNAL_ERROR",
        )
        raise typer.Exit(exit_code_for("INTERNAL_ERROR"))


_agent_typer.add_typer(_agent_update_app, name="update", help="Check for updates")


# ── Custom extension: agent auth ──────────────────────────────────


_agent_auth_app = typer.Typer(
    name="auth",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
    help="Authentication status checks",
)


@_agent_auth_app.command(name="status")
def agent_auth_status() -> None:
    """Check LLM API key validity via lightweight 1-token completion ping.

    Outputs type=result JSONL with status (valid/invalid/not_configured),
    masked key hint, and response latency.  Never outputs plaintext tokens.
    """
    import time

    import httpx

    from web_clip_helper.config import _mask_api_key, get_config

    config = get_config()

    if not config.llm.api_key or not config.llm.api_key.strip():
        jsonl_emit_result(
            stage="agent_auth_status",
            status="not_configured",
            masked_key="",
            message="No API key configured",
        )
        return

    masked_key = _mask_api_key(config.llm.api_key)
    url = f"{config.llm.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.llm.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.llm.model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }

    start = time.monotonic()
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
        elapsed_ms = (time.monotonic() - start) * 1000
        resp.raise_for_status()
        jsonl_emit_result(
            stage="agent_auth_status",
            status="valid",
            masked_key=masked_key,
            latency_ms=round(elapsed_ms, 2),
        )
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start) * 1000
        jsonl_emit_result(
            stage="agent_auth_status",
            status="invalid",
            masked_key=masked_key,
            latency_ms=round(elapsed_ms, 2),
            detail=str(exc),
        )


_agent_typer.add_typer(_agent_auth_app, name="auth", help="Authentication status checks")


# ── Custom extension: agent debug-env ─────────────────────────────


@_agent_typer.command("debug-env")
def agent_debug_env(
    redact: bool = typer.Option(True, "--redact/--no-redact", help="Force redaction of sensitive values"),
) -> None:
    """Collect and output an environment snapshot as type=result JSONL.

    Includes Python version, OS details, tool version, directory paths,
    LLM configuration (with api_key masked), dependency versions, and
    environment variable indicators.
    """
    import platform

    from web_clip_helper import __version__
    from web_clip_helper.config import get_config

    config = get_config()

    # ── Python section ─────────────────────────────────────────
    python_info: dict[str, str] = {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
    }

    # ── OS section ─────────────────────────────────────────────
    os_info: dict[str, str] = {
        "name": os.name,
        "platform": sys.platform,
        "architecture": platform.machine(),
    }

    # ── Tool section ───────────────────────────────────────────
    tool_info: dict[str, str] = {
        "version": __version__,
    }

    # ── Directories section ────────────────────────────────────
    dirs_info: dict[str, str] = {
        "config_dir": str(get_config_dir()),
        "data_dir": str(get_data_dir()),
        "state_dir": str(get_state_dir()),
    }

    # ── LLM section (sensitive values masked) ──────────────────
    llm_info: dict[str, str] = {
        "base_url": config.llm.base_url,
        "model": config.llm.model,
        "api_key_set": "true" if config.llm.api_key else "false",
    }
    if config.llm.api_key:
        from web_clip_helper.config import _mask_api_key

        llm_info["api_key_hint"] = _mask_api_key(config.llm.api_key)

    # ── Dependencies section ───────────────────────────────────
    deps_info: dict[str, str] = {}
    for dep_name in ("httpx", "typer", "readability", "markdownify", "platformdirs", "yaml"):
        try:
            if dep_name == "yaml":
                import yaml

                deps_info["yaml"] = yaml.__version__
            elif dep_name == "readability":
                import readability

                deps_info["readability-lxml"] = getattr(readability, "__version__", "unknown")
            else:
                mod = __import__(dep_name)
                deps_info[dep_name] = getattr(mod, "__version__", "unknown")
        except ImportError:
            deps_info[dep_name] = "not_installed"

    # ── Environment indicators ─────────────────────────────────
    env_indicators: dict[str, str] = {}
    for var in ("WEB_CLIP_LLM_API_KEY", "WEB_CLIP_LLM_BASE_URL", "WEB_CLIP_LLM_MODEL", "AGENT_TRACE_ID"):
        env_indicators[var] = "set" if os.environ.get(var) else "unset"

    # ── Redaction pass (force-redact any sensitive values) ──────
    all_sections: dict[str, dict[str, str]] = {
        "python": python_info,
        "os": os_info,
        "tool": tool_info,
        "directories": dirs_info,
        "llm": llm_info,
        "dependencies": deps_info,
        "env_indicators": env_indicators,
    }

    if redact:
        for section_data in all_sections.values():
            for key in list(section_data.keys()):
                key_lower = key.lower()
                if any(p in key_lower for p in _SENSITIVE_KEY_PARTS):
                    val = section_data[key]
                    if isinstance(val, str) and val:
                        section_data[key] = f"{val[:3]}****"
                    else:
                        section_data[key] = "****"

    jsonl_emit_result(data=all_sections, stage="agent_debug_env")


# ── Custom extension: agent feature ──────────────────────────────


_agent_feature_app = typer.Typer(
    name="feature",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
    help="Record and list feature/capability requests",
)


@_agent_feature_app.command("record")
def agent_feature_record(
    name: str = typer.Option(..., "--name", "-n", help="Feature name"),
    desc: str = typer.Option(..., "--desc", "-d", help="Feature description"),
) -> None:
    """Record a feature/capability request to state_dir/feature_requests.jsonl.

    Each entry includes: id (uuid4 hex[:12]), name, description,
    recorded_at (ISO 8601 UTC), tool_version.  Outputs type=result
    JSONL with the recorded entry's id and file path.
    """
    from datetime import datetime, timezone

    from web_clip_helper import __version__

    if not name or not name.strip():
        jsonl_emit_error(
            stage="agent_feature_record",
            detail="--name must be non-empty",
            error_code="INPUT_INVALID",
        )
        raise typer.Exit(exit_code_for("INPUT_INVALID"))

    if not desc or not desc.strip():
        jsonl_emit_error(
            stage="agent_feature_record",
            detail="--desc must be non-empty",
            error_code="INPUT_INVALID",
        )
        raise typer.Exit(exit_code_for("INPUT_INVALID"))

    entry_id = uuid.uuid4().hex[:12]
    entry = {
        "id": entry_id,
        "name": name.strip(),
        "description": desc.strip(),
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
        "tool_version": __version__,
    }

    state_dir = get_state_dir()
    feature_file = state_dir / "feature_requests.jsonl"

    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with open(feature_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        jsonl_emit_result(
            stage="agent_feature_record",
            id=entry_id,
            file=str(feature_file),
            status="recorded",
        )
    except OSError as exc:
        jsonl_emit_error(
            stage="agent_feature_record",
            detail=f"Failed to write feature request: {exc}",
            error_code="STORAGE_ERROR",
        )
        raise typer.Exit(exit_code_for("STORAGE_ERROR"))


@_agent_feature_app.command("list")
def agent_feature_list() -> None:
    """Read all feature request entries and output one type=dict JSONL line per entry.

    If file doesn't exist or is empty, outputs type=result with total=0.
    Entries sorted newest-first.
    """
    state_dir = get_state_dir()
    feature_file = state_dir / "feature_requests.jsonl"

    if not feature_file.exists():
        jsonl_emit_result(
            stage="agent_feature_list",
            total=0,
            detail="No feature requests file found",
        )
        return

    entries: list[dict] = []
    try:
        for line in feature_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    except (json.JSONDecodeError, OSError) as exc:
        jsonl_emit_error(
            stage="agent_feature_list",
            detail=f"Failed to read feature requests: {exc}",
            error_code="STORAGE_ERROR",
        )
        raise typer.Exit(exit_code_for("STORAGE_ERROR"))

    if not entries:
        jsonl_emit_result(
            stage="agent_feature_list",
            total=0,
            detail="Feature requests file is empty",
        )
        return

    # Output newest-first
    for entry in reversed(entries):
        jsonl_emit_dict(data=entry, stage="agent_feature_list")

    jsonl_emit_result(
        stage="agent_feature_list",
        total=len(entries),
    )


_agent_typer.add_typer(_agent_feature_app, name="feature", help="Record and list feature/capability requests")


# ── Custom extension: agent metrics ──────────────────────────────


_agent_metrics_app = typer.Typer(
    name="metrics",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=True,
    help="Metrics and tracing",
)


@_agent_metrics_app.command("trace")
def agent_metrics_trace(
    id: str = typer.Option(..., "--id", help="Trace ID to search for in crash dumps"),
) -> None:
    """Search crash dump files for entries matching the given trace_id.

    First checks .last-crash.json, then scans any other .json files
    in the crash_dumps directory.  For each match, outputs type=dict
    JSONL with the crash data.  If no matches found, outputs type=result
    with status=not_found.
    """
    if not id or not id.strip():
        jsonl_emit_error(
            stage="agent_metrics_trace",
            detail="--id must be non-empty",
            error_code="INPUT_INVALID",
        )
        raise typer.Exit(exit_code_for("INPUT_INVALID"))

    trace_id = id.strip()
    crash_dir = get_crash_dumps_dir()
    matches: list[dict] = []

    # Check .last-crash.json first
    last_crash = crash_dir / ".last-crash.json"
    if last_crash.exists():
        try:
            data = json.loads(last_crash.read_text(encoding="utf-8"))
            if data.get("trace_id") == trace_id:
                matches.append(data)
        except (json.JSONDecodeError, OSError):
            pass

    # Scan other .json files in crash_dumps directory
    if crash_dir.exists():
        for json_file in sorted(crash_dir.glob("*.json")):
            if json_file.name == ".last-crash.json":
                continue  # already checked
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                # Could be a list of entries or a single dict
                if isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict) and entry.get("trace_id") == trace_id:
                            matches.append(entry)
                elif isinstance(data, dict) and data.get("trace_id") == trace_id:
                    matches.append(data)
            except (json.JSONDecodeError, OSError):
                pass

    if not matches:
        jsonl_emit_result(
            stage="agent_metrics_trace",
            status="not_found",
            trace_id=trace_id,
            detail=f"No crash dumps found matching trace_id={trace_id}",
        )
        return

    for match in matches:
        jsonl_emit_dict(data=match, stage="agent_metrics_trace")


_agent_typer.add_typer(_agent_metrics_app, name="metrics", help="Metrics and tracing")

# Register agent namespace on main app
app.add_typer(_agent_typer, name="agent", help="Agent reserved namespace — discovery, health, introspection, and runtime management")



@app.command(name="version")
def version_command() -> None:
    """Print the current version as JSONL."""
    from web_clip_helper import __version__

    jsonl_emit_result(stage="version", version=__version__)


def main() -> None:
    """Entry point: delegate to SDK App.run() for stdout hijacking, signals, and panic recovery."""
    sdk_app = get_app()
    code = sdk_app.run(app)
    captured = sdk_app.captured_output
    if captured and code == 0 and not captured.lstrip().startswith("{"):
        # Non-JSONL output on success path — likely --help rendering Rich text.
        # The _SDKGroup no longer handles this, so we intercept here.
        _emit_jsonl_help_from_capture(sdk_app, captured)
    sys.exit(code)


def _emit_jsonl_help_from_capture(sdk_app: Any, captured: str) -> None:
    """Emit JSONL help when captured output is non-JSONL (e.g. Rich-rendered --help)."""
    # Best-effort: try to parse the args from the captured output to resolve
    # the subcommand.  Fall back to root help on failure.
    jsonl_emit_help(
        commands=_COMMAND_HELP,
        description="LLM Agent-oriented web clipping CLI tool",
    )


if __name__ == "__main__":
    main()
