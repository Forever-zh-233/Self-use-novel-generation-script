# POV 影响种子 seed_id 全链路修复计划

## 结论

POV 章的 `seed_id` 在 `arc_planner` prompt 中是正式契约，但没有进入 beat、writer 输入或完成后的 deployed 标记逻辑。当前账本里暂无 `impact_seeds`，所以没有现行坏数据；但一旦记录员重新产生多颗影响种子，同一角色多 seed 会被错误匹配。

## 当前证据

- `prompts/arc_planner.md:131-138`：`narrative_ops.pov` 必填 `seed_id`（如有）。
- `scripts/pipeline/planning.py:1291-1293`：传给 beat_planner 的 POV 指令只输出角色、类型、时间、锚点、目的，没有输出 `seed_id`。
- `scripts/pipeline/context.py:1352-1356`：`build_pov_writer_input()` 只按 `who == pov_char` 取第一颗 seed。
- `scripts/run_pipeline.py:1000-1008`：POV 章完成后也只按角色名把第一颗 pending seed 标记为 `deployed`。
- 测试覆盖不足：
  - 现有测试覆盖 `impact_seeds` merge，但未覆盖 “arc 指定 seed -> beat -> POV writer -> deployed”。

## 影响

- 同一角色有多颗 pending seed 时，POV 章可能拿错 `ignorant_of` 和 `pov_voice`。
- 被 arc_planner 点名的 seed 可能仍保持 pending，之后又被规划师推荐或超窗 dropped。
- 错误的知识边界会导致 POV 章泄露该角色不该知道的信息，属于穿帮风险。

## 修复建议

1. `active_arcs_for_beat()` 输出 POV 指令时保留 `seed_id`。
2. `beat_planner.md` 明确：若弧线给了 POV `seed_id`，必须在 beat 中保留。
3. `normalize_beat()` 保留 `seed_id` 或在 `多角度叙事/叙事手法` 外新增结构字段，例如：
   - `POV种子ID`
   - `pov_seed_id`
4. `build_pov_writer_input()` 优先按 seed_id 查找 seed；没有 seed_id 时才按角色 fallback。
5. POV 完成后的 deployed 标记同样按 seed_id，避免误关同角色另一颗 seed。
6. 增加 scenario 测试：
   - 同一角色两颗 pending seed。
   - arc/beat 指定第二颗 seed_id。
   - writer 输入只含第二颗的 `ignorant_of`。
   - 完成后只部署第二颗。

## 验收标准

- `seed_id` 从 arc 节点进入 beat JSON。
- POV writer 输入使用指定 seed 的知识边界。
- POV 章完成后只把指定 seed 标为 deployed。

