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
| `result` | 操作结果数据 |
| `error` | 错误信息，包含 `stage` 和 `detail` |
| `warning` | 非致命警告 |
| `help` | 帮助信息（`--help` 时输出） |

## 支持的 URL 类型

| 适配器 | 说明 |
|--------|------|
| GitHub | GitHub 仓库页面 |
| 微博 | 微博正文 |
| 微博头条 | 微博头条文章 |
| 微博卡片 | 微博卡片内容 |
| 微信公众号 | 微信公众号文章 |
| arXiv | arXiv 论文页面 |
| 通用网页 | 所有其他网页（默认回退） |

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
python -m pytest tests/ -v
```

## License

MIT
