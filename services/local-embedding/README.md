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

生成模型与Embedding模型并行运行时，默认GPU显存配额分别为0.75和0.15。
如需单独运行服务，可分别使用SCHOLARMIND_LLM_GPU_MEMORY_UTILIZATION和
SCHOLARMIND_EMBEDDING_GPU_MEMORY_UTILIZATION调整，但两者总和必须为GPU和
CUDA运行时保留余量。
