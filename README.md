# web-clip-helper

LLM Agent 驱动的网页剪藏 CLI 工具。通过命令行将网页内容剪藏为本地 Markdown，并利用 LLM 自动生成标题、提取标签和分类。

## 安装

```bash
pip install web-clip-helper
```

## 快速开始

```bash
# 剪藏一个网页
web-clip-helper clip https://example.com/article

# 列出所有剪藏
web-clip-helper list

# 查看某条剪藏
web-clip-helper get 1
```

## CLI 命令

所有输出均为 JSONL 格式（每行一个 JSON 对象），便于 Agent 程序解析。

### clip — 剪藏网页或文本

```bash
# 剪藏 URL
web-clip-helper clip <url>

# 剪藏纯文本
web-clip-helper clip --text "要剪藏的文本内容"
```

### list — 列出剪藏

```bash
# 列出所有
web-clip-helper list

# 按标签筛选
web-clip-helper list --tag python

# 按分类筛选
web-clip-helper list --category article

# 按来源类型筛选
web-clip-helper list --source-type github
```

选项：

| 选项 | 缩写 | 说明 |
|------|------|------|
| `--tag` | `-t` | 按标签筛选 |
| `--category` | `-c` | 按分类筛选 |
| `--source-type` | `-s` | 按来源类型筛选 |

### get — 获取单条剪藏

```bash
web-clip-helper get <clip-id>
```

### search — 关键词搜索

```bash
web-clip-helper search <query>
```

在标题和 URL 中搜索包含关键词的剪藏。

### tags — 列出所有标签

```bash
web-clip-helper tags
```

输出所有标签及其使用次数。

### update — 更新剪藏属性

```bash
# 标记为动态内容，并设置 3 天刷新间隔
web-clip-helper update 42 --dynamic --interval 3

# 取消动态标记
web-clip-helper update 7 --no-dynamic

# 仅修改刷新间隔
web-clip-helper update 15 --interval 14
```

更新剪藏的动态标记和刷新间隔。输出 JSONL 格式。

选项：

| 选项 | 缩写 | 说明 |
|------|------|------|
| `--dynamic` / `--no-dynamic` | — | 设置 `is_dynamic` 标记 |
| `--interval` | `-i` | 刷新间隔天数（正整数） |

**验证规则：**
- 未指定任何选项 → 退出码 1
- `--interval` ≤ 0 → 退出码 1
- 不存在的 ID → 退出码 1

### refresh — 刷新动态剪藏

```bash
web-clip-helper refresh
```

重新剪藏到期的动态内容（根据 `refresh.default_interval_days` 配置的间隔判断）。

### feedback — 提交反馈

```bash
web-clip-helper feedback "问题描述" --type bug
```

在 `~/.web-clip-helper/feedback/` 目录下生成包含环境信息的反馈文件。

选项：

| 选项 | 说明 |
|------|------|
| `--type` | 反馈类型：`bug`（默认）、`feature`、`other` |

## 配置管理

### config list — 列出所有配置

```bash
web-clip-helper config list
# 指定配置文件路径
web-clip-helper config list --path /path/to/config.yaml
```

输出所有配置项，其中 `llm.api_key` 会被自动掩码显示（如 `sk-****1234`）。

### config get — 获取单个配置

```bash
web-clip-helper config get llm.model
```

使用 dot-path 表示法访问嵌套配置项，如 `llm.api_key`、`refresh.default_interval_days`、`prompts.title`。

### config set — 设置配置

```bash
# 设置 API Key
web-clip-helper config set llm.api_key sk-your-key

# 设置模型
web-clip-helper config set llm.model gpt-4o

# 设置刷新间隔
web-clip-helper config set refresh.default_interval_days 14

# 设置自定义提示词
web-clip-helper config set prompts.title "请为以下内容生成标题：{content}"
web-clip-helper config set prompts.tags "请提取标签：{content}"
web-clip-helper config set prompts.classify "请分类：{content}"
```

配置值会持久化到 YAML 文件，并自动清除内存缓存使后续命令立即生效。值会根据字段类型自动转换（字符串/整数）。

### config prompt test — 提示词对比测试

```bash
web-clip-helper config prompt test --type title --url https://example.com
web-clip-helper config prompt test --type tags --url https://example.com
web-clip-helper config prompt test --type classify --url https://example.com
```

并排显示内置提示词和自定义提示词对同一 URL 的处理结果，方便对比调优。

## 配置文件

配置文件位于 `~/.web-clip-helper/config.yaml`，首次运行时自动创建。

```yaml
# 存储路径
storage_path: ~/.web-clip-helper/clips
db_path: ~/.web-clip-helper/clips.db

# LLM 配置
llm:
  api_key: ""                # OpenAI API Key
  base_url: "https://api.openai.com/v1"  # API 基础 URL
  model: "gpt-4o-mini"      # 模型名称

# 刷新配置
refresh:
  default_interval_days: 7  # 动态内容默认刷新间隔（天）

# 自定义提示词模板
prompts:
  title: ""      # 标题生成提示词（留空使用内置模板）
  tags: ""       # 标签提取提示词（留空使用内置模板）
  classify: ""   # 分类提示词（留空使用内置模板）
```

## 环境变量

以下环境变量会覆盖 YAML 配置文件中的对应值：

| 环境变量 | 覆盖字段 | 说明 |
|----------|----------|------|
| `WEB_CLIP_LLM_API_KEY` | `llm.api_key` | LLM API 密钥 |
| `WEB_CLIP_LLM_BASE_URL` | `llm.base_url` | API 基础 URL |
| `WEB_CLIP_LLM_MODEL` | `llm.model` | 模型名称 |

```bash
export WEB_CLIP_LLM_API_KEY="sk-your-key"
export WEB_CLIP_LLM_BASE_URL="https://api.openai.com/v1"
export WEB_CLIP_LLM_MODEL="gpt-4o-mini"
```

环境变量优先级高于配置文件，设置后即时生效。

## 自定义提示词模板

通过 `config set` 命令设置自定义提示词模板：

```bash
web-clip-helper config set prompts.title "请为以下{content_type}内容生成一个简洁的中文标题：\n\n{content}"
```

### 支持的占位符

| 占位符 | 说明 |
|--------|------|
| `{content}` | 剪藏的 Markdown 内容（截断至约 4000 字符） |
| `{content_type}` | 内容来源类型（如 `github`、`weibo`、`web` 等） |

### 未知占位符处理

模板中使用的未知占位符（如 `{foo}`）会被替换为空字符串，并输出警告日志，不会导致程序崩溃。

## 输出格式

所有输出使用 JSONL 格式（JSON Lines）——每行一个独立的 JSON 对象，通过 `type` 字段区分类型：

```jsonl
{"type": "progress", "message": "正在剪藏...", "percent": 50}
{"type": "result", "stage": "clip", "title": "文章标题", "url": "https://..."}
{"type": "error", "stage": "clip", "detail": "网络超时"}
{"type": "warning", "message": "图片下载失败，已跳过"}
{"type": "help", "commands": [...], "description": "..."}
```

| type | 说明 |
|------|------|
| `progress` | 进度消息，可选包含 `percent` |
| `result` | 操作结果数据，包含 `stage` 字段标识来源命令 |
| `error` | 错误信息，包含 `stage` 和 `detail` |
| `warning` | 非致命警告 |
| `help` | 帮助信息（`--help` 时输出） |

### 退出码约定

| 退出码 | 说明 |
|--------|------|
| `0` | 命令执行成功 |
| `1` | 命令执行失败（查看 JSONL 中的 `error` 消息获取详情） |

## 支持的 URL 类型

| 适配器 | URL 格式 | 说明 |
|--------|----------|------|
| 微博头条 | `https://weibo.com/ttarticle/...`、`https://m.weibo.cn/ttarticle/...` | 微博头条文章（优先匹配） |
| 微博卡片 | `https://card.weibo.com/article/...` | 微博卡片内容 |
| 微博 | `https://weibo.com/...`、`https://m.weibo.cn/...` | 微博正文 |
| 微信公众号 | `https://mp.weixin.qq.com/...` | 微信公众号文章 |
| GitHub | `https://github.com/{owner}/{repo}` | GitHub 仓库页面 |
| arXiv | `https://arxiv.org/abs/...`、`https://arxiv.org/pdf/...` | arXiv 论文页面 |
| 通用网页 | 任何其他 URL | 默认回退适配器 |

> **匹配规则：** URL 按适配器注册顺序匹配，第一个匹配的适配器被使用。微博头条和微博卡片优先于通用微博适配器。

## For AI Agents

本节为 AI agent 提供集成所需的完整信息。

### 快速集成流程

```bash
# 1. 剪藏一个 URL
web-clip-helper clip https://example.com/article
# 解析最后一行 type=result 的 JSON，获取 record_id、title、tags 等

# 2. 搜索已有剪藏
web-clip-helper search "关键词"
# 每行 type=result 的 JSON 包含匹配的剪藏记录

# 3. 查看特定剪藏
web-clip-helper get <record_id>
```

### 逐行解析 JSONL 输出

所有命令输出多行 JSONL。一个 `clip` 操作的典型输出：

```jsonl
{"type": "progress", "message": "Starting clip for URL: https://...", "percent": 0}
{"type": "progress", "message": "Using adapter: GenericWebAdapter", "percent": 10}
{"type": "progress", "message": "Fetched content: 文章标题", "percent": 30}
{"type": "progress", "message": "LLM enrichment starting", "percent": 35}
{"type": "progress", "message": "LLM enrichment complete", "percent": 45}
{"type": "progress", "message": "Created storage entry: 2026-05-01_文章标题", "percent": 40}
{"type": "progress", "message": "Downloaded 3 images", "percent": 70}
{"type": "progress", "message": "Saved markdown: 2026-05-01_文章标题.md", "percent": 85}
{"type": "progress", "message": "Saved to index: record #42", "percent": 95}
{"type": "result", "stage": "clip", "url": "https://...", "title": "文章标题", "source_type": "web", "folder": "/path/to/clips/2026-05-01_文章标题", "markdown": "/path/to/markdown.md", "image_count": 3, "file_count": 0, "record_id": 42, "tags": ["标签1", "标签2"], "category": "技术"}
{"type": "progress", "message": "Clip complete", "percent": 100}
```

**Agent 应该：** 逐行解析 JSONL，收集所有 `type=result` 的行。使用 `stage` 字段区分来自不同命令的结果。

### 各命令的 result schema

#### clip result

```json
{
  "type": "result",
  "stage": "clip",
  "url": "https://...",
  "title": "文章标题",
  "source_type": "web",
  "folder": "/path/to/clip/folder",
  "markdown": "/path/to/file.md",
  "image_count": 3,
  "file_count": 0,
  "record_id": 42,
  "tags": ["标签1", "标签2"],
  "category": "技术"
}
```

#### list / search result

```json
{
  "type": "result",
  "stage": "list",
  "id": 42,
  "url": "https://...",
  "title": "文章标题",
  "source_type": "web",
  "category": "技术",
  "tags": ["标签1"],
  "folder_path": "/path/to/folder",
  "markdown_path": "/path/to/file.md",
  "image_count": 3,
  "is_dynamic": 0,
  "refresh_interval_days": 7,
  "last_refreshed_at": null,
  "created_at": "2026-05-01T10:00:00",
  "updated_at": "2026-05-01T10:00:00"
}
```

#### get result

与 list result 相同的字段结构，`stage` 为 `"get"`。

#### tags result

```json
{
  "type": "result",
  "stage": "tags",
  "tag": "python",
  "count": 15
}
```

#### config result

```json
{
  "type": "result",
  "stage": "config",
  "key": "llm.api_key",
  "value": "sk-****1234"
}
```

#### feedback result

```json
{
  "type": "result",
  "stage": "feedback",
  "file": "/path/to/feedback.md",
  "feedback_type": "bug",
  "message": "Feedback file generated: /path/to/feedback.md"
}
```

### 常见错误及排查

| 错误 stage | 典型 detail | 原因 | 解决方式 |
|-----------|-------------|------|---------|
| `routing` | `Invalid URL: ...` | URL 为空或格式无效 | 检查 URL 参数 |
| `fetch` | `HTTP 404` / `Timeout` | 目标网站不可达 | 重试或检查 URL 是否正确 |
| `fetch` | `AdapterError: ...` | 适配器解析失败 | 可能是页面结构变化，提交 feedback |
| `storage` | `Cannot write...` | 磁盘空间不足或权限问题 | 检查 storage_path 配置 |
| `index` | `database is locked` | SQLite 并发写入冲突 | 确保不并发调用 clip |
| `llm` (warning) | `LLM enrichment skipped: no API key` | 未配置 API key | 运行 `config set llm.api_key <key>` |

### LLM 未配置时的行为

如果未配置 API key，`clip` 命令仍然可以正常工作（退出码 0），但：

- **标题**：使用 URL 域名 + 时间戳，或内容前 50 个字符
- **标签**：返回空数组 `[]`
- **分类**：返回空字符串

clip 完成后会输出一条汇总 warning：

```jsonl
{"type": "warning", "message": "LLM 未配置：标题/标签/分类使用默认值。请运行 `web-clip-helper config set llm.api_key <key>` 或设置环境变量 WEB_CLIP_LLM_API_KEY。", "stage": "llm"}
```

### 动态内容与刷新机制

`refresh` 命令会重新剪藏所有到期的动态内容。哪些内容被标记为动态取决于适配器：

| 适配器 | is_dynamic | 说明 |
|--------|-----------|------|
| 微博 | True | 微博正文会随编辑/删除变化 |
| 微博头条 | True | 头条文章内容可能更新 |
| 微博卡片 | True | 卡片内容可能更新 |
| GitHub | False | 仓库内容虽会变化但刷新频率低，由用户按需标记 |
| 微信公众号 | False | 文章发布后通常不再变化 |
| arXiv | False | 论文发布后不会变化 |
| 通用网页 | False | 默认不标记为动态 |

- 适配器在 `clip` 时自动设置 `is_dynamic` 标记
- 用户可通过 `update` 命令覆盖自动标记结果
- 刷新间隔默认为 `refresh.default_interval_days`（默认 7 天）

#### 示例 1：微博自动标记为动态

```bash
# 剪藏微博 — 自动标记为动态（is_dynamic=1）
web-clip-helper clip https://weibo.com/12345/abc

# 覆盖刷新间隔为 3 天
web-clip-helper update 42 --interval 3

# 稍后刷新所有到期的动态剪藏
web-clip-helper refresh
```

#### 示例 2：手动将 GitHub 仓库标记为动态

```bash
# 剪藏 GitHub 仓库 — 不自动标记（is_dynamic=0）
web-clip-helper clip https://github.com/user/repo

# 手动标记为动态，每 14 天刷新一次
web-clip-helper update 15 --dynamic --interval 14

# 现在该仓库会每 14 天自动刷新
web-clip-helper refresh
```

### 剪藏文本内容

使用 `--text` 选项剪藏纯文本（注意不是位置参数）：

```bash
# 正确
web-clip-helper clip --text "要剪藏的文本内容"
web-clip-helper clip -t "短选项形式"

# 错误 — 这会把文本当作 URL 处理
web-clip-helper clip "要剪藏的文本内容"
```

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
python -m pytest tests/ -v
```

## License

MIT
