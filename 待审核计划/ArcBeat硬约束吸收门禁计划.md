# Arc-Beat 硬约束吸收门禁计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

ArcPlanner 传给 BeatPlanner 的 POV、伏笔、暗线、多角度、高潮关键章等内容被文本标成“必须执行/硬约束”，但主流程只做 StoryDirector 方向检查，没有机器门禁确认 Beat 是否吸收了这些弧线硬约束。结果是 ArcPlanner 写了，BeatPlanner 可以漏，主流程仍保存 beat 并进入正文生成。

## 当前证据

- `scripts/pipeline/planning.py:1283-1300`：当前节点 `narrative_ops` 被写成“必须执行”，包括 POV、伏笔、暗线。
- `scripts/pipeline/planning.py:1320-1322`：章内多角度提示要求必须落实到 beat 的 `多角度叙事` 字段。
- `scripts/pipeline/planning.py:1323-1333`：高潮节点要求 BeatPlanner 必须标 `关键章=true`。
- `scripts/pipeline/planning.py:1406-1408`：当前弧线走向作为“硬约束”注入 BeatPlanner。
- `scripts/run_pipeline.py:310-328`：主流程已知的 beat 后检查主要是 `beat_direction_check()`。
- `scripts/run_pipeline.py:138-178`：已有检查偏 StoryDirector / 重复钩子，不覆盖 arc narrative_ops 的吸收。

## 根因判断

- “硬约束”只存在于 prompt 文本中，没有结构化 obligation ledger。
- ArcPlanner 输出没有转成可机器验证的待兑现项。
- BeatPlanner 保存前缺少 arc-to-beat absorption gate，导致职责链断在“模型应该听话”。

## 影响

- POV 章可能没有切 POV，暗线/伏笔/多角度节点可能漏掉。
- 弧线高潮标记可能未进入 `关键章`，Writer 因而不会按关键章爆点写。
- 用户看到“弧线规划已经写了”，但实际后续章节没有执行，问题很晚才暴露。

## 治本方案

1. 生成结构化 arc obligations。
   - 从当前章节相关 `narrative_ops`、`multi_angle`、`tension` 中提取 `obligation_id/type/source_arc/source_node/required_field/expected_value/severity`。
2. Beat 保存前执行 absorption gate。
   - 检查 `视角角色`、`叙事手法`、`伏笔操作`、`多角度叙事`、`关键章` 等字段是否吸收 obligation。
   - 严重项未吸收时退回 BeatPlanner 重试，而不是保存。
3. 输出审计报告。
   - 每章保存 `runtime/arc_obligations/chapter_N.json`，记录 fulfilled/missing/waived。
   - waiver 必须有明确理由，如“角色未出场且 arc 节点已迁移”，不能空跳。
4. 主流程测试补强。
   - 构造 arc 要求 `关键章=true`，Beat 返回 false，断言触发重试/失败。
   - 构造 POV obligation，Beat 默认沈安视角，断言拦截。
   - 构造多角度 obligation，Beat 写“无”且无理由，断言拦截。

## 验收标准

- ArcPlanner 的硬约束不再只靠 prompt 文本自觉执行。
- BeatPlanner 输出保存前能证明每条弧线 obligation 已吸收或被显式豁免。
- 主流程测试能复现并拦住“弧线写了但 beat 没接”的问题。
