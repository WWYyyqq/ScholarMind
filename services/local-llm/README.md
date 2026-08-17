# ScholarMind 本地模型服务

该目录提供项目专用的 vLLM 环境与启动脚本，不修改系统 Python、Conda
环境或其他项目。当前模型为 `Qwen3-14B-AWQ`，通过 OpenAI 兼容 API
监听仅本机可访问的 IPv6 回环地址 `[::1]:8000`。

## 当前存储布局

- 推理环境：`services/local-llm/.venv`（WSL 虚拟磁盘，约 7.6 GB）
- 模型：`/mnt/d/ScholarMindLocalLLM/models/Qwen3-14B-AWQ-modelscope`（约 9.4 GB）
- 下载缓存：`/mnt/d/ScholarMindLocalLLM/hf-cache` 和 `uv-cache`
- 编译缓存：项目内 `.cache/`（已被 Git 忽略）

## 启动

在 WSL 的项目根目录执行：

```bash
./services/local-llm/start.sh
```

如果模型环境位于另一个 ScholarMind 工作树，可显式复用同一个项目专用环境，
不会安装到系统 Python：

```bash
SCHOLARMIND_VLLM_ENV=/path/to/ScholarMind/services/local-llm/.venv \
  ./services/local-llm/start.sh
```

首次冷启动通常需要数分钟。看到 `Application startup complete` 后，在另一个
WSL 终端执行：

```bash
services/local-llm/.venv/bin/python services/local-llm/smoke_test.py
```

停止服务时在启动终端按 `Ctrl+C`。

## 启动完整本地开发栈

模型冒烟测试通过后，在另一个 WSL 终端执行：

```bash
.venv/bin/langgraph dev \
  --config langgraph.local.json \
  --allow-blocking \
  --n-jobs-per-worker 1
```

该命令使用仅供本地开发的无认证配置。上游 `langgraph.json` 保留 Supabase
认证，用于需要认证的部署场景。LangGraph 启动后会输出 API、API Docs 和
Studio URL。

## ScholarMind 配置

项目根目录 `.env` 使用以下本地配置：

```dotenv
OPENAI_API_KEY=local
OPENAI_BASE_URL=http://[::1]:8000/v1
RESEARCH_MODEL=openai:qwen3-14b-local
SUMMARIZATION_MODEL=openai:qwen3-14b-local
COMPRESSION_MODEL=openai:qwen3-14b-local
FINAL_REPORT_MODEL=openai:qwen3-14b-local
MAX_CONCURRENT_RESEARCH_UNITS=1
```

`.env` 已被 Git 忽略。要切回云模型，只需移除 `OPENAI_BASE_URL`，填入真实
API Key，并恢复所需的模型名称。

ScholarMind 论文 Agent 默认仍使用确定性抽取式验证，不需要本服务。启用同义
改写、关系方向和多证据语义判断时，再设置：

```dotenv
SCHOLARMIND_VERIFICATION_MODE=semantic
SCHOLARMIND_VERIFIER_MODEL=qwen3-14b-local
SCHOLARMIND_VERIFIER_BASE_URL=http://[::1]:8000/v1
SCHOLARMIND_VERIFIER_MINIMUM_CONFIDENCE=0.75
```

数字、否定极性和 Evidence ID 仍由确定性硬门先检查；Qwen 无法覆盖这些失败。
模型服务超时、不可用或返回非法 JSON 时，Claim 会拒绝发布而不是降级为成功。
