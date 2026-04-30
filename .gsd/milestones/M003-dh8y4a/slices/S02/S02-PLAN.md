# S02: UAT 人工抽查新旧内容主题一致性

**Goal:** 人工对比每种适配器至少 1 个 URL 的新旧抓取结果，确认内容主题一致，记录抽查结果
**Demo:** S02-UAT.md 中记录至少 5 个 URL 的人工抽查结果（每种适配器 ≥1），全部主题一致

## Must-Haves

- S02-SUCCESS:\n- 至少抽查 5 个 URL（GitHub ≥1, Weibo ≥1, WeChat ≥1, WeiboCard ≥1, Arxiv ≥1）\n- 每个抽查项记录：URL、旧文件标题/主题、新抓取标题/主题、一致性判定\n- 抽查结果写入 S02-UAT.md

## Proof Level

- This slice proves: full

## Integration Closure

S02 完成后 M002 遗留的 UAT 验证类别缺口关闭。

## Verification

- UAT 抽查记录为后续适配器维护提供人工质量基线。

## Tasks

- [x] **T01: 执行人工抽查并记录结果** `est:15min`
  从集成测试报告中每种适配器各选 1 个 URL。从 docs/exsample/my-things/ 找到对应旧文件。对比新旧内容主题是否一致。记录到 S02-UAT.md。用户已确认 5/5 主题一致，并提出了两个 LLM 标题增强建议（GitHub 标题应为中文概括、Arxiv 标题应为中文）。
  - Files: `.gsd/milestones/M003-dh8y4a/slices/S02/S02-UAT.md`
  - Verify: S02-UAT.md 存在且包含 5 个 URL 的对比结果

## Files Likely Touched

- .gsd/milestones/M003-dh8y4a/slices/S02/S02-UAT.md
