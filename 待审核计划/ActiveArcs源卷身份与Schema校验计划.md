# ActiveArcs 源卷身份与 Schema 校验计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

`runtime/active_arcs.json` 只保存裸 `arcs` 数组，没有记录这些弧线来自哪一卷、哪份卷纲、哪个章节水位或 schema 版本。BeatPlanner 读取 active arcs 时无法判断它们是否属于当前卷/当前草稿，弧线一旦残留或提前换卷，就会被当成硬约束注入。

## 当前证据

- `scripts/pipeline/state.py:539-546`：`load_active_arcs()` / `save_active_arcs()` 只读写 `{"arcs": arcs}`。
- `scripts/pipeline/planning.py:1175-1212`：ArcPlanner 生成或补线后直接 `save_active_arcs()`，没有写入 source volume 或 plan hash。
- `scripts/pipeline/planning.py:1406-1408`：`active_arcs_for_beat(chapter)` 生成的弧线文本会以“硬约束”注入 BeatPlanner。
- 当前 `runtime/active_arcs.json` 被观察到有 102-130 弧线，但无 source metadata。

## 根因判断

- ActiveArcs 被视为“当前唯一弧线状态”，但缺少判断“当前”的身份字段。
- 写入与读取都没有 schema 校验，无法发现旧格式、旧书残留、卷纲覆盖后未刷新等情况。
- 弧线输入优先级很高，一旦错源，会直接压过 BeatPlanner 的其他规划材料。

## 影响

- 当前卷可能继续执行上一卷或下一卷的弧线。
- 卷纲被重写后，旧 active arcs 仍可能存在并被当作硬约束。
- 弧线 schema 演进时，旧字段缺失不会阻断，只会在下游表现成规划漂移。

## 治本方案

1. 扩展 active_arcs manifest。
   - 顶层字段：`book_id`、`source_volume_id`、`source_volume_range`、`volume_plan_hash`、`arc_schema_version`、`generated_at_chapter`、`valid_chapter_range`、`commit_state`。
   - `arcs` 保留为业务数组。
2. 读取时做身份校验。
   - 当前章节必须落在 `valid_chapter_range`。
   - 当前 active 卷纲 hash 必须匹配 `volume_plan_hash`。
   - `book_id` 必须匹配当前 profile。
3. 写入时做 schema 校验。
   - ArcPlanner 输出缺少必填字段时不保存为 active。
   - 旧格式文件只能进入迁移/只读告警，不得静默作为硬约束。
4. BeatPlanner 注入前降级策略。
   - 身份不匹配时不注入“硬约束”，改为阻断或低优先级告警。
5. 增加测试。
   - active arcs 的卷号与当前章节不匹配时，断言 BeatPlanner 输入不含该硬约束。
   - 卷纲 hash 变化后旧 arcs 失效。
   - 旧格式 active_arcs 文件触发 schema 告警。

## 验收标准

- ActiveArcs 能说明自己来自哪一卷、哪份卷纲、覆盖哪些章节。
- 错卷、旧书、旧 schema 的 arcs 不会作为硬约束进入 BeatPlanner。
- ArcPlanner 写入和 BeatPlanner 读取都有同一套 schema 校验。
