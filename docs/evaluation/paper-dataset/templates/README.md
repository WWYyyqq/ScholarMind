# 论文评测人工标注空模板

本目录只保存公开、未填写的教学模板：

- [`review-record.template.json`](review-record.template.json)：记录两轮人工复核、最终 resolution 和 Gold 导出状态；
- [`gold-question.template.json`](gold-question.template.json)：表示一条最终 Gold 问题。

使用前先阅读 [Silver → Gold 人工标注手册](../silver-to-gold.md)。复制模板后，只能在仓库外或被 Git 忽略的私有目录填写；真实论文内容、题目、答案、证据和审阅记录禁止推送到公开 GitHub。

模板字段已与正式的
[`paper_review.schema.json`](../../../../evaluation/schemas/paper_review.schema.json) 和
[`paper_gold_question.schema.json`](../../../../evaluation/schemas/paper_gold_question.schema.json)
对齐。模板中的 `template_notice` 仅用于公开说明；创建私有工作区时脚本会移除它，
再用正式 Review Schema 验证生成记录。
