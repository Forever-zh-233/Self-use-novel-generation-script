# StoryDirector 钩子型重复输入契约修复计划

## 结论

StoryDirector prompt 要求根据最近 beat 摘要里的 `钩子型` 判断短期重复，但主流程注入的 `recent_beats_summary()` 只给标题、冲突和章末钩子文本，没有给结构化 `钩子型`。这会让 StoryDirector 被迫从自然语言钩子里猜类型，无法稳定执行“5 章里 4 章同型则写入 watch_repetition”的职责。

## 当前证据

- `prompts/story_director.md:30`：要求“看最近 beat 摘要里的钩子型标注”，判断 5 章里 4 章同型。
- `scripts/pipeline/planning.py:226`：StoryDirector 输入注入 `recent_beats_summary(chapter, lookback=5)`。
- `scripts/pipeline/planning.py:747-758`：`recent_beats_summary()` 只读取 `标题`、`本章冲突`、`章末钩子`，没有读取或渲染 `钩子型`。
- `scripts/run_pipeline.py:119-130`：`normalize_beat()` 会保留 `钩子型`，说明字段在正式 beat 中可用，只是没有进入 StoryDirector 摘要。

## 根因判断

- StoryDirector 的判断职责扩展后，最近 beat 摘要函数没有同步字段。
- `recent_beats_summary()` 同时给 arc_planner 和 story_director 使用，但注释只说“给 arc_planner 看已经发生了什么”，没有按 StoryDirector 的钩子重复职责渲染结构化诊断字段。
- 结构化诊断字段存在，却被降级成自然语言钩子文本，破坏了防重复判断的稳定性。

## 影响

- StoryDirector 可能漏掉连续同型钩子。
- `watch_repetition` 的依据不可审计：不知道它是看字段判断，还是从文本猜测。
- Hook 自查改写 `钩子型` 后，StoryDirector 仍可能看不到改写后的类型分布。

## 治本方案

1. 拆分最近 beat 摘要用途。
   - ArcPlanner 用实现态/剧情摘要。
   - StoryDirector 用结构化节奏摘要。
2. StoryDirector 专用摘要必须包含：
   - chapter
   - title
   - scene_type
   - tension
   - hook
   - hook_type
   - dominant_strand
   - tone
3. `watch_repetition` 生成时保存依据。
   - 最近 N 章钩子型分布。
   - 哪些章触发重复。
4. 增加测试。
   - 构造最近 5 章中 4 章 `钩子型=悬念`，断言 StoryDirector 输入包含这 5 个 hook_type。
   - hook_type 缺失时，输入应标“缺字段”，不得让模型以为已给完整标注。

## 验收标准

- StoryDirector 能看到它被要求判断的 `钩子型` 字段。
- 钩子重复判断有结构化依据。
- 新增或改名 beat 诊断字段时，StoryDirector 输入测试能同步发现。
