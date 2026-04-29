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

__all__ = ["app"]

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


@app.command()
def clip(
    url: Optional[str] = typer.Argument(None, help="URL to clip"),
    text: Optional[str] = typer.Argument(None, help="Raw text to clip"),
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
