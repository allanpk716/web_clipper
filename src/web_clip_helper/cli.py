"""CLI entry point — Typer application with JSONL output.

All user-facing output goes through ``output.jsonl_emit`` — no bare ``print()`` calls.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Optional

import click
import typer
from typer.core import TyperGroup

import io

from web_clip_helper.output import jsonl_emit_error, jsonl_emit_help, jsonl_emit_progress, jsonl_emit_result, jsonl_emit_warning, set_quiet

# Trigger adapter auto-discovery registration
import web_clip_helper.adapters._registry  # noqa: F401

__all__ = ["app", "config_app", "report_app"]


class _CapturedOutput(io.StringIO):
    """A StringIO that also remembers the real stdout for write-through on success.

    Delegates attribute access to the real stdout for any attribute not
    found on StringIO itself.  This is necessary because Click/Rich call
    ``sys.stdout.reconfigure()``, read ``sys.stdout.encoding``, etc.
    during normal command execution — not just on error paths.
    """

    def __init__(self, real_stdout: Any) -> None:
        super().__init__()
        self._real_stdout = real_stdout

    def __getattr__(self, name: str) -> Any:
        # Delegate to the real stdout for any attribute we don't have.
        # This covers reconfigure(), encoding, buffer, isatty(), fileno(), etc.
        return getattr(self._real_stdout, name)


class _JSONLGroup(TyperGroup):
    """Custom TyperGroup that intercepts Click/Typer exceptions and emits JSONL errors.

    Instead of letting Click/Typer render exceptions as rich text (or plain text),
    we run the command in ``standalone_mode=False`` so that
    ``click.exceptions.ClickException`` (MissingParameter, NoSuchOption,
    BadParameter, NoArgsIsHelpError, etc.) propagates back to us.  We then
    emit a single JSONL error line with ``error_code=INPUT_INVALID`` and
    propagate the correct exit code.
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
        if not standalone_mode:
            # Non-standalone callers (programmatic use) get default behaviour
            return super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                windows_expand_args=windows_expand_args,
                **extra,
            )

        # Standalone mode — intercept all Click/Typer exceptions for JSONL output.
        # We run the inner main in non-standalone mode so ClickException and
        # Abort propagate rather than being handled by Click's default renderer.
        #
        # Redirect stdout to a buffer during execution.  Some Click exceptions
        # (notably NoArgsIsHelpError) render Rich help text to stdout as a
        # side-effect of constructing the exception object — before the
        # exception even reaches our handler.  By capturing stdout, we prevent
        # that Rich text from leaking into the JSONL output stream.
        original_stdout = sys.stdout
        captured = _CapturedOutput(original_stdout)
        sys.stdout = captured
        try:
            rv = super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,  # let exceptions propagate
                windows_expand_args=windows_expand_args,
                **extra,
            )
            captured_output = captured.getvalue()
            sys.stdout = original_stdout

            # When Click returns exit code 0 with captured output that is NOT
            # valid JSONL, this is typically --help rendering Rich text.
            # Intercept and emit JSONL help instead of flushing Rich text.
            # Normal command output is JSONL (starts with '{'), while Rich
            # help output starts with whitespace/box-drawing chars.
            is_help_output = (
                captured_output
                and rv in (0, None)
                and not captured_output.lstrip().startswith("{")
            )
            if is_help_output:
                self._emit_subcommand_jsonl_help(args)
                sys.exit(0)

            # Success path: flush any legitimate captured output back to real stdout.
            if captured_output:
                original_stdout.write(captured_output)
                original_stdout.flush()
            # In non-standalone mode, a non-None return value is an exit code
            # (from click.exceptions.Exit being caught internally).  Propagate
            # it as a real exit so the CLI behaves correctly.
            if rv is not None:
                sys.exit(rv)
            return rv
        except click.exceptions.ClickException as exc:
            # Discard any Rich/Click text that was written to stdout before
            # the exception reached us, then restore the real stdout.
            sys.stdout = original_stdout
            # ClickException covers MissingParameter, NoSuchOption, BadParameter,
            # NoArgsIsHelpError, UsageError, etc.
            detail = str(exc.format_message()).strip()
            if not detail:
                # NoArgsIsHelpError: ctx.get_help() renders Rich text to stdout
                # (captured and discarded above) and returns "".  Provide a
                # meaningful detail instead.
                detail = "Missing subcommand"
            jsonl_emit_error(
                stage="cli",
                detail=detail,
                error_code="INPUT_INVALID",
            )
            sys.exit(exc.exit_code)
        except click.exceptions.Abort:
            sys.stdout = original_stdout
            jsonl_emit_error(
                stage="cli",
                detail="Aborted",
                error_code="INPUT_INVALID",
            )
            sys.exit(1)
        except SystemExit as exc:
            sys.stdout = original_stdout
            # If exit code is 0, help was already emitted by the success-path
            # handler above.  Just propagate the exit.
            sys.exit(exc.code if exc.code is not None else 0)
        except Exception:
            sys.stdout = original_stdout
            raise

    def _emit_subcommand_jsonl_help(self, args: Any) -> None:
        """Resolve the subcommand from *args* and emit JSONL help.

        Walks the Click command tree using the argument list (minus ``--help``/``-h``)
        to find the leaf command/group.  Then extracts its parameters (options and
        arguments) and emits structured JSONL help via :func:`jsonl_emit_help`.
        """
        import click as _click

        # Normalise args to a list of strings
        if args is None:
            args = sys.argv[1:]
        arg_list = list(args)

        # Strip --help / -h from the end so command resolution works
        cleaned = [a for a in arg_list if a not in ("--help", "-h")]
        if not cleaned:
            # Bare --help with no subcommand — root help is handled by
            # the main callback's eager help_flag, but belt-and-suspenders.
            jsonl_emit_help(
                commands=_COMMAND_HELP,
                description="LLM Agent-oriented web clipping CLI tool",
            )
            return

        # Walk the command tree
        ctx = _click.Context(_click.Command("root"))
        cmd: click.Command | click.MultiCommand | None = self  # type: ignore[assignment]
        command_chain: list[str] = []

        for token in cleaned:
            if not isinstance(cmd, (click.MultiCommand, click.Group)):
                break
            resolved = cmd.get_command(ctx, token)  # type: ignore[union-attr]
            if resolved is None:
                break
            command_chain.append(token)
            cmd = resolved  # type: ignore[assignment]

        if cmd is None or cmd is self:
            # Fell through — emit root help as fallback
            jsonl_emit_help(
                commands=_COMMAND_HELP,
                description="LLM Agent-oriented web clipping CLI tool",
            )
            return

        command_name = " ".join(command_chain)

        # Extract description from the command's docstring / help attribute
        description = getattr(cmd, "help", None) or ""

        # Build options list from the command's parameters
        options: list[dict[str, str]] = []
        if isinstance(cmd, (click.MultiCommand, click.Group)):
            # It's a group (like config, prompt) — list sub-commands
            for name in sorted(cmd.list_commands(ctx)):
                sub = cmd.get_command(ctx, name)
                help_text = getattr(sub, "help", None) or "" if sub else ""
                options.append({"name": name, "help": help_text.strip()})
        else:
            # Leaf command — list its params
            for param in getattr(cmd, "params", []):
                if isinstance(param, click.Argument):
                    opts = [param.human_readable_name]
                    help_text = getattr(param, "help", "") or ""
                    options.append({"name": opts[0], "help": help_text})
                elif isinstance(param, click.Option):
                    opts = param.opts + param.secondary_opts
                    help_text = getattr(param, "help", "") or ""
                    options.append({"name": ", ".join(opts), "help": help_text})

        jsonl_emit_help(
            commands=options,
            description=description.strip(),
            command=command_name,
        )


app = typer.Typer(
    name="web-clip-helper",
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
    cls=_JSONLGroup,
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
]


@app.callback()
def main(
    ctx: typer.Context,
    quiet: bool = typer.Option(False, "--quiet", "-q", is_eager=True, help="Suppress progress and warning output; only emit result and error lines"),
    help_flag: bool = typer.Option(False, "--help", "-h", is_flag=True, is_eager=True),
) -> None:
    """web-clip-helper — LLM Agent-oriented web clipping tool.

    All output (including --help) is JSONL so agents can parse it easily.
    """
    if quiet:
        set_quiet(True)

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
        jsonl_emit_error(stage="config", detail=str(exc), error_code="CONFIG_ERROR")
        raise typer.Exit(1)
    except Exception as exc:
        jsonl_emit_error(stage="config", detail=f"Failed to get config: {exc}", error_code="CONFIG_ERROR")
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
        jsonl_emit_error(stage="config", detail=str(exc), error_code="CONFIG_ERROR")
        raise typer.Exit(1)
    except Exception as exc:
        jsonl_emit_error(stage="config", detail=f"Failed to set config: {exc}", error_code="CONFIG_ERROR")
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
    """Compare built-in and custom prompt results as JSONL."""
    import sys as _sys

    # Windows GBK encoding fix (MEM043/MEM047)
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    if type not in ("title", "tags", "classify"):
        jsonl_emit_error(stage="prompt_test", detail=f"Unsupported type: {type}", error_code="INVALID_TYPE")
        raise typer.Exit(1)

    from web_clip_helper.config import Config
    from web_clip_helper.llm import LLMClient

    try:
        config = Config.load(path)
    except Exception as exc:
        jsonl_emit_error(stage="prompt_test", detail=f"Config load failed: {exc}", error_code="CONFIG_ERROR")
        raise typer.Exit(1)

    # Check if custom prompt is set for the requested type
    custom_template = getattr(config.prompts, type, "")
    if not custom_template or not custom_template.strip():
        jsonl_emit_error(stage="prompt_test", detail=f"No custom prompt set for prompts.{type}", error_code="NO_CUSTOM_PROMPT")
        raise typer.Exit(1)

    # Route URL and fetch content via adapter
    try:
        from web_clip_helper.adapter import route_url
        adapter_cls = route_url(url)
        adapter = adapter_cls()
        raw_content = adapter.fetch(url)
    except ValueError as exc:
        jsonl_emit_error(stage="prompt_test", detail=f"URL routing failed: {exc}", error_code="URL_ROUTE_ERROR")
        raise typer.Exit(1)
    except Exception as exc:
        jsonl_emit_error(stage="prompt_test", detail=f"Content fetch failed: {exc}", error_code="FETCH_ERROR")
        raise typer.Exit(1)

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
        raise typer.Exit(1)

    # Handle --attach option
    attach_content: str | None = None
    attach_path_resolved: str | None = None
    attach_truncated: bool = False
    max_attach_size = 100 * 1024  # 100 KB

    if attach is not None:
        attach_file = Path(attach).expanduser().resolve()
        if not attach_file.is_file():
            jsonl_emit_error(stage="report_submit", detail=f"Attached file not found: {attach}", error_code="INPUT_INVALID")
            raise typer.Exit(1)

        try:
            raw_bytes = attach_file.read_bytes()
            if len(raw_bytes) > max_attach_size:
                raw_bytes = raw_bytes[:max_attach_size]
                attach_truncated = True
            attach_content = raw_bytes.decode("utf-8", errors="replace")
            attach_path_resolved = str(attach_file)
        except OSError as exc:
            jsonl_emit_error(stage="report_submit", detail=f"Failed to read attached file: {exc}", error_code="INPUT_INVALID")
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

    reports_dir = Path.home() / ".web-clip-helper" / "reports"
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
        raise typer.Exit(1)


@report_app.command(name="list")
def report_list() -> None:
    """List all submitted reports. Output is JSONL."""
    from pathlib import Path

    reports_dir = Path.home() / ".web-clip-helper" / "reports"

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

    reports_dir = Path.home() / ".web-clip-helper" / "reports"
    file_path = reports_dir / f"{report_id}.md"

    if not file_path.is_file():
        jsonl_emit_error(stage="report_show", detail=f"Report not found: {report_id}", error_code="NOT_FOUND")
        raise typer.Exit(1)

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
        raise typer.Exit(1)


# Register report sub-app on main app
app.add_typer(report_app, name="report", help="Submit and view structured feedback reports")


@app.command()
def clip(
    url: Optional[str] = typer.Argument(None, help="URL to clip"),
    text: Optional[str] = typer.Option(None, "--text", "-t", help="Clip raw text instead of URL"),
    no_images: bool = typer.Option(False, "--no-images", help="Skip image downloading entirely"),
    timeout: int = typer.Option(60, "--timeout", help="Wall-clock timeout in seconds for the entire clip operation"),
) -> None:
    """Clip a URL or raw text into Markdown + storage."""
    if not url and not text:
        jsonl_emit_error(stage="clip", detail="Either a URL or text must be provided", error_code="INPUT_INVALID")
        raise typer.Exit(1)

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

    from web_clip_helper.config import get_config
    from web_clip_helper.pipeline import clip_text, clip_url

    config = get_config()

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
        raise typer.Exit(1)

    executor.shutdown(wait=False)
    if result is None:
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
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Maximum number of results to return"),
    offset: Optional[int] = typer.Option(None, "--offset", help="Number of results to skip"),
) -> None:
    """List clipped items with optional filters and pagination. Output is JSONL."""
    if limit is not None and limit <= 0:
        jsonl_emit_error(stage="list", detail=f"Invalid limit: {limit}. Must be a positive integer", error_code="INPUT_INVALID")
        raise typer.Exit(1)
    if offset is not None and offset < 0:
        jsonl_emit_error(stage="list", detail=f"Invalid offset: {offset}. Must be a non-negative integer", error_code="INPUT_INVALID")
        raise typer.Exit(1)

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
        for clip in results:
            jsonl_emit_result(stage="list", **clip)
    except Exception as exc:
        jsonl_emit_error(stage="list", detail=f"Query failed: {exc}", error_code="INDEX_ERROR")
        raise typer.Exit(1)
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
            raise typer.Exit(1)

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
        raise typer.Exit(1)
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
        for clip in results:
            jsonl_emit_result(stage="search", **clip)
    except Exception as exc:
        jsonl_emit_error(stage="search", detail=f"Search failed: {exc}", error_code="INDEX_ERROR")
        raise typer.Exit(1)
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
            raise typer.Exit(1)

        folder_path = record.get("folder_path", "")

        # Delete from SQLite
        deleted = idx.delete_clip(clip_id)
        if not deleted:
            jsonl_emit_error(stage="delete", detail=f"Failed to delete clip {clip_id}", error_code="INDEX_ERROR")
            raise typer.Exit(1)

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
        jsonl_emit_error(stage="tags", detail=f"Failed to list tags: {exc}", error_code="INDEX_ERROR")
        raise typer.Exit(1)
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
        raise typer.Exit(1)

    if interval is not None and interval <= 0:
        jsonl_emit_error(stage="update", detail=f"Invalid interval: {interval}. Must be a positive integer", error_code="INPUT_INVALID")
        raise typer.Exit(1)

    # Parse tags JSON array
    parsed_tags: list[str] | None = None
    if tags is not None:
        try:
            parsed_tags = json.loads(tags)
            if not isinstance(parsed_tags, list):
                jsonl_emit_error(stage="update", detail=f"Invalid tags: must be a JSON array, got {type(parsed_tags).__name__}", error_code="INPUT_INVALID")
                raise typer.Exit(1)
            for i, t in enumerate(parsed_tags):
                if not isinstance(t, str):
                    jsonl_emit_error(stage="update", detail=f"Invalid tags: element at index {i} is not a string ({type(t).__name__})", error_code="INPUT_INVALID")
                    raise typer.Exit(1)
        except json.JSONDecodeError as exc:
            jsonl_emit_error(stage="update", detail=f"Invalid tags JSON: {exc}", error_code="INPUT_INVALID")
            raise typer.Exit(1)

    idx = _get_index()
    try:
        record = idx.get_clip(clip_id)
        if record is None:
            jsonl_emit_error(stage="update", detail=f"Clip {clip_id} not found", error_code="NOT_FOUND")
            raise typer.Exit(1)

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
        raise typer.Exit(1)
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

    except Exception as exc:
        jsonl_emit_error(stage="refresh", detail=f"Refresh command failed: {exc}", error_code="REFRESH_ERROR")
        raise typer.Exit(1)
    finally:
        idx.close()


@app.command(name="version")
def version_command() -> None:
    """Print the current version as JSONL."""
    from web_clip_helper import __version__

    jsonl_emit_result(stage="version", version=__version__)


if __name__ == "__main__":
    app()
