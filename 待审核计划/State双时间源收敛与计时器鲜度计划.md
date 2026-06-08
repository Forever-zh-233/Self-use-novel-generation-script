# State 双时间源收敛与计时器鲜度计划

## 结论

`runtime/state.json` 里同时存在顶层自然语言 `story_time` 和结构化 `timeline.absolute_day/time_of_day/pending_timers` 两套时间源。当前两者已经明显分裂：顶层时间到“第二十六天”，结构化时间仍是第 18.2 日。BeatPlanner/Writer 会同时看到两套时间，过期计时器也会按旧 absolute_day 继续注入，导致时间线和紧迫事件判断被旧状态污染。

## 当前证据

- `runtime/state.json:3`：顶层 `story_time` 是“第二十六天清晨至第二十六天午后（山坳口南行·进入无人镇子）”。
- `runtime/state.md:4`：人类可读状态同样写“第二十六天清晨至第二十六天午后”。
- `runtime/state.json:1187-1206`：结构化 `timeline.absolute_day` 仍是 `18.200000000000003`，`pending_timers` 仍含 due_day 20、22、24 的旧事件。
- `beats/_debug/第099章/beat_input.md:486-488`：第 99 章 BeatPlanner 输入已经注入“第18.2日·午后”以及截止第20/24日的旧高紧急计时器。
- `beats/_debug/第099章/beat_input.md:540,574`：同一份输入稍后又写“第二十五天→第二十六天”，形成同章输入自相矛盾。
- `scripts/pipeline/state.py:263-270`、`scripts/pipeline/state.py:288-294`：`structured_state_text()` 和 `structured_state_for_planner()` 优先渲染 `timeline.absolute_day` 与 `pending_timers`。
- `scripts/pipeline/context.py:62-77`：writer 输入会先渲染 `timeline.absolute_day`，再渲染顶层 `story_time`，两套时间同时出现。
- `scripts/pipeline/gates.py:188-195`：过期计时器检测使用 `timeline.absolute_day` 判断，因此旧 absolute_day 会让已过期事件继续看起来没过期。
- `scripts/pipeline/archivist.py:83-85`：顶层 `story_time` 直接由 state update 写入；`scripts/pipeline/archivist.py:795-816`：结构化 timeline 另由 `timeline_update` 单独更新。二者没有一致性校验。

## 根因判断

- `story_time` 和 `timeline` 是同一事实域的两种表达，却没有声明谁是权威源。
- Archivist 可以更新顶层 `story_time` 而不推进 `timeline.absolute_day`，也可以反过来只更新 timeline。
- 上下文构造层没有检查同一 state 内部是否自洽，而是把两套时间都喂给规划/写手。
- pending timers 的鲜度完全依赖 `absolute_day`，当 absolute_day 停更时，旧事件不会正常过期。

## 影响

- BeatPlanner 在第 99 章同时收到“第18.2日”和“第二十六天”的时间信号，只能猜。
- Writer 可能按旧日程写回已过期事件，或误判韩铮/窑厂等紧迫事件仍处在截止日前。
- Fact/gate 的“过期计时器”检查会失效，因为它用旧 absolute_day 判断是否过期。
- 后续时间锚点门禁即便修好了 beat，也会被上游 state 双时间源污染。

## 治本方案

1. 定义唯一权威时间源。
   - 推荐结构化 `timeline` 为权威，`story_time` 由 timeline + location/event 摘要渲染。
   - 或反向由 `story_time` 解析回 timeline，但必须只有一个提交入口。
2. Archivist 提交前做 state 时间一致性校验。
   - `story_time` 中的故事日必须能解析并与 `timeline.absolute_day` 相容。
   - 若只更新 `story_time` 不更新 `timeline_update`，提交失败或标为 `time_source_conflict`。
   - 若只更新 `timeline_update` 不更新可读 `story_time`，由渲染层生成可读文本，不让模型自由写两份。
3. 上下文构造层增加防污染。
   - 发现 `story_time` 与 `timeline.absolute_day` 冲突时，不得把两者并列喂给 BeatPlanner/Writer。
   - 应停机、重建 state 时间，或只注入权威源并附冲突告警。
4. pending timers 鲜度改为基于权威故事日。
   - 到期超过阈值的 timer 必须自动转为 `expired/unresolved`，不能继续显示为未来提醒。
   - timer 需要 `created_chapter/source_hash/status`，便于章节重写时失效。
5. 增加 scenario 测试。
   - state 顶层 `story_time=第二十六天`，timeline `absolute_day=18.2`，构造 beat input 必须失败或产生 `time_source_conflict`。
   - writer_state_digest 不得同时输出两套互相矛盾的时间。
   - due_day 20/24 的计时器在权威第26天时必须标过期，不得继续作为高紧急未来事件注入。

## 验收标准

- state 内部不再有两个互相矛盾的时间源。
- BeatPlanner/Writer 输入只看到一个权威故事日。
- 过期计时器不会因 `absolute_day` 停更而继续污染上下文。
- 第 99 章这类“第18.2日 + 第二十六天”同输入冲突能被测试捕获。
