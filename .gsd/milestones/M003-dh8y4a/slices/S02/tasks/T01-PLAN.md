---
estimated_steps: 1
estimated_files: 1
skills_used: []
---

# T01: 执行人工抽查并记录结果

从集成测试报告中每种适配器各选 1 个 URL。从 docs/exsample/my-things/ 找到对应旧文件。对比新旧内容主题是否一致。记录到 S02-UAT.md。用户已确认 5/5 主题一致，并提出了两个 LLM 标题增强建议（GitHub 标题应为中文概括、Arxiv 标题应为中文）。

## Inputs

- `scripts/integration_report.json`
- `docs/exsample/my-things/`

## Expected Output

- `.gsd/milestones/M003-dh8y4a/slices/S02/S02-UAT.md`

## Verification

S02-UAT.md 存在且包含 5 个 URL 的对比结果
