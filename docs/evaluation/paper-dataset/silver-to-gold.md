# 论文评测集 Silver → Gold 人工标注操作手册

导航：[文档中心](../../README.md) · [评测与论文数据](../README.md) · [论文数据集说明](README.md) · [空模板](templates/README.md)

> 适用范围：ScholarMind 论文问答评测集。本文面向第一次做数据标注的开发者，目标是把程序生成的 Silver 候选问题，经过人工检查、复核和裁决，整理为可重复使用的 Gold 评测集。

规范版本：`1.0-draft`。在正式 Review/Gold Schema、构建器和验证器落地前，本文规定的是人工操作协议，不代表自动化 Gold 流程已经完成。

## 1. 先理解三个概念

| 名称 | 含义 | 能否直接作为正式评测结论 |
|---|---|---|
| Silver | 程序按规则自动生成的候选问题，可能存在章节误判、答案不完整或证据错误 | 不能 |
| Review | 人工对某条 Silver 记录做出的判断和修改建议 | 不能，仍需复核 |
| Gold | 通过约定流程审核，且问题、答案、证据和来源都一致的最终记录 | 可以 |

Gold 不是“把 Silver 文件改个名字”。它必须保留输入版本、人工判断、修改过程和最终依据，确保以后可以解释每一道题为什么被保留。

## 2. 当前待标注数据概况

当前数据管线生成的候选集为：

| 项目 | 数量 |
|---|---:|
| 测试集论文作品 | 24 |
| Silver 候选问题 | 42 |
| `abstract_evidence` | 19 |
| `method_section_locator` | 23 |
| 至少有一道候选题的论文 | 23 |
| 暂无候选题的论文 | 1 |

这些数字描述的是当前候选集，不是最终 Gold 的硬性目标。错误题应当拒绝，所以最终题数可以少于 42。本版 `paper-gold-v1` 只处理这 42 道 Silver 候选；缺题论文和人工新题另开后续版本，不能混入本轮而丢失来源。

## 3. 标注前的安全规则

1. **不要修改原始 Silver 文件。** 它是可追溯的输入快照。
2. **不要修改论文 PDF。** PDF 只用于查证原文。
3. **不要把真实标注结果推送到公开 GitHub。** 论文正文、真实问题、答案、证据和审阅记录都保存在本地私有目录。
4. **不要用测试集调提示词、选模型或改检索参数。** Gold 测试集只用于最终评价，`tuning_allowed` 必须为 `false`。
5. **不要使用 `git add -f` 绕过忽略规则。** 提交前运行 `git status`，确认没有 PDF、真实 JSONL 或个人路径。
6. 公开仓库只保存本手册和虚构的空模板：
   - [审阅记录模板](templates/review-record.template.json)
   - [Gold 记录模板](templates/gold-question.template.json)

如果只有一位标注者，两个轮次使用同一个匿名代号（如 `reviewer-a`），不要在公开材料中写真实姓名、邮箱或本机路径。

## 4. 建议的本地目录

程序生成的数据集目录：

```text
<DATASET_OUTPUT>/
└── evaluation/
    ├── papers.jsonl
    ├── corpus.chunks.jsonl
    └── questions.silver.jsonl
```

建议把人工成果放在数据集目录之外，避免重新执行 `--replace` 时一起被删除：

```text
<ANNOTATION_ROOT>/paper-eval-v1/
├── source_manifest.json
├── source_checksums.sha256
├── reviews/
│   ├── round-1.work.jsonl
│   ├── round-2.work.jsonl
│   ├── records/
│   └── questions.review.jsonl
├── gold/
│   └── questions.gold.v1.jsonl
├── build_manifest.json
└── review_summary.md
```

`round-*.work.jsonl` 是两轮互不可见的临时工作文件；两轮锁定后才合并为每题唯一一条的 `questions.review.jsonl`。最终决定统一写在该记录的 `resolution` 中，它是 Gold 导出的唯一人工结论来源。

如果必须放在仓库目录内，只能使用已经被 Git 忽略的 `evaluation/private/`，并在提交前再次检查。不要把人工记录只放进自动生成的 `v1` 目录。

`paper-eval-v1` 是人为指定的本地 release ID，不是生成器当前自动写入的字段。确定后要在 `source_manifest.json`、Review 和 Gold 中保持一致；输入发生变化时改用新的 release ID。

先创建私有工作目录，否则后续重定向会失败：

```bash
mkdir -p "<ANNOTATION_ROOT>/paper-eval-v1/reviews/records" "<ANNOTATION_ROOT>/paper-eval-v1/gold"
```

## 5. 第一步：冻结输入版本

只冻结 Silver 文件不足以复现证据。开始标注前，应同时冻结规范清单、构建配置、测试论文、测试语料、Silver 问题和所有解析文档。以下命令在文件中只留下相对路径：

```bash
(
  cd "<DATASET_OUTPUT>" || exit 1
  sha256sum dataset_config.json canonical_manifest.jsonl evaluation/papers.jsonl evaluation/corpus.chunks.jsonl evaluation/questions.silver.jsonl
  find documents -maxdepth 1 -type f -name 'paper-*.json' -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
) > "<ANNOTATION_ROOT>/paper-eval-v1/source_checksums.sha256"

sha256sum "<ANNOTATION_ROOT>/paper-eval-v1/source_checksums.sha256"
```

每次继续标注前复验输入：

```bash
(cd "<DATASET_OUTPUT>" && sha256sum -c "<ANNOTATION_ROOT>/paper-eval-v1/source_checksums.sha256")
```

出现任意 `FAILED` 就停止标注，查明变化并创建新的 release，不能继续写入旧 Review。

在 `source_manifest.json` 中至少记录：

- 本地 release ID 和生成日期；
- `source_checksums.sha256` 自身的 SHA-256；
- `evaluation/questions.silver.jsonl` 的 SHA-256；
- ScholarMind Git commit；
- 论文、候选题及各题型数量；
- 标注规范版本 `1.0-draft`；
- 标注者匿名代号和轮次日期。

Review 和 Gold 只记录整套校验文件的哈希与 `question_id`，不使用未定义算法的“单行哈希”。

## 6. 第二步：先做 5 道校准题

正式开始前挑 5 道题共同校准判定尺度：

- 2 道 `abstract_evidence`；
- 3 道 `method_section_locator`；
- 尽量包含一条可直接保留、一条需要修正和一条应拒绝的候选题。

完成后回看：两轮是否使用相同标准；“答案正确”和“证据足够”是否被分别判断；章节标题边界是否一致。规则仍不清楚时，先补充说明，不要急着标完 42 道。

校准题经过共同讨论后不再是独立判断：两位标注者应在规则冻结后重新独立标一次，或者把这 5 道从独立一致率统计中剔除。

## 7. 单条问题的实际操作

对 `questions.silver.jsonl` 中的每一行按以下顺序操作。

### 7.1 找到来源

1. 记录 `question_id`、`paper_id`、`work_id` 和 `question_type`。
2. 在 `evaluation/papers.jsonl` 确认它属于隔离测试集；该文件不保存 PDF 路径。
3. 在 `canonical_manifest.jsonl` 按 `paper_id` 找到 `canonical_relative_path`，与只读的 `<PDF_SOURCE_DIR>` 拼接后打开原始 PDF。
4. 在 `documents/<paper_id>.json` 中按 `block_ids` 逐个核对原文、页面和单块坐标。
5. 在 `evaluation/corpus.chunks.jsonl` 核对检索 chunk；这里的 bbox 是整个 chunk 的合并框，不能代替 `documents/` 中的单块坐标。

`page_number` 是 PDF 文件中第 N 个物理页面，从 1 开始，即 PyMuPDF page index + 1；它不是论文正文印刷页码，也不以阅读器自定义页签为准。

`bbox = [x0, y0, x1, y1]` 使用 PDF point，原点在左上角；`bbox_normalized_top_left` 是横坐标除页面宽度、纵坐标除页面高度后的结果。题目证据 bbox 是同页所选 `block_ids` 的并集框，必须由程序计算，不能手工猜测。

不熟悉 JSONL 时，可以先用 ID 搜索，不需要一次读完整个大文件：

```bash
rg '<QUESTION_ID>' "<DATASET_OUTPUT>/evaluation/questions.silver.jsonl"
rg '<PAPER_ID>' "<DATASET_OUTPUT>/evaluation/papers.jsonl"
rg '<PAPER_ID>' "<DATASET_OUTPUT>/canonical_manifest.jsonl"
rg '<PAPER_ID>' "<DATASET_OUTPUT>/evaluation/corpus.chunks.jsonl"
rg -n -C 12 '"block_id": "<BLOCK_ID>"' "<DATASET_OUTPUT>/documents/<PAPER_ID>.json"
```

把尖括号中的占位符替换为当前记录的真实值。最后一个命令要对 `evidence.block_ids` 中的每个 ID 分别执行。

### 7.2 分开检查四件事

- **问题**：语句是否自然、含义是否唯一、没有泄露答案？
- **答案**：是否直接回答问题，且没有混入不必要内容？
- **证据**：原文是否明确支持答案，而不只是主题相关？
- **定位**：页码、文本块与边界框是否指向同一段原文？

不能因为答案“看起来合理”就判定正确；Gold 要求答案能被所附证据直接支持。

当前两类题都是抽取式问题：规范化空白后，`answer` 应与所选 `evidence.text` 一致。将来如果允许同义表述，应通过正式 Gold schema 的 `acceptable_answers` 明确记录，不能在本轮悄悄改成自由生成式评分。

### 7.3 给出决定

| 决定 | 什么时候使用 | 后续处理 |
|---|---|---|
| `keep` | 问题、答案、证据和定位均正确 | 可进入复核 |
| `edit` | 题意有效，但可通过有限修改修正 | 填写完整修订版本后复核 |
| `reject` | 题型不适用、来源错误、歧义严重或无法可靠修复 | 保留审计记录，不进入 Gold |
| `needs_adjudication` | 两轮意见冲突，当前无法决定 | 进入裁决队列 |

`edit` 不是只写一句“答案需要修改”，而是必须把新的问题、答案和证据完整填入 `proposed_revision`。

字段填写必须遵守：

- `keep`：所有 `checks` 为 `true`、`issue_codes=[]`，修订字段保持为空；
- `edit`：至少一项检查为 `false`、至少一个错误码，并填写完整修订；
- `reject`：至少一个错误码和非空 `notes`，修订字段保持为空；
- `needs_adjudication`：至少一个错误码和说明，记录进入待裁决状态；
- 使用 `OTHER` 时，`notes` 必须解释具体问题。

如果修改了证据，必须重新选择真实的 `block_ids`；`page_number`、`bbox` 和 `bbox_normalized_top_left` 应由后续校验/构建脚本根据文本块重新计算。在工具尚未实现前先保留为 `null` 并进入待处理队列，不能手工猜坐标后导出 Gold。

本 v1 的 `question_type` 只允许 `abstract_evidence` 和 `method_section_locator`。`keep` 与 `edit` 都必须保持原 Silver 题型；如果必须改变题型，说明已超出有限修正范围，本轮应 `reject`，留到后续人工新题版本处理。

## 8. 两类问题的判定标准

### 8.1 `abstract_evidence`

合格记录应满足：

- 证据确实来自论文摘要；
- 文本能表达论文要解决的问题、目标或核心工作；
- 答案是摘要中能够完整支持问题的原文证据；
- 文本上下文完整，没有因双栏、换行或页眉页脚造成拼接错误。

下列内容通常不能当作摘要证据：关键词、作者单位、ACM Reference Format、版权声明、目录、只介绍领域常识的背景句、摘要尾部残句或正文中再次出现的相似段落。

### 8.2 `method_section_locator`

人工应查看章节标题的相邻正文，判断它是否确实开始介绍作者的方法、模型、框架或算法。但是在本 v1 中，`answer` 和 `evidence.text` 仍只保存章节标题原文，不把相邻正文拼入证据。

合格标题通常不是：

- 论文标题、摘要、Introduction；
- Related Work、Background、Motivation、Preliminaries；
- Baselines、Experiments、Results、Ablation；
- 单独的公式编号或图注。

综述、立场文或数据说明类论文可能没有“作者方法章节”。这种情况使用 `reject` 和 `NOT_APPLICABLE`，不要为了凑题数强行把普通章节认作方法章节。

## 9. 统一错误代码

每条记录可以填写多个 `issue_codes`。只用以下固定值，详细情况写入 `notes`：

| 错误代码 | 含义 |
|---|---|
| `NOT_ABSTRACT` | 所选文本不是摘要 |
| `WRONG_SECTION` | 章节识别错误 |
| `WRONG_ANSWER` | 答案错误或答非所问 |
| `WRONG_EVIDENCE` | 证据不能支持答案 |
| `WRONG_PAGE` | 页码错误 |
| `EVIDENCE_NOT_EXTRACTIVE` | 声称为原文证据但无法在来源中找到 |
| `INCOMPLETE_CONTEXT` | 上下文被截断，无法独立判断 |
| `LAYOUT_NOISE` | 双栏、页眉页脚或版面解析噪声 |
| `HYPHENATION` | 断行连字符影响文本 |
| `OCR_ERROR` | OCR 或字符识别错误 |
| `QUESTION_NOT_NATURAL` | 问题表达不自然 |
| `AMBIGUOUS_QUESTION` | 存在多个合理解释 |
| `MULTIPLE_VALID_ANSWERS` | 未约束到唯一或可接受答案集合 |
| `NOT_APPLICABLE` | 该论文不适合此题型 |
| `DUPLICATE_QUESTION` | 与另一题重复 |
| `LEAKAGE_RISK` | 可能泄露测试信息或被用于调参 |
| `OTHER` | 其他问题，必须在备注中解释 |

## 10. 如何填写审阅 JSONL

JSONL 是“一行一个完整 JSON 对象”，不是一个外层数组。复制[公开审阅模板](templates/review-record.template.json)到私有目录后，每道题最终只保留一条合并记录。

公开模板为了便于阅读使用多行缩进。实际保存 `questions.review.jsonl` 时，要把每个对象压缩成一行；也可以先将每题保存成单独的 `.json`，复核无误后再导出。

关键字段：

- `annotation_record_id`：格式为 `annotation-` 加 16 位小写十六进制，创建一次后不再改变；
- `source`：其中三个 ID 必须逐字等于 Silver；同时记录 release ID、Silver 文件哈希和 `source_checksums.sha256` 的哈希；
- `record_status`：`draft`、`round_1_complete`、`round_2_complete`、`pending_adjudication` 或 `resolved`；
- `review_protocol`：双人时为 `independent_two_reviewer`，单人间隔复查时为 `single_reviewer_interval_recheck`；
- `reviews.round_1` / `round_2`：两轮判断；
- `checks`：问题清晰度、答案正确性/唯一性、证据、页码及版面定位；
- `decision`：`keep`、`edit`、`reject` 或 `needs_adjudication`；
- `issue_codes`：上节定义的标准错误码；
- `proposed_revision`：`edit` 时的完整修订内容；
- `confidence`：只允许 `high`、`medium`、`low`；
- `resolution`：无论是否发生冲突，都在这里写唯一最终决定；
- `gold_export`：是否满足导出条件。

`resolution.status` 只允许 `not_evaluated`、`not_required`、`pending`、`resolved`；`final_decision` 只允许 `keep`、`edit`、`reject`，不能继续是 `needs_adjudication`。

源 ID 必须符合：

```text
question_id          ^eval-[0-9a-f]{16}$
paper_id             ^paper-[0-9a-f]{16}$
work_id              ^work-[0-9a-f]{16}$
annotation_record_id ^annotation-[0-9a-f]{16}$
gold_question_id     ^gold-[0-9a-f]{16}$
```

以下所有 `.venv/bin/python` 命令都必须先进入 ScholarMind 仓库根目录。可用项目环境生成一次性新 ID：

```bash
cd "<SCHOLARMIND_REPO>"
.venv/bin/python -c 'import secrets; print("annotation-" + secrets.token_hex(8))'
.venv/bin/python -c 'import secrets; print("gold-" + secrets.token_hex(8))'
```

`reviewed_at_utc` 和 `resolved_at_utc` 使用带时区的 RFC 3339，推荐 UTC，例如 `2026-08-01T08:30:00Z`。不要填写本地时间却省略时区。

先把每道合并完成的记录保存为 `reviews/records/<annotation_record_id>.json`。然后按文件名排序，一次性覆盖重建 JSONL：

```bash
.venv/bin/python -c 'import json,pathlib,sys; [print(json.dumps(json.loads(p.read_text(encoding="utf-8")), ensure_ascii=False, separators=(",", ":"))) for p in sorted(pathlib.Path(sys.argv[1]).glob("*.json"))]' "<ANNOTATION_ROOT>/paper-eval-v1/reviews/records" > "<ANNOTATION_ROOT>/paper-eval-v1/reviews/questions.review.jsonl"

.venv/bin/python -c 'import json,sys; rows=[json.loads(x) for x in open(sys.argv[1], encoding="utf-8") if x.strip()]; assert len(rows)==42, f"expected 42 records, got {len(rows)}"; assert len({r["annotation_record_id"] for r in rows})==42, "duplicate annotation_record_id"; assert len({r["source"]["question_id"] for r in rows})==42, "duplicate or missing question_id"; print("JSONL syntax/count/IDs OK")' "<ANNOTATION_ROOT>/paper-eval-v1/reviews/questions.review.jsonl"
```

不要用 `>>` 对同一最终文件反复追加；它会静默制造重复记录。上述检查只覆盖 JSON 语法、数量与两个 ID 的唯一性，完整字段和证据仍需未来的正式验证器检查。

公开模板是教学用的草案结构，不是当前项目已有 schema 的替代品。真实标注程序上线后，还应为 Review 与 Gold 分别建立正式 JSON Schema 和验证器。

## 11. 两轮复核怎么做

### 有两位标注者

拆分任务前，由协调者为 42 道题各生成一次 `annotation_record_id`，连同相同的 `source` 字段复制到两轮工作文件。两轮合并时必须用 `question_id + annotation_record_id` 对齐，只复制各自负责的 round；标注者不能自行重新生成 ID。

1. 标注者 A 只在自己的 `round-1.work.jsonl` 填 `round_1`；
2. 标注者 B 在看不到 A 文件的情况下，只在 `round-2.work.jsonl` 填 `round_2`；
3. 两人使用不同匿名代号；两份文件锁定后才合并到 `questions.review.jsonl`；
4. 按下表生成 `resolution`，不能简单用第二轮覆盖第一轮；
5. 有冲突时由裁决者查看两轮与 PDF，填写最终结论、理由、代号和时间。

### 只有一位标注者

1. 完成第一轮后至少间隔 24 小时；
2. 第二轮重新打开 PDF，从来源重新判断，不直接复制第一轮；
3. 在 `review_protocol` 中写 `single_reviewer_interval_recheck`；
4. 两轮使用同一匿名代号，第二轮时间必须晚于第一轮；
5. 如实记录为同一标注者复查，不能声称是独立双人标注。

### 唯一最终决定

| 两轮结果 | `resolution.status` | `final_payload_source` 与最终来源 |
|---|---|---|
| 都是 `keep` | `not_required` | `silver`；`final_decision=keep` |
| 都是 `reject` | `not_required` | `none`；`final_decision=reject` |
| 都是 `edit` 且完整修订逐字段相同 | `not_required` | `final_revision`；复制相同修订并令 `final_decision=edit` |
| 决定不同、任一轮待裁决，或修订内容不同 | `pending` → `resolved` | 裁决者填写 `final_decision`、来源和必要修订 |

即使 `status=not_required`，也必须填写 `final_decision`；只有 `resolution` 是 Gold 构建时的权威来源。`reviewer_count` 统计两轮标注者的去重人数，裁决者另记在 `resolver_alias`，不加入该数。

## 12. Gold 导出规则

Gold 数据复制规则是确定的：

| `resolution.final_decision` | Gold 有效载荷 | `review_status` | `derivation` |
|---|---|---|---|
| `keep` | 原 Silver 的题型、问题、答案和证据 | `accepted` | `unchanged` |
| `edit` | `resolution.final_revision` | `corrected` | `corrected` |
| `reject` | 不生成 Gold 记录 | — | — |

导出前还必须满足：

- `record_status=resolved`，且没有待裁决状态；
- 两轮的 `reviewer_alias`、`decision`、全部 `checks`、`confidence` 和 `reviewed_at_utc` 均已填写；
- `review_protocol` 已填写且符合双人或单人间隔复查规则；
- `resolution.status` 只能是 `not_required` 或 `resolved`，`final_decision`、`final_payload_source` 和 `resolved_at_utc` 始终非空；
- `resolution.status=resolved` 时，`resolver_alias` 和 `rationale` 非空；`not_required` 时两者可以为空；
- 修订后的 `page_number`、`block_ids`、`bbox` 和归一化 bbox 均已由程序重算，不能为 `null`；
- `answer` 规范化空白后等于 `evidence.text`；本 v1 的 `acceptable_answers` 保持空数组；
- Gold 的来源 ID 和 `question_type` 逐字等于 Review/Silver，`source_review_record_id` 等于当前 `annotation_record_id`；
- `gold_export.gold_question_id` 等于 Gold 中的 `gold_question_id`，且所有 Review/Gold ID 全局唯一；
- `label_quality=human_verified_gold`、`tuning_allowed=false`。

Review 中的 `gold_export` 也必须与最终文件同步：`keep/edit` 时令 `eligible=true`，填写有效 Gold ID、`human_verified_gold` 以及对应的 `accepted/unchanged` 或 `corrected/corrected`；`reject` 时令 `eligible=false`，其余导出字段保持 `null`。

当前 Silver schema 将质量和审阅状态固定为 Silver 值，所以不要直接在原记录上改常量并声称通过验证。Gold 应使用独立文件、独立 ID 和后续独立 schema。被拒绝的题保留在审计记录中，但不写入 Gold。

本 v1 不接收 `human_authored` 新题。缺题论文应在后续版本定义独立来源、复核和 ID 规则后再补，不能伪造 `source_question_id`。

## 13. 最终质量检查清单

导出前逐项确认：

- [ ] `source_checksums.sha256`、其自身哈希和 Git commit 已记录；
- [ ] 42 条候选题每题恰有一条 `resolved` 记录，ID 无重复、无遗漏；
- [ ] 所有 `edit` 都包含完整修订内容；
- [ ] 所有冲突都已裁决；
- [ ] Gold 中不存在 `reject` 或待裁决记录；
- [ ] 所有证据都能在对应 PDF 页找到；
- [ ] 页码、文本块、边界框与证据一致；
- [ ] Gold、Review、Silver、论文和作品的跨文件引用一致；
- [ ] `tuning_allowed` 全部为 `false`；
- [ ] 私有目录没有被 Git 跟踪；
- [ ] `build_manifest.json` 记录输入/输出哈希、代码 commit、Schema/规范版本、保留/修正/拒绝数、Gold 数量、论文覆盖数和生成时间；
- [ ] `review_summary.md` 记录流程和聚合数量；若公开，不含真实题目、答案、证据、论文标题/路径或审阅者身份。

## 14. 合理时间预算

| 工作 | 预计时间 |
|---|---:|
| 5 道题校准 | 30–45 分钟 |
| 42 道第一轮审阅 | 3.5–5.5 小时 |
| 第二轮复核 | 1.5–2 小时 |
| 冲突裁决与最终检查 | 30–60 分钟 |
| 合计 | 约 5.5–8 小时 |

建议分两天完成，避免后半段因疲劳放宽标准。遇到证据定位困难的题先标 `needs_adjudication`，不要靠猜测快速通过。

## 15. 常见问题

**可以让本地 Qwen 自动完成 Gold 标注吗？**

可以用模型帮助发现可疑项或润色问题，但不能替代人工查看 PDF 和证据。模型建议也必须由人确认。

**最终必须有 42 道 Gold 吗？**

不必须。Gold 质量高于数量，拒绝错误题后可以少于 42 道。本 v1 不补新题；缺题论文留到定义了人工新题来源规则的后续版本。

**文本有换行连字符怎么办？**

若只是显示差异且定位仍明确，记录 `HYPHENATION` 并在规范化文本中修正；若改变含义或无法定位，应修订或拒绝。

**可以把真实 Gold 上传到公开仓库吗？**

按当前项目政策，禁止把真实 Gold、逐题 Review 或论文内容提交到公开仓库。只有完成授权审查并作出明确发布决定后，才能另行制定公开方案；当前只允许公开规范、空模板和不含可还原内容的聚合统计。

## 16. 当前项目已经具备与仍需开发的能力

已经具备：PDF 清单与去重、开发/测试隔离、Silver 候选生成、现有数据校验、本文操作规范和公开空模板。

仍需后续开发：正式 Review/Gold schema、逐题审阅界面或命令行工具、证据修改后的边界框重算、Gold 构建器与 Gold 专用验证器。因此目前应按本文手工记录，并明确标注模板为 `draft-1`，不要声称 Gold 自动化流程已经完成。
