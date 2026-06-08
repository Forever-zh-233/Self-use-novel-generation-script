# StoryDirector 正文摘录输入名实不符修复计划

## 结论

这是 story_director 职责与输入事实不一致：提示词告诉故事总监会看到“最近几章正文摘录”，输入构造也用“最近章节正文摘录”作区块标题，但实现明确“不注入原文”，只从 `state.recent_events` 取事件摘要。故事总监被要求判断读者体验、重复模式、节奏冷热，却没有真实正文片段作为依据。

## 当前证据

- `prompts/story_director.md:13`：提示词写“你会看到……最近几章正文摘录、最近 beat 摘要”。
- `scripts/pipeline/planning.py:53-55`：`recent_text_blob()` 注释明确“用 state.json 的 recent_events + beat 标题，不注入原文”。
- `scripts/pipeline/planning.py:57-65`：实际读取的是 `state.recent_events` 并拼成“最近发生的事”。
- `scripts/pipeline/planning.py:225`：该内容仍以“最近章节正文摘录”标题注入 story_director。
- `runtime/story_director_input.md` 检索没有第 85-87 章真实正文标题或正文段落，只看到卷纲标题等大纲内容。
- `prompts/story_director.md:48`：要求故事总监检查最近 15 章生命危险密度/世界重量。
- `scripts/pipeline/planning.py:225-226`：实际只给 `recent_text_blob(...lookback=3)` 和 `recent_beats_summary(...lookback=5)`。
- `scripts/pipeline/state.py:175`：结构化状态里的 `recent_events` 也只保留最后 6 条，无法支撑“最近 15 章”的判断。

## 根因判断

- 为节省 token，代码把正文摘录替换成事件摘要，但 prompt 和区块标题没有同步改名。
- story_director 的职责包含“读起来顺不顺、重复模式、自然阅读感”，这些不是只靠事件摘要能可靠判断的。
- 事件摘要来自 archivist/state，是二手加工信息；如果正文有句式重复、视角拖沓、氛围过密，摘要可能完全看不出来。
- 世界重量/生命危险密度是跨 15 章的统计性判断，但输入窗口最多 3-6 条事件摘要，职责窗口和输入窗口不一致。

## 影响

- story_director 可能误以为自己看过正文，实际只看了台账事件。
- 对重复句式、节奏疲劳、段落模式、阅读体验的纠偏依据不足。
- 对“最近 15 章是否过轻/过重、生命危险密度是否合适”的判断依据不足，容易把世界重量校准变成猜测。
- 近期已经出现 final_gate 能抓到的句式问题，而 story_director 的输入无法承担同类风格/阅读感监督。

## 治本方案

1. 做职责和输入二选一对齐。
   - 若 story_director 要判断阅读体验：注入每章短正文摘录，优先开头、转折、章末钩子和 gate 命中片段。
   - 若只给事件摘要：prompt 和区块标题改为“最近章节事件摘要”，删除“正文摘录/阅读感”类职责。
   - 若保留“最近 15 章世界重量”职责：注入 15 章结构化窗口，至少包含每章危险等级、失败代价、世界压力来源、情义/天地推进标签。
2. 建立正文摘录压缩策略。
   - 每章 500-800 字，覆盖开头、关键转折、结尾。
   - 同时注入 hard_gate/style_gate 摘要，让总监知道近期风格问题。
3. 增加输入契约测试。
   - 若区块标题叫“正文摘录”，测试断言包含来自 `输出/文章/第NNN章.md` 的真实片段。
   - 若只含 `recent_events`，测试断言标题和 prompt 不得写“正文摘录”。
   - prompt 若要求“最近 15 章”，测试断言 story_director input 含 15 章窗口或明确的统计摘要。

## 验收标准

- story_director prompt 对自己看到的材料描述准确。
- 如果保留“阅读体验/重复模式”职责，输入必须包含真实正文证据。
- 如果保留“最近 15 章世界重量”职责，输入必须覆盖对应窗口。
- 测试能防止“名为正文摘录，实为事件摘要”的回归。
