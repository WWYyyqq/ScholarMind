# ScholarMind 开发计划与日志

本目录统一保存 ScholarMind 的开发计划、每日工程记录和阶段复盘。代码实现、
环境变更、测试结果与已知限制应在当天结束前写入日志，避免只保留终端历史或
口头结论。

当前有效文档路径以 [文档中心](../README.md) 为准；每日历史日志会保留当时的文件名和操作记录，因此其中个别代码路径可能是移动前的旧路径。

## 目录

- [`PLAN.md`](PLAN.md)：42 天总体开发计划、每日目标与验收标准。
- [`daily/`](daily/)：每日开发日志。
- [`daily/TEMPLATE.md`](daily/TEMPLATE.md)：新日志模板。
- [`supplemental/`](supplemental/)：不改变 42 天 Day 状态的专项工程记录。

## 每日日志索引

| Day | 日期 | 核心目标 | 状态 | 日志 | 验收 Commit |
| --- | --- | --- | --- | --- | --- |
| Day 1 | 2026-07-29 | 在 WSL2 中稳定运行本地 Baseline | ✅ 完成 | [详细日志](daily/2026-07-29-day-01.md) | `36a1898` |
| Day 2 | 2026-07-30 | 理解 Baseline 状态图 | ✅ 完成 | [详细日志](daily/2026-07-30-day-02.md) | `aa2b04a` |
| Day 3 | 2026-07-31 | 建立可重复 Baseline Runner | ✅ 完成 | [详细日志](daily/2026-07-31-day-03.md) | `0e5c694` |
| Day 4 | 2026-07-31 | 完成 Baseline 错误分析 | ✅ 完成 | [详细日志](daily/2026-07-31-day-04.md) | `d9b9b59` |
| Day 5 | 2026-08-02 | 失败隔离与结构化证据门 | ✅ 提前完成 | [详细日志](daily/2026-08-02-day-05.md) | 待 PR 合并 |
| Day 6 | 2026-08-04 | 本地 Qwen Embedding + pgvector 真实闭环 | ✅ 完成 | [详细日志](daily/2026-08-04-day-06.md) | 待 PR 合并 |

## 专项记录

| 日期 | 主题 | 状态 | 记录 |
| --- | --- | --- | --- |
| 2026-08-01 | 97 篇本地论文数据预处理 | ✅ 完成并通过独立验证 | [详细日志](supplemental/2026-08-01-paper-dataset-preparation.md) · [标注手册](../evaluation/paper-dataset/silver-to-gold.md) |
| 2026-08-02 | 证据模型、pgvector、检索、File Researcher 与 CI 基础 | ✅ 代码、单测与真实 pgvector CI 通过 | [Day 5 日志](daily/2026-08-02-day-05.md) · [架构说明](../architecture/evidence-pipeline.md) · [Silver 七天计划](../evaluation/paper-dataset/silver-review-plan.md) |

## 记录规范

每天的日志至少包含：

1. 当日目标和完成结论；
2. 开始时的代码、环境和服务状态；
3. 按时间或阶段排列的工作记录；
4. 执行过的关键命令；
5. 新增或修改的文件；
6. 遇到的问题、根因、排查证据和解决方案；
7. 格式、类型、单元、集成或端到端测试结果；
8. CPU、内存、GPU、磁盘或外部 API 等资源影响；
9. 安全检查和密钥处理情况；
10. 尚未完成的边界、风险和下一天的输入。

日志只记录可公开的信息。真实 API Key、访问令牌、个人凭据、`.env` 内容、
未脱敏的用户目录和其他敏感信息不得提交到 Git。

## 文件命名

每日文件使用：

```text
YYYY-MM-DD-day-NN.md
```

如果同一天存在补充工作，继续更新同一文件并在“追加记录”中注明时间，不创建
含义不清的 `final-v2`、`new` 或 `latest` 文件。
