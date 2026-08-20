# ScholarMind

ScholarMind 是一个基于
[LangChain Open Deep Research](https://github.com/langchain-ai/open_deep_research)
构建的证据优先研究 Agent。目标是在 42 天内完成一个适合秋招简历、技术面试
演示和后续开源迭代的 `v0.1.0`。

项目强调的不只是“生成一篇报告”，而是让报告中的事实能够沿着下面的链路回到
原始资料：

```text
Research Brief
    ↓
Web / Paper / File Researcher
    ↓
Source → Evidence → Claim
    ↓
Claim-Evidence / Citation Verification
    ↓
带来源、页码和原文定位的研究报告
```

当前 Baseline 在 WSL2 中运行，应用与推理环境彼此隔离，本地模型为
`Qwen3-14B-AWQ`，由 vLLM 提供 OpenAI 兼容 API。上游归属和固定 Commit
记录在 [`docs/project/upstream.md`](docs/project/upstream.md)。

## 当前进度

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| Day 1：环境与本地 Baseline | ✅ 完成并复验 | [详细日志](docs/development/daily/2026-07-29-day-01.md) |
| Day 2：理解 Baseline 状态图 | ✅ 完成 | [架构文档](docs/architecture/baseline.md) · [详细日志](docs/development/daily/2026-07-30-day-02.md) |
| Day 3：可重复 Baseline Runner | ✅ 完成 | [评测说明](evaluation/README.md) · [详细日志](docs/development/daily/2026-07-31-day-03.md) |
| Day 4：Baseline 错误分析 | ✅ 完成 | [错误分析](docs/evaluation/baseline-error-analysis.md) · [详细日志](docs/development/daily/2026-07-31-day-04.md) |
| Day 5：并行失败隔离与证据门 | ✅ 提前完成 | [可靠性与证据流水线](docs/architecture/evidence-pipeline.md) · [详细日志](docs/development/daily/2026-08-02-day-05.md) |
| Day 6：本地语义检索闭环 | ✅ 提前完成 | Qwen3-Embedding-0.6B + PostgreSQL/pgvector · [详细日志](docs/development/daily/2026-08-04-day-06.md) |
| Day 7：全量可恢复索引 | ✅ 提前完成 | 49 篇论文、6,853 条 1024 维向量，支持断点续跑 · [详细日志](docs/development/daily/2026-08-04-day-07.md) |
| Day 8：混合检索与本地重排 | ✅ 加速完成 | BM25 + pgvector + RRF + 质量门 + Qwen Rerank · [详细日志](docs/development/daily/2026-08-04-day-08.md) |
| Day 9：ScholarMind Agent 与 API | ✅ 核心代码完成 | 公共 Research Service + LangGraph API + 三态结构化输出 · [详细日志](docs/development/daily/2026-08-15-day-09.md) |
| Day 10：真实 API 与运行可靠性 | ✅ 本地真实闭环通过 | Runtime Doctor + 启动脚本 + API 冒烟 + 引用噪声/截断 Claim 拦截 · [详细日志](docs/development/daily/2026-08-16-day-10.md) |
| 论文数据预处理（专项） | ✅ 完成并通过独立验证 | [数据说明](docs/evaluation/paper-dataset/README.md) · [Gold 标注手册](docs/evaluation/paper-dataset/silver-to-gold.md) · [详细日志](docs/development/supplemental/2026-08-01-paper-dataset-preparation.md) |
| 证据流水线基础（专项） | ✅ 代码、单测与真实 pgvector CI 通过 | Source/Evidence/Claim/Citation、pgvector、BM25/RRF、File Researcher、Verifier 和自动 CI；不等于后续各 Day 已全部验收 |
| 本地论文向量库 | ✅ development + test 均可检索 | 82 篇论文、10,879 条 1024 维向量；模型/内容哈希校验、断点续传与分区隔离 |
| 本地论文检索 | ✅ 核心闭环完成 | Dense、BM25、RRF、证据质量过滤和本地 Qwen 二阶段重排 |
| Agent/API | ✅ 已真实验收 | CLI 与 LangGraph 共用同一 Research Service；真实 Hybrid+Rerank 请求返回 5/5/5 Evidence/Claim/Citation |
| Web 搜索 | ⏳ 未接入 | 当前使用 `SEARCH_API=none` |
| 简历可投递版本 | 计划 2026-08-26 | Day 28 |
| `v0.1.0` | 计划 2026-09-09 | Day 42 |

## 文档导航

所有说明统一从 [文档中心](docs/README.md) 查找。常用入口：

- [项目总览](docs/project/overview.md)
- [开发计划与日志](docs/development/README.md)
- [可靠性与证据流水线](docs/architecture/evidence-pipeline.md)
- [完整本地运行与故障排查](docs/guides/local-runtime.md)
- [Baseline 评测与论文数据](docs/evaluation/README.md)
- [本地 Qwen3 / vLLM 服务](services/local-llm/README.md)
- [Silver → Gold 人工标注手册](docs/evaluation/paper-dataset/silver-to-gold.md)
- [42 道 Silver 问题七天复核计划](docs/evaluation/paper-dataset/silver-review-plan.md)

## v0.1.0 核心范围

必须完成：

- Open Deep Research Baseline 与可重复评测；
- Source—Evidence—Claim—Citation 数据闭环；
- PostgreSQL + pgvector；
- PDF 解析、混合检索、RRF 与 Reranker；
- File Researcher 与 Paper Researcher；
- Claim-Evidence 与 Citation 验证；
- 证据查看界面、Docker、评测、README 和演示视频。

增强功能只选择一个，默认是简化版 Gap-driven Research。完整 DOCX/PPTX、
GraphRAG、Kubernetes、多租户、第二个本地模型等功能不进入 `v0.1.0`。

## 关键里程碑

| 日期 | 里程碑 | 可交付结果 |
| --- | --- | --- |
| 8 月 5 日 | Baseline Ready | 上游固定、可重复运行、初始评测完成 |
| 8 月 12 日 | Evidence Loop | Source → Evidence → Claim → Citation 跑通 |
| 8 月 19 日 | PDF RAG Ready | 混合检索、Reranker、页码级 Evidence |
| 8 月 26 日 | Resume Ready | 可演示完整流程，写入简历并开始投递 |
| 9 月 2 日 | Evaluation Ready | 正式评测、消融和可靠性数据 |
| 9 月 9 日 | `v0.1.0` | Docker、文档、视频和 GitHub Release |

## 42 天逐日路线图

下面是主页版路线图；每一天的任务、产出和验收条件见
[完整计划](docs/development/PLAN.md)。

| 周 | Day / 日期 | 核心目标 | 状态 |
| --- | --- | --- | --- |
| 1 | Day 1 · 7/30 | 初始化开发环境 | ✅ 已提前完成 |
| 1 | Day 2 · 7/31 | 理解 Baseline 状态图 | ✅ 已提前完成 |
| 1 | Day 3 · 8/1 | 建立 Baseline Runner | ✅ 已提前完成 |
| 1 | Day 4 · 8/2 | Baseline 错误分析 | ✅ 已提前完成 |
| 1 | Day 5 · 8/3 | 隔离子研究任务失败 | ✅ 已提前完成 |
| 1 | Day 6 · 8/4 | 建立 ScholarMind 模块骨架 | ✅ 已加速完成 |
| 1 | Day 7 · 8/5 | 第一周复盘与架构冻结 | ✅ 已加速完成 |
| 2 | Day 8 · 8/6 | 混合检索、质量门与 Qwen Rerank | ✅ 已加速完成 |
| 2 | Day 9 · 8/15 | 接入 ScholarMind Agent 与 LangGraph API | ✅ 已加速完成 |
| 2 | Day 10 · 8/16 | 真实 API 闭环、准确性加固与运行自检 | ✅ 已加速完成 |
| 2 | Day 11 · 8/17 | 语义证据验证与真实 Qwen 全栈验收 | ✅ PR #13 已合并，main CI 通过 |
| 2 | Day 12 · 8/20 | 正式 Review/Gold Schema 与确定性 Gold 构建器 | ✅ PR #13 已合并，main CI 通过 |
| 2 | Day 13 · 8/11 | 网页来源注册与快照 | 计划 |
| 2 | Day 14 · 8/12 | 网页 Evidence 闭环 | 计划 |
| 3 | Day 15 · 8/13 | 安全文件上传 | 计划 |
| 3 | Day 16 · 8/14 | Docling PDF 解析 | 计划 |
| 3 | Day 17 · 8/15 | 结构化分块 | 计划 |
| 3 | Day 18 · 8/16 | PDF 解析复盘 | 计划 |
| 3 | Day 19 · 8/17 | Dense Retrieval | 计划 |
| 3 | Day 20 · 8/18 | Sparse Retrieval | 计划 |
| 3 | Day 21 · 8/19 | RRF 与 Reranker | 计划 |
| 4 | Day 22 · 8/20 | File Researcher | 计划 |
| 4 | Day 23 · 8/21 | Paper Researcher 搜索层 | 计划 |
| 4 | Day 24 · 8/22 | Paper Researcher 分析层 | 计划 |
| 4 | Day 25 · 8/23 | Researcher 对比与修复 | 计划 |
| 4 | Day 26 · 8/24 | Claim Generator | 计划 |
| 4 | Day 27 · 8/25 | Claim-Evidence Verifier | 计划 |
| 4 | Day 28 · 8/26 | Citation 与简历可投递版本 | 计划 |
| 5 | Day 29 · 8/27 | 来源与 Evidence 去重 | 计划 |
| 5 | Day 30 · 8/28 | 预算、限流与缓存 | 计划 |
| 5 | Day 31 · 8/29 | Checkpoint 与 PartialResult | 计划 |
| 5 | Day 32 · 8/30 | 增强功能设计与最小实现 | 计划 |
| 5 | Day 33 · 8/31 | 增强功能实验 | 计划 |
| 5 | Day 34 · 9/1 | 正式评测集 | 计划 |
| 5 | Day 35 · 9/2 | 三组消融实验 | 计划 |
| 6 | Day 36 · 9/3 | 最小 Agent Trace | 计划 |
| 6 | Day 37 · 9/4 | 证据查看界面 | 计划 |
| 6 | Day 38 · 9/5 | Docker Compose | 计划 |
| 6 | Day 39 · 9/6 | 故障注入与发布阻断问题 | 计划 |
| 6 | Day 40 · 9/7 | 文档与架构材料 | 计划 |
| 6 | Day 41 · 9/8 | 演示视频与面试材料 | 计划 |
| 6 | Day 42 · 9/9 | 发布 `v0.1.0` | 计划 |

## 开发原则

1. 先完成端到端闭环，再增加功能宽度；
2. LangGraph State 保存实体 ID，完整数据进入数据库；
3. 每个事实 Claim 必须关联可定位 Evidence；
4. 每天只保留一个核心目标，超时优先缩小功能；
5. 每天结束前执行质量检查并提交详细日志；
6. Day 28 开始投递，不等待所有增强功能完成。

## Local development baseline

### Environment layout

- Pinned upstream Commit:
  `d337ae32ed4ff8f4c6fbe192ba3bf1b2d6610799`
- Application environment: `.venv` (Python 3.11, managed with `uv`)
- Inference environment: `services/local-llm/.venv` (isolated from `.venv`)
- Model weights: `/mnt/d/ScholarMindLocalLLM/models/Qwen3-14B-AWQ-modelscope`
- Local model API: `http://[::1]:8000/v1`
- LangGraph API: `http://127.0.0.1:2024`
- Search on Day 1: disabled with `SEARCH_API=none`

The model weights and download caches stay on drive D. Both virtual environments
are project-specific and do not modify system Python or Conda environments.

### Start the local stack

Open two WSL terminals in the repository.

Terminal 1:

```bash
./services/local-llm/start.sh
```

Wait for `Application startup complete`, then verify the model:

```bash
services/local-llm/.venv/bin/python services/local-llm/smoke_test.py
```

Terminal 2:

```bash
.venv/bin/langgraph dev \
  --config langgraph.local.json \
  --allow-blocking \
  --n-jobs-per-worker 1
```

LangGraph prints the local API, API documentation, and Studio URL. The separate
`langgraph.local.json` deliberately omits the upstream Supabase authentication
block for local development only. Keep `langgraph.json` for authenticated
deployment scenarios.

The local configuration now exposes two independent graphs:

- `Deep Researcher`: upstream-compatible web research baseline;
- `ScholarMind Researcher`: PostgreSQL/pgvector local-paper research with
  evidence, claim verification, and page-level citations.

Before invoking `ScholarMind Researcher`, also start PostgreSQL and the local
embedding/reranking service, then configure the `SCHOLARMIND_*` variables shown
in `.env.example`. A minimal LangGraph API request is:

```bash
curl -sS http://127.0.0.1:2024/runs/wait \
  -H 'Content-Type: application/json' \
  -d '{
    "assistant_id": "ScholarMind Researcher",
    "input": {
      "question": "Which evidence supports the reported method?",
      "retrieval_mode": "hybrid-rerank",
      "verification_mode": "deterministic",
      "top_k": 5
    }
  }'
```

The response always contains `success`, `partial`, or `failed`. A failed
database/model request returns `report: null`; it is never rendered as a
successful research report.

`verification_mode=semantic` 会在数字、否定极性和 Evidence ID 硬门之后调用本地
Qwen3-14B 判断同义改写、关系方向与多段证据。只有达到置信阈值且返回有效证据
索引的 Claim 才能发布；模型超时或输出不合法时保持 fail-closed。安全合成集可用
以下命令复现实验：

```bash
.venv/bin/python scripts/evaluate_claim_verifier.py --mode deterministic
.venv/bin/python scripts/evaluate_claim_verifier.py --mode semantic
```

在 8 条公开合成冒烟案例上，确定性模式为 62.50% accuracy / 100% publication
precision / 33.33% publication recall；本机 Qwen3-14B-AWQ 语义模式实测为
100% / 100% / 100%。该小集合用于覆盖硬门、同义改写、关系反转与多证据回归，
不是论文 Gold 集，也不代表生产事实准确率；正式效果必须在人工复核 Gold 上报告。

Copy `.env.example` to `.env` when configuring a new checkout. Never commit
`.env`; it is ignored by Git.

Development plans and daily engineering logs are organized under
[`docs/development/`](docs/development/README.md). Start with the
[`42-day plan`](docs/development/PLAN.md) and the detailed
[`Day 1 log`](docs/development/daily/2026-07-29-day-01.md).
