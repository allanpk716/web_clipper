# S01: 补全 S03 评估文档与集成测试覆盖

**Goal:** 创建 S03-ASSESSMENT.md，将 arxiv URL 加入集成测试数据集，重新执行全部集成测试并生成更新报告
**Demo:** python scripts/test_real_urls.py 全量通过（含 arxiv），S03-ASSESSMENT.md 格式完整

## Must-Haves

- S01-SUCCESS:\n- S03-ASSESSMENT.md 创建，verdict=PASS，包含所有测试类别\n- 集成测试脚本支持 arxiv URL\n- 全量集成测试通过，pass_rate=100%\n- 报告文件更新（integration_report.json + .md）

## Proof Level

- This slice proves: full

## Integration Closure

S01 独立完成，无跨 slice 依赖。产出文件供 S02 抽查使用。

## Verification

- 更新后的集成报告包含 arxiv 类型，为后续里程碑提供完整基线。

## Tasks

- [x] **T01: 创建 M002 S03-ASSESSMENT.md** `est:10min`
  读取 S01-ASSESSMENT.md 和 S02-ASSESSMENT.md 了解格式。基于 S03-SUMMARY.md 中的验证结果和 S03-UAT.md 中的检查项，创建 S03-ASSESSMENT.md，verdict=PASS，包含所有测试类别（smoke test、路由、集成、错误处理等）。写入路径：.gsd/milestones/M002-uwd8l7/slices/S03/S03-ASSESSMENT.md
  - Files: `.gsd/milestones/M002-uwd8l7/slices/S03/S03-ASSESSMENT.md`
  - Verify: cat .gsd/milestones/M002-uwd8l7/slices/S03/S03-ASSESSMENT.md | head -5 确认文件存在且格式正确

- [x] **T02: 将 arxiv URL 加入集成测试脚本** `est:15min`
  读取 scripts/test_real_urls.py 了解 URL 数据来源逻辑。找到 URL 提取方式（从 docs/exsample/my-things/ 基线数据提取）。将 arxiv URL（https://arxiv.org/abs/2603.00195）添加到测试数据集中，确保脚本识别 arxiv 类型并正确路由。方式：要么在测试脚本中添加硬编码的 arxiv URL，要么在基线数据目录创建一个包含 arxiv URL 的文件。
  - Files: `scripts/test_real_urls.py`
  - Verify: python scripts/test_real_urls.py --dry-run 确认输出包含 arxiv URL

- [x] **T03: 执行全量集成测试并更新报告** `est:20min`
  运行 python scripts/test_real_urls.py 执行全量集成测试（含 arxiv）。确认所有 URL 通过（pass_rate=100%）。验证报告文件更新（integration_report.json + integration_report.md）。
  - Files: `scripts/integration_report.json`, `scripts/integration_report.md`
  - Verify: python -c "import json; r=json.load(open('scripts/integration_report.json')); print(f'total={r["aggregate"]["total"]} passed={r["aggregate"]["passed"]} pass_rate={r["aggregate"]["pass_rate"]}')"

## Files Likely Touched

- .gsd/milestones/M002-uwd8l7/slices/S03/S03-ASSESSMENT.md
- scripts/test_real_urls.py
- scripts/integration_report.json
- scripts/integration_report.md
