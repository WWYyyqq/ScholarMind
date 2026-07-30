# ScholarMind

ScholarMind 是一个基于 [Open Deep Research](https://github.com/langchain-ai/open_deep_research)
构建的证据优先研究 Agent 项目。项目目标是在 6 周内完成一个适合秋招简历、
技术面试演示和后续开源迭代的 `v0.1.0`。

核心流程：

```text
Research Brief
    ↓
Web / Paper / File Researcher
    ↓
Source → Evidence → Claim
    ↓
Claim-Evidence Verification
    ↓
带页码和来源定位的研究报告
```

## 计划周期

- 开始日期：2026-07-30
- 简历可投递版本：2026-08-26（第 28 天）
- `v0.1.0` 发布日期：2026-09-09（第 42 天）
- 预计投入：每天 5～6 小时，每周开发 6 天

完整的逐日任务、验收标准和范围控制见：

> [42 天每日开发计划](development/PLAN.md)

## v0.1.0 核心范围

- Open Deep Research Baseline 与评测框架
- Source—Evidence—Claim 数据模型
- PostgreSQL + pgvector
- PDF 解析和页码级 Evidence
- Dense + Sparse + RRF + Reranker
- File Researcher 与 Paper Researcher
- Claim-Evidence Verifier
- Citation Verifier 与可定位引用
- 简洁的证据查看界面
- Docker Compose、评测报告和演示视频

以下功能不属于 `v0.1.0` 的硬性要求：

- 完整 DOCX/PPTX 支持
- 完整多模态 Researcher
- Kubernetes、多租户和复杂权限系统
- GraphRAG、A2A 和复杂长期记忆
- 大规模本地模型推理

## 关键里程碑

| 日期 | 里程碑 | 可交付结果 |
|---|---|---|
| 8 月 5 日 | Baseline Ready | 上游版本固定、可重复运行、初始评测完成 |
| 8 月 12 日 | Evidence Loop | Source → Evidence → Claim → Citation 跑通 |
| 8 月 19 日 | PDF RAG Ready | 混合检索、Reranker、页码级 Evidence |
| 8 月 26 日 | Resume Ready | 可演示完整流程，可写入简历并开始投递 |
| 9 月 2 日 | Evaluation Ready | 正式评测、消融和可靠性数据 |
| 9 月 9 日 | v0.1.0 | Docker、文档、视频和 GitHub Release |

## 开发原则

1. 先完成端到端闭环，再增加功能宽度。
2. LangGraph State 保存实体 ID，完整数据进入数据库。
3. 每个事实 Claim 必须关联可定位 Evidence。
4. 任何可选功能超期一天，立即从当前版本移除。
5. 第 28 天开始投递，不等待项目完全结束。
