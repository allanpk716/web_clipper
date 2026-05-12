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
| `dict` | Dictionary data (emitted by `agent errors`) | Always emitted |
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
| `import <dir>` | Import previously clipped data from an external directory | Yes |
| `refresh` | Re-clip dynamic items that are due for refresh | Yes |
| `version` | Print current version | Yes |

### Config Commands

| Command | Description |
|---------|-------------|
| `config list` | List all config values (api_key is masked) |
| `config get <key>` | Get a single config value by dot-path (e.g. `llm.model`) |
| `config set <key> <value>` | Set a config value and persist to YAML |
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
| `agent cache clean` | Clean XDG cache directory |
| `agent debug last-crash` | Read last crash dump file |
| `agent debug env` | Environment snapshot (Python, OS, deps, paths) |
| `agent feature record --name N --desc D` | Record a feature request |
| `agent feature list` | List recorded feature requests |
| `agent metrics trace --id <tid>` | Search crash dumps for a trace ID |

For full parameter details (types, required/optional, defaults), run:
```bash
web-clip-helper agent schema
```

## 5. Agent SOP (Standard Operating Procedure)

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

# Preview without executing (no network, no filesystem writes)
web-clip-helper clip https://example.com/article --dry-run
```

**Dry-run mode** returns an ExecutionPlan with estimated actions but performs **no real IO** — no network fetch, no filesystem writes, no SQLite writes. Use it to preview before committing:

```jsonl
{"type":"result","stage":"clip","dry_run":true,"plan":{"adapter":"GenericWebAdapter","url":"https://example.com/article","estimated_actions":["fetch","markdown","storage","index"],"estimated_image_count":"unknown","duplicate":false},"version":"0.2.0","tool":"web-clip-helper","timestamp":"...","trace_id":"..."}
```

**Duplicate handling:** If the URL was already clipped, the result includes `"duplicate": true` and `"existing_id": <id>`. The existing record is **not modified**. You may optionally `update` or `delete` it.

### Step 3: Query Clips

```bash
# List all clips
web-clip-helper list

# List with filters
web-clip-helper list --tag python --limit 10 --offset 0

# Search by keyword
web-clip-helper search "machine learning"

# Full-text search (includes Markdown content)
web-clip-helper search "machine learning" --full

# Get a specific clip with full Markdown content
web-clip-helper get 42 --content
```

### Step 3.5: Import Existing Data

Use `import` to bulk-register previously clipped data from an external directory into the index:

```bash
# Preview what would be imported (no writes)
web-clip-helper import /path/to/clipped/data --dry-run

# Import in-place (references original files, no copy)
web-clip-helper import /path/to/clipped/data

# Import and copy files into storage_path
web-clip-helper import /path/to/clipped/data --copy

# Override source_type for entries without manifest data
web-clip-helper import /path/to/clipped/data --source-type wechat
```

**What it scans:**
- Recursively scans all subdirectories for `DATE_Title/DATE_Title.md` folder structures
- Reads `_manifest.json` files (supports both `{"items": [...]}` and `{"repos": [...]}` schemas) for URL, source_type, and metadata
- When no manifest exists, extracts URLs from markdown content (patterns: `**链接**: URL`, `来源: URL`, `Source: URL`, Markdown `[text](url)`, bare URL lines)

**Deduplication:** Entries with the same `folder_path` are skipped automatically. Second import of the same directory produces `imported: 0, skipped: N`.

**Output (dry-run):**
```jsonl
{"type":"result","stage":"import","dry_run":true,"folder":"/path/2026-04-10_Article","markdown_exists":true,"manifest":true,"url":"https://...","source_type":"web",...}
```

**Output (import):**
```jsonl
{"type":"progress","stage":"import","message":"Imported","record_id":42,...}
{"type":"result","stage":"import","imported":5,"skipped":1,"total_scanned":6,...}
```

**Error codes:** `INPUT_INVALID` (source dir not found), `IMPORT_SCAN_ERROR` (scan failure), `IMPORT_ERROR` (DB write failure).

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

## 6. Error Handling

### Exit Codes

| Exit Code | Meaning |
|-----------|---------|
| 0 | Success |
| 1 | Fatal/unknown (`INTERNAL_ERROR`, `FATAL_CRASH`) |
| 2 | Input/config (`INPUT_INVALID`, `CONFIG_ERROR`, `INVALID_TYPE`, `NO_CUSTOM_PROMPT`) |
| 3 | Resource/dependency (`NOT_FOUND`, `STORAGE_ERROR`, `INDEX_ERROR`, `REFRESH_ERROR`, `BACKUP_ERROR`, `BACKUP_NOT_FOUND`) |
| 4 | Network/third-party (`NETWORK_ERROR`, `FETCH_ERROR`, `ROUTING_ERROR`, `URL_ROUTE_ERROR`, `TIMEOUT_ERROR`, `IMPORT_ERROR`, `IMPORT_SCAN_ERROR`) |
| 5 | Concurrency (`RESOURCE_LOCKED`) |

### Error Codes

| error_code | Description | Guidance |
|------------|-------------|----------|
| `INPUT_INVALID` | Invalid or missing input argument | Check command arguments. Run with `--help`. |
| `NOT_FOUND` | Requested resource does not exist | Verify the ID/key exists. Use `list`/`search` to find valid identifiers. |
| `STORAGE_ERROR` | File-system storage operation failed | Check disk space and file permissions. |
| `INDEX_ERROR` | SQLite index operation failed | Database may be locked or corrupted. Retry or rebuild. |
| `NETWORK_ERROR` | Network connectivity or DNS failure | Check internet. Retry after network recovery. |
| `ROUTING_ERROR` | URL could not be routed to an adapter | Ensure the URL matches a supported adapter. |
| `FETCH_ERROR` | Adapter failed to fetch content | Site may be down or blocking automated access. |
| `CONFIG_ERROR` | Configuration load/save/validation error | Validate config file syntax (YAML). Check path and permissions. |
| `INTERNAL_ERROR` | Unexpected internal error | Check logs. Consider filing a bug report. |
| `FATAL_CRASH` | Unrecoverable crash (signal/unhandled exception) | Check crash dump files. |
| `REFRESH_ERROR` | Dynamic clip refresh failed | Verify the source URL is still accessible. |
| `TIMEOUT_ERROR` | Operation exceeded wall-clock timeout | Increase `--timeout` or check network/server responsiveness. |
| `INVALID_TYPE` | Invalid or unsupported type argument | Check `--type` value against supported types. |
| `NO_CUSTOM_PROMPT` | Custom prompt referenced but not configured | Provide `--prompt` or configure in settings. |
| `URL_ROUTE_ERROR` | URL pattern matched no adapter route | Ensure the URL matches a supported adapter. |
| `IMPORT_ERROR` | Failed to import clip data into the index | Check disk space, file permissions, and database integrity. |
| `IMPORT_SCAN_ERROR` | Failed to scan source directory for clip folders | Check that the source directory exists and is readable. |
| `RESOURCE_LOCKED` | Concurrent access conflict — resource locked by another process | Wait for the other process to finish or remove stale lock files. |
| `BACKUP_ERROR` | Backup operation failed | Check disk space, file permissions, and that output directory is writable. |
| `BACKUP_NOT_FOUND` | No data found to back up (data directory is empty or missing) | Verify the data directory exists and contains files to back up. |

### Error JSONL Format

```jsonl
{"type":"error","stage":"clip","detail":"Network request timed out after 60s","error_code":"TIMEOUT_ERROR","version":"0.2.0","tool":"web-clip-helper","timestamp":"2026-05-04T12:00:00.000Z","trace_id":"abc123"}
```

### Recommended Error Handling Strategy

| error_code | Action |
|------------|--------|
| `NETWORK_ERROR`, `FETCH_ERROR`, `TIMEOUT_ERROR` | **Retry** with exponential backoff (these are transient) |
| `NOT_FOUND` | **Skip** — not a real error, the resource simply doesn't exist |
| `INPUT_INVALID`, `CONFIG_ERROR`, `ROUTING_ERROR`, `INVALID_TYPE`, `NO_CUSTOM_PROMPT` | **Fix input** — check arguments, config, or URL format |
| `STORAGE_ERROR`, `INDEX_ERROR` | **Check system** — disk space, file permissions, DB locks |
| `BACKUP_ERROR` | **Check system** — disk space, output dir permissions |
| `BACKUP_NOT_FOUND` | **Check system** — verify data directory exists and contains files |
| `IMPORT_ERROR`, `IMPORT_SCAN_ERROR` | **Fix input** (check source directory) or **Retry** |
| `RESOURCE_LOCKED` | **Wait** — another process holds the lock; retry after a delay |
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

Uses **XDG-compliant** directories via `platformdirs`:

| Path | Purpose |
|------|---------|
| `~/.config/web-clip-helper/config.yaml` (Linux/macOS) | Config file |
| `~/.local/share/web-clip-helper/clips/` | Clipped content storage |
| `~/.local/share/web-clip-helper/clips.db` | SQLite index |
| `~/.local/state/web-clip-helper/` | State, locks, crash dumps |
| `~/.local/state/web-clip-helper/reports/` | Feedback reports |

> **Legacy path:** `~/.web-clip-helper/` — migrated automatically on first run (data is **copied**, not moved).

### Key Config Values

```yaml
storage_path: ~/.local/share/web-clip-helper/clips   # Content storage
db_path: ~/.local/share/web-clip-helper/clips.db      # SQLite database

llm:
  api_key: ""                  # LLM API key (required for enrichment)
  base_url: "https://api.openai.com/v1"  # API base URL
  model: "gpt-4o-mini"        # Model name

refresh:
  default_interval_days: 7     # Dynamic clip refresh interval

prompts:
  title: ""                    # Custom title prompt (empty = built-in)
  tags: ""                     # Custom tags prompt
  classify: ""                 # Custom classify prompt
```

### Setting Config

```bash
# Via CLI
web-clip-helper config set llm.api_key sk-your-key
web-clip-helper config set llm.model gpt-4o

# Via environment variables (override YAML)
export WEB_CLIP_LLM_API_KEY="sk-your-key"
export WEB_CLIP_LLM_BASE_URL="https://api.openai.com/v1"
export WEB_CLIP_LLM_MODEL="gpt-4o-mini"
```

Environment variables take **priority** over YAML config.

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

## 10. Structured Logs

Every CLI invocation writes a **structured log file** for diagnostics. This is independent of JSONL stdout output and is not affected by `--quiet` mode.

### Log File Location

```
~/.web-clip-helper/logs/web-clip-helper.log
```

Read it directly with standard file tools:

```bash
cat ~/.web-clip-helper/logs/web-clip-helper.log
# Or tail for recent entries
tail -50 ~/.web-clip-helper/logs/web-clip-helper.log
```

### Log Format

```
YYYY-MM-DD HH:MM:SS.mmm - [LEVEL]: message key=value
```

### Correlating Logs with JSONL trace_id

Every CLI invocation includes a `trace_id` in both JSONL output and log file entries. To correlate:

```bash
# Step 1: Run a command, capture the trace_id from JSONL output
web-clip-helper clip https://example.com
# → {"type":"result","trace_id":"abc123def4567890",...}

# Step 2: Search the log file for that trace_id
grep "abc123def4567890" ~/.web-clip-helper/logs/web-clip-helper.log
```

### Stage-by-Stage Log Fields

| Stage | Key Fields | Description |
|-------|-----------|-------------|
| `route` | `adapter`, `elapsed_ms` | Which adapter was selected for the URL |
| `fetch` | `content_length`, `elapsed_ms` | Content fetch result and size in bytes |
| `llm` | `tags_count`, `category`, `reason`, `elapsed_ms` | LLM enrichment result; `reason` = `no_api_key` or `error` |
| `images` | `image_count`, `elapsed_ms` | Number of images downloaded |
| `store` | `entry_name`, `elapsed_ms` | Storage folder name |
| `index` | `record_id`, `elapsed_ms` | SQLite record ID assigned |

Error stages additionally include an `error` field with the error message.

### Redaction Constraints

Logs contain **only metadata** — never full content:

| What IS logged | What is NOT logged |
|---------------|-------------------|
| `content_length` (integer) | Full markdown content |
| `image_count` (integer) | Image URLs |
| `tags_count` (integer) | Config values / API keys |
| `elapsed_ms` (float) | User text content |

**Do not** expect to find full article text, image URLs, or API keys in the log file.

### Diagnostic Workflow

When a clip operation fails, follow this workflow:

```bash
# 1. Run the clip and note the trace_id from JSONL output
web-clip-helper clip https://example.com
# → {"type":"error","trace_id":"abc123","error_code":"FETCH_ERROR",...}

# 2. Search logs for that trace_id to find the failure stage
grep "abc123" ~/.web-clip-helper/logs/web-clip-helper.log
# → 2026-05-11 21:25:05.100 - [ERROR]: fetch failed elapsed_ms=5200 error=HTTP 404 url=https://example.com

# 3. Diagnose based on the stage and error field
# - route error → URL not matching any adapter → check URL format
# - fetch error → network or site issue → retry or check site accessibility
# - llm error → API key issue or LLM timeout → check config, retry
# - images warning → individual image download failed → non-fatal, content is preserved
```

### Log Rotation

The SDK manages log rotation automatically: daily rotation with 7-day retention. No manual cleanup needed.

## 11. Quiet Mode

Use `--quiet` / `-q` to suppress progress and warning messages. Only `result`, `error`, `help`, `schema`, `dict`, and `diagnostics` lines are emitted.

```bash
# Only result/error output — no progress chatter
web-clip-helper --quiet clip https://example.com/article

# Useful for automation where you only need the final outcome
web-clip-helper -q list --limit 10
```

**Quiet mode suppresses:** `type=progress`, `type=warning`
**Quiet mode keeps:** `type=result`, `type=error`, `type=help`, `type=schema`, `type=dict`, `type=diagnostics`

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
