# StoryDirector 整理债务落账接入修复计划

## 结论

StoryDirector 已经能识别“可整理债务”，但这部分只被渲染成 Markdown 批注，没有进入 active_threads、ledger 或期待账本的结构化提交链。它能说“F-202/F-204 已兑现、T-013 可收束”，但系统不会据此落账，旧债仍以活跃/未回收状态继续污染后续规划。

## 当前证据

- `runtime/story_director.json:14-17`：`tidy_threads` 要求 `F-202/F-204` 标记回收、`T-013` 标记收束。
- `runtime/story_director.md:17-20`：Markdown 批注同样写明可整理债务。
- `runtime/active_threads.json:1915-1922`：`F-202` 仍是 `未回收`。
- `runtime/active_threads.json:1933-1940`：`F-204` 仍是 `未回收`。
- `08-期待账本.md:894-896`：`F-202/F-204` 仍显示 `未回收`。
- `runtime/ledger.json:3460-3466`：`T-013` 仍是 `活跃`。
- `scripts/pipeline/state.py:461-466`：`tidy_threads` 只渲染到 StoryDirector Markdown。
- `scripts/pipeline/archivist.py:998-1014`：提交链只消费 Archivist 的 `STRUCTURED_UPDATE`，没有读取 StoryDirector 的 `tidy_threads`。

## 根因判断

- StoryDirector 是“诊断/批注”角色，不是正典提交者；这是合理边界。
- 但系统没有一座桥把“建议整理债务”转成待确认的结构化提交任务。
- Archivist 也不会自动拿 StoryDirector 的 `tidy_threads` 对照正文，生成对应 `threads_update`。

## 影响

- 已兑现的伏笔继续被当成未回收债务催收。
- 已收束的倒计时/行动线继续影响 story director、arc planner、beat planner 的输入。
- 后续章节可能为了偿还已经偿还的债，再写一遍或硬解释。

## 治本方案

1. 给 `tidy_threads` 建结构化 schema。
   - `{id, kind, suggested_status, evidence_chapter, reason, confidence}`。
   - 不再只存自然语言列表。
2. 建立“债务整理候选队列”。
   - StoryDirector 只写 candidate，不直接改正典。
   - Archivist 在本章提交时读取候选，并对照正文/台账决定是否正式提交。
3. Archivist prompt 和提交校验补齐。
   - 输入中给出待整理候选。
   - 输出必须明确：接受、拒绝或延期，并写理由。
4. 提交时更新两个权威面。
   - `runtime/active_threads.json` / `08-期待账本.md` 中伏笔状态。
   - `runtime/ledger.json` 中 obligations 状态。
5. 增加 scenario 测试。
   - fake StoryDirector 给出 `F-202 resolved / T-013 closed`。
   - fake Archivist 接受候选。
   - 断言 active_threads、期待账本、ledger 都同步更新。

## 验收标准

- StoryDirector 点名“可整理债务”后，不会只停留在 Markdown。
- 债务整理必须经 Archivist 正典提交，不由 StoryDirector 越权改账。
- 已整理债务不再作为活跃债务进入后续规划输入。
