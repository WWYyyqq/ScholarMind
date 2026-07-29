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

首次冷启动通常需要数分钟。看到 `Application startup complete` 后，在另一个
WSL 终端执行：

```bash
services/local-llm/.venv/bin/python services/local-llm/smoke_test.py
```

停止服务时在启动终端按 `Ctrl+C`。

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
