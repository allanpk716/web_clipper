"""CLI entry point — Typer application with JSONL output.

All user-facing output goes through ``output.jsonl_emit`` — no bare ``print()`` calls.
"""

from __future__ import annotations

import sys
from typing import Optional

import typer

from web_clip_helper.output import jsonl_emit_error, jsonl_emit_help, jsonl_emit_progress

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
    """Clip a URL or raw text into Markdown + storage.

    For now this validates input and emits progress/error JSONL.
    Full pipeline is wired in subsequent slices.
    """
    if not url and not text:
        jsonl_emit_error(stage="clip", detail="Either --url or --text must be provided")
        raise typer.Exit(1)

    if url:
        jsonl_emit_progress(message=f"Starting clip for URL: {url}", percent=0)
        # TODO: adapter dispatch, fetch, convert, store (S02+)
        jsonl_emit_progress(message="Clip pipeline not yet wired", percent=100)
    elif text:
        jsonl_emit_progress(message="Starting clip for raw text", percent=0)
        # TODO: text processing pipeline (S02+)
        jsonl_emit_progress(message="Clip pipeline not yet wired", percent=100)
