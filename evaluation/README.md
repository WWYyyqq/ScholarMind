# Baseline Evaluation

本目录保存 ScholarMind 的固定评测问题、结果 Schema、原始运行结果和人工标注。
评测数据与实现分开，使后续架构改造能够与同一批 Baseline 结果对照。

## 目录

- `cases/baseline.jsonl`：8 个固定问题，每个问题拥有稳定 `case_id`；
- `schemas/baseline_result.schema.json`：单条运行结果的 JSON Schema；
- `results/`：Runner 逐条追加的原始 JSONL；
- `labels/`：Day 4 人工事实与引用标注。

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
