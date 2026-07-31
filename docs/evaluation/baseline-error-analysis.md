# Open Deep Research Baseline 错误分析

导航：[文档中心](../README.md) · [评测与论文数据](README.md) · [Baseline 架构](../architecture/baseline.md)

## 1. 结论

本次评测使用本地 `Qwen3-14B-AWQ`、vLLM 0.26.0 和
`SEARCH_API=none`，对8个固定问题运行 Open Deep Research Baseline，并人工
核验32条事实结论。

8个用例在图层面都生成了最终报告，但8个都被 Runner 标记为 `degraded`：模型
请求了未配置的 `tavily_search`，实际搜索次数为0，Researcher 没有完成
Compression，Supervisor 又因当前无条件异常分支提前结束研究。Writer 随后仅凭
模型已有知识生成带 URL 的报告。因此“状态为 success”只表示 Writer 返回文本，
不能解释为研究成功。

引用格式覆盖率为87.50%，但 Citation Precision 只有21.43%，精确来源目标有效率
为50.00%。这说明 Baseline 很擅长生成“看起来像引用”的文本，却没有证明引用
存在、引用支持结论或结论本身正确。

## 2. 可复现输入

- 固定问题：`evaluation/cases/baseline.jsonl`；
- 原始追加式结果：`evaluation/results/day3-qwen3-local-20260731.jsonl`；
- 人工标注：`evaluation/labels/baseline.csv`；
- 汇总结果：`evaluation/results/day4-summary-20260731.json`；
- 复算命令：

```bash
.venv/bin/python scripts/analyze_baseline.py
```

结果文件共有13行。`baseline-001` 保留了 Runner 开发过程中的6次 attempt，其中
包含代理502、事件兼容修复和最终成功记录；其他7个用例各1行。统计只选择每个
稳定 `case_id` 的最高 attempt，历史行没有被覆盖或删除。

## 3. 运行配置

| 配置 | 值 |
| --- | --- |
| 模型 | `openai:qwen3-14b-local` |
| 权重 | `Qwen3-14B-AWQ` |
| 推理服务 | vLLM 0.26.0 |
| 搜索 | `none` |
| 并发 Researcher | 1 |
| Supervisor 最大迭代 | 2 |
| Researcher 最大 Tool Call 迭代 | 4 |
| Clarification | 关闭 |
| 运行方式 | 8个用例串行 |

Runner 从 LangGraph v2 事件采集节点、LLM 和 Tool Call，从本地 vLLM
`/metrics` 前后差值采集精确输入/输出 Token。工具指标区分模型“请求”与程序
“实际执行”，避免把幻觉工具调用误记成搜索成功。

## 4. 指标定义

| 指标 | 定义 |
| --- | --- |
| Citation Precision | 被官方/原始来源直接支持的已引用 Claim ÷ 有引用 Claim |
| Citation Coverage | 有引用 Claim ÷ 全部人工标注 Claim |
| Source Validity | 精确引用目标存在的 Claim ÷ 有引用 Claim |
| Factual Accuracy | 经官方/原始来源核实为正确的 Claim ÷ 全部 Claim |
| Temporal Accuracy | 时间敏感 Claim 中正确者 ÷ 已标注时间 Claim |
| Scope Completeness | 没有关键范围遗漏的 Claim ÷ 全部 Claim |

`source_exists=true` 只表示精确 URL 目标存在，不代表它支持相邻结论；存在但指向
无关论文的 URL 会计入 Source Validity，但不会计入 Citation Precision。

## 5. 量化结果

| 指标 | 结果 |
| --- | ---: |
| 最新用例数 | 8 |
| 图层面生成报告 | 8 / 8 |
| 降级用例 | 8 / 8 |
| 人工核验 Claim | 32 |
| Citation Precision | 21.43% |
| Citation Coverage | 87.50% |
| 精确来源目标有效率 | 50.00% |
| Factual Accuracy | 40.62% |
| Temporal Accuracy | 33.33% |
| Numeric Accuracy | 77.78% |
| Scope Completeness | 40.62% |
| 平均来源数 | 4.12 |
| 平均耗时 | 21.563 秒 |
| 平均总 Token | 6,767 |
| 模型请求搜索 | 13 次 |
| 实际执行搜索 | 0 次 |

平均来源数必须结合50%的 Source Validity 阅读。单独展示“平均4.12个来源”会掩盖
失效路径、无关论文和模型拼接锚点。

## 6. 可复现错误样例

### 6.1 错误来源与方法事实同时错误

`baseline-002` 把 RAG 原始论文写成 `arXiv:2007.01527`。该编号实际对应
《Spectral Theorem approach to the Characteristic Function of Quantum
Observables》，正确的 RAG 原始论文是 `arXiv:2005.11401`。

同一报告继续声称原始 RAG 使用 BM25 且检索器与生成器分别训练。原论文实际使用
DPR dense retriever 与 BART，并把检索文档作为隐变量进行端到端训练。一个错误
来源由此扩散成多个方法错误。

证据：

- https://arxiv.org/abs/2007.01527
- https://arxiv.org/abs/2005.11401

### 6.2 时间错误

`baseline-005` 在明确写出当前日期2026-07-31后，仍称 Qwen3 发布时间、尺寸、
Thinking/Non-thinking、工具能力和许可证“尚未公布”。Qwen 官方已在
2025-04-29发布 Qwen3，列出6个 Dense、2个 MoE 模型、Hybrid Thinking Modes
和 Apache 2.0 许可证。

证据：https://qwenlm.github.io/blog/qwen3/

`baseline-007` 将 AI RMF 1.0 写成2023年11月发布，将 Generative AI Profile
写成2024年1月发布。NIST 官方日期分别是2023-01-26和2024-07-26。

证据：

- https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10
- https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence

### 6.3 API 与查询语法错误

`baseline-003` 给出的 LangGraph 示例导入不存在的 `Graph`、`State`、`Reducer`
和 `Checkpointer` API，并调用不存在的 `set_reducer`。它列出的
`docs.langgraph.com/...` 路径也不是当前官方文档路径。

当前 Graph API 使用 `StateGraph`，Reducer 通过 `Annotated` 声明；无 Reducer
时同一字段默认覆盖，`operator.add` 可追加列表。

证据：https://docs.langchain.com/oss/python/langgraph/graph-api

`baseline-006` 生成：

```sql
WHERE vector_column => query_vector
ORDER BY vector_column <=> query_vector
```

其中 `=>` 不是 pgvector 的近邻过滤操作符。官方示例使用 `ORDER BY embedding
<-> query LIMIT n` 等距离操作符。报告还遗漏 cosine、L1、Hamming 和 Jaccard，
并没有解释 HNSW 无训练步骤、IVFFlat 应在表中已有数据后建立的差异。

证据：https://github.com/pgvector/pgvector

### 6.4 引用路径由模型拼接

`baseline-008` 正确说出 OWASP 2025 的四个风险名称，却生成了12个
`owasp.org/www-project-top-ten-llm-security-risks/#...` 锚点；抽查目标均为
404。当前官方入口在 `genai.owasp.org`。

其 Vector and Embedding Weaknesses 解释成“模型对特定向量过于敏感”，偏离官方
重点：未授权访问与数据泄露、跨上下文泄露、Embedding Inversion 和数据投毒。

证据：

- https://genai.owasp.org/llm-top-10/
- https://genai.owasp.org/llmrisk/llm082025-vector-and-embedding-weaknesses/

## 7. 错误分类

| 错误类型 | 标注次数 | 含义 |
| --- | ---: | --- |
| `invalid_url` | 18 | 精确引用目标不存在或已失效 |
| `temporal_error` | 6 | 未识别当前已公开资料或日期错误 |
| `technical_error` | 6 | 方法、参数或执行语义错误 |
| `wrong_source` | 5 | 来源存在但与所述主题无关 |
| `scope_error` | 4 | 关键任务、算子或边界遗漏 |
| `api_error` | 1 | 使用不存在的框架 API |
| `syntax_error` | 1 | 生成不可用查询语法 |
| `taxonomy_error` | 1 | 将 NIST 四函数写成自创分类 |
| `unsupported_mitigation` | 1 | 把非官方建议写成官方缓解项 |

同一 Claim 可以同时拥有多个错误标签，因此次数之和大于错误 Claim 数。

## 8. 三个最高优先级改造

### P0：研究执行完整性与失败隔离

证据：8/8 用例降级，模型请求13次搜索但实际执行0次；Researcher 未完成
Compression，Writer 仍返回表面成功报告。

改造：

- Day 5 移除 Supervisor 的 `or True`；
- 未知 Tool 名称进入结构化 Tool Error；
- 并行子任务部分成功时保留成功结果和失败原因；
- 报告状态区分 `success`、`partial` 与 `failed`；
- Writer 不得把空 Research Notes 当作完整研究成功。

### P1：Source 注册、URL 验证与内容快照

证据：精确来源目标有效率仅50%，出现无关 arXiv 论文和大量拼接 URL。

改造：

- 搜索工具返回结构化 SourceRecord，而不是让 Writer 自由生成 URL；
- 注册来源时执行规范化、HTTP 状态和内容类型检查；
- 保存标题、作者、发布日期、抓取时间和内容哈希；
- 引用只能选择已注册 Source ID。

对应计划：Day 8、Day 13、Day 14。

### P2：Claim–Evidence–Citation 验证门

证据：Coverage 87.50% 但 Precision 21.43%，Factual Accuracy 40.62%。引用存在感
无法转化成证据支持。

改造：

- 每个 Claim 必须链接可定位 Evidence；
- Verifier 分别判断 entailment、时间、数字与范围；
- 不支持的 Claim 进入修订或删除队列；
- 报告生成只消费验证通过的 Claim/Citation。

对应计划：Day 9、Day 10、Day 26、Day 27、Day 28。

## 9. 限制

1. 除 Runner 调试用例外，每个问题只有一次最新有效运行，尚未测随机性；
2. 只有一名人工标注者，尚无双人一致性指标；
3. `SEARCH_API=none` 是故意设置的离线 Baseline，不代表接入真实搜索后的上限；
4. Citation Precision 采用 Claim 级二元严格判定，部分支持不计为支持；
5. 本轮优先建立可复现失败样例，不将32条标注扩展成正式评测集。

这些限制不改变核心结论：当前系统允许没有真实研究结果的 Writer 生成带引用
外观的报告，下一步必须先修执行完整性，再建设 Source 和 Evidence 闭环。
