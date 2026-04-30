# M003-dh8y4a: M002 遗留项补全

**Vision:** 补全 M002-uwd8l7 验证阶段发现的三个遗留项：缺失的 S03-ASSESSMENT.md、arxiv 适配器未纳入集成测试、UAT 人工抽查未执行。确保里程碑验证类别全部达标。

## Success Criteria

- S03-ASSESSMENT.md 已创建，格式与 S01/S02 一致
- arxiv URL 加入集成测试数据集，全量测试 100% 通过
- 人工抽查至少 5 个 URL（每种适配器 ≥1），主题一致性确认
- 所有抽查结果记录在 S02-UAT.md

## Slices

- [x] **S01: S01** `risk:low` `depends:[]`
  > After this: python scripts/test_real_urls.py 全量通过（含 arxiv），S03-ASSESSMENT.md 格式完整

- [x] **S02: S02** `risk:low` `depends:[]`
  > After this: S02-UAT.md 中记录至少 5 个 URL 的人工抽查结果（每种适配器 ≥1），全部主题一致

## Boundary Map

### S01 (no cross-boundary)

Produces:
  S03-ASSEMENT.md — 补全评估文档
  scripts/integration_report.json — 更新后的集成报告（含 arxiv）
Consumes:
  scripts/test_real_urls.py — 复用现有测试脚本

### S02 → S01

Produces:
  S02-UAT.md — 人工抽查结果记录
Consumes from S01:
  更新后的集成报告 — 抽查样本来源

### S02 (no downstream)

Produces:
  M003 验证类别 UAT 的完成证据
Consumes:
  docs/exsample/my-things/ — 旧内容基线
  scripts/integration_report.json — 新抓取结果
