# ScholarMind 文档中心

这里是 ScholarMind 人类可读文档的统一入口。第一次查看项目时，从本页按任务进入，不需要在仓库中逐层猜文件位置。

## 按任务查找

| 我想做什么 | 从这里开始 |
|---|---|
| 了解项目目标、范围与里程碑 | [项目总览](project/overview.md) |
| 启动本地 Qwen3 与 vLLM | [本地模型服务](../services/local-llm/README.md) |
| 查看 42 天计划和每日记录 | [开发计划与日志](development/README.md) |
| 理解 Baseline 状态图 | [Baseline 架构](architecture/baseline.md) |
| 运行固定 Baseline 评测 | [机器可读评测资产与运行命令](../evaluation/README.md) |
| 查看 Day 4 错误分析 | [Baseline 错误分析](evaluation/baseline-error-analysis.md) |
| 构建 97 篇论文数据集 | [论文数据集说明](evaluation/paper-dataset/README.md) |
| 把 Silver 问题复核为 Gold | [Silver → Gold 人工标注手册](evaluation/paper-dataset/silver-to-gold.md) |
| 复制人工复核空模板 | [Review 模板](evaluation/paper-dataset/templates/review-record.template.json) |
| 复制 Gold 问题空模板 | [Gold 模板](evaluation/paper-dataset/templates/gold-question.template.json) |
| 查看上游来源和固定 Commit | [上游基线说明](project/upstream.md) |

## 目录结构

```text
docs/
├── README.md
├── project/
│   ├── overview.md
│   └── upstream.md
├── architecture/
│   └── baseline.md
├── evaluation/
│   ├── README.md
│   ├── baseline-error-analysis.md
│   └── paper-dataset/
│       ├── README.md
│       ├── silver-to-gold.md
│       └── templates/
└── development/
    ├── README.md
    ├── PLAN.md
    ├── daily/
    └── supplemental/
```

## 文件放置规则

- `docs/`：项目总览、架构、评测方法、数据说明和开发记录等人类可读内容。
- `evaluation/`：程序直接读取的用例、Schema、标签和运行结果；其 [README](../evaluation/README.md) 与资产就近放置。
- `services/*/README.md`：某个组件的安装、启动和运维说明，与组件代码放在一起。
- `examples/`：示例输入或输出，不属于项目说明文档。
- `CLAUDE.md` 与 `src/legacy/` 内文档：工具或上游历史上下文，不作为主文档入口。

这种分法避免复制同一份内容：主文档统一从本页导航，运行资产与组件说明仍放在最接近代码的位置。

## 为什么 GitHub 链接中有 `blob`

`blob` 不是仓库里的文件夹，而是 GitHub 的页面路由：

- `/blob/<branch>/<path>`：打开某一个文件；
- `/tree/<branch>/<path>`：浏览某一个目录。

因此，即使 Markdown 或 JSON 已经位于 `docs/`，打开单个文件时 URL 仍然会包含 `blob`。判断真实位置时，应看分支名之后的路径；例如 `/blob/main/docs/evaluation/...` 的真实目录就是 `docs/evaluation/`。
