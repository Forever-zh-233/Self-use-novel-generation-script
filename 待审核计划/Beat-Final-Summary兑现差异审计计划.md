# Beat-Final-Summary 兑现差异审计计划

## 结论

写手有时会越过 beat 的场景边界或角色边界，summary 会如实记录最终正文，但 beat 仍作为规划文本留存。当前管路没有生成“beat 计划 vs final 实现 vs summary 摘要”的兑现差异记录，导致后续很难知道是 beat 未执行、writer 合理演化，还是正文跑偏。

## 当前证据

- `beats/chapter_89.json:31-34`：第 89 章 beat 出场角色只有沈安、黑子。
- `beats/chapter_89.json:28`：第 89 章章末钩子停在“继续朝南”。
- `runtime/summaries/chapter_089.json:55`：summary 记录实际发生为“与韩铮相遇、短暂交流后韩铮离开、沈安返回回春堂”。
- `输出/文章/第089章.md` 实际正文已经写到韩铮出场、对话和返回回春堂。
- `scripts/run_pipeline.py:949-955`：summary 在最终正文后生成，但只作为写作摘要使用。
- 当前没有代码把 beat、final、summary 做结构化差异对账。
- 第 92 章样本：beat 写 `伏笔操作: 无`，正文实际写远志试探与铜牌磕痕，台账把 F-210 标成部分回收，属于“计划字段未标但实现态发生”。
- 第 94 章样本：beat 只写收 F-183 / 酿 F-221，最终正文和 Archivist 新增 F-227/F-228/F-229，应被 delta 标成“计划外新增但已被记录员接受”。
- 第 95 章样本：正式 beat 的 `具体动作` 和 `出场角色` 未列赶路妇人/发烧孩子，`beats/chapter_95.json:20-27`、`beats/chapter_95.json:35-40` 仍停在离镇/韩铮/周济送别；但 debug 输入里卷纲/阶段安排要求官道遇妇人和孩子，见 `beats/_debug/第095章/beat_input.md:411`、`beats/_debug/第095章/beat_input.md:440`。
- 第 95 章最终正文实际写了妇人、发烧孩子、后颈异常、碎屑方向朝下，见 `输出/文章/第095章.md:145-177`；`runtime/state.md:201-203`、`runtime/state.md:250-255` 也把这些写入事实态。这说明同一章里“上游阶段计划”“正式 beat”“最终正文/台账”三层都各自自洽，但缺少 delta 来说明哪里发生了计划变形。
- 第 96 章样本：beat 计划韩铮出场并 `收[F-186]/酿[F-218]`，final 只写匿名东门哨所靴声，`runtime/state.md:207` 明确“但这次不是韩铮”，Archivist 新增 F-234。delta 应能标出 `beat_expected_character=韩铮`、`missing_from_final`、`extra_in_final=东门哨所靴声/F-234`。
- 第 97 章样本：正式 beat 内部同时写“寿命+1”和“寿命+0.5”，final 执行 `+0.5` 且药包未拆，summary 只记“药包硬棱未解”。delta 应能标出 `system_value_conflict`、`outline_requirement_missing_from_beat`、`summary_preserves_uncertain_fact`。
- 第 99 章样本：formal beat 是“翻页/巷子喊名/小满问还要走多久/黑子往前走”，见 `beats/chapter_99.json:7-11,18-22,28,30`；`beats/_debug/第099章/beat_raw.md:33` 明确 `修炼锚点=无`。
- 第 99 章最终正文却同时写入了卷纲的“第四息过横纹/铁锈味/系统警告眼盲封印松动”，见 `输出/文章/第099章.md:27-37,47-67`；正文又保留 formal beat 的巷口选择和黑子西向钩子，见 `输出/文章/第099章.md:3-13,197-203`。delta 应标出 `final_used_non_formal_outline_event` 与 `formal_beat_missing_core_final_event`。
- 第 99 章分数表与实际正文错位：`输出/分数表/第099章.md:10` 称“小满梦话+黑子停步耳朵转西”未执行，但正文 `输出/文章/第099章.md:197-203` 已执行。这说明 review/score report 也需要与 final hash 绑定，否则会把旧草稿诊断当作当前正文诊断。
- Reviewer prompt 要求“对照 beat 评文”，但 `scripts/pipeline/gates.py:517-558` 的 `parse_review_verdict()` 只保留 `needs_revision/total/blockers/source`，不保存 beat fidelity、scores 或具体兑现差异，因此 reviewer 即使看到了偏差也不会沉淀成后续可读 delta。

## 根因判断

- beat 是计划态，final 是实现态，summary 是实现态摘要；三者没有统一对账层。
- Reviewer 会读 beat 和正文，但评审结果没有沉淀成可供后续管路消费的 delta。
- Archivist 只基于正文做记忆更新，不能告诉后续“哪些 beat 承诺未兑现/哪些正文新增了计划外事实”。
- Review/score report 没有绑定所评正文 hash；正文后续被 editor/fact fixer 改写后，旧评审结论仍可能留在当前章产物里。

## 影响

- 未兑现 beat 字段可能继续被后续当作“本章计划已完成”。
- 正文新增的关键人物、地点、转折如果只在 summary/ledger 中出现，beat 仍会误导规划回顾。
- 排查跑偏时只能人工读三份文件，没有机器可消费的差异报告。

## 治本方案

1. 新增章节兑现审计产物。
   - `runtime/chapter_deltas/chapter_N.json`
   - 字段：`beat_expected`、`final_observed`、`summary_digest`、`matched`、`missing_from_final`、`extra_in_final`、`risk_level`。
2. 审计输入使用标准化 beat、最终正文、summary。
   - 低成本版本先做结构字段对账：标题、POV、出场角色、地点、章末状态、关键物件、转折。
   - 伏笔字段必须对账：beat 计划的 F/LF/EA ID、final 实际触碰的 ID、Archivist 新增/回收的 ID。
   - 语义复杂项可交给 reviewer/LLM delta checker。
3. 后续规划优先读取 delta。
   - 未兑现项不能自动当历史。
   - 计划外新增项如果已被 Archivist 接受，标为实现态事实。
4. Reviewer verdict 增加“beat_fidelity”结构化字段。
   - `parse_review_verdict()` 必须保留该字段，并写入章节审计产物。
   - 若 reviewer 未给 `beat_fidelity`，不能假设 beat 已兑现，只能标为 `not_checked`。
5. 增加 scenario 测试。
   - beat 出场角色不含韩铮，final/summary 含韩铮，delta 必须记录 extra character。
   - beat 钩子说继续朝南，summary 说返回回春堂，delta 必须记录 end-state mismatch。
   - beat 无伏笔但 final/Archivist 新增伏笔，delta 必须记录 `extra_in_final`。
   - beat 计划 F-173 但 final/Archivist 未推进，delta 必须记录 `missing_from_final` 或 `skipped`。
   - beat 未列妇人/孩子，但上游卷纲输入和 final/state 都出现该段时，delta 必须记录为 `formal_beat_missing_upstream_requirement` 或同等风险项，而不是只把它当 writer 自由发挥。
   - beat 内 `寿命+1/+0.5` 这类系统数值冲突，delta 必须记录并阻断后续提交或进入人工复核。
   - formal beat `修炼锚点=无`，final 写入修炼突破与系统警告时，delta 必须记录非 formal 来源，并要求 manifest 标注 `chosen_source`。
   - score report 声称钩子未执行但 final hash 对应正文已执行时，必须标 `review_report_stale_or_wrong_input`。

## 验收标准

- 每章都有机器可读的计划/实现差异记录。
- 后续规划不会把未兑现 beat 终点当成已发生历史。
- 计划外新增事实能被显式标记，而不是悄悄进入记忆链。
