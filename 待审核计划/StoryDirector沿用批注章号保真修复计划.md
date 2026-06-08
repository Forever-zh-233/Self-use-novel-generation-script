# StoryDirector 沿用批注章号保真修复计划

## 结论

StoryDirector 批注在未重新调用模型时会复用上一份判断，但主流程会直接把 `chapter` 改成当前章。这样旧判断被伪装成当前章专属批注，导致 Markdown 和 beat 输入出现“标题是第93章，原因却在说第91章”的混合文本。

## 当前证据

- `scripts/pipeline/planning.py:250-253`：未重新调用模型时复制 `previous`，然后直接 `data["chapter"] = chapter`。
- `scripts/pipeline/state.py:441-449`：Markdown 渲染使用 `data.chapter` 作为“章节”。
- `scripts/pipeline/planning.py:1397` 附近：beat 输入直接注入 `story_director_context(chapter)`。
- `runtime/story_director.json:2-8`：当前标为第 93 章，但 `reason` 仍以“第91章正处于……”开头。
- `runtime/story_director.md:3-10`：渲染显示“章节：第93章”，原因和弧线指令仍围绕 91-93/91-95 这批判断。
- `beats/_debug/第091章/beat_input.md:23-30`：原始批注确实曾作为第91章判断进入 beat；后续沿用时应保留“评估章/适用范围”，而不是改写原始章号。

## 根因判断

- `chapter` 同时承担“这份判断由哪章生成”和“当前消费到哪章”的双重含义。
- 沿用逻辑只有过期时间，没有 `evaluated_chapter`、`applies_from`、`applies_until`、`current_consumer_chapter`。
- 渲染层无法表达“这是第91章生成、适用于91-94章、当前第93章正在沿用”。

## 影响

- BeatPlanner 可能把旧判断当成当前章新判断，误解指令粒度。
- 审计时无法判断 StoryDirector 何时真正复评过。
- 批注里出现“第93章/第91章”混合文本，降低下游模型对约束的信任。

## 治本方案

1. 拆分 StoryDirector 元数据字段。
   - `evaluated_chapter`：模型实际评估的章节。
   - `applies_from_chapter` / `expires_after_chapter`：有效范围。
   - `current_chapter`：本次渲染/消费章节。
2. 沿用时不改写 `evaluated_chapter` 和原始判断。
   - 只更新 `current_chapter` 或在渲染函数参数中传入当前章。
3. Markdown 渲染明确显示沿用状态。
   - “评估章：第91章”
   - “当前消费章：第93章”
   - “有效期：至第94章”
4. Beat 输入中的标题改为“故事总监批注（沿用第N章评估）”。
5. 增加 scenario 测试。
   - 构造第91章批注，第92/93章未触发模型。
   - 断言 JSON 保留 evaluated_chapter=91，渲染显示当前消费章但不伪装成新评估。

## 验收标准

- 沿用批注不会改写原始评估章。
- 下游能看懂这是一份跨章有效的批注，而不是当前章重新评估。
- 审计时能准确还原每次 StoryDirector 真正调用模型的章节。
