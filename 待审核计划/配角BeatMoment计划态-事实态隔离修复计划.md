# 配角 BeatMoment 计划态-事实态隔离修复计划

## 结论

`side_characters.beat_moments` 是 arc_planner 规划出的未来动作，但当前管路会把它直接写入正典 ledger，并在对应章节作为“配角议程·本章动作提示”注入 beat_planner。规划态内容因此被事实态账本承载，未来/未发生动作可能被当成既成信息回灌到章纲。

## 当前证据

- `scripts/pipeline/planning.py:1118-1125`：`_ingest_side_characters()` 注释说明会把 `beat_moments` 附到 `arc_core.beat_moments`，供 beat_planner 消费。
- `scripts/pipeline/planning.py:1160-1164`：实际把 `side_characters.beat_moments` 写进 `ledger.entities[*].arc_core.beat_moments`。
- `scripts/pipeline/planning.py:1468-1475`：`build_beat_input()` 会把 `_beat_moments_for_chapter()` 结果作为“配角议程·本章动作提示”注入。
- `runtime/active_arcs.json:18-26`：韩铮 `ch:88` 的 beat_moment 是“灭门夜，韩铮一刀捅死陈家老仆……”。
- `runtime/summaries/chapter_088.json:47`：第 88 章实际摘要只是“沈安被拽、黑子探望、摸到布条后决定出门”，没有发生灭门夜动作。
- `beats/_debug/第088章/beat_input.md:869-870`：同一未发生动作作为本章动作提示注入了第 88 章 beat 输入。

## 根因判断

- `ledger.entities` 同时承载“已发生事实”和“未来计划提示”，缺少 namespace 区分。
- `beat_moments` 没有 `planned/actualized/cancelled` 状态，也没有“本章是否已经发生”的校验。
- 下游命名“本章动作提示”会强化模型把计划当事实执行。

## 影响

- 未来动作可能被提前写进章节，造成抢节点、剧透和节奏坍缩。
- 未兑现计划沉进 ledger 后，会长期污染 writer/beat_planner 的人物理解。
- Archivist 后续若按正文如实记账，会和 ledger 里已有计划态冲突，难以判断谁是正典。

## 治本方案

1. 分离计划态与事实态。
   - `ledger.entities` 只保存已发生事实、已知边界和当前目标。
   - arc 规划动作保存到 `runtime/arc_plan_index.json` 或 `ledger.planned_character_beats`。
2. 给 beat_moments 加状态字段。
   - `planned_chapter`
   - `status: planned | actualized | skipped | superseded`
   - `source_arc_id`
   - `actualized_chapter`
3. beat_planner 输入只读取状态为 `planned` 且匹配本章的计划。
   - 文案改为“规划候选动作”，不要写成“事实提示”。
   - 明确“可顺势调整，不得把未发生内容当历史回忆”。
4. Archivist 提交后对计划态做 reconcile。
   - 正文确实发生：标 `actualized`。
   - 正文未发生：保留为 planned 或标 skipped，不能变成事实。
5. 增加 scenario 测试。
   - arc_planner 产出第 N 章未来动作，未发生前不得进入实体 facts/secrets。
   - build_beat_input 只注入计划态区块，且不出现在正典事实区块。
   - summary/archivist 未兑现时，计划状态不会被误标事实。

## 验收标准

- 规划态配角动作不再写入正典事实字段。
- beat_planner 能看到本章相关计划，但不会把它误认为已发生历史。
- 计划兑现与否有明确状态，而不是靠正文和 ledger 互相猜。
