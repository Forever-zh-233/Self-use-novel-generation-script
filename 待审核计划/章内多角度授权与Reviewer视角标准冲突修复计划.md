# 章内多角度授权与 Reviewer 视角标准冲突修复计划

## 结论

这是角色职责互相打架：beat_planner / writer / editor 要求或允许主角章节加入“章内多角度叙事”，但 reviewer 的视角评分标准仍把“全章第三人称有限、无跳跃”作为满分标准，只对整章 POV 章提供例外授权。系统缺少“本章允许章内短切”的结构化授权，导致 writer/editor 忠实执行多角度时，reviewer 可能按视角跳跃扣分或触发修稿。

## 当前证据

- `prompts/beat_planner.md:64`：要求在触发条件命中时安排章内短切，连续超过 3 章纯单一视角且有配角在场时必须安排一次。
- `prompts/beat_planner.md:104`：弧线的 `narrative_ops.in_chapter_angles` 命中本章时，必须落实到 `多角度叙事` 字段。
- `prompts/writer.md:103-136`：写手被要求执行章内多角度叙事，beat 给了就必须执行。
- `prompts/writer.md:134`：普通 writer 还允许在 beat 写“无”时自行判断是否安排短切，这意味着未授权短切也可能由 writer 主动产生。
- `prompts/editor.md:44-46`：修稿时要保留配角视角段落，必要时还可以新增短切。
- `prompts/reviewer.md:44`：视角一致性 5 分标准是“全章第三人称有限视角，无跳跃”。
- `prompts/reviewer.md:56`：视角例外只定义为“授权 POV 章”。
- `scripts/run_pipeline.py:708-709`：主流程只在 `视角角色 != 沈安` 的整章 POV 分支给 reviewer 注入授权说明；主角章内短切没有同类授权。

## 根因判断

- “整章 POV 章”和“主角章内多角度短切”是两种不同叙事机制，但 reviewer 只认识前者。
- beat 中的 `多角度叙事` 没有转成 reviewer 可读的授权字段。
- editor 被允许新增短切，但 final review / final gate 不会按“授权短切”重新校准视角标准。
- writer 自主短切没有结构化授权记录，reviewer 无法判断它是“被允许的盲区补视角”还是普通视角跳跃。

## 影响

- writer/editor 执行多角度越认真，越可能被 reviewer 当作视角跳跃。
- reviewer 要求删短切、editor 要求保留或新增短切，形成角色拉扯。
- 后续修复 beat 字段保真后，这个冲突会更明显，因为 `多角度叙事` 字段真正进入 writer/reviewer 链路。

## 治本方案

1. 定义统一的视角授权模型。
   - `视角角色`：整章 POV。
   - `章内多角度叙事`：主角章内短切授权。
   - `allowed_angle_cuts[]`：角色、位置、目的、知识边界、最大篇幅。
2. reviewer 输入中加入“本章授权章内短切”区块。
   - reviewer 对授权短切检查知识边界、篇幅和节奏。
   - 未授权短切才按视角跳跃扣分。
3. editor prompt 与 reviewer prompt 统一术语。
   - editor 新增短切时必须输出或保留可追溯说明，供 reviewer/final gate 判断。
4. 增加测试。
   - fake beat 含授权短切，正文含对应短切，reviewer input 应出现授权说明。
   - fake 正文含未授权短切，reviewer/gate 应能标出视角风险。
   - fake beat 写 `多角度叙事=无` 但 writer 输出配角短切时，必须标 `unauthorized_angle_cut` 或要求 editor/reviewer 复核。

## 验收标准

- 主角章内短切不再被 reviewer 默认为视角跳跃。
- 未授权视角跳跃仍会被识别。
- writer/editor/reviewer 对“章内多角度”的术语和边界一致。
