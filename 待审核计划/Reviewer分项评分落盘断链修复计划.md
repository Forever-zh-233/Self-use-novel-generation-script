# Reviewer 分项评分落盘断链修复计划

## 结论

Reviewer prompt 要求输出 12 项 `scores`，`write_score_report()` 也准备写“各项分数”，但 `parse_review_verdict()` 没有把 `scores` 传下去，导致当前分数表只有总分和阻断原因，缺失分项评分。

## 当前证据

- `prompts/reviewer.md` 要求输出：
  - `scores`：12 项各 1-5 分。
  - `total`：12 项之和。
- `scripts/pipeline/gates.py:517-558` 的 `parse_review_verdict()` 只返回：
  - `needs_revision`
  - `total`
  - `blockers`
  - `source`
- `scripts/pipeline/gates.py:548-553` 在 JSON 解析成功时直接构造新 dict，没有透传 `scores`；即使 reviewer 按 `prompts/reviewer.md:220,231` 输出了 12 项分数，也会在这里丢失。
- `scripts/run_pipeline.py:48-79` 的 `write_score_report()` 会读取 `verdict.get("scores")`，但上游没有保留该字段。
- 当前 `输出/分数表` 已有 74 份报告，扫描结果：
  - 总数：74
  - 缺少 `## 各项分数`：74/74

## 影响

- 人类事后看不到每章 12 项评分走势。
- reviewer 的结构化分项判断被丢弃，质量追踪只能看总分。
- 这不是 Goodhart 回灌问题，因为分数表仍然可以保持 write-only；问题是“应落盘的诊断信息没有落盘”。

## 修复建议

1. 修改 `parse_review_verdict()`，在 JSON 判定块解析成功时保留 `scores`。
2. 对 `scores` 做轻校验：
   - 必须是 dict。
   - 键名可按 reviewer prompt 的 12 项做白名单检查。
   - 值应能转成 1-5 的数字；异常值保留原文也可，但报告应标注异常。
   - JSON 有 `needs_revision` 但 `scores` 缺失/不完整时，`source` 不应继续标成纯 `json`，应标 `json_incomplete` 或触发 reviewer 重试。
3. `write_score_report()` 保持 write-only，不把分数表注入任何角色输入。
4. 增加 quick/scenario 测试：
   - reviewer JSON 包含 `scores` 时，`parse_review_verdict()` 返回包含 `scores`。
   - `write_score_report()` 能写出 `## 各项分数`。
   - reviewer 输入仍不读取 `输出/分数表`。
   - reviewer JSON 缺少部分分项时，报告应显示缺项并记录 `json_incomplete`，不能静默当完整评分。

## 验收标准

- 新生成章节的分数表包含 12 项分数。
- 旧测试“分数表不注入 reviewer”继续通过。
- `scripts/run_tests.py all` 通过。
