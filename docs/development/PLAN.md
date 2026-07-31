# ScholarMind 42 天每日开发计划

## 0. 执行约束

- 时间：2026-07-30 至 2026-09-09。
- 强度：每天 5～6 小时，每周安排一天复盘或缓冲。
- 第 28 天必须形成简历可投递版本，后两周边投递边增强。
- 每天只设一个核心目标；当天未完成时优先缩小功能，不向后无限顺延。
- 每天结束前至少执行格式检查、类型检查、单元测试并记录开发日志。

### 范围优先级

必须完成：

1. Baseline；
2. Source—Evidence—Claim；
3. PostgreSQL + pgvector；
4. PDF RAG；
5. File/Paper Researcher；
6. Claim 与 Citation 验证；
7. 评测、Docker、README 和演示。

候选增强功能只选择一个：

1. 简化版 Gap-driven Research（默认推荐）；
2. GitHub Researcher；
3. 多模态页面分析。

暂缓：

- 完整 DOCX/PPTX；
- Redis、MinIO；
- GraphRAG、A2A；
- Kubernetes；
- 多租户和完整权限；
- 30～50 个大规模 Benchmark；
- 第二个本地模型或多模型路由。

---

# 第一周：Baseline 与工程基础

## Day 1｜7 月 30 日：初始化开发环境

**核心目标：** 在 WSL2 中稳定运行上游项目。

**状态：** ✅ 已于 2026-07-29 提前完成。详细记录见
[`daily/2026-07-29-day-01.md`](daily/2026-07-29-day-01.md)。

任务：

- [x] Fork 并克隆 Open Deep Research；
- [x] 固定上游 Commit，配置 `origin` 和 `upstream`；
- [x] 使用 `uv` 安装 Python 3.11 和项目依赖；
- [x] 创建独立 vLLM 环境，在 D 盘部署 Qwen3-14B-AWQ；
- [x] 配置本地 OpenAI 兼容 API，并将模型并发限制为 1；
- [x] 配置搜索 API（无 Key 时先用 `SEARCH_API=none` 完成本地模型验收）；
- [x] 启动 LangGraph Server 和 Studio；
- [x] 保存第一次完整运行 Trace。

产出：

- 可运行的本地仓库；
- `docs/upstream.md`；
- `services/local-llm/` 启动脚本、固定依赖和冒烟测试；
- 初始环境说明。

验收：

- Studio 能提交研究问题并生成报告；
- README 记录上游仓库和 Commit；
- 密钥未进入 Git。

## Day 2｜7 月 31 日：理解 Baseline 状态图

**核心目标：** 能脱离源码解释系统工作流。

**状态：** ✅ 已于 2026-07-30 提前完成。详细记录见
[`daily/2026-07-30-day-02.md`](daily/2026-07-30-day-02.md)。

任务：

- [x] 阅读主图、状态、配置、Prompt 和工具模块；
- [x] 梳理 Clarify、Brief、Supervisor、Researcher、Compression、Writer；
- [x] 标出每个状态字段的写入者与读取者；
- [x] 记录并行 Researcher 和 Reducer 的工作方式。

产出：

- [x] `docs/baseline_architecture.md`；
- [x] Baseline Mermaid 流程图；
- [x] 状态字段流向表。

验收：

- [x] 能解释 Supervisor 为什么委派子任务；
- [x] 能解释 Researcher 为什么压缩结果；
- [x] 能说明异常和 Token 超限的处理路径。

## Day 3｜7 月 31 日：建立 Baseline Runner（✅ 已完成）

**核心目标：** 让后续改进都有可重复对照。

任务：

- [x] 准备 8 个固定测试问题；
- [x] 编写支持续跑与重跑的批量执行脚本；
- [x] 记录报告、来源、延迟、Token、搜索次数和工具调用数；
- [x] 为运行结果建立 JSONL Schema。

产出：

- [x] `scripts/run_baseline.py`；
- [x] `evaluation/cases/baseline.jsonl`；
- [x] `evaluation/results/day3-qwen3-local-20260731.jsonl`；
- [x] `evaluation/schemas/baseline_result.schema.json`。

验收：

- [x] 一条命令可批量运行；
- [x] 中断后不覆盖历史结果；
- [x] 每个任务拥有稳定 `case_id`。

## Day 4｜7 月 31 日：Baseline 错误分析（✅ 已完成）

**核心目标：** 定义 ScholarMind 真正要解决的问题。

任务：

- [x] 人工检查 32 条事实结论；
- [x] 标记引用不存在、引用不支持、时间错误、数字错误和范围遗漏；
- [x] 计算 Citation Precision、Citation Coverage、平均来源数和平均耗时；
- [x] 整理三个最优先问题。

产出：

- [x] `docs/baseline_error_analysis.md`；
- [x] `evaluation/labels/baseline.csv`；
- [x] `evaluation/results/day4-summary-20260731.json`。

验收：

- [x] 每个核心改造项都能对应到一个 Baseline 缺陷；
- [x] 结论均可回溯到固定 case、原始输出、人工标签和证据 URL。

## Day 5｜8 月 3 日：隔离子研究任务失败

**核心目标：** 一个子任务失败不终止整个研究。

任务：

- 移除无条件结束异常的逻辑；
- 对并行子任务保留成功结果和失败状态；
- 为 Token、Rate Limit、Tool Error 和未知异常定义最小处理策略；
- 增加部分成功、全部失败和单工具失败测试。

产出：

- 失败隔离实现；
- `tests/unit/test_researcher_failures.py`。

验收：

- 部分成功时仍能生成 PartialResult；
- 错误原因进入结构化状态；
- 单元测试稳定通过。

## Day 6｜8 月 4 日：建立 ScholarMind 模块骨架

**核心目标：** 在保持 Baseline 可运行的前提下创建增强架构。

任务：

- 创建 `graph`、`models`、`storage`、`ingestion`、`retrieval`、`researchers`、`evaluation`；
- 添加 Baseline Adapter；
- 定义统一 Settings；
- 设置 Ruff、mypy、pytest 和 pre-commit。

产出：

- `src/scholarmind/`；
- 基础配置和质量工具。

验收：

- 上游 Baseline 仍然可运行；
- 新模块可独立导入；
- CI 可执行最小测试。

## Day 7｜8 月 5 日：第一周复盘与架构冻结

**核心目标：** 冻结 `v0.1.0` 技术边界。

任务：

- 绘制 ScholarMind 目标图；
- 明确哪些数据存在图状态、数据库和文件系统；
- 编写 ADR；
- 清理第一周遗留问题；
- 将可选项移入 Backlog。

产出：

- `docs/architecture_v1.md`；
- `docs/adr/001-evidence-first.md`；
- 第一周演示。

验收：

- Baseline Ready；
- 后续两周不再进行大规模目录重构；
- 每个节点有输入、输出、失败和持久化策略。

---

# 第二周：Source—Evidence—Claim 闭环

## Day 8｜8 月 6 日：实现 SourceRecord

**核心目标：** 统一网页、论文和上传文件来源。

任务：

- 定义 SourceRecord 和 SourceType；
- 实现 URL 规范化、内容 Hash、稳定 ID；
- 设计权威度、新鲜度和元数据字段；
- 编写序列化与去重测试。

验收：

- 同一 URL 不重复；
- 相同内容不同 URL 可被识别；
- 所有来源均能 JSON 序列化。

## Day 9｜8 月 7 日：实现 EvidenceItem

**核心目标：** 每条证据都可回到原始位置。

任务：

- 定义文本、表格、图、公式和代码 Evidence；
- PDF 使用页码与 Bounding Box；
- 网页使用 URL、标题和章节；
- 为 Evidence 生成稳定 ID 和内容 Hash。

验收：

- Evidence 必须关联 Source；
- Evidence 保留定位信息；
- 无法定位的内容不能标为精确证据。

## Day 10｜8 月 8 日：实现 Claim 与 Citation

**核心目标：** 报告由结构化 Claim 驱动。

任务：

- 定义 Fact、Number、Temporal、Comparison、Inference Claim；
- 建立 Claim 与 Evidence 多对多关系；
- 定义 Supported、Partial、Contradicted、Insufficient；
- 定义 Citation Renderer 输入。

验收：

- 事实 Claim 没有 Evidence 时不能进入最终报告；
- Inference 必须明确标记；
- 数字和时间 Claim 有专门校验字段。

## Day 11｜8 月 9 日：模型测试与 Fixture

**核心目标：** 在接入 Agent 前稳定领域模型。

任务：

- 编写 Source、Evidence、Claim、Citation 单元测试；
- 准备网页、PDF、论文和反例 Fixture；
- 测试非法页码、重复 Evidence、空引用和反序列化；
- 将模型覆盖率提升至 90% 左右。

验收：

- 模型测试全部通过；
- Fixture 可供后续检索与 Verifier 复用。

## Day 12｜8 月 10 日：PostgreSQL 与 pgvector

**核心目标：** 将实体移出 LangGraph 大状态。

任务：

- 使用 Docker Compose 启动 PostgreSQL + pgvector；
- 添加 SQLAlchemy、asyncpg 和 Alembic；
- 建立 Job、Task、Source、Evidence、Claim、Link 表；
- Graph State 只保存实体 ID 和计数器。

验收：

- Alembic 可升级和回滚；
- 可从 Claim 查询 Evidence；
- Checkpoint 中不保存大段原始正文。

## Day 13｜8 月 11 日：网页来源注册与快照

**核心目标：** 将 Baseline 搜索结果转为真实 Source。

任务：

- 注册 URL、标题、正文、抓取时间和 Hash；
- 保存经过清理的正文或 Markdown；
- 去除脚本、追踪参数和危险 HTML；
- 处理重复 URL 和抓取失败。

验收：

- 搜索结果均有 Source ID；
- 重复网页不会重复入库；
- 抓取失败不会中断整项研究。

## Day 14｜8 月 12 日：网页 Evidence 闭环

**核心目标：** 跑通第一个端到端证据流程。

任务：

- 按标题和段落切分网页；
- 相关性筛选后提取 Evidence；
- 生成 Claim 并关联 Evidence；
- 使用 Citation Renderer 生成 URL 引用；
- 执行第二周集成测试。

验收：

```text
Web Search → Source → Evidence → Claim → Citation → Report
```

- 至少三个测试问题端到端通过；
- 引用 URL 不由 Writer 自行生成。

---

# 第三周：PDF RAG 与混合检索

## Day 15｜8 月 13 日：安全文件上传

**核心目标：** 支持研究文件进入系统。

任务：

- 实现上传、读取和删除接口；
- 校验文件类型、大小和 SHA-256；
- 使用 UUID 存储，原文件名仅作元数据；
- v0.1 只承诺 PDF。

验收：

- 重名文件不覆盖；
- 相同 Hash 可识别；
- 危险类型被拒绝；
- 解析状态可查询。

## Day 16｜8 月 14 日：Docling PDF 解析

**核心目标：** 获得带页码和结构的 PDF 内容。

任务：

- 封装 DocumentParser 接口；
- 解析段落、标题、表格、图题和公式；
- 保存页码及可用 Bounding Box；
- 建立解析失败状态。

验收：

- 三种不同布局论文可解析；
- PDF 可导出结构化 Markdown；
- 表格和图题可独立读取。

## Day 17｜8 月 15 日：结构化分块

**核心目标：** 避免固定长度粗暴切分。

任务：

- 按章节、段落、表格和图题分块；
- 对过长块执行带重叠二次切分；
- 保留页码、章节路径和相邻块；
- 建立 Chunk Fixture。

验收：

- Chunk 不跨越无关章节；
- 每个 Chunk 能回溯 Source 和页码；
- 表格上下文完整。

## Day 18｜8 月 16 日：PDF 解析复盘

**核心目标：** 修复真实文档中的高频解析问题。

任务：

- 测试双栏论文、扫描 PDF、复杂表格和公式；
- 记录成功率、耗时和失败原因；
- 只修复影响核心演示的问题；
- 形成 PDF 支持边界说明。

验收：

- 至少 10 个 PDF 测试样本；
- 失败可解释；
- 不承诺尚未验证的格式。

## Day 19｜8 月 17 日：Dense Retrieval

**核心目标：** 建立 pgvector 语义检索。

任务：

- 选择 Embedding 模型并固定版本；
- 批量生成和缓存 Embedding；
- 实现文件过滤与跨文件检索；
- 返回相似度、页码、章节和 Chunk ID。

验收：

- 1000 个 Chunk 可检索；
- 有延迟记录；
- 相同 Chunk 不重复计算 Embedding。

## Day 20｜8 月 18 日：Sparse Retrieval

**核心目标：** 找回专有名词、版本号和精确变量。

任务：

- 选择 PostgreSQL FTS 或 `rank_bm25`；
- 明确将实现命名为 FTS 或 BM25；
- 支持文件和元数据过滤；
- 准备精确关键词测试。

验收：

- 在名称、缩写、版本和变量测试中优于 Dense；
- 结果带完整定位信息。

## Day 21｜8 月 19 日：RRF 与 Reranker

**核心目标：** 完成 PDF 混合检索。

任务：

- 实现 Dense + Sparse 的 RRF；
- 对 Top-30 候选进行 Rerank；
- 比较 Dense、Sparse、Hybrid、Hybrid+Reranker；
- 计算 Recall@5、MRR 和平均延迟。

验收：

- Hybrid+Reranker 的 MRR 提升；
- Recall@5 不明显下降；
- PDF RAG Ready。

---

# 第四周：Researcher、Claim 与简历版本

## Day 22｜8 月 20 日：File Researcher

**核心目标：** Agent 能主动检索上传文件。

任务：

- 暴露 Search、Read Page、Read Section、Read Table 工具；
- 输出 Source ID、Evidence ID、摘要和未解决问题；
- 限制工具调用次数；
- 测试纯本地文件研究。

验收：

- 比较三篇上传论文；
- 找到方法与实验部分；
- 不依赖网页搜索；
- 输出页码级 Evidence。

## Day 23｜8 月 21 日：Paper Researcher 搜索层

**核心目标：** 搜索并规范化论文元数据。

任务：

- 接入 arXiv 和一个论文元数据源；
- 统一标题、作者、年份、摘要和 DOI/arXiv ID；
- 处理版本、重复论文和缺失 PDF；
- 关联可用代码仓库链接。

验收：

- 返回至少五篇代表论文；
- 标题、年份和作者可验证；
- 不把搜索摘要当作论文正文 Evidence。

## Day 24｜8 月 22 日：Paper Researcher 分析层

**核心目标：** 从论文原文提取结构化研究结果。

任务：

- 提取 Problem、Method、Dataset、Metric、Result、Limitation；
- 重要字段必须绑定 Evidence；
- 复用 PDF Parser 与 Retrieval；
- 生成论文间结构化比较。

验收：

- 方法、数字和局限来自正文证据；
- 关键结论有页码；
- 论文元数据与正文来源不混淆。

## Day 25｜8 月 23 日：Researcher 对比与修复

**核心目标：** 证明专用 Researcher 有实际价值。

任务：

- 对相同问题比较 Web、File 和 Paper Researcher；
- 记录来源质量、Evidence 数、页码准确率、Token 和延迟；
- 修复最影响结果的路由或 Prompt 问题；
- 不增加新 Researcher。

验收：

- 专用 Researcher 的无关搜索更少；
- Evidence 定位更准确；
- 有一张对比表。

## Day 26｜8 月 24 日：Claim Generator

**核心目标：** 写报告前先生成证据关联 Claim。

任务：

- 从 Research Brief、Task 和 Evidence 生成 15～30 条 Claim；
- 区分事实、数字、时间、比较和推断；
- 删除没有 Evidence 的事实 Claim；
- 保存生成理由和 Evidence ID。

验收：

- 数字 Claim 引用含数字 Evidence；
- 时间 Claim 引用含日期 Evidence；
- Writer 不直接创造新事实。

## Day 27｜8 月 25 日：Claim-Evidence Verifier

**核心目标：** 判断 Evidence 是否真正支持 Claim。

任务：

- 实现 Supported、Partial、Contradicted、Insufficient；
- 检查主体、数值、时间、因果和泛化；
- 准备 30 个正负样例；
- 支持修订过度表述的 Claim。

验收：

- 人工标注样例准确率达到初步可用水平；
- 矛盾和证据不足不会进入最终事实段落；
- 验证过程可解释。

## Day 28｜8 月 26 日：Citation 与简历可投递版本

**核心目标：** 完成第一版公开演示。

任务：

- Citation 由 Claim → Evidence → Source 确定；
- PDF 引用包含页码，网页包含 URL；
- 构建最简证据查看页面；
- 更新 README、架构图和评测数据；
- 录制 1～2 分钟短演示。

验收：

- 点击引用可看到证据原文；
- 至少三个端到端案例稳定通过；
- 项目可写入简历；
- 从今天开始投递。

---

# 第五周：可靠性、评测与一个增强功能

## Day 29｜8 月 27 日：来源与 Evidence 去重

**核心目标：** 降低重复上下文和 Token。

任务：

- URL 规范化、内容 Hash、文本重复和语义近重复；
- 冲突时优先权威、更新且定位完整的 Evidence；
- 对比去重前后的 Token 与信息损失。

验收：

- 重复 Evidence 明显减少；
- 关键来源不会被误删；
- 有对比数据。

## Day 30｜8 月 28 日：预算、限流与缓存

**核心目标：** 控制任务成本。

任务：

- 定义搜索、工具、Token、时间和并发预算；
- 缓存搜索结果、网页正文、Embedding 和验证结果；
- 达到预算后返回未完成原因；
- 记录每个 Job 的资源使用。

验收：

- 相同查询可命中缓存；
- 超预算时优雅停止；
- 并发任务数量受控。

## Day 31｜8 月 29 日：Checkpoint 与 PartialResult

**核心目标：** 失败后不从头重跑。

任务：

- 为关键节点设置持久化边界；
- 设计幂等 Task；
- 已完成任务恢复后不重复执行；
- API 返回明确 ErrorState。

验收：

- 中断后可继续；
- 单个 Researcher 崩溃不丢失其他结果；
- PartialResult 可生成带限制说明的报告。

## Day 32｜8 月 30 日：增强功能设计与最小实现

**核心目标：** 只选择一个差异化功能。

默认选择简化版 Gap-driven：

- 根据 `expected_evidence` 计算覆盖率；
- 识别缺少论文、源码、实验或官方文档；
- 生成下一轮定向查询；
- 连续两轮无新增 Evidence 时停止。

若目标岗位不同，可替换为 GitHub Researcher 或视觉页面选择器，但不可同时进行。

验收：

- 新功能不破坏现有闭环；
- 有清晰输入、输出和停止条件。

## Day 33｜8 月 31 日：增强功能实验

**核心目标：** 证明增强功能有效，而不是只增加代码。

任务：

- 选择 8～10 个适合的问题；
- 与无增强版本比较；
- 记录质量、Token、搜索次数和延迟；
- 对无提升场景如实记录。

验收：

- 能得出是否保留该功能的结论；
- 没有收益时允许从 v0.1 移除。

## Day 34｜9 月 1 日：正式评测集

**核心目标：** 建立小而可信的秋招评测。

任务：

- 扩展至 12～20 个任务；
- 覆盖 Web、Paper、File 和混合研究；
- 标注关键 Evidence 与事实 Claim；
- 冻结测试集版本。

验收：

- 测试任务和开发 Prompt 分离；
- 每个任务有人工可核验标准；
- 评测可重复执行。

## Day 35｜9 月 2 日：三组消融实验

**核心目标：** 形成简历可量化结果。

实验组：

```text
A：Open Deep Research Baseline
B：Evidence-first + Hybrid Retrieval
C：完整 ScholarMind + Claim Verifier
```

指标：

- Citation Precision；
- Citation Coverage；
- Unsupported Claim Rate；
- Recall@5、MRR；
- Token、搜索次数、平均与 p95 延迟。

验收：

- 生成可复现 JSONL；
- README 中只写真实测量结果；
- Evaluation Ready。

---

# 第六周：产品化、发布与面试准备

## Day 36｜9 月 3 日：最小 Agent Trace

**核心目标：** 面试时能解释 Agent 在做什么。

任务：

- 记录 Job、Task、Researcher、Tool、Verifier 层级；
- 展示模型、Token、延迟、错误和重试；
- 记录 Evidence、Claim 和 Gap 数；
- 优先复用 LangSmith/LangGraph Trace。

验收：

- 能追踪一次完整研究；
- 能定位失败节点；
- 不建设复杂自研可观测平台。

## Day 37｜9 月 4 日：证据查看界面

**核心目标：** 让演示者看见可信研究闭环。

最低界面：

- 左侧：研究计划与 Agent 时间线；
- 中间：最终报告；
- 右侧：Source、Evidence、Citation；
- 点击引用显示页码、章节、原文和验证状态。

验收：

- 核心演示流程不需要打开数据库；
- 页面异常时不影响后端结果保存。

## Day 38｜9 月 5 日：Docker Compose

**核心目标：** 新环境可以复现项目。

任务：

- 容器化 API、数据库和前端；
- 添加健康检查与持久化卷；
- 编写 `.env.example`；
- 从空环境执行一次安装。

验收：

- 一条 Compose 命令启动核心服务；
- 密钥不写入镜像；
- README 命令与实际一致。

## Day 39｜9 月 6 日：故障注入与发布阻断问题

**核心目标：** 修复会破坏演示的可靠性问题。

测试：

- 搜索超时；
- 网页不可访问；
- PDF 解析失败；
- 非法结构化输出；
- PostgreSQL 短暂失败；
- Rate Limit 和 Token 超限。

验收：

- 单工具失败不导致全局失败；
- 前端显示失败原因；
- 已完成结果不重复执行。

## Day 40｜9 月 7 日：文档与架构材料

**核心目标：** 仓库对面试官友好。

任务：

- 完善 README；
- 编写架构、数据流、评测和部署文档；
- 绘制系统架构图和 Claim-Evidence 流程图；
- 添加真实截图和结果表；
- 说明上游来源和个人贡献。

验收：

- 新读者十分钟内理解项目；
- 所有功能描述与实际实现一致；
- 不夸大未完成能力。

## Day 41｜9 月 8 日：演示视频与面试材料

**核心目标：** 将工程成果转化为秋招材料。

任务：

- 录制 3～5 分钟演示视频；
- 准备一页项目介绍；
- 编写简历项目描述；
- 准备架构、难点、权衡、指标和失败案例问答；
- 完整演练一次现场 Demo。

验收：

- 视频无密钥和私人数据；
- 五分钟内讲清问题、方案、贡献和结果；
- 准备网络不可用时的离线演示结果。

## Day 42｜9 月 9 日：发布 v0.1.0

**核心目标：** 发布稳定、诚实、可复现的版本。

任务：

- 运行全部测试与最终 Smoke Test；
- 清理临时文件、密钥、无效分支和过时文档；
- 固定依赖版本；
- 创建 `v0.1.0` Tag 和 GitHub Release；
- 将未完成功能转为 Issues/Milestone；
- 记录下一版本路线。

验收：

- 核心演示连续运行三次；
- Docker 安装路径验证通过；
- README、评测和视频链接有效；
- Release 内容与当前代码一致。

---

# 每日工作模板

开始前：

```text
1. 选择当天唯一核心目标
2. 写出可验证的完成条件
3. 将增强需求放入 Backlog
```

结束前：

```text
1. 运行 Ruff、mypy、pytest
2. 执行当天 Smoke Test
3. 更新开发日志
4. 提交一个语义清晰的 Commit
5. 记录未完成项和次日第一个动作
```

# 时间失控时的删减顺序

```text
完整多模态
→ GitHub Researcher
→ Gap-driven
→ Redis / MinIO
→ DOCX / PPTX
→ 复杂前端
```

以下内容不能删除：

```text
Evidence 数据模型
→ PDF 混合检索
→ Claim 验证
→ 精确引用
→ 正式评测
→ README 与演示
```
