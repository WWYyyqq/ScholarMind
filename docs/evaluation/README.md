# 评测与论文数据文档

本目录保存评测方法、结果分析和论文数据人工流程。程序直接读取的用例、Schema、标签与结果仍在仓库根目录的 [`evaluation/`](../../evaluation/README.md)，两者不重复。

## Baseline 评测

- [评测资产、Runner 命令和结果字段](../../evaluation/README.md)
- [Day 4 Baseline 错误分析](baseline-error-analysis.md)

## 论文数据集

- [97 篇 PDF 的数据预处理说明](paper-dataset/README.md)
- [Silver → Gold 人工标注操作手册](paper-dataset/silver-to-gold.md)
- [42 道 Silver 问题七天人工复核计划](paper-dataset/silver-review-plan.md)
- [人工复核记录空模板](paper-dataset/templates/review-record.template.json)
- [Gold 问题空模板](paper-dataset/templates/gold-question.template.json)
- [正式 Review Schema](../../evaluation/schemas/paper_review.schema.json)
- [正式 Gold Schema](../../evaluation/schemas/paper_gold_question.schema.json)

真实 PDF、解析语料、逐题 Review 和 Gold 数据均不得提交到公开仓库。
