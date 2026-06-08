# Reviewer 负向指标阈值统一修复计划

## 结论

Reviewer prompt 内同一负向指标存在两套返工阈值：有的地方写“低于 3 分必须修改”，示例和硬性触发列表又把 3 分或低于 4 分当 blocker。模型会按哪条执行不可控，主流程也难以解释 verdict。

## 当前证据

- `prompts/reviewer.md:21`：原文复写风险和 AI 腔任何一项低于 3 分必须修改。
- `prompts/reviewer.md:248`、`prompts/reviewer.md:307`：继续使用“低于 3 分”口径。
- `prompts/reviewer.md:226`：JSON 示例把 `AI腔检测=3` 写进 blocker。
- `prompts/reviewer.md:261`：硬性触发列表写 `AI腔检测低于4分`。

## 根因判断

- 评分 rubric 多处重复维护，示例、特别说明、硬触发列表没有统一来源。
- “3 分”到底是可用但需建议，还是必须返工，没有被机器契约固定。

## 影响

- Reviewer verdict 可能同分不同判。
- Editor 是否触发取决于模型读 prompt 的哪一段。
- 分数表统计和质量门禁语义不稳定。

## 治本方案

1. 定义唯一阈值表。
   - `AI腔检测`
   - `原文复写风险`
   - `读者体验`
   - `方向对齐`
2. 明确每个分数的语义。
   - 例如 1-2：硬 blocker；3：可用但必须给建议；4-5：通过。
   - 或明确 3 也 blocker，但全 prompt 必须统一。
3. 从阈值表生成或同步 prompt 示例。
4. `parse_review_verdict()` 不推断阈值，只信 JSON；测试单独检查 prompt 阈值一致。
5. 增加 check 测试。
   - 扫描 Reviewer prompt 的阈值声明，防止 `<3` 与 `<4` 并存。
   - JSON 示例与硬触发规则一致。

## 验收标准

- 同一指标只有一套返工阈值。
- 示例、特别说明、硬触发列表一致。
- Reviewer verdict 的 `needs_revision` 可解释。
