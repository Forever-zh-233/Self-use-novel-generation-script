# Relationships 账本命名空间收敛修复计划

## 结论

这是记忆账本格式分裂问题。Archivist prompt 同时给出顶层 `relationships` 对象和 `canon.relationships` 数组两套格式；代码也分别把它们写入不同位置。模型按任一“正确示例”输出，都可能只更新一半记忆，导致 state 和 ledger 的关系权威源分裂。

## 当前证据

- `prompts/archivist.md:107`：示例中存在顶层 `relationships` 对象。
- `prompts/archivist.md:258`：同一 prompt 又给出 `canon.relationships` 数组格式。
- `prompts/archivist.md:441`：字段说明里又单独解释 `relationships`。
- `scripts/pipeline/archivist.py:87`：`merge_state_update()` 会把顶层 `relationships` 合并进 state。
- `scripts/pipeline/archivist.py:451-455`：`merge_ledger_update()` 只处理 `canon/ledger` 内部的 `relationships` 数组，并写入 ledger。
- `scripts/pipeline/state.py:28`、`50`：state 与 ledger 都有 relationships 概念，使用者容易混淆权威源。

## 根因判断

- prompt 没有清楚区分“运行态关系摘要”和“正典关系账”。
- 代码允许两个路径同时存在，却没有同步、归一或冲突检测。
- 下游 planner/writer/fact_checker 可能读取不同来源，从而看到不同关系状态。

## 影响

- 关系成长、决裂、信任升级可能只写到 state 或只写到 ledger。
- FactChecker 查关系账时可能漏掉 state 中的关系变化。
- Writer 读 ledger 时可能看不到 Archivist 顶层 relationships 更新，人物关系回滚或停滞。

## 治本方案

1. 收敛关系账权威源。
   - 推荐保留 `canon.relationships` 作为唯一写入格式。
   - 顶层 `relationships` 改名为 `runtime_relationship_notes` 或废弃。
2. Archivist prompt 只保留一种关系输出 schema。
   - `pair`
   - `current`
   - `event`
   - `confidence`
   - `chapter`
3. 提交前做 schema 归一。
   - 如果模型仍输出旧顶层 relationships，转换到新 schema 或拒绝提交。
   - 同一 pair 在两个命名空间同时出现且内容冲突时阻断。
4. 下游读取统一来源。
   - writer / fact_checker / planner 均从 ledger relationships 权威源读取。
5. 增加测试。
   - 顶层 relationships、canon.relationships、两者冲突三种样本。
   - 断言最终只进入一个权威账本，冲突会被捕获。

## 验收标准

- Archivist 关系输出只有一个正典格式。
- state/ledger 不再各自保存互不校验的关系版本。
- 下游角色读取同一份关系权威源。
