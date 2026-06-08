# StructuredState 当前场景与近期活跃角色分域计划

> 状态：待审核。  
> 范围：只治理未来规划输入的语义分域，不修改已落盘正文、beat 或 state 内容。

## 现网证据

- `scripts/pipeline/state.py:302` 用 `_last_active` 和 `gap <= 30` 筛出近 30 章活跃角色。
- `scripts/pipeline/state.py:312` 将这批角色输出为 `【在场角色·N人】`。
- `输出/章纲/第105章_beat_input.md:480` 显示 `【在场角色·29人】`，其中混入远处、已离场、未出场、死亡或不同地点角色。
- `scripts/pipeline/planning.py:953` 与 `scripts/pipeline/planning.py:1401` 将该摘要注入 ArcPlanner / BeatPlanner。
- `prompts/beat_planner.md:40` 要求规划空间布局和出场角色初始走位；`prompts/beat_planner.md:65` 又要求根据“本章有哪些配角在场”安排多角度叙事。

## 根因

当前 section 的真实语义是“近期活跃/近期相关角色”，但标题写成“在场角色”。这不是文案小错，而是消费端语义错配：BeatPlanner 会把它当作可用于本章空间布局、多角度切换、出场角色安排的场内名单。

## 治本动作

1. 将结构化状态分成至少两个语义域。
   - `当前地点/随行角色/本章候选在场角色`：只放当前场景可合理出场的人物。
   - `近期活跃角色/近期相关角色`：只作为关系和债务背景，不得默认出场。
2. 每个角色条目带上 `presence_status` 或等价字段。
   - 可选值示例：`present / nearby / remote / departed / dead / mentioned_only`。
   - 代码只做客观分域，不替 BeatPlanner 判断该角色是否“该出场”。
3. BeatPlanner / ArcPlanner 输入标题必须与真实语义一致。
   - 不允许把 `_last_active` 窗口筛出的名单命名为“在场角色”。
4. 测试使用现网第 105 章样本做回归。
   - 远处、死亡、已离开、未出场角色不得出现在“在场角色”栏。

## 验收

- `structured_state_for_planner()` 不再输出误导性 `【在场角色】` 标题承载近活跃列表。
- BeatPlanner 输入中，“当前可在场”与“近期相关”能被明确区分。
- 第 105 章样本中，周济、韩铮、陈家老仆、巡夜卒等不会被作为当前场景在场角色注入。
- 多角度叙事触发不再因为“近期活跃但不在场”的角色被误判。
