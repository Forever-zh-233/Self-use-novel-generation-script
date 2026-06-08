# ArcPlanner 章内多角度字段名断链修复计划

## 结论

ArcPlanner prompt 要求 `in_chapter_angles` 每项使用 `chapter` 字段，但真实 `runtime/active_arcs.json` 使用的是 `ch`。消费端 `planning.py` 只读 `angle.get("chapter")`，导致弧线规划师安排的章内多角度提示没有进入 BeatPlanner。这是上游字段名接线断链，不是单纯的 reviewer 标准冲突。

## 当前证据

- `prompts/arc_planner.md:139-141`：`in_chapter_angles` 每条包含 `chapter`、`character`、`what`、`why`。
- `prompts/arc_planner.md:70-83`、`prompts/arc_planner.md:91-102`、`prompts/arc_planner.md:109-113`：示例 `narrative_ops` 只展示 `pov/foreshadowing/dark_thread`，没有展示 `in_chapter_angles`，模型即使阅读字段说明也容易在示例结构里漏掉该字段。
- `runtime/active_arcs.json:189-194`：第 97 章老妇人视角条目实际使用 `ch: 97`。
- `runtime/active_arcs.json:66-151`：第 94-96 章同类条目也使用 `ch`。
- `scripts/pipeline/planning.py:1316-1317`：消费端遍历 `in_chapter_angles` 后只判断 `int(angle.get("chapter", 0) or 0) == chapter`。
- `prompts/beat_planner.md:104`：BeatPlanner 被要求把弧线的 `narrative_ops.in_chapter_angles` 落实到 `多角度叙事` 字段，但由于字段名不匹配，这条指令实际收不到。

## 根因判断

- ArcPlanner 输出 schema 和消费端字段名没有统一契约。
- `chapter_drift` 使用 `ch`，`in_chapter_angles` prompt 使用 `chapter`，模型沿用了邻近字段 `ch`，但消费者没有 alias。
- 缺少 arc output schema 校验和“规划字段是否被消费”的接线测试。
- 示例 JSON 与字段说明不一致，缺少“示例也必须覆盖新增字段”的 prompt 契约检查。

## 影响

- 第 97 章“老妇人看沈安的手”这类能强化反差的短切不会进入 BeatPlanner。
- 多视角系统会被误判为“模型没写好”，实际是输入没接上。
- 后续即便修复 reviewer 授权，ArcPlanner 的多角度提示仍可能在入口丢失。

## 治本方案

1. 统一字段名。
   - 方案 A：prompt、schema、消费者统一使用 `chapter`。
   - 方案 B：统一归一层支持 `ch -> chapter` alias，但正式 active_arcs 落盘只保留 canonical 字段。
2. ArcPlanner 输出后做 schema 校验。
   - `in_chapter_angles[]` 必须包含章节字段、角色、目的。
   - 未知字段或 alias 使用要记录 normalize warning。
   - prompt 示例必须与 schema 同步；新增字段至少在示例里出现空数组或一条合法样例。
3. BeatPlanner 输入构造增加接线断言。
   - active_arcs 中命中本章的 `in_chapter_angles` 不为空时，beat_input 必须出现对应角色和目的。
4. 与多角度授权计划联动。
   - 被接入 BeatPlanner 的短切还要转成 reviewer/editor 可读授权。
5. 增加 scenario 测试。
   - active_arcs 使用 `ch: 97` 时，归一后 BeatPlanner 输入能看到老妇人短切。
   - active_arcs 使用错误字段且无法归一时，schema 校验失败。

## 验收标准

- `in_chapter_angles` 不再因 `ch/chapter` 字段名漂移丢失。
- ArcPlanner 输出字段、归一层、BeatPlanner 消费端共享同一 schema。
- 第 97 章老妇人短切样本能被测试捕获并接入 beat_input。
