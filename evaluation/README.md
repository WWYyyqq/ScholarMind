# Baseline Evaluation

本目录保存 ScholarMind 的固定评测问题、结果 Schema、原始运行结果和人工标注。
评测数据与实现分开，使后续架构改造能够与同一批 Baseline 结果对照。


人类可读的评测方法、错误分析和论文数据说明统一从 [评测文档索引](../docs/evaluation/README.md) 进入。
## 目录

- `cases/baseline.jsonl`：8 个固定问题，每个问题拥有稳定 `case_id`；
- `schemas/baseline_result.schema.json`：单条运行结果的 JSON Schema；
- `results/`：Runner 逐条追加的原始 JSONL；
- `labels/`：Day 4 人工事实与引用标注。
- [`docs/evaluation/paper-dataset/templates/`](../docs/evaluation/paper-dataset/templates/)：论文 Silver → Gold 标注所用的公开空模板。
- `claim-verifier/cases.synthetic.jsonl`：不含私有论文内容的 8 个 Claim–Evidence
  语义验证回归案例。

## 论文 Silver → Gold 标注

程序生成的论文问题只是 Silver 候选，必须人工查阅 PDF、复核问题/答案/证据并处理冲突后，才能形成 Gold。字段与判定规则见 [Silver → Gold 人工标注手册](../docs/evaluation/paper-dataset/silver-to-gold.md)，42 道题的每日工作量见 [七天人工复核执行计划](../docs/evaluation/paper-dataset/silver-review-plan.md)。

公开仓库只保存规范和虚构模板；真实论文内容、逐题审阅记录及 Gold 数据保存在本地私有目录。

找到原始数据集输出目录后，可一次性冻结输入并创建两轮盲审工作区：

```bash
.venv/bin/python scripts/prepare_silver_review.py \
  --dataset "<DATASET_OUTPUT>" \
  --output "<ANNOTATION_ROOT>/paper-eval-v1"
```

脚本严格要求当前 42 题版本（19 摘要题、23 方法题），记录所有证据输入哈希，
生成 5/12/13/12 批次、两轮 ID-only 队列和 42 个空 Review 记录。输出目录已存在
时会拒绝覆盖；它不会修改 Silver、PDF 或解析语料。

两轮人工复核与冲突裁决完成后构建 Gold：

```bash
.venv/bin/python scripts/build_gold_dataset.py \
  --dataset "<DATASET_OUTPUT>" \
  --workspace "<ANNOTATION_ROOT>/paper-eval-v1" \
  --gold-version paper-gold-v1
```

构建器使用正式 Review/Gold Schema，逐项核对冻结 SHA-256、ID、来源、两轮协议和
最终 resolution。`edit` 的页码、block 顺序、PDF bbox 与归一化 bbox 从
`documents/*.json` 重算；`answer` 不等于选中原文、存在未裁决记录或来源被修改时
立即停止且不生成新聚合文件。已有生成文件默认拒绝覆盖；仅在明确重建时使用
`--replace-generated`。真实 Review 与 Gold 始终保存在仓库外。

Claim Verifier 的可重复合成评测：

```bash
.venv/bin/python scripts/evaluate_claim_verifier.py --mode deterministic
.venv/bin/python scripts/evaluate_claim_verifier.py --mode semantic
```

2026-08-17 在本机 Qwen3-14B-AWQ 上的真实固定集结果：

| 模式 | 分类准确率 | 发布精确率 | 发布召回率 |
| --- | ---: | ---: | ---: |
| Deterministic | 62.50% | 100.00% | 33.33% |
| Semantic | 100.00% | 100.00% | 100.00% |

这 8 条是用于代码回归的公开合成冒烟案例，不是私有论文 Gold；不得据此声称最终
问答系统在真实论文上的事实准确率为 100%。

## 运行

先启动本地模型：

```bash
./services/local-llm/start.sh
```

另开终端执行：

```bash
.venv/bin/python scripts/run_baseline.py \
  --run-id day3-qwen3-local \
  --output evaluation/results/day3-qwen3-local.jsonl
```

Runner 串行执行用例，适配 RTX 3090 Ti 的单研究单元限制。每完成一个用例就
追加一行、刷新并同步到磁盘；同一 `run_id` 与 `case_id` 已存在时默认跳过，
因此中断后重复同一命令可以安全续跑。需要保留新的重复实验时，使用新的
`run_id` 和输出文件；`--rerun` 只用于明确需要在同一文件中追加新 attempt 的
场景。

只验证用例和 CLI、不调用模型：

```bash
.venv/bin/python scripts/run_baseline.py --dry-run
```

## 结果字段

每行记录：

- 稳定的 `case_id`、实验 `run_id`、记录 `record_id`；
- Thread ID 和 LangGraph 根 Run ID；
- 完整问题、最终报告、抽取出的来源 URL；
- 运行配置，但不记录 API Key；
- 总耗时及节点耗时；
- LLM 调用数、输入/输出 Token；
- 工具调用、搜索调用和 Researcher 数量；
- `success`、`report_error` 或 `failed` 状态及错误。

`SEARCH_API=none` 的结果只能验证图和本地模型兼容性。来源存在、引用支持和事实
正确性必须通过 `labels/` 中的人工标注判断。
