# MasterOutline Schema 校验与摘要字段对齐计划

## 结论

MasterOutline prompt 要求输出 JSON，但生成后没有 schema 校验；下游 StoryDirector 摘要读取的字段与 prompt schema 不完全一致。结果是模型即使按 prompt 输出，`_outline_digest_for_director()` 也可能读不到它想要的字段，全书骨架的全局定位信息会变薄或丢失。

## 当前证据

- `prompts/master_outline.md:12`：要求输出 JSON。
- `prompts/master_outline.md:17`：schema 包含 `volumes/world_geography/power_progression` 等字段。
- `scripts/pipeline/planning.py:351`、`scripts/pipeline/planning.py:370`：`generate_master_outline()` 直接调用角色并写入 `全书骨架.md`。
- `scripts/pipeline/planning.py:171`、`scripts/pipeline/planning.py:186`：下游 `_outline_digest_for_director()` 解析后读取 `core_arc/ending/world_evolution` 等字段。
- Prompt schema 中没有明确的 `world_evolution`，字段名和下游摘要读取存在漂移。

## 根因判断

- MasterOutline schema、下游 digest schema、测试样本没有共享同一份字段定义。
- 生成后没有校验必填字段、未知字段、字段类型或摘要可读性。
- 下游读取字段时容错过宽，字段缺失不会阻断，只会让故事总监失去全局信息。

## 影响

- StoryDirector 看到的“全书骨架摘要”可能缺少世界演化、终局方向或主线弧。
- VolumePlanner/ArcPlanner 可能基于不完整全书骨架继续规划。
- 用户以为生成了全书骨架，实际关键字段未被下游消费。

## 治本方案

1. 定义 MasterOutline schema。
   - 必填字段、可选字段、字段类型、下游消费字段。
   - 明确 `world_evolution` 是否存在；若改名为 `world_geography` 或 `power_progression`，下游同步调整。
2. 生成后做 schema 校验。
   - JSON 可解析。
   - 必填字段齐全。
   - 下游 digest 需要的字段存在或有兼容映射。
3. `_outline_digest_for_director()` 使用同一 schema。
   - 不再读取 prompt 未声明字段。
   - 字段缺失时写诊断，而不是静默变空。
4. 增加测试。
   - fake MasterOutline 按 prompt schema 输出，下游 digest 必须读到核心弧、卷结构、世界/势力演化。
   - fake 输出缺关键字段，生成流程不得覆盖正式 `全书骨架.md` 或必须写待修诊断。
   - prompt schema 与 digest 消费字段不一致时 check 失败。

## 验收标准

- MasterOutline prompt、生成校验、下游 digest 使用同一字段契约。
- 按 prompt 输出的全书骨架能被 StoryDirector/VolumePlanner 稳定消费。
- 错 schema 的全书骨架不会静默成为正式规划依据。
