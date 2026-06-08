# ActiveArcs 实体别名与事实态 Canonical 对账计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

`active_arcs` 使用的计划态人物名与 `state/ledger` 的事实态人物名缺少 canonical 合并。第105章输入里，同一位捞鞋老人被同时注入为“捞女老汉”和“捞鞋老头”，模型会把同一实体当成两个角色，放大重复事件和角色水位回滚风险。

## 当前证据

- `runtime/active_arcs.json:14`：`side_characters` 使用 `捞女老汉`。
- `runtime/active_arcs.json:129`：节点 beat_hint 使用 `捞女老汉`。
- `runtime/active_arcs.json:360`：`characters_involved` 使用 `捞女老汉`。
- `runtime/state.json:820`：事实态实体名是 `捞鞋老头`。
- `runtime/state.json:958-960`：关系事实也使用 `捞鞋老头`。
- `输出/章纲/第105章_beat_input.md:622`：实体索引注入 `捞女老汉`。
- `输出/章纲/第105章_beat_input.md:625`：同一实体索引又注入 `捞鞋老头`。

## 根因判断

- ArcPlanner 产物中的人物名是自然语言计划态，Archivist/State 落盘后的实体名是事实态，两者没有 `canonical_entity_id`。
- 别名合并只在部分角色/模块场景里做，没有覆盖 `active_arcs.side_characters / characters_involved / narrative_ops.*.character` 与 `state.characters` 的跨源对账。
- 章节输入构造把弧线实体和事实实体并列注入，没有在进入 BeatPlanner 前做同一实体归一。

## 影响

- BeatPlanner 可能把已发生的捞鞋老人当成另一个待登场角色。
- 已兑现事件会被不同名字重新规划，造成“同一老人/同一怨愿”重复推进。
- 后续关系、知识边界、配角议程可能分裂到两个实体名下。

## 治本方案

1. 为弧线实体建立 canonical 字段。
   - `side_characters[]`、`characters_involved[]`、`narrative_ops.*.character` 增加 `canonical_entity_id` 或 `canonical_name`。
   - 自然语言显示名可保留为 `display_name`，不作为机器主键。
2. ActiveArcs 入库前做实体解析。
   - 与 `ledger.entities`、`state.characters`、book profile aliases 做相似匹配。
   - 相似度高但未能自动确认时，生成待审核 alias proposal，不直接新开实体。
3. BeatPlanner 输入前做去重。
   - 同一 canonical id 的计划态和事实态合并成一个实体块。
   - 显示“计划名/事实名曾不同”，但只给模型一个权威当前状态。
4. Archivist 落账时反查弧线实体。
   - 新事实实体若匹配活跃弧线人物，应回写 canonical id。
   - 不允许同一弧线中同一人物以两个名字并行推进。
5. 增加测试。
   - active_arcs 有 `捞女老汉`，state 有 `捞鞋老头`，断言 BeatPlanner 输入只出现一个 canonical 实体块。
   - 若确实是两个不同角色，必须有 disambiguation 字段说明。

## 验收标准

- 计划态人物和事实态人物通过 canonical id 对齐。
- 同一章节输入不会把同一实体重复注入成两个角色。
- 新别名/疑似同一实体会进入待审核，而不是静默分裂。
