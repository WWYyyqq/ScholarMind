# ScholarMind 可靠性与证据流水线

导航：[文档中心](../README.md) · [Baseline 架构](baseline.md) · [开发计划](../development/PLAN.md)

## 1. 这次改造解决什么

上游 Baseline 的目标是尽快完成研究报告，但旧链路可能把“生成了文本”误当作
“研究成功”。ScholarMind 在它外面增加两层约束：

1. **执行可靠性层**：一个并行 Researcher 失败时保留其他成功结果；未知工具、
   Token 限制和工具异常进入结构化状态；Writer 只接受可回溯到成功工具调用且
   内容哈希有效的证据记录。
2. **证据领域层**：本地文件流程使用 Source → Evidence → Claim → Citation；
   只有验证为 `supported` 的 Claim 才能进入确定性报告。

```text
                    ┌─ Researcher A ─ successful tool output ─┐
Research Brief ────┼─ Researcher B ─ structured failure      ├─ success/partial/failed
                    └─ Researcher C ─ successful tool output ─┘
                                         │
                                 hash-verified evidence records
                                         │
                                      Writer gate

paper manifest + page chunks
            │
            ▼
Source → page-located Evidence → Dense/BM25/RRF retrieval
            │
            ▼
Claim draft → strict evidence verifier → supported Claim + Citation
            │
            ▼
deterministic page-cited File Research report
```

两条链路目前同时保留。`open_deep_research` 是兼容上游的 Web/Baseline 图；
`scholarmind` 是逐步替代旧链路的证据优先模块。不能因为后者已有基础类，就声称
所有上游 Web 报告已经完成 Claim 级验证。

## 2. 三态执行结果

主图和 File Researcher 统一使用：

| 状态 | 含义 | Writer/报告行为 |
| --- | --- | --- |
| `success` | 必要阶段均成功，存在可发布证据 | 可以生成报告 |
| `partial` | 至少有一项成功，也有明确失败或被拒 Claim | 只保留成功证据或 supported Claim，并公开错误 |
| `failed` | 没有任何可发布证据 | 不生成看似完整的报告 |

`research_errors` 记录阶段、错误码、说明、是否可恢复，以及可用的 topic/tool/call
标识。Baseline Runner 把这些字段和 `evidence_count` 同时写入顶层与 metrics，
并保留旧 `report_error` 记录的向后兼容。

## 3. Writer 为什么不再相信一个数字

旧状态只有 `notes` 和计数，任意非空字符串都可能被当作研究结果。现在每个成功
工具输出先转换为轻量 `ResearchEvidence`：

- `source`：普通工具或模型原生搜索；
- `tool_name`、`tool_call_id`：输出来自哪个调用；
- `content`：实际观察结果；
- `content_hash`：正文 SHA-256；
- `evidence_id`：由来源、调用和哈希稳定生成。

Researcher、Supervisor 和 Writer 每层都会重新检查内容、哈希、稳定 ID 和重复项。
未知工具、异常字符串、空结果或被篡改的记录不能提高证据计数。Writer 即使收到
`notes=["看似合理的摘要"]` 和 `evidence_count=1`，只要没有有效的
`evidence_records`，仍必须返回 `failed`。

这是一道执行来源门，不等于完整的语义事实验证。Web Writer 仍是生成模型；真正
的 Claim 级发布门目前在 File Researcher 中实现，后续再接入主图。

## 4. 领域模型

代码位于 `src/scholarmind/models/`。

### Source

表示论文、网页、文件或数据集来源，包含稳定 `source_id`、URI、内容 SHA-256、
`paper_id/work_id` 和元数据。同一输入重复导入得到相同 ID。

### Evidence

表示可以逐字回查的原文。它必须关联 Source，并保存页码、章节、bbox、chunk ID
和 block IDs。论文 Adapter 保留 chunk 内部换行；如果上游提供
`content_sha256`，保存后的正文必须与该哈希一致，否则拒绝导入。

### Claim

表示报告中的事实陈述。Claim 可关联一个或多个 Evidence ID，状态为
`unverified/supported/partial/contradicted/insufficient`。声明为 supported 或
partial 时不能没有 Evidence。

### Citation

表示 Claim 到 Evidence 的可审计边，同时复制 Source ID 和 EvidenceLocator。
Repository 会检查 Claim、Evidence、Source 和 locator 四者一致，防止 Writer
自行拼接一个没有来源关系的引用。

这些模型使用 Pydantic 校验和稳定 ID，可 JSON 序列化。`metadata` 仍用于扩展，
业务必需字段不能只藏在 metadata 中。

## 5. 论文数据适配与 split 防泄漏

`PaperDatasetAdapter` 消费论文预处理产物的 manifest 与 page-bounded chunks。
开发建库默认只接受 `dataset_split=development`。即使误把全量 `chunks.jsonl`
传入，也不能把 `test` 作品带入开发索引。正式评测时必须显式选择 `test`，并继续
保持 `tuning_allowed=false`。

推荐输入：

| 场景 | Manifest | Chunks | split |
| --- | --- | --- | --- |
| 开发索引 | `canonical_manifest.jsonl` | `chunks.development.jsonl` | `development` |
| 正式评测 | `canonical_manifest.jsonl` | `evaluation/corpus.chunks.jsonl` | `test` |

不要用全量 `chunks.jsonl` 作为日常索引入口。Adapter 的 split 检查是最后一道
保险，不替代物理文件隔离。

正式评测索引必须显式选择 test，且使用与 development 分开的进度文件：

```bash
.venv/bin/python -m scholarmind.cli index \
  --dataset "<DATASET_DIR>" \
  --dataset-split test
```


## 6. 检索层

当前提供三个可组合实现：

1. `DenseRetriever`：接收任意 `EmbeddingProvider`，以内存余弦相似度排序；
2. `SparseRetriever`：无外部依赖的 BM25，适合术语、缩写和精确关键词；
3. `HybridRetriever`：用加权 Reciprocal Rank Fusion 合并 Dense 与 Sparse 排名。

`HashingEmbedder` 是**零下载的词法哈希回退**，用于单元测试、接口联调和无网络
冒烟测试。它不是语义 embedding 模型，不能作为正式 Dense Retrieval 效果结论。
正式演示前应固定一个真实 embedding 模型、版本和维度，再为对应维度建立 HNSW
索引。

实际 CLI 的默认链路已经升级为：

```text
Qwen query embedding → pgvector Dense ─┐
accepted corpus → BM25 Sparse ─────────┤
                                       ▼
                            weighted RRF fusion
                                       ▼
                         evidence quality gate
                                       ▼
                         local Qwen /rerank
```

`EvidenceQualityPolicy` 会拒绝参考文献、标题式短块、低文本密度和缺页码证据，
`QualityFilteredRetriever` 通过扩大候选集降低过滤带来的召回损失。
`OpenAIRerankProvider` 复用 Qwen3-Embedding-0.6B 服务的 `/rerank` 接口，
没有新增模型或环境。CLI 保留 `dense`、`hybrid`、`hybrid-rerank` 三种模式，
默认使用最后一种。

42 道待人工复核 Silver 问题的工程诊断中，Hybrid + Rerank 的 Source Recall@8
为 100%，Page Recall@8 为 73.81%，最终 Top-8 明确噪声率由 Dense 的 4.46% 降至
0%。这些数值不是 Gold 成绩；3 条标签证据本身被判为标题式/非完整句子，另 1 条
无法精确映射，必须在人工复核后再冻结正式指标。


## 7. File Researcher 发布门

File Researcher 的顺序固定为：

```text
question
  → Retriever.search
  → 只保留有页码的 Evidence
  → ClaimGenerator
  → ClaimVerifier
  → Citation
  → supported-only renderer
```

当前默认 `ExtractiveClaimGenerator` 直接从 Evidence 句子产生候选 Claim。验证器先
检查 Evidence ID，再检查数字、否定极性和词项覆盖；最终判为 `supported` 还必须
满足：Claim 经空白规范化后可从某条已链接 Evidence 句子中严格抽取。

因此 `A outperforms B` 与证据 `B outperforms A` 即使词集合完全相同，也不能进入
报告。这个保守门会拒绝合理的同义改写；在语义/NLI 验证器上线前，这是有意的
安全边界。

畸形检索项、某个 Claim 校验异常、Verifier 异常或 Citation 异常只影响对应项：

- 仍有 supported Claim：返回 `partial`，报告只包含成功项；
- 全部失败或没有页码 Evidence：返回 `failed`，`report=None`；
- 全部有效：返回 `success`。

## 8. 项目独立环境

Python 依赖继续安装在仓库自己的 `.venv`，不会修改系统 Python、Conda 或其他
项目：

```bash
cd "<SCHOLARMIND_REPO>"
uv sync --locked --extra dev --extra postgres
```

`postgres` extra 只增加 psycopg 与 pgvector Python 包。模型权重仍由单独的
`services/local-llm/.venv` 和 D 盘模型目录管理。

## 9. 本地 PostgreSQL + pgvector

本地服务使用独立 Compose 文件、loopback 端口和命名卷：

```bash
cd "<SCHOLARMIND_REPO>"
cp .env.postgres.example .env.postgres
# 打开 .env.postgres，把示例密码同时替换为只在本机使用的强密码

docker compose \
  --env-file .env.postgres \
  -f compose.pgvector.yml \
  up -d
```

`.env.postgres` 不会被 Git 跟踪。Compose 将 schema 挂到
`/docker-entrypoint-initdb.d/`，所以全新数据卷首次启动会自动建表；应用侧
`PostgresEvidenceRepository.initialize_schema()` 仍是幂等入口，可用于 CI 或
已有空数据库。

检查服务：

```bash
docker compose \
  --env-file .env.postgres \
  -f compose.pgvector.yml \
  ps
```

停止但保留数据：

```bash
docker compose \
  --env-file .env.postgres \
  -f compose.pgvector.yml \
  down
```

不要随手添加 `-v`；它会删除 ScholarMind 的 PostgreSQL 命名卷。Docker 镜像、
卷和 embedding 会额外占用磁盘，数据通常位于 Docker Desktop 的磁盘映像中。
若 C 盘空间紧张，应先把 Docker Desktop 数据磁盘迁到 D 盘，再导入大规模向量；
代码不会自动下载模型或在未明确执行 Compose 命令时启动数据库。

2026-08-04 已完成本机真实验收：Docker Desktop WSL2 后端启动
`pgvector/pgvector:pg16`，启用 pgvector 0.8.6，创建 6 张证据关系表，并通过
Repository 往返集成测试。随后使用 Qwen3-Embedding-0.6B 写入 49 篇 development
论文的 6,853 条 Evidence，以及 33 篇 test 论文的 4,026 条 Evidence，共计
82 篇数据集论文、10,879 条 1024 维向量。索引器支持按模型和 Evidence 内容哈希
判断向量是否有效、默认跳过已完成记录、批量写入、JSONL 进度审计以及失败隔离；
development 与 test 使用独立进度文件，同一分区重跑可跳过全部有效记录。

GitHub Actions 仍会独立启动同类服务，执行 Schema、CRUD、embedding 入库与向量
检索，避免本机成功掩盖 CI 环境问题。若 WSL Integration 尚未启用，可以暂时从
WSL 调用 Docker Desktop 自带的 Windows CLI；推荐最终在 Docker Desktop 设置中
为 Ubuntu 启用集成。

## 10. CI 与本地验证

GitHub Actions 在每次 PR 及 main push 时执行：

1. `uv lock --check`；
2. 安装锁定的 dev 与 postgres extras；
3. Ruff 检查 ScholarMind、新测试和可靠性生产文件；
4. 全部单元测试；
5. 真实 PostgreSQL/pgvector 集成测试。

本地无 Docker 时仍可执行：

```bash
.venv/bin/ruff check src/scholarmind tests/unit tests/integration scripts/evaluate_paper_retrieval.py
.venv/bin/python -m pytest -q -s tests/unit
.venv/bin/python -m pytest -q -s tests/integration/test_postgres_repository.py
```

最后一条会在没有 `SCHOLARMIND_TEST_DATABASE_DSN` 时明确 skip，不会伪装成数据库
已经运行。

## 11. 当前边界

已实现的是可测试的证据流水线基础，不是完整产品：

- Web/Baseline Writer 已有哈希与调用来源门，但尚未接入 Claim 级语义后验验证；
- File Researcher 是库级 MVP，尚未连接主 LangGraph 节点、HTTP API 或界面；
- 本地论文链路已接入 Qwen Dense、BM25、RRF、质量过滤和 Qwen Rerank，但当前
  指标来自待人工复核 Silver 标签；Gold 数据集与正式消融尚未完成，pgvector
  生产索引参数也尚未冻结；
- PostgreSQL 目前使用幂等 schema，尚未引入 Alembic 升降级；
- 正式 Review/Gold schema、构建器和验证器仍是 Silver 人工复核阶段的后续工具；
- 本地数据库需用户先安装/启用 Docker Desktop 的 WSL 集成。

这些边界必须保留在简历和演示说明中。可以说“实现了证据模型、混合检索、
pgvector Repository、失败隔离和严格抽取式发布门”，不能说“已经完成生产级
语义事实验证或完整 PDF RAG 产品”。
