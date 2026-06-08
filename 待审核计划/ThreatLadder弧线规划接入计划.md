# ThreatLadder 弧线规划接入计划

## 结论

`config/threat_ladder.json` 的说明承诺 beat_planner 和 arc_planner 都参考威胁升级阶梯，但当前只接入了 beat_planner。ArcPlanner 在规划弧线节点、敌人强度、高潮层级时看不到这份配置，威胁边界只能等到单章 beat 阶段再补救。

## 当前证据

- `config/threat_ladder.json:2`：说明写明“beat_planner 和 arc_planner 参考此表决定敌人强度”。
- `scripts/pipeline/planning.py:943-1041`：`build_arc_input()` 未读取 `threat_ladder.json`。
- `scripts/pipeline/planning.py:1454-1463`：威胁升级阶梯只在 `build_beat_input()` 中注入。
- `tests/scenario_test.py` 只在临时工作区种了空 threat_ladder 文件，没有断言 ArcPlanner 能收到威胁边界。

## 根因判断

- 威胁表原本是规划层/beat 层共用约束，但只完成了 beat 消费端。
- ArcPlanner 的职责是决定弧长、节点、高潮、敌人层级；如果它拿不到威胁表，beat_planner 只能在单章局部修补。

## 影响

- ArcPlanner 可能提前规划超出当前卷敌人上限的对抗。
- BeatPlanner 即使看到 threat ladder，也可能已经被弧线节点锁进高强度冲突。
- 威胁升级会变成单章补丁，而不是弧线层节奏设计。

## 治本方案

1. 抽出 `threat_ladder_for_chapter(chapter, scope)`。
   - `scope="arc"` 给弧线规划师当前卷和下一卷边界。
   - `scope="beat"` 保持单章当前卷摘要。
2. `build_arc_input()` 注入威胁升级阶梯。
   - 包含本卷敌人 ceiling、BOSS 级别、升级规则。
   - 明确 ArcPlanner 不得规划超 ceiling 的正面战力压制。
3. Prompt 契约同步。
   - `arc_planner.md` 增加一句：节点强度必须遵守输入的威胁升级阶梯。
4. 增加 scenario 测试。
   - 临时 threat_ladder 写入明显规则。
   - 断言 `build_arc_input()` 包含该规则。

## 验收标准

- ArcPlanner 和 BeatPlanner 都能看到各自尺度的威胁边界。
- threat_ladder 的配置说明与实际消费端一致。
- 弧线层不会规划出当前卷不该出现的敌人强度。
