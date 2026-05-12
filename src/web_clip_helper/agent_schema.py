"""Agent schema — complete parameter descriptions for all business commands.

Provides :func:`get_commands_schema` which returns a list of command
metadata dictionaries.  Each entry includes the command name, a description,
an ``is_idempotent`` flag, and a list of parameter descriptions with
``name / type / required / description`` fields (plus optional ``default``).

This module is consumed by ``agent schema`` in :mod:`web_clip_helper.cli`.
"""

from __future__ import annotations

from typing import Any

__all__ = ["get_commands_schema"]


# ── Parameter description type ───────────────────────────────────
# {
#   "name": str,          # CLI param name (e.g. "url_or_text", "--timeout")
#   "type": str,          # Python type name (e.g. "str", "int", "bool")
#   "required": bool,     # Whether the param must be provided
#   "description": str,   # Human-readable explanation
#   "default": Any|None,  # Omitted when None to keep output compact
# }

# ── Command metadata type ────────────────────────────────────────
# {
#   "name": str,
#   "description": str,
#   "is_idempotent": bool,
#   "parameters": list[dict],
# }


def _build_commands() -> list[dict[str, Any]]:
    """Return the full command metadata list.

    Kept as a private builder so the data is constructed at call-time,
    making it easier to test and avoiding module-level side-effects.
    """
    return [
        # ── clip ──────────────────────────────────────────────────
        {
            "name": "clip",
            "description": "Clip a URL or raw text into Markdown + storage",
            "is_idempotent": False,  # duplicate clip of same URL returns duplicate marker
            "parameters": [
                {
                    "name": "url",
                    "type": "str",
                    "required": False,
                    "description": "URL to clip (mutually exclusive with --text)",
                },
                {
                    "name": "--text",
                    "type": "str",
                    "required": False,
                    "description": "Clip raw text instead of URL (mutually exclusive with url)",
                },
                {
                    "name": "--no-images",
                    "type": "bool",
                    "required": False,
                    "description": "Skip image downloading entirely",
                    "default": False,
                },
                {
                    "name": "--timeout",
                    "type": "int",
                    "required": False,
                    "description": "Wall-clock timeout in seconds for the entire clip operation",
                    "default": 60,
                },
                {
                    "name": "--dry-run",
                    "type": "bool",
                    "required": False,
                    "description": "Preview execution plan without performing real IO (no network, no filesystem writes, no SQLite writes)",
                    "default": False,
                },
            ],
        },
        # ── list ──────────────────────────────────────────────────
        {
            "name": "list",
            "description": "List clipped items with optional filters and pagination",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "--tag",
                    "type": "str",
                    "required": False,
                    "description": "Filter by tag",
                },
                {
                    "name": "--category",
                    "type": "str",
                    "required": False,
                    "description": "Filter by category",
                },
                {
                    "name": "--source-type",
                    "type": "str",
                    "required": False,
                    "description": "Filter by source type",
                },
                {
                    "name": "--limit",
                    "type": "int",
                    "required": False,
                    "description": "Maximum number of results to return",
                },
                {
                    "name": "--offset",
                    "type": "int",
                    "required": False,
                    "description": "Number of results to skip",
                },
            ],
        },
        # ── get ───────────────────────────────────────────────────
        {
            "name": "get",
            "description": "Get a single clipped item by ID",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "clip_id",
                    "type": "int",
                    "required": True,
                    "description": "Clip ID to retrieve",
                },
                {
                    "name": "--content",
                    "type": "bool",
                    "required": False,
                    "description": "Include markdown body as 'content' field in the result",
                    "default": False,
                },
            ],
        },
        # ── search ────────────────────────────────────────────────
        {
            "name": "search",
            "description": "Search clipped items by keyword in title and URL",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "keyword",
                    "type": "str",
                    "required": True,
                    "description": "Search keyword for title/URL",
                },
                {
                    "name": "--full",
                    "type": "bool",
                    "required": False,
                    "description": "Search markdown file content in addition to title/URL",
                    "default": False,
                },
            ],
        },
        # ── tags ──────────────────────────────────────────────────
        {
            "name": "tags",
            "description": "List all unique tags with usage counts",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── delete ────────────────────────────────────────────────
        {
            "name": "delete",
            "description": "Delete a clipped item by ID. Removes record from DB and folder from disk",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "clip_id",
                    "type": "int",
                    "required": True,
                    "description": "Clip ID to delete",
                },
            ],
        },
        # ── update ────────────────────────────────────────────────
        {
            "name": "update",
            "description": "Update clip fields (title, tags, category, dynamic flag, refresh interval)",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "clip_id",
                    "type": "int",
                    "required": True,
                    "description": "Clip ID to update",
                },
                {
                    "name": "--dynamic/--no-dynamic",
                    "type": "bool",
                    "required": False,
                    "description": "Set dynamic flag",
                },
                {
                    "name": "--interval",
                    "type": "int",
                    "required": False,
                    "description": "Refresh interval in days",
                },
                {
                    "name": "--title",
                    "type": "str",
                    "required": False,
                    "description": "New title for the clip",
                },
                {
                    "name": "--tags",
                    "type": "str",
                    "required": False,
                    "description": "New tags as JSON array string, e.g. '[\"tag1\",\"tag2\"]'",
                },
                {
                    "name": "--category",
                    "type": "str",
                    "required": False,
                    "description": "New category for the clip",
                },
            ],
        },
        # ── refresh ───────────────────────────────────────────────
        {
            "name": "refresh",
            "description": "Refresh dynamic clipped items that are due for re-clip",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "--re-enrich",
                    "type": "bool",
                    "required": False,
                    "description": "Re-run LLM enrichment to regenerate tags/category",
                    "default": False,
                },
            ],
        },
        # ── import ───────────────────────────────────────────────────
        {
            "name": "import",
            "description": "Import previously clipped data from an external directory into the index",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "source_dir",
                    "type": "str",
                    "required": True,
                    "description": "Directory containing previously clipped data to import",
                },
                {
                    "name": "--copy",
                    "type": "bool",
                    "required": False,
                    "description": "Copy files into storage_path instead of referencing in-place",
                    "default": False,
                },
                {
                    "name": "--source-type",
                    "type": "str",
                    "required": False,
                    "description": "Override source_type for entries without manifest data",
                },
                {
                    "name": "--dry-run",
                    "type": "bool",
                    "required": False,
                    "description": "Preview what would be imported without writing to index",
                    "default": False,
                },
            ],
        },
        # ── version ───────────────────────────────────────────────
        {
            "name": "version",
            "description": "Print the current version",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── config list ───────────────────────────────────────────
        {
            "name": "config list",
            "description": "List all configuration values (api_key is masked)",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "--path",
                    "type": "str",
                    "required": False,
                    "description": "Path to config file",
                },
            ],
        },
        # ── config get ────────────────────────────────────────────
        {
            "name": "config get",
            "description": "Get a single configuration value by dot-path key",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "key",
                    "type": "str",
                    "required": True,
                    "description": "Config key in dot-path notation (e.g. llm.api_key)",
                },
                {
                    "name": "--path",
                    "type": "str",
                    "required": False,
                    "description": "Path to config file",
                },
            ],
        },
        # ── config set ────────────────────────────────────────────
        {
            "name": "config set",
            "description": "Set a configuration value by dot-path key and save to file",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "key",
                    "type": "str",
                    "required": True,
                    "description": "Config key in dot-path notation (e.g. llm.api_key)",
                },
                {
                    "name": "value",
                    "type": "str",
                    "required": True,
                    "description": "Value to set",
                },
                {
                    "name": "--path",
                    "type": "str",
                    "required": False,
                    "description": "Path to config file",
                },
            ],
        },
        # ── config prompt test ────────────────────────────────────
        {
            "name": "config prompt test",
            "description": "Compare built-in and custom prompt results",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "--type",
                    "type": "str",
                    "required": True,
                    "description": "Prompt type: title | tags | classify",
                },
                {
                    "name": "--url",
                    "type": "str",
                    "required": True,
                    "description": "URL to fetch content from",
                },
                {
                    "name": "--path",
                    "type": "str",
                    "required": False,
                    "description": "Path to config file",
                },
            ],
        },
        # ── report submit ─────────────────────────────────────────
        {
            "name": "report submit",
            "description": "Submit a structured feedback report",
            "is_idempotent": False,  # creates a new file each time
            "parameters": [
                {
                    "name": "description",
                    "type": "str",
                    "required": True,
                    "description": "Problem description",
                },
                {
                    "name": "--type",
                    "type": "str",
                    "required": False,
                    "description": "Report type: bug | feature | other",
                    "default": "bug",
                },
                {
                    "name": "--attach",
                    "type": "str",
                    "required": False,
                    "description": "Attach a file (e.g. JSONL log) to the report",
                },
            ],
        },
        # ── report list ───────────────────────────────────────────
        {
            "name": "report list",
            "description": "List all submitted reports",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── report show ───────────────────────────────────────────
        {
            "name": "report show",
            "description": "Show a specific report by ID",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "report_id",
                    "type": "str",
                    "required": True,
                    "description": "Report ID (filename stem, e.g. report_bug_20260503_105540)",
                },
            ],
        },
        # ── agent info ────────────────────────────────────────────
        {
            "name": "agent info",
            "description": "Output tool version, description, and documentation pointers",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── agent schema ──────────────────────────────────────────
        {
            "name": "agent schema",
            "description": "Output complete parameter descriptions for all business commands",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── agent errors ──────────────────────────────────────────
        {
            "name": "agent errors",
            "description": "Output all error codes with descriptions and troubleshooting guidance",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── agent doctor ──────────────────────────────────────────
        {
            "name": "agent doctor",
            "description": "Run health diagnostics (storage, SQLite, config, LLM connectivity)",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── agent update check ────────────────────────────────────
        {
            "name": "agent update check",
            "description": "Check PyPI for a newer version of web-clip-helper",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── agent auth status ─────────────────────────────────────
        {
            "name": "agent auth status",
            "description": "Check LLM API key validity via lightweight 1-token completion ping",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── agent config list ─────────────────────────────────────
        {
            "name": "agent config list",
            "description": "List all config values with forced redaction of sensitive fields",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── agent config set ──────────────────────────────────────
        {
            "name": "agent config set",
            "description": "Set a config value at runtime with whitelist path validation and persistence",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "key",
                    "type": "str",
                    "required": True,
                    "description": "Config key in dot-path notation (e.g. llm.model)",
                },
                {
                    "name": "value",
                    "type": "str",
                    "required": True,
                    "description": "Value to set (type-coerced to match field type)",
                },
            ],
        },
        # ── agent debug last-crash ────────────────────────────────
        {
            "name": "agent debug last-crash",
            "description": "Read and output the last crash dump file contents",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── agent debug env ───────────────────────────────────────
        {
            "name": "agent debug env",
            "description": "Collect and output environment snapshot (Python, OS, deps, config paths, LLM info)",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "--redact/--no-redact",
                    "type": "bool",
                    "required": False,
                    "description": "Force redaction of sensitive values (default: redacted)",
                    "default": True,
                },
            ],
        },
        # ── agent cache clean ─────────────────────────────────────
        {
            "name": "agent cache",
            "description": "Clean the XDG cache directory, removing all files and subdirectories",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "action",
                    "type": "str",
                    "required": False,
                    "description": "Cache action (currently only 'clean' supported)",
                    "default": "clean",
                },
            ],
        },
        # ── agent feature record ────────────────────────────────
        {
            "name": "agent feature record",
            "description": "Record a feature/capability request to persistent JSONL storage",
            "is_idempotent": False,
            "parameters": [
                {
                    "name": "--name",
                    "type": "str",
                    "required": True,
                    "description": "Feature name",
                },
                {
                    "name": "--desc",
                    "type": "str",
                    "required": True,
                    "description": "Feature description",
                },
            ],
        },
        # ── agent feature list ──────────────────────────────────
        {
            "name": "agent feature list",
            "description": "List all recorded feature/capability requests (newest-first)",
            "is_idempotent": True,
            "parameters": [],
        },
        # ── agent metrics trace ─────────────────────────────────
        {
            "name": "agent metrics trace",
            "description": "Search crash dump files for entries matching a trace ID",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "--id",
                    "type": "str",
                    "required": True,
                    "description": "Trace ID to search for in crash dumps",
                },
            ],
        },
        # ── agent update apply ──────────────────────────────────
        {
            "name": "agent update apply",
            "description": "Trigger an in-place upgrade via pip install --upgrade",
            "is_idempotent": False,
            "parameters": [
                {
                    "name": "--yes",
                    "type": "bool",
                    "required": False,
                    "description": "Confirm upgrade without interactive prompt",
                    "default": False,
                },
            ],
        },
        # ── backup create ──────────────────────────────────────
        {
            "name": "backup create",
            "description": "Create a backup zip archive of config and data directories",
            "is_idempotent": False,  # creates a new zip each time
            "parameters": [
                {
                    "name": "--output-dir",
                    "type": "str",
                    "required": False,
                    "description": "Override default backup output directory",
                },
            ],
        },
        # ── backup list ────────────────────────────────────────
        {
            "name": "backup list",
            "description": "List existing backup files",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "--output-dir",
                    "type": "str",
                    "required": False,
                    "description": "Override default backup output directory",
                },
            ],
        },
        # ── backup cleanup ─────────────────────────────────────
        {
            "name": "backup cleanup",
            "description": "Rotate backups according to retention policy",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "--output-dir",
                    "type": "str",
                    "required": False,
                    "description": "Override default backup output directory",
                },
                {
                    "name": "--config-path",
                    "type": "str",
                    "required": False,
                    "description": "Override default backup config file path",
                },
            ],
        },
        # ── backup config show ─────────────────────────────────
        {
            "name": "backup config show",
            "description": "Show effective backup configuration (retention policy, output directory, config source)",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "--config-path",
                    "type": "str",
                    "required": False,
                    "description": "Override default backup config file path",
                },
            ],
        },
        # ── backup config set ──────────────────────────────────
        {
            "name": "backup config set",
            "description": "Set a backup configuration value (retention_policy.daily/weekly/monthly or output_dir)",
            "is_idempotent": True,
            "parameters": [
                {
                    "name": "key",
                    "type": "str",
                    "required": True,
                    "description": "Config key (retention_policy.daily/weekly/monthly or output_dir)",
                },
                {
                    "name": "value",
                    "type": "str",
                    "required": True,
                    "description": "Value to set",
                },
                {
                    "name": "--config-path",
                    "type": "str",
                    "required": False,
                    "description": "Override default backup config file path",
                },
            ],
        },
    ]


def get_commands_schema() -> list[dict[str, Any]]:
    """Return the complete commands schema.

    Each entry is a dict with keys:
    ``name``, ``description``, ``is_idempotent``, ``parameters``.
    Each parameter has keys:
    ``name``, ``type``, ``required``, ``description``, and optionally ``default``.
    """
    return _build_commands()
