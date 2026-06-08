# 章节证据 Schema 收敛计划

## 结论

多个待审核计划都在提出章节 manifest、audit manifest、阶段 sidecar、final commit 凭证，但字段边界和落点尚未收敛。如果各自独立实现，测试只能证明“某个文件存在”，不能证明同一章的提交证据链一致。

## 当前证据

- `章节元数据清单与产物链对账修复计划.md` 提出 `runtime/chapter_manifest.json` 或 `runtime/chapters/chapter_N.json`，字段包含 title/pov/hash/commit_status。
- `章节产物审计留痕最小清单修复计划.md` 提出 `runtime/audit/chapter_N.json`，字段包含各阶段输入输出 hash、路径、模型、通过状态。
- `阶段级续跑输入指纹修复计划.md` 提出 `beat.meta.json`、`draft.meta.json`、`review.meta.json`、`edited.meta.json` 等 sidecar。
- 这些计划都指向同一件事：证明 beat、draft、review、edited、final、summary、Archivist 提交属于同一输入版本，但目前没有统一 schema 名称、字段归属和测试层级。
- 第 99 章样本证明证据链不只是“文件是否存在”：`输出/分数表/第099章.md:10` 声称黑子西向钩子未执行，但 `输出/文章/第099章.md:197-203` 已执行；没有 review/score report 对应正文 hash，就无法判断分数表评的是哪一版文本。
- 第 99 章 formal beat 没有修炼锚点，正文却写入修炼突破和系统警告；章节证据 schema 需要能表达 `formal_beat_hash`、`writer_input_hash`、`final_hash`、`non_formal_source_used`，否则只能人工猜混源发生在哪一段。

## 根因判断

- 章节证据链按问题分散设计，没有先定义统一证据模型。
- manifest/audit/stage meta 的职责边界不清，可能重复保存 hash 或漏掉关键状态。
- 恢复、清理、审计、测试各自读取不同证据文件，会再次形成新断链。

## 治本方案

1. 定义统一章节证据 schema。
   - `chapter_identity`：chapter、title、pov、story_time。
   - `stage_commits`：beat/draft/review/edit/fact/final/summary/archive 的 input/output hash、prompt hash、schema version、model role、status。
   - `deltas`：beat-final-summary 差异、F-ID 对账、time anchor 对账、review-score-final hash 对账。
   - `source_decisions`：多源冲突仲裁结果、chosen_source、discarded_source、non_formal_source_used。
   - `retention`：哪些大文件被 clean，保留了哪些 hash/短摘要。
2. 明确文件落点。
   - 可以是单个 `runtime/chapters/chapter_N.json`，也可以拆文件，但必须有 canonical index。
   - sidecar 是阶段缓存凭证，chapter evidence 是提交后的权威索引。
3. 让现有 manifest/audit/续跑计划复用同一 schema 字段名。
4. 增加测试。
   - quick/schema 测字段默认值和旧版本兼容。
   - scenario 测 clean 后仍能证明 final、summary、Archivist 使用同一 final hash。
   - 上游 hash 变化时，下游 stage status 自动失效。
   - reviewer/score report 的正文 hash 与最终正文不一致时，chapter evidence 标为 stale，不得作为当前章质量结论。
   - formal beat 未包含的卷纲事件进入 final 时，evidence 必须记录来源决策或标 `unattributed_final_event`。

## 验收标准

- 章节证据链只有一套 canonical schema。
- 各计划落地后不会产生互不相认的 manifest/audit/meta 文件。
- 恢复、审计、清理和测试都读取同一提交证据。
