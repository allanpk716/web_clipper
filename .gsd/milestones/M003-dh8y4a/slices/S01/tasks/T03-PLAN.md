---
estimated_steps: 1
estimated_files: 2
skills_used: []
---

# T03: 执行全量集成测试并更新报告

运行 python scripts/test_real_urls.py 执行全量集成测试（含 arxiv）。确认所有 URL 通过（pass_rate=100%）。验证报告文件更新（integration_report.json + integration_report.md）。

## Inputs

- `scripts/test_real_urls.py`

## Expected Output

- `scripts/integration_report.json`
- `scripts/integration_report.md`

## Verification

python -c "import json; r=json.load(open('scripts/integration_report.json')); print(f'total={r["aggregate"]["total"]} passed={r["aggregate"]["passed"]} pass_rate={r["aggregate"]["pass_rate"]}')"
