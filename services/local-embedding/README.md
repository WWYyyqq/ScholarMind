# ScholarMind本地Embedding服务

该服务使用项目已有的vLLM虚拟环境加载Qwen3-Embedding-0.6B，通过
[::1]:8001/v1/embeddings提供OpenAI兼容Embedding API。模型权重位于D盘，
不进入Git。

## 下载

在项目根目录执行：

~~~bash
services/local-llm/.venv/bin/python services/local-embedding/download_model.py
~~~

默认从ModelScope下载到：

~~~text
/mnt/d/ScholarMindLocalLLM/models/Qwen3-Embedding-0.6B-modelscope
~~~

## 启动和验证

~~~bash
./services/local-embedding/start.sh
~~~

等待服务启动后，在另一终端执行：

~~~bash
.venv/bin/python services/local-embedding/smoke_test.py
~~~

启动脚本默认把vLLM进程间通信文件放在
`/tmp/scholarmind-embedding-<UID>`，以免工作树路径过长超过Linux Unix
Socket的107字符上限。可用`SCHOLARMIND_EMBEDDING_TMPDIR`单独覆盖。

## 可恢复地建立论文索引

启动 Embedding 服务和 PostgreSQL 后，在项目虚拟环境中执行：

~~~bash
set -a
source .env.postgres
set +a
.venv/bin/python -m scholarmind.cli index \
  --dataset /path/to/paper-dataset-v1 \
  --embedding-base-url http://[::1]:8001/v1 \
  --embedding-model qwen3-embedding-0.6b-local \
  --batch-size 64
~~~

默认启用断点续跑：数据库中模型名与 Evidence 内容哈希都匹配的向量会被跳过。
进度以 JSONL 写入数据集下的 `.scholarmind/` 目录，运行中的批次信息写到
stderr，最终摘要写到 stdout。该进度文件只保存数量、ID、模型名和失败摘要，不
保存论文正文或数据库密码。

常用控制参数：

- `--force-reindex`：忽略已有向量，强制重新计算；
- `--fail-fast`：遇到首个数据错误就停止；默认隔离单条坏数据并继续；
- `--progress-file PATH`：覆盖默认 JSONL 进度文件位置。

生成模型与Embedding模型并行运行时，默认GPU显存配额分别为0.75和0.15。
如需单独运行服务，可分别使用SCHOLARMIND_LLM_GPU_MEMORY_UTILIZATION和
SCHOLARMIND_EMBEDDING_GPU_MEMORY_UTILIZATION调整，但两者总和必须为GPU和
CUDA运行时保留余量。
