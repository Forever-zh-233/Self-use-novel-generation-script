# Reviewer 评分判定一致性门禁计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

Reviewer prompt 明确规定“读者体验低于4分必须修改”“硬性必修条件必须 needs_revision=true”，但代码解析只相信 `needs_revision` 布尔，丢弃 `scores`，也不校验分数与布尔是否一致。Reviewer 如果输出低分却误填 `needs_revision=false`，主流程会放行。

## 当前证据

- `prompts/reviewer.md:230-233`：结构化 JSON 要求 `needs_revision`、`scores`、`total`、`blockers`。
- `prompts/reviewer.md:247-252`：特别说明要求读者体验低于4分、方向对齐低于4分、明显注水等必须修改。
- `prompts/reviewer.md:257-270`：硬性必修条件命中时 `needs_revision` 必须为 true。
- `scripts/pipeline/gates.py:517-558`：`parse_review_verdict()` 只返回 `needs_revision/total/blockers/source`，不读取 `scores`。
- `tests/quick_test.py:79-82`：测试只验证 JSON 能解析出 `needs_revision` 和 `total`。

## 根因判断

- Reviewer 的结构化评分契约没有 schema 校验。
- “分数阈值 -> 必修判定”的规则只存在于 prompt，代码没有二次计算。
- 当前已有“分项评分落盘”计划解决 scores 丢失，但还需要“scores 与 needs_revision 一致性”门禁。

## 影响

- `读者体验=2`、`needs_revision=false` 这类自相矛盾输出会被主流程当通过。
- Reviewer 的好文标准无法稳定触发 Editor。
- 质量闭环过度依赖模型自己遵守 JSON 布尔。

## 治本方案

1. 扩展 `parse_review_verdict()`。
   - 解析并保留 `scores`。
   - 校验 12 项键名和 1-5 分范围。
2. 代码重算必修判定。
   - 任一硬性阈值命中：`computed_needs_revision=true`。
   - `needs_revision` 与 computed 不一致时，以 computed 为准，并记录 `verdict_inconsistency`。
3. blockers 自动补全。
   - 若分数触发必修但 blockers 为空，生成机器 blocker：如“读者体验=2<4”。
4. 增加 Reviewer 重试策略。
   - JSON 缺 scores 或判定矛盾时，可要求 Reviewer 只重出判定块。
5. 增加测试。
   - `scores.读者体验=2` 且 `needs_revision=false`，断言最终需要修稿。
   - `total=22` 以下但 false，断言改为 true。
   - scores 缺项，断言 source 标为 `json_incomplete` 或触发重试。

## 验收标准

- Reviewer 的分项评分会反向约束 `needs_revision`。
- 质量低分不会因布尔填错而放行。
- 评分、blockers、修稿触发之间有可审计一致性结果。
