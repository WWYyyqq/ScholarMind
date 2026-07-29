# Day 1 本地 Baseline 验收记录

## 验收结论

2026-07-29，ScholarMind 在 WSL2 中完成第一次本地端到端运行。应用依赖和
vLLM 推理依赖分别位于两个项目专用虚拟环境中；Qwen3 模型权重位于 D 盘。
本次运行未配置外部 API Key，也未启用联网搜索。

## 固定版本与环境

- ScholarMind Commit（验收开始时）：
  `f507df000263bdec8377423e775517a9a59b73a5`
- 上游 Open Deep Research：
  `d337ae32ed4ff8f4c6fbe192ba3bf1b2d6610799`
- Python：3.11
- 推理服务：vLLM 0.26.0
- 模型：Qwen3-14B-AWQ
- 模型服务名：`qwen3-14b-local`
- 模型 API：`http://[::1]:8000/v1`
- LangGraph API：`http://127.0.0.1:2024`
- Studio：`https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`
- LangGraph 配置：`langgraph.local.json`
- 搜索配置：`SEARCH_API=none`
- 最大并行研究单元：1

## 本地模型冒烟测试

以下四项全部通过：

1. 健康检查与模型发现；
2. 中文 Chat Completion；
3. JSON Schema 结构化输出；
4. OpenAI 兼容工具调用。

## LangGraph 完整运行

- 提交时间：2026-07-29 23:13（Asia/Shanghai）
- 问题：`请用简洁中文说明 Transformer 的三个核心组成，并明确说明当前未启用联网搜索。`
- Thread ID：`019fae70-7c4a-7dc0-9972-5a9dabb8f86a`
- Run ID：`019fae70-7c4c-7d50-815f-e25e104e1a7c`
- 最终状态：`success`
- 实际模型：`qwen3-14b-local`
- 最终报告输出：成功

运行经过研究问题改写、Supervisor 规划、子研究任务、结果压缩和最终报告生成。
本地开发服务器将线程、运行和状态历史保存在被 Git 忽略的
`.langgraph_api/` 中，以上 Thread ID 和 Run ID 用于定位该次本地 Trace。

## 边界与下一步

本次使用 `SEARCH_API=none`，目的是验收本地模型与完整状态图是否兼容。
报告中的事实和引用来自模型已有知识，不能作为检索质量证据，也不代表
ScholarMind 已经具备联网深度研究能力。后续应接入搜索工具后再建立正式
Baseline 质量评测。
