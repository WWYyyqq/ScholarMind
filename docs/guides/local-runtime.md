# ScholarMind 本地运行手册

本页只描述本地论文 Agent 的最短可靠启动路径。所有 Python 依赖都保存在项目的
`.venv` 或 `services/local-llm/.venv` 中，模型权重和下载缓存保存在 D 盘，不修改
系统 Python，也不与其他项目共享数据库表。

## 1. 三个组件分别做什么

```text
PostgreSQL + pgvector（保存论文、证据和 1024 维向量）
                 ↑
Qwen3-Embedding-0.6B + vLLM（生成向量并对候选重排）
                 ↑
ScholarMind LangGraph Agent（检索、Claim 验证、Citation 和 HTTP API）
```

- **Qwen3-Embedding-0.6B** 是模型，负责把问题/证据变成向量，也通过 `/rerank`
  给候选证据重新打分；
- **vLLM** 是模型服务引擎，把这个模型暴露为本机 HTTP API；
- **PostgreSQL/pgvector** 保存论文 Evidence 和向量；
- **LangGraph** 编排检索、Claim 验证与 Citation，并暴露 `/runs/wait`。

运行 `ScholarMind Researcher` 不需要同时启动 14B 生成模型。只有运行上游
`Deep Researcher` 时才需要 `Qwen3-14B-AWQ` 的 8000 端口。

## 2. 首次准备

在仓库根目录执行：

```bash
cp .env.postgres.example .env.postgres
```

只在 `.env.postgres` 中设置本项目的本地数据库密码。该文件已被 Git 忽略，不得
上传。Docker Desktop 需要处于运行状态；首次创建数据库时执行：

```bash
docker compose --env-file .env.postgres -f compose.pgvector.yml up -d
```

如果 WSL 提示找不到 `docker`，在 Docker Desktop 的
`Settings → Resources → WSL integration` 中为 Ubuntu 开启集成。不要通过删除
volume 解决连接问题；`docker compose down -v` 会删除已建立的论文索引。

## 3. 每次启动

### 终端 A：启动 Qwen Embedding/Rerank

```bash
./services/local-embedding/start.sh
```

看到 `Application startup complete` 后保持终端开启。该服务监听
`http://[::1]:8001`。

如果模型环境位于另一个 ScholarMind 工作树，可显式指定项目隔离环境：

```bash
SCHOLARMIND_VLLM_ENV=/path/to/ScholarMind/services/local-llm/.venv \
  ./services/local-embedding/start.sh
```

### 终端 B：确认数据库、Embedding 和 Rerank

```bash
set -a
source .env.postgres
set +a
.venv/bin/python -m scholarmind.cli doctor
```

只有输出 `"status": "ready"` 才继续。该命令不会打印 DSN、密码、论文正文或
模型分数，只报告服务状态、向量维度和索引数量。

### 终端 B：启动 ScholarMind Agent

```bash
./scripts/start_scholarmind_agent.sh
```

脚本自动读取 `.env.postgres`，并只为当前进程设置 Qwen Embedding 配置。默认
API 地址为 `http://127.0.0.1:2024`。

### 终端 C：执行端到端检查

```bash
.venv/bin/python scripts/smoke_scholarmind_api.py
```

通过时会输出：

```json
{
  "status": "passed",
  "publication_ready": true,
  "citation_links_valid": true
}
```

脚本会真实执行 Hybrid + Rerank → File Researcher → Claim Verifier → Citation，
但只打印计数和校验结果，不把本地论文原文写入日志。

## 4. 自己提问

命令行方式：

```bash
set -a
source .env.postgres
set +a
.venv/bin/python -m scholarmind.cli research \
  "你的论文研究问题" \
  --retrieval-mode hybrid-rerank \
  --top-k 5
```

LangGraph API 方式：

```bash
curl -sS http://127.0.0.1:2024/runs/wait \
  -H 'Content-Type: application/json' \
  -d '{
    "assistant_id": "ScholarMind Researcher",
    "input": {
      "question": "你的论文研究问题",
      "retrieval_mode": "hybrid-rerank",
      "top_k": 5
    }
  }'
```

`success` 表示完整证据链可发布；`partial` 表示只有部分 Claim 通过；`failed`
表示不生成伪成功报告，此时 `report` 必须为 `null`。

## 5. 正确停止

- Qwen 服务和 LangGraph：在各自终端按 `Ctrl+C`；
- PostgreSQL：可长期保持运行，或执行
  `docker compose --env-file .env.postgres -f compose.pgvector.yml stop`；
- 不要使用 `down -v`，除非明确决定永久删除 ScholarMind 数据库卷。

## 6. 常见问题

| 现象 | 含义 | 处理 |
| --- | --- | --- |
| `doctor` 的 database 失败 | 容器未运行、端口/密码不匹配或没有索引 | 检查 Docker 和 `.env.postgres` |
| embedding 失败 | 8001 服务未启动或模型名不匹配 | 先启动 `local-embedding/start.sh` |
| reranker 失败 | `/rerank` 不可用或语义排序异常 | 查看 vLLM 终端日志，不绕过检查 |
| LangGraph 首次启动约 20 秒 | 需要导入两个图和依赖 | 等待 `Application started up` |
| API 返回 `failed` 且 `report=null` | 证据链未达到发布条件 | 查看结构化 `errors`，不要把它改成成功 |
| 关闭时提示 `.langgraph_api/*.tmp` 不存在 | 同一工作树同时启动了多个 dev Server，争用本地持久化文件 | 每个工作树只运行一个 LangGraph dev Server |
