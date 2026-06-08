# Archivist Markdown 报告小节提交校验修复计划

## 结论

Archivist prompt 要求输出 `状态台账增量`、`期待账本增量`、`人物内在笔记` 等 Markdown 小节，但 `validate_archivist_report()` 只校验 `STRUCTURED_UPDATE` 和 JSON 可解析。缺小节时 `apply_archivist_update()` 还会静默降级或跳过，导致可读台账和人物笔记缺失而主流程仍提交。

## 当前证据

- `prompts/archivist.md:464`：要求输出 `状态台账增量`。
- `prompts/archivist.md:479`：要求输出 `期待账本增量`。
- `prompts/archivist.md:490`：要求输出 `人物内在笔记`，并标为必写。
- `scripts/pipeline/archivist.py:975-995`：`validate_archivist_report()` 只查报告长度、`STRUCTURED_UPDATE` 存在、JSON 可解析。
- `scripts/pipeline/archivist.py:1016-1025`：缺 `状态台账增量` 时会把整个报告追加进 07，缺 `期待账本增量` 则不追加。

## 根因判断

- 结构化 JSON 校验和 Markdown 报告契约没有统一提交标准。
- “无变化”没有结构化表达，导致缺小节和合法空增量无法区分。
- 报告模式、提交模式没有共享同一套完整性校验。

## 影响

- 07/08 可读台账可能被整份报告污染或漏写。
- 人物内在笔记缺失不会阻断，后续角色弧线输入变薄。
- 使用者看到 Archivist done，但不知道报告其实少了必填小节。

## 治本方案

1. `validate_archivist_report()` 校验必填 Markdown 小节。
   - `STRUCTURED_UPDATE`
   - `状态台账增量`
   - `期待账本增量`
   - `人物内在笔记`
2. 允许显式无变更。
   - 小节必须存在，内容可写“无新增”。
3. `apply_archivist_update()` 不再静默 fallback。
   - 缺小节直接拒绝提交。
   - 报告模式也记录同样的问题。
4. 增加 scenario 测试。
   - 缺期待账本增量不得提交。
   - 缺人物内在笔记不得提交。
   - 小节存在且写“无新增”可以提交。

## 验收标准

- Prompt 必填小节与提交校验一致。
- 缺小节不会静默提交。
- 07/08 追加内容只来自对应小节。
