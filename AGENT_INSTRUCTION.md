# AGENT_INSTRUCTION.md — web-clip-helper

> **Audience:** This document is written for AI agents (LLMs) that have **zero prior knowledge** of this tool. Read this file in full before invoking any command.

## 1. Tool Overview

**web-clip-helper** is a CLI tool that clips web pages (or raw text) into local Markdown files with structured metadata. It uses LLM enrichment to auto-generate titles, tags, and categories. Every command emits **JSONL output** (one JSON object per line) to stdout, making it safe for programmatic consumption.

- **Invocation:** `web-clip-helper <command> [options]`
- **Package:** `web-clip-helper` (pip installable)
- **Python:** Requires Python 3.11+

### What It Does

1. Fetches a URL or accepts raw text input
2. Converts content to Markdown
3. Optionally downloads images
4. Enriches metadata via LLM (title, tags, category) — LLM is optional; without an API key, defaults are used
5. Stores Markdown + metadata in a local SQLite-backed index
6. Provides query, search, update, delete, and refresh operations

### What It Does NOT Do

- **No daemon or server mode** — every invocation is a one-shot CLI process
- **No batch mode** — clip one URL at a time; loop externally if needed
- **No scheduling** — no cron/timer built in; use external schedulers
- **No streaming** — each command runs to completion, then exits
- **No concurrent safety** — avoid parallel `clip` calls against the same database (SQLite locking)

## 2. Quick Start

### Discover the Tool

```bash
# Get version, description, and doc pointers
web-clip-helper agent info

# Full parameter schema for every command
web-clip-helper agent schema

# All error codes with descriptions and troubleshooting hints
web-clip-helper agent errors

# Health check: storage, SQLite, config, LLM connectivity
web-clip-helper agent doctor
```

### First Clip

```bash
web-clip-helper clip https://example.com/article
```

Parse the JSONL output. The **last** `type=result` line contains the clip record:

```jsonl
{"type":"result","stage":"clip","url":"https://example.com/article","title":"Example Article","source_type":"web","folder":"/path/to/clips/2026-05-04_Example_Article","markdown":"/path/to/file.md","image_count":2,"file_count":0,"record_id":42,"tags":["example"],"category":"article","dry_run":false,"version":"0.2.0","tool":"web-clip-helper","timestamp":"2026-05-04T12:00:00.000Z","trace_id":"abc123def4567890"}
```

The key field is **`record_id`** — use it for subsequent `get`, `update`, and `delete` operations.

## 3. JSONL Output Contract

### Envelope Fields

Every JSONL line includes these envelope fields:

| Field | Type | Description |
|-------|------|-------------|
| `type` | `string` | Message category. One of: `progress`, `result`, `error`, `warning`, `help`, `schema`, `dict`, `diagnostics` |
| `version` | `string` | Tool's semantic version (e.g. `"0.2.0"`) |
| `tool` | `string` | Always `"web-clip-helper"` |
| `timestamp` | `string` | ISO 8601 UTC with millisecond precision (e.g. `"2026-05-04T12:34:56.789Z"`) |
| `trace_id` | `string` | Correlation ID for the invocation. Set via `AGENT_TRACE_ID` env var or auto-generated |

### Valid `type` Values

| type | Description | Quiet mode |
|------|-------------|------------|
| `progress` | Status updates during execution (optional `percent`, `stage` fields) | **Suppressed** |
| `result` | Final output data. Contains `stage` field identifying the source command | Always emitted |
| `error` | Error details. Contains `stage`, `detail`, and `error_code` fields | Always emitted |
| `warning` | Non-fatal warnings (e.g. image download failed) | **Suppressed** |
| `help` | Help text (emitted by `--help`) | Always emitted |
| `schema` | Schema data (emitted by `agent schema`) | Always emitted |
| `dict` | Dictionary data (emitted by `agent errors`, `agent feature list`, `agent metrics trace`) | Always emitted |
| `diagnostics` | Diagnostic data (emitted by `agent doctor`, `agent debug env`) | Always emitted |

### Parsing Rules

1. Read stdout **line by line** — each line is a complete JSON object
2. Filter by `type` field — agents typically need `result` and `error` only
3. The **last** `type=result` line is usually the primary output
4. Multiple `type=result` lines can appear (e.g. `list` emits one per record)
5. Never assume a fixed number of lines — parse until EOF

## 4. Command Reference

### Business Commands

| Command | Description | Idempotent |
|---------|-------------|------------|
| `clip <url>` or `clip --text "..."` | Clip a URL or raw text into Markdown + storage | No (duplicate URL returns existing record) |
| `list` | List clipped items with filters and pagination | Yes |
| `get <id>` | Get a single clipped item by ID | Yes |
| `search <keyword>` | Search by keyword in title/URL (optionally full text) | Yes |
| `tags` | List all unique tags with usage counts | Yes |
| `update <id>` | Update clip fields (title, tags, category, dynamic, interval) | Yes |
| `delete <id>` | Delete a clip by ID (DB record + folder) | Yes |
| `refresh` | Re-clip dynamic items that are due for refresh | Yes |
| `version` | Print current version | Yes |

### Config Commands

| Command | Description |
|---------|-------------|
| `config list` | List all config values (api_key is masked) |
| `config get <key>` | Get a single config value by dot-path (e.g. `llm.model`) |
| `config set <key> <value>` | Set a config value and persist to JSON |
| `config prompt test --type <t> --url <u>` | Compare built-in vs custom prompt results |

### Report Commands

| Command | Description |
|---------|-------------|
| `report submit <desc>` | Submit a feedback report |
| `report list` | List submitted reports |
| `report show <id>` | Show a specific report |

### Agent Discovery Commands

| Command | Description |
|---------|-------------|
| `agent info` | Tool version, description, doc pointers |
| `agent schema` | Full parameter descriptions for all commands |
| `agent errors` | All error codes with descriptions and guidance |
| `agent doctor` | Health diagnostics (storage, SQLite, config, LLM) |
| `agent auth status` | Validate LLM API key via 1-token completion ping |
| `agent update check` | Check PyPI for newer version |
| `agent update apply` | Trigger in-place pip upgrade |
| `agent config list` | List config with forced redaction |
| `agent config set <key> <val>` | Set config with whitelist validation |
| `agent cache clean` | Clean cache directory |
| `agent debug last-crash` | Read last crash dump file |
| `agent debug env` | Environment snapshot (Python, OS, deps, paths) |
| `agent feature record --name N --desc D` | Record a feature request |
| `agent feature list` | List recorded feature requests |
| `agent metrics trace --id <tid>` | Search crash dumps for a trace ID |

For full parameter details (types, required/optional, defaults), run:
```bash
web-clip-helper agent schema
```

## 5. Command Details

### clip

Clip a URL or raw text into Markdown + storage.

```bash
web-clip-helper clip <url> [options]
web-clip-helper clip --text "raw text content" [options]
```

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `<url>` | — | string | — | URL to clip (mutually exclusive with `--text`) |
| `--text` | `-t` | string | — | Clip raw text instead of a URL |
| `--no-images` | — | flag | off | Skip image downloading entirely |
| `--timeout` | — | int | 60 | Wall-clock timeout in seconds for the entire clip operation |
| `--dry-run` | — | flag | off | Preview execution plan without performing real IO |

**Dry-run mode** returns an ExecutionPlan with estimated actions but performs **no real IO** — no network fetch, no filesystem writes, no SQLite writes. Use it to preview before committing:

```jsonl
{"type":"result","stage":"clip","dry_run":true,"plan":{"adapter":"GenericWebAdapter","url":"https://example.com/article","estimated_actions":["fetch","markdown","storage","index"],"estimated_image_count":"unknown","duplicate":false},"version":"0.2.0","tool":"web-clip-helper","timestamp":"...","trace_id":"..."}
```

**Duplicate handling:** If the URL was already clipped, the result includes `"duplicate": true` and `"existing_id": <id>`. The existing record is **not modified**. You may optionally `update` or `delete` it.

### list

List clipped items with optional filters and pagination.

```bash
web-clip-helper list [options]
```

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--tag` | `-t` | string | — | Filter by tag |
| `--category` | `-c` | string | — | Filter by category |
| `--source-type` | `-s` | string | — | Filter by source type |
| `--limit` | `-n` | int | — | Maximum number of results to return |
| `--offset` | — | int | 0 | Number of results to skip |

**Output:** Emits one `type=result` line per matching clip record. Each result line includes pagination metadata fields:

| Field | Type | Description |
|-------|------|-------------|
| `_total_count` | int | Total number of matching records (before limit/offset) |
| `_limit` | int\|null | Applied limit (null if not specified) |
| `_offset` | int | Applied offset (0 if not specified) |

When no results match, a single `type=result` line with `"count": 0` and pagination metadata is emitted:

```jsonl
{"type":"result","stage":"list","count":0,"_total_count":0,"_limit":null,"_offset":0,"version":"0.2.0","tool":"web-clip-helper","timestamp":"...","trace_id":"..."}
```

### search

Search clipped items by keyword.

```bash
web-clip-helper search <keyword> [options]
```

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `<keyword>` | — | string | — | Search keyword for title/URL |
| `--full` | — | flag | off | Search markdown file content in addition to title/URL |

> **Note:** `search` does not support `--limit` or `--offset`. It returns all matching results.

**Output:** Same pagination metadata structure as `list` (`_total_count`, `_limit`, `_offset`). When no results match, emits `"count": 0` with `_total_count: 0`.

### get

Get a single clipped item by ID.

```bash
web-clip-helper get <id> [--content]
```

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `<id>` | — | int | — | Clip ID to retrieve |
| `--content` | — | flag | off | Include markdown body as `content` field in the result |

### update

Update clip fields.

```bash
web-clip-helper update <id> [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--title` | string | — | New title for the clip |
| `--tags` | string | — | New tags as JSON array string, e.g. `'["tag1","tag2"]'` |
| `--category` | string | — | New category for the clip |
| `--dynamic` / `--no-dynamic` | flag | — | Set or clear dynamic flag |
| `--interval` | int | — | Refresh interval in days (positive integer) |

### delete

Delete a clip by ID. Removes the DB record and folder from disk.

```bash
web-clip-helper delete <id>
```

### tags

List all unique tags with usage counts.

```bash
web-clip-helper tags
```

**Output:** One `type=result` line per tag entry. When no tags exist, emits `"count": 0`.

### refresh

Refresh dynamic clipped items that are due for re-clip.

```bash
web-clip-helper refresh [options]
```

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--re-enrich` | flag | off | Re-run LLM enrichment to regenerate tags/category |

## 6. Error Handling

### Exit Codes

| Exit Code | Meaning | Error Codes |
|-----------|---------|-------------|
| 0 | Success | — |
| 1 | Fatal / unknown error | `INTERNAL_ERROR`, `FATAL_CRASH` |
| 2 | Input / config error | `INPUT_INVALID`, `CONFIG_ERROR`, `INVALID_TYPE`, `NO_CUSTOM_PROMPT` |
| 3 | Resource / dependency error | `NOT_FOUND`, `STORAGE_ERROR`, `INDEX_ERROR`, `REFRESH_ERROR` |
| 4 | Network / third-party error | `NETWORK_ERROR`, `FETCH_ERROR`, `ROUTING_ERROR`, `URL_ROUTE_ERROR`, `TIMEOUT_ERROR` |
| 5 | Concurrency error | `RESOURCE_LOCKED` |

### Error Codes

| error_code | Description | Guidance |
|------------|-------------|----------|
| `INPUT_INVALID` | Invalid or missing input argument | Check command arguments and required options. Run with `--help` for usage. |
| `NOT_FOUND` | Requested resource (clip, config key) does not exist | Verify the resource ID or key exists. Use `list`/`search` commands to find valid identifiers. |
| `STORAGE_ERROR` | File-system storage operation failed | Check disk space and file permissions on the storage directory. |
| `INDEX_ERROR` | SQLite index operation failed | The SQLite database may be locked or corrupted. Try again or delete the `.db` file to rebuild. |
| `NETWORK_ERROR` | Network connectivity or DNS failure | Check internet connectivity and DNS resolution. Retry after network recovery. |
| `ROUTING_ERROR` | URL could not be routed to an adapter | The URL scheme/host is not supported. Ensure the URL matches a registered adapter. |
| `FETCH_ERROR` | Adapter failed to fetch content from the URL | The site may be down or blocking automated access. |
| `CONFIG_ERROR` | Configuration load/save/validation error | Validate the config file syntax (JSON). Check file path and permissions. |
| `INTERNAL_ERROR` | Unexpected internal error (possible bug) | An unexpected error occurred. Check logs for details and consider filing a bug report. |
| `FATAL_CRASH` | Unrecoverable crash (signal or unhandled exception) | The process crashed unexpectedly. Check crash dump files in the crash_dumps directory. |
| `REFRESH_ERROR` | Dynamic clip refresh failed | Verify the source URL is still accessible. |
| `TIMEOUT_ERROR` | Clip operation exceeded the configured wall-clock timeout | Increase `--timeout` or check network/server responsiveness. |
| `RESOURCE_LOCKED` | Concurrent access conflict — resource is locked by another process | Another process holds a lock on the resource. Wait for it to finish or remove stale lock files. |

### Error JSONL Format

```jsonl
{"type":"error","stage":"clip","detail":"Network request timed out after 60s","error_code":"TIMEOUT_ERROR","version":"0.2.0","tool":"web-clip-helper","timestamp":"2026-05-04T12:00:00.000Z","trace_id":"abc123"}
```

### Recommended Error Handling Strategy

| error_code | Action |
|------------|--------|
| `NETWORK_ERROR`, `FETCH_ERROR`, `TIMEOUT_ERROR` | **Retry** with exponential backoff (these are transient) |
| `NOT_FOUND` | **Skip** — not a real error, the resource simply doesn't exist |
| `INPUT_INVALID`, `CONFIG_ERROR`, `ROUTING_ERROR`, `INVALID_TYPE`, `NO_CUSTOM_PROMPT`, `URL_ROUTE_ERROR` | **Fix input** — check arguments, config, or URL format |
| `STORAGE_ERROR`, `INDEX_ERROR`, `REFRESH_ERROR` | **Check system** — disk space, file permissions, DB locks |
| `RESOURCE_LOCKED` | **Wait** — another process holds a lock; retry after delay |
| `INTERNAL_ERROR`, `FATAL_CRASH` | **Escalate** — check crash dumps, file a report |

## 7. Tool Boundaries

The tool **does not** provide the following capabilities. If your workflow needs them, implement externally:

| Capability | Alternative |
|-----------|-------------|
| Daemon / server mode | Run CLI commands on demand; schedule externally |
| Batch clipping (multiple URLs) | Loop `clip` in your own script |
| Scheduling / cron | Use system cron, systemd timers, or external schedulers |
| Concurrent writes | Avoid parallel `clip` calls (SQLite); serialize or lock externally |
| Webhook / event notifications | Poll with `list`/`search` or check timestamps |
| Content diffing | `get --content` to retrieve Markdown; diff externally |
| Export / sync | Access files directly from `storage_path` directory |
| Image processing | Downloaded images are stored as-is in the clip folder |

## 8. Configuration

### Config File Location

Uses **SDK sandbox** directories under `~/.web-clip-helper/`:

| Path | Purpose |
|------|---------|
| `~/.web-clip-helper/data/config.json` | Config file (JSON format) |
| `~/.web-clip-helper/data/clips/` | Clipped content storage |
| `~/.web-clip-helper/data/clips.db` | SQLite index |
| `~/.web-clip-helper/data/reports/` | Feedback reports |
| `~/.web-clip-helper/cache/` | Cache directory |
| `~/.web-clip-helper/crash_dumps/` | Crash dump files |

> **Note:** The tool uses `config.json` (JSON format), **not** `config.yaml`. Environment variables override config file values.

### Key Config Values

```json
{
  "storage_path": "~/.web-clip-helper/data/clips",
  "db_path": "~/.web-clip-helper/data/clips.db",
  "llm": {
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini"
  },
  "refresh": {
    "default_interval_days": 7
  },
  "prompts": {
    "title": "",
    "tags": "",
    "classify": ""
  }
}
```

### Setting Config

```bash
# Via CLI
web-clip-helper config set llm.api_key sk-your-key
web-clip-helper config set llm.model gpt-4o

# Via environment variables (override config file)
export WEB_CLIP_LLM_API_KEY="sk-your-key"
export WEB_CLIP_LLM_BASE_URL="https://api.openai.com/v1"
export WEB_CLIP_LLM_MODEL="gpt-4o-mini"
```

Environment variables take **priority** over config file values.

### LLM Without Configuration

If `llm.api_key` is not set, `clip` still works (exit code 0) but:
- **Title:** Uses domain + timestamp or first 50 characters of content
- **Tags:** Empty array `[]`
- **Category:** Empty string

A warning JSONL line is emitted:
```jsonl
{"type":"warning","message":"LLM 未配置：标题/标签/分类使用默认值。请运行 `web-clip-helper config set llm.api_key <key>` 或设置环境变量 WEB_CLIP_LLM_API_KEY。","stage":"llm"}
```

## 9. Trace IDs

Every CLI invocation gets a **trace ID** for log correlation:

- **Source:** Set via `AGENT_TRACE_ID` environment variable, or auto-generated as a 16-char hex UUID
- **Location:** Present in every JSONL line's `trace_id` field
- **Use case:** Correlate multiple CLI invocations in a multi-step agent workflow

### Setting a Trace ID

```bash
# Pass your own trace ID for correlation
AGENT_TRACE_ID="my-workflow-step-1" web-clip-helper clip https://example.com

# Search crash dumps for a specific trace ID
web-clip-helper agent metrics trace --id my-workflow-step-1
```

### Example: Multi-Step Correlation

```bash
export AGENT_TRACE_ID="job-$(date +%s)"

web-clip-helper clip https://example.com/article    # trace_id links to this job
web-clip-helper get 42 --content                     # same trace_id
web-clip-helper update 42 --tags '["read"]'          # same trace_id
```

All JSONL output from these invocations shares the same `trace_id`, enabling post-hoc log correlation.

## 10. Quiet Mode

Use `--quiet` / `-q` to suppress progress and warning messages. Only `result`, `error`, `help`, `schema`, `dict`, and `diagnostics` lines are emitted.

```bash
# Only result/error output — no progress chatter
web-clip-helper --quiet clip https://example.com/article

# Useful for automation where you only need the final outcome
web-clip-helper -q list --limit 10
```

**Quiet mode suppresses:** `type=progress`, `type=warning`
**Quiet mode keeps:** `type=result`, `type=error`, `type=help`, `type=schema`, `type=dict`, `type=diagnostics`

## 11. Agent SOP (Standard Operating Procedure)

### Step 1: Discovery

Always start by confirming the tool is functional:

```bash
web-clip-helper agent info        # Confirm tool is installed and get version
web-clip-helper agent errors      # Load error code reference (cache for later)
web-clip-helper agent doctor      # Verify storage, DB, config, LLM connectivity
```

If `agent doctor` reports issues, fix them before proceeding (e.g. set `llm.api_key`).

### Step 2: Clip Content

```bash
# Clip a URL
web-clip-helper clip https://example.com/article

# Or clip raw text
web-clip-helper clip --text "Content to clip here"

# Skip images
web-clip-helper clip https://example.com/article --no-images

# Set a custom timeout (default is 60 seconds)
web-clip-helper clip https://example.com/article --timeout 120

# Preview without executing (no network, no filesystem writes)
web-clip-helper clip https://example.com/article --dry-run
```

### Step 3: Query Clips

```bash
# List all clips
web-clip-helper list

# List with tag filter
web-clip-helper list --tag python --limit 10 --offset 0

# List with category filter
web-clip-helper list --category article

# List with source type filter
web-clip-helper list --source-type web

# Combine filters
web-clip-helper list --category article --source-type web --limit 5

# Search by keyword (title/URL only)
web-clip-helper search "machine learning"

# Full-text search (includes Markdown content)
web-clip-helper search "machine learning" --full

# Get a specific clip with full Markdown content
web-clip-helper get 42 --content
```

### Step 4: Maintain Clips

```bash
# Update metadata
web-clip-helper update 42 --title "New Title" --tags '["tag1","tag2"]' --category "article"

# Mark as dynamic for auto-refresh
web-clip-helper update 42 --dynamic --interval 7

# Refresh all due dynamic clips
web-clip-helper refresh

# Refresh and re-run LLM enrichment
web-clip-helper refresh --re-enrich

# Delete a clip
web-clip-helper delete 42
```

### Step 5: Troubleshoot Issues

```bash
# Check LLM auth
web-clip-helper agent auth status

# View environment details
web-clip-helper agent debug env

# Check last crash
web-clip-helper agent debug last-crash

# Search crash dumps by trace ID
web-clip-helper agent metrics trace --id <trace_id>

# Submit a bug report
web-clip-helper report submit "Description of the issue" --type bug
```

---

## Appendix: Supported URL Adapters

| Adapter | URL Pattern | Auto-Dynamic |
|---------|------------|-------------|
| 微博头条 (Weibo Article) | `weibo.com/ttarticle/...`, `m.weibo.cn/ttarticle/...` | Yes |
| 微博卡片 (Weibo Card) | `card.weibo.com/article/...` | Yes |
| 微博 (Weibo) | `weibo.com/...`, `m.weibo.cn/...` | Yes |
| 微信公众号 (WeChat) | `mp.weixin.qq.com/...` | No |
| GitHub | `github.com/{owner}/{repo}` | No |
| arXiv | `arxiv.org/abs/...`, `arxiv.org/pdf/...` | No |
| 通用网页 (Generic) | Any other URL | No |

**Matching rule:** URLs are matched in registration order. First matching adapter wins. Weibo-specific adapters (头条, 卡片) take priority over the general Weibo adapter.
