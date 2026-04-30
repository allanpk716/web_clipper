---
estimated_steps: 1
estimated_files: 1
skills_used: []
---

# T02: 将 arxiv URL 加入集成测试脚本

读取 scripts/test_real_urls.py 了解 URL 数据来源逻辑。找到 URL 提取方式（从 docs/exsample/my-things/ 基线数据提取）。将 arxiv URL（https://arxiv.org/abs/2603.00195）添加到测试数据集中，确保脚本识别 arxiv 类型并正确路由。方式：要么在测试脚本中添加硬编码的 arxiv URL，要么在基线数据目录创建一个包含 arxiv URL 的文件。

## Inputs

- `scripts/test_real_urls.py`
- `scripts/integration_report.json`

## Expected Output

- `更新后的 scripts/test_real_urls.py`

## Verification

python scripts/test_real_urls.py --dry-run 确认输出包含 arxiv URL
