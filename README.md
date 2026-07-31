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
记录在 [`docs/upstream.md`](docs/upstream.md)。

## 当前进度

| 项目 | 状态 | 证据 |
| --- | --- | --- |
| Day 1：环境与本地 Baseline | ✅ 完成并复验 | [详细日志](docs/development/daily/2026-07-29-day-01.md) |
| Day 2：理解 Baseline 状态图 | ✅ 完成 | [架构文档](docs/baseline_architecture.md) · [详细日志](docs/development/daily/2026-07-30-day-02.md) |
| Day 3：可重复 Baseline Runner | ✅ 完成 | [评测说明](evaluation/README.md) · [详细日志](docs/development/daily/2026-07-31-day-03.md) |
| Day 4：Baseline 错误分析 | ✅ 完成 | [错误分析](docs/baseline_error_analysis.md) · [详细日志](docs/development/daily/2026-07-31-day-04.md) |
| 论文数据预处理（专项） | ✅ 完成并通过独立验证 | [数据说明](docs/paper_dataset.md) · [Gold 标注手册](docs/paper_gold_annotation.md) · [详细日志](docs/development/supplemental/2026-08-01-paper-dataset-preparation.md) |
| 搜索能力 | ⏳ 未接入 | 当前使用 `SEARCH_API=none` |
| 简历可投递版本 | 计划 2026-08-26 | Day 28 |
| `v0.1.0` | 计划 2026-09-09 | Day 42 |

开发文档入口：

- [开发计划与日志索引](docs/development/README.md)
- [完整 42 天计划、每日任务与验收标准](docs/development/PLAN.md)
- [Day 1 详细开发日志](docs/development/daily/2026-07-29-day-01.md)
- [Baseline 架构说明](docs/baseline_architecture.md)
- [Day 2 详细开发日志](docs/development/daily/2026-07-30-day-02.md)
- [Baseline Runner、固定问题与结果说明](evaluation/README.md)
- [Day 3 详细开发日志](docs/development/daily/2026-07-31-day-03.md)
- [Baseline 错误分析](docs/baseline_error_analysis.md)
- [Day 4 详细开发日志](docs/development/daily/2026-07-31-day-04.md)
- [本地论文数据集预处理说明](docs/paper_dataset.md)
- [论文评测集 Silver → Gold 人工标注手册](docs/paper_gold_annotation.md)
- [论文数据预处理专项日志](docs/development/supplemental/2026-08-01-paper-dataset-preparation.md)
- [每日日志模板](docs/development/daily/TEMPLATE.md)

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
| 1 | Day 5 · 8/3 | 隔离子研究任务失败 | 计划 |
| 1 | Day 6 · 8/4 | 建立 ScholarMind 模块骨架 | 计划 |
| 1 | Day 7 · 8/5 | 第一周复盘与架构冻结 | 计划 |
| 2 | Day 8 · 8/6 | 实现 SourceRecord | 计划 |
| 2 | Day 9 · 8/7 | 实现 EvidenceItem | 计划 |
| 2 | Day 10 · 8/8 | 实现 Claim 与 Citation | 计划 |
| 2 | Day 11 · 8/9 | 模型测试与 Fixture | 计划 |
| 2 | Day 12 · 8/10 | PostgreSQL 与 pgvector | 计划 |
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

Copy `.env.example` to `.env` when configuring a new checkout. Never commit
`.env`; it is ignored by Git.

Development plans and daily engineering logs are organized under
[`docs/development/`](docs/development/README.md). Start with the
[`42-day plan`](docs/development/PLAN.md) and the detailed
[`Day 1 log`](docs/development/daily/2026-07-29-day-01.md).

---

# 🔬 Open Deep Research

<img width="1388" height="298" alt="full_diagram" src="https://github.com/user-attachments/assets/12a2371b-8be2-4219-9b48-90503eb43c69" />

Deep research has broken out as one of the most popular agent applications. This is a simple, configurable, fully open source deep research agent that works across many model providers, search tools, and MCP servers. It's performance is on par with many popular deep research agents ([see Deep Research Bench leaderboard](https://huggingface.co/spaces/Ayanami0730/DeepResearch-Leaderboard)).

<img width="817" height="666" alt="Screenshot 2025-07-13 at 11 21 12 PM" src="https://github.com/user-attachments/assets/052f2ed3-c664-4a4f-8ec2-074349dcaa3f" />

### 🔥 Recent Updates

**August 14, 2025**: See our free course [here](https://academy.langchain.com/courses/deep-research-with-langgraph) (and course repo [here](https://github.com/langchain-ai/deep_research_from_scratch)) on building open deep research.

**August 7, 2025**: Added GPT-5 and updated the Deep Research Bench evaluation w/ GPT-5 results.

**August 2, 2025**: Achieved #6 ranking on the [Deep Research Bench Leaderboard](https://huggingface.co/spaces/Ayanami0730/DeepResearch-Leaderboard) with an overall score of 0.4344. 

**July 30, 2025**: Read about the evolution from our original implementations to the current version in our [blog post](https://rlancemartin.github.io/2025/07/30/bitter_lesson/).

**July 16, 2025**: Read more in our [blog](https://blog.langchain.com/open-deep-research/) and watch our [video](https://www.youtube.com/watch?v=agGiWUpxkhg) for a quick overview.

### 🚀 Quickstart

1. Clone the repository and activate a virtual environment:
```bash
git clone https://github.com/langchain-ai/open_deep_research.git
cd open_deep_research
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:
```bash
uv sync
# or
uv pip install -r pyproject.toml
```

3. Set up your `.env` file to customize the environment variables (for model selection, search tools, and other configuration settings):
```bash
cp .env.example .env
```

4. Launch agent with the LangGraph server locally:

```bash
# Install dependencies and start the LangGraph server
uvx --refresh --from "langgraph-cli[inmem]" --with-editable . --python 3.11 langgraph dev --allow-blocking
```

This will open the LangGraph Studio UI in your browser.

```
- 🚀 API: http://127.0.0.1:2024
- 🎨 Studio UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
- 📚 API Docs: http://127.0.0.1:2024/docs
```

Ask a question in the `messages` input field and click `Submit`. Select different configuration in the "Manage Assistants" tab.

### ⚙️ Configurations

#### LLM :brain:

Open Deep Research supports a wide range of LLM providers via the [init_chat_model() API](https://python.langchain.com/docs/how_to/chat_models_universal_init/). It uses LLMs for a few different tasks. See the below model fields in the [configuration.py](https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/configuration.py) file for more details. This can be accessed via the LangGraph Studio UI. 

- **Summarization** (default: `openai:gpt-4.1-mini`): Summarizes search API results
- **Research** (default: `openai:gpt-4.1`): Power the search agent
- **Compression** (default: `openai:gpt-4.1`): Compresses research findings
- **Final Report Model** (default: `openai:gpt-4.1`): Write the final report

> Note: the selected model will need to support [structured outputs](https://python.langchain.com/docs/integrations/chat/) and [tool calling](https://python.langchain.com/docs/how_to/tool_calling/).

> Note: For OpenRouter: Follow [this guide](https://github.com/langchain-ai/open_deep_research/issues/75#issuecomment-2811472408) and for local models via Ollama  see [setup instructions](https://github.com/langchain-ai/open_deep_research/issues/65#issuecomment-2743586318).

#### Search API :mag:

Open Deep Research supports a wide range of search tools. By default it uses the [Tavily](https://www.tavily.com/) search API. Has full MCP compatibility and work native web search for Anthropic and OpenAI. See the `search_api` and `mcp_config` fields in the [configuration.py](https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/configuration.py) file for more details. This can be accessed via the LangGraph Studio UI. 

#### Other 

See the fields in the [configuration.py](https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/configuration.py) for various other settings to customize the behavior of Open Deep Research. 

### 📊 Evaluation

Open Deep Research is configured for evaluation with [Deep Research Bench](https://huggingface.co/spaces/Ayanami0730/DeepResearch-Leaderboard). This benchmark has 100 PhD-level research tasks (50 English, 50 Chinese), crafted by domain experts across 22 fields (e.g., Science & Tech, Business & Finance) to mirror real-world deep-research needs. It has 2 evaluation metrics, but the leaderboard is based on the RACE score. This uses LLM-as-a-judge (Gemini) to evaluate research reports against a golden set of reports compiled by experts across a set of metrics.

#### Usage

> Warning: Running across the 100 examples can cost ~$20-$100 depending on the model selection.

The dataset is available on [LangSmith via this link](https://smith.langchain.com/public/c5e7a6ad-fdba-478c-88e6-3a388459ce8b/d). To kick off evaluation, run the following command:

```bash
# Run comprehensive evaluation on LangSmith datasets
python tests/run_evaluate.py
```

This will provide a link to a LangSmith experiment, which will have a name `YOUR_EXPERIMENT_NAME`. Once this is done, extract the results to a JSONL file that can be submitted to the Deep Research Bench.

```bash
python tests/extract_langsmith_data.py --project-name "YOUR_EXPERIMENT_NAME" --model-name "you-model-name" --dataset-name "deep_research_bench"
```

This creates `tests/expt_results/deep_research_bench_model-name.jsonl` with the required format. Move the generated JSONL file to a local clone of the Deep Research Bench repository and follow their [Quick Start guide](https://github.com/Ayanami0730/deep_research_bench?tab=readme-ov-file#quick-start) for evaluation submission.

#### Results 

| Name | Commit | Summarization | Research | Compression | Total Cost | Total Tokens | RACE Score | Experiment |
|------|--------|---------------|----------|-------------|------------|--------------|------------|------------|
| GPT-5 | [ca3951d](https://github.com/langchain-ai/open_deep_research/pull/168/commits) | openai:gpt-4.1-mini | openai:gpt-5 | openai:gpt-4.1 |  | 204,640,896 | 0.4943 | [Link](https://smith.langchain.com/o/ebbaf2eb-769b-4505-aca2-d11de10372a4/datasets/6e4766ca-613c-4bda-8bde-f64f0422bbf3/compare?selectedSessions=4d5941c8-69ce-4f3d-8b3e-e3c99dfbd4cc&baseline=undefined) |
| Defaults | [6532a41](https://github.com/langchain-ai/open_deep_research/commit/6532a4176a93cc9bb2102b3d825dcefa560c85d9) | openai:gpt-4.1-mini | openai:gpt-4.1 | openai:gpt-4.1 | $45.98 | 58,015,332 | 0.4309 | [Link](https://smith.langchain.com/o/ebbaf2eb-769b-4505-aca2-d11de10372a4/datasets/6e4766ca-6[…]ons=cf4355d7-6347-47e2-a774-484f290e79bc&baseline=undefined) |
| Claude Sonnet 4 | [f877ea9](https://github.com/langchain-ai/open_deep_research/pull/163/commits/f877ea93641680879c420ea991e998b47aab9bcc) | openai:gpt-4.1-mini | anthropic:claude-sonnet-4-20250514 | openai:gpt-4.1 | $187.09 | 138,917,050 | 0.4401 | [Link](https://smith.langchain.com/o/ebbaf2eb-769b-4505-aca2-d11de10372a4/datasets/6e4766ca-6[…]ons=04f6002d-6080-4759-bcf5-9a52e57449ea&baseline=undefined) |
| Deep Research Bench Submission | [c0a160b](https://github.com/langchain-ai/open_deep_research/commit/c0a160b57a9b5ecd4b8217c3811a14d8eff97f72) | openai:gpt-4.1-nano | openai:gpt-4.1 | openai:gpt-4.1 | $87.83 | 207,005,549 | 0.4344 | [Link](https://smith.langchain.com/o/ebbaf2eb-769b-4505-aca2-d11de10372a4/datasets/6e4766ca-6[…]ons=e6647f74-ad2f-4cb9-887e-acb38b5f73c0&baseline=undefined) |

### 🚀 Deployments and Usage

#### LangGraph Studio

Follow the [quickstart](#-quickstart) to start LangGraph server locally and test the agent out on LangGraph Studio.

#### Hosted deployment
 
You can easily deploy to [LangGraph Platform](https://langchain-ai.github.io/langgraph/concepts/#deployment-options). 

#### Open Agent Platform

Open Agent Platform (OAP) is a UI from which non-technical users can build and configure their own agents. OAP is great for allowing users to configure the Deep Researcher with different MCP tools and search APIs that are best suited to their needs and the problems that they want to solve.

We've deployed Open Deep Research to our public demo instance of OAP. All you need to do is add your API Keys, and you can test out the Deep Researcher for yourself! Try it out [here](https://oap.langchain.com)

You can also deploy your own instance of OAP, and make your own custom agents (like Deep Researcher) available on it to your users.
1. [Deploy Open Agent Platform](https://docs.oap.langchain.com/quickstart)
2. [Add Deep Researcher to OAP](https://docs.oap.langchain.com/setup/agents)

### Legacy Implementations 🏛️

The `src/legacy/` folder contains two earlier implementations that provide alternative approaches to automated research. They are less performant than the current implementation, but provide alternative ideas understanding the different approaches to deep research.

#### 1. Workflow Implementation (`legacy/graph.py`)
- **Plan-and-Execute**: Structured workflow with human-in-the-loop planning
- **Sequential Processing**: Creates sections one by one with reflection
- **Interactive Control**: Allows feedback and approval of report plans
- **Quality Focused**: Emphasizes accuracy through iterative refinement

#### 2. Multi-Agent Implementation (`legacy/multi_agent.py`)  
- **Supervisor-Researcher Architecture**: Coordinated multi-agent system
- **Parallel Processing**: Multiple researchers work simultaneously
- **Speed Optimized**: Faster report generation through concurrency
- **MCP Support**: Extensive Model Context Protocol integration
