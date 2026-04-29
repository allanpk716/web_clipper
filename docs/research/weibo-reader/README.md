# 微博内容抓取调研报告

> 调研日期：2026-04-11
> 需求：给 AI Agent 提供读取单条微博内容的能力（URL → 正文/图片/评论 → MD 文档化）

---

## 一、现有开源项目

### 1. mcp-server-weibo (qinyuanpei) — 推荐 ⭐⭐⭐⭐

- **GitHub**: https://github.com/qinyuanpei/mcp-server-weibo
- **语言**: Python (FastMCP)
- **协议**: MIT
- **工具数量**: 10 个
- **认证方式**: 无需登录，自动通过微博访客通行证生成凭证
- **安装方式**: `uvx mcp-server-weibo`

**提供的 MCP 工具**：

| 工具名 | 参数 | 描述 |
|--------|------|------|
| `search_users` | keyword, limit, page | 搜索微博用户 |
| `get_profile` | uid | 获取用户详细资料 |
| `get_feeds` | uid, limit | 获取用户动态 |
| `get_hot_feeds` | uid, limit | 获取用户热门微博 |
| `get_trendings` | limit | 获取微博热搜榜 |
| `search_content` | keyword, limit, page | 搜索微博内容 |
| `search_topics` | keyword, limit, page | 搜索微博话题 |
| `get_comments` | feed_id, page | 获取指定微博下的评论 |
| `get_followers` | uid, limit, page | 获取关注列表 |
| `get_fans` | uid, limit, page | 获取粉丝列表 |

**Claude Code 安装命令**：
```bash
claude mcp add weibo uvx --from git+https://github.com/qinyuanpei/mcp-server-weibo.git mcp-server-weibo
```

**settings.json 配置**：
```json
{
  "mcpServers": {
    "weibo": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/qinyuanpei/mcp-server-weibo.git", "mcp-server-weibo"]
    }
  }
}
```

**不足**: 没有提供"通过 URL 直接获取单条微博内容"的工具。

---

### 2. mcp-server-weibo (Selenium39) — Node.js 版

- **GitHub**: https://github.com/Selenium39/mcp-server-weibo
- **语言**: TypeScript
- **工具数量**: 5 个（搜索用户、用户资料、动态、热搜、内容搜索）
- **安装方式**: `npx @iflow-mcp/weibo`

**与 Python 版对比**：

| 对比项 | qinyuanpei (Python) | Selenium39 (TypeScript) |
|--------|---------------------|------------------------|
| 工具数量 | 10 个 | 5 个 |
| 评论获取 | 有 | 无 |
| 话题搜索 | 有 | 无 |
| 关注/粉丝 | 有 | 无 |
| Docker 支持 | 有 | 无 |
| URL 单条提取 | 不支持 | 不支持 |

结论：Python 版功能更完善，推荐使用。

---

### 3. MediaCrawler — 多平台爬虫 ⭐⭐⭐

- **GitHub**: https://github.com/NanmiCoder/MediaCrawler
- **Stars**: 30K+
- **语言**: Python (Playwright)
- **支持平台**: 小红书、抖音、快手、B站、微博、贴吧、知乎

**微博功能**：
- 关键词搜索、帖子爬取、二级评论
- 创作者主页内容获取
- 登录态缓存、IP代理池
- Pro 版支持 AI Agent (Claude Code / Cursor) 一键安装

**不足**: 重量级方案，基于 Playwright 浏览器自动化，资源消耗大。

---

### 4. weibo-mcp-server (Yooki-K)

- **GitHub**: https://github.com/Yooki-K/weibo-mcp-server
- **功能**: 专注于热搜数据获取
- **适用场景**: 仅需热搜榜单

---

## 二、RSS 方案

### RSSHub

- **GitHub**: https://github.com/DIYgod/RSSHub
- 支持微博，但**必须配置 `WEIBO_COOKIES` 环境变量**
- Cookie 需从 m.weibo.cn 登录后抓包获取
- 常见 432 错误均因缺少 Cookie 导致
- 适合订阅某个用户的动态，**不适合单条 URL 提取**

### weibo-rss

- **GitHub**: https://github.com/zgq354/weibo-rss
- 轻量级微博专用 RSS 生成器
- 同样不适合单条 URL 场景

---

## 三、Web 提取服务

| 服务 | 微博可用性 | 说明 |
|------|-----------|------|
| **Jina Reader API** | 不可用 | 无法绕过微博反爬 |
| **Firecrawl** | 不可用 | 主动屏蔽社交媒体平台 |
| **ScraperAPI** | 可用(付费) | 专业反爬绕过代理服务 |
| **Bright Data** | 可用(付费) | 专业代理网络 |

---

## 四、Read-it-later 工具

- **Pocket**: 已于 2025年7月关闭
- **Instapaper**: 对微博中文内容提取能力有限
- **wallabag**: 自托管，但对微博无特殊适配
- 没有专门适配中国社交媒体的 Read-it-later 工具

---

## 五、关键技术信息

### 微博移动端公开 API

微博移动端 `m.weibo.cn` 有一个无需登录的公开接口：

```
GET https://m.weibo.cn/statuses/show?id={id}
Headers: {
  "User-Agent": "Mozilla/5.0 ...",
  "Content-Type": "application/json"
}
```

返回 JSON 包含：
- 正文（HTML 格式）
- 图片（缩略图和大图 URL）
- 视频（流媒体 URL）
- 作者信息（昵称、头像、认证信息）
- 转发/评论/点赞数
- 发布时间
- 定位信息

### 微博 URL 格式

| 格式 | 示例 | ID 提取方式 |
|------|------|------------|
| PC 端 | `weibo.com/{uid}/{bid}` | bid 需转换为 mid |
| 移动端 | `m.weibo.cn/status/{id}` | id 直接使用 |
| 详情页 | `weibo.com/detail/{id}` | id 直接使用 |
| 新版 | `weibo.com/statuses/{id}` | id 直接使用 |

**bid → mid 转换算法**：微博使用 Base62 编码的短 ID (bid)，需要解码为数字 ID (mid)。

---

## 六、推荐实施方案

### 方案：mcp-server-weibo + 自建 URL 解析脚本

**Step 1**: 安装 mcp-server-weibo MCP Server（获取搜索、评论等能力）

**Step 2**: 编写 `weibo_reader.py` 脚本，核心功能：
- 解析微博各种 URL 格式 → 提取帖子 ID
- 调用 m.weibo.cn 公开 API 获取单条内容
- HTML 正文 → Markdown 转换（使用 `markdownify` 库）
- 输出干净的 MD 文档到 clips 目录

**依赖**: `requests`, `markdownify`

**Step 3**: 集成方式（二选一）：
- **方式A**: 封装为 MCP Server 的新工具 `get_post_by_url`
- **方式B**: 创建为 Claude Code Skill，通过 Bash 执行

### 文件结构

```
researches/weibo-reader/
├── README.md              # 本调研报告
├── weibo_reader.py        # URL解析 + 内容抓取 + MD转换脚本
├── requirements.txt       # 依赖：requests, markdownify
└── clips/                 # 剪藏 MD 文件输出目录
```

### 验证方式

1. 运行脚本：`python weibo_reader.py "https://weibo.com/xxx/xxx"`
2. 检查输出 MD 内容完整（正文、图片URL、元信息）
3. 通过 MCP 工具在 Claude Code 中直接调用
4. 测试不同 URL 格式的兼容性

---

## 七、参考链接

- https://github.com/qinyuanpei/mcp-server-weibo
- https://github.com/Selenium39/mcp-server-weibo
- https://github.com/NanmiCoder/MediaCrawler
- https://github.com/DIYgod/RSSHub
- https://github.com/zgq354/weibo-rss
- https://jina.ai/reader/
- https://mcpmarket.com/zh/server/weibo
