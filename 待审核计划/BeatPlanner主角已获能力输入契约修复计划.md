# BeatPlanner 主角已获能力输入契约修复计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

BeatPlanner prompt 要求规划前检查主角已有能力是否能更简单解决本章冲突，但实际规划层账本摘要明确不给全量 skills，也没有提供主角当前已获技能清单。职责要求和输入材料不匹配，未来 beat 仍可能设计出“主角明明会却不用”的冲突。

## 当前证据

- `prompts/beat_planner.md:94`：要求 BeatPlanner 对照主角已有能力，检查冲突是否会被能力绕过。
- `scripts/pipeline/planning.py:1395-1403`：`build_beat_input()` 注入故事核、修炼、卷纲、当前状态摘要、正典账本摘要等，但没有独立的主角已获技能 section。
- `scripts/pipeline/context.py:201-202`：`ledger_context_for_planner()` 注释明确“不给全量 facts/secrets/skills”。
- `scripts/pipeline/context.py:374-379`：角色卡技能摘要存在于 Writer 侧详细角色卡构造中。
- `scripts/pipeline/context.py:663` 附近的安全故事核/能力材料属于设定层，不等同于当前已获技能事实。

## 根因判断

- “能力检查”是规划职责，但能力事实主要接在 Writer/FactChecker 侧。
- 故事核和修炼体系只能说明可能能力，不能说明当前已获得、可使用、禁用或过时的技能。
- 为节省 token，规划层摘要排除了 skills，却没有给一个有界的能力摘要替代。

## 影响

- Beat 可能设计主角已有技能可轻易解决的冲突。
- Writer 会忠实执行错误 beat，后续只能靠 Reviewer/FactChecker 返工。
- 质量退化表现为人物降智、能力遗忘、冲突变假。

## 治本方案

1. 增加规划层能力摘要。
   - 只给主角和本章关键角色的当前可用能力。
   - 字段包括 `name/level/source/limits/costs/disabled_reason/last_used_chapter`。
   - 严格有界，避免全量技能库塞入。
2. 调整 BeatPlanner prompt。
   - 明确能力检查以“主角当前可用能力摘要”为准。
   - 没有摘要时不得假设主角会或不会某能力。
3. 统一能力来源。
   - 从实体技能、机制状态、修炼境界、profile 能力窗口生成同一摘要。
   - 与 `Archivist技能库与可用技能清单同步修复计划` 对齐。
4. 增加门禁。
   - beat 输出应在“能力为何用不上/为何仍有冲突”中留下机器可读字段。
   - 若本章冲突被已有能力明显绕过且未解释，Reviewer 或 Beat gate 阻断。
5. 增加测试。
   - 主角有“接骨手法”，beat 设计普通接骨困难但不解释，断言 gate 失败。
   - 有环境限制/代价解释时允许通过。

## 验收标准

- BeatPlanner 能看到当前已获能力的有界摘要。
- beat 不再只靠故事核泛化设定判断能力。
- 已有能力绕过冲突的问题能在规划阶段被拦住。
