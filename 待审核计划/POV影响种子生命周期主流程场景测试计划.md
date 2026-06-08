# POV 影响种子生命周期主流程场景测试计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

现有测试覆盖 `impact_seeds` merge，但没有覆盖章节成功提交后主流程对 seed 的 `deployed/dropped` 生命周期处理。这个逻辑发生在 Archivist 之后，属于提交尾段副作用；只测 merge 不能证明它在真实章节流程里按目标 seed 正确变更。

## 当前证据

- `scripts/run_pipeline.py:1000-1008`：POV 章完成后，按 `who == pov_character` 把第一个 pending seed 标记为 `deployed`。
- `scripts/run_pipeline.py:1010-1022`：章节完成后，解析 `best_window`，超窗 +10 章的 pending seed 标记为 `dropped`。
- Turing 审计确认：现有测试只覆盖 `impact_seeds` merge，未覆盖主流程提交尾段生命周期。

## 根因判断

- seed 生命周期散在主流程尾部，不属于 Archivist merge 自身，因此局部 merge 测试无法证明最终状态。
- 当前 deployed 匹配只按 `who`，缺少 seed_id / source obligation 验证；测试也没覆盖误标风险。
- 超窗 dropped 依赖中文窗口解析，缺少主流程场景验证。

## 影响

- POV 章成功后可能没有正确标记对应 seed，导致后续重复安排 POV 回响。
- 同一角色多个 pending seed 时，可能部署错 seed。
- 超窗 seed 可能长期污染 POV 候选池，或误伤仍可用 seed。

## 治本方案

1. 增加主流程级 POV seed fixture。
   - mock writer/reviewer/editor/fact/archivist，跑到 `run_one_chapter()` 尾段。
   - ledger 中放多个同角色 seed，验证只标目标 seed。
2. 引入 seed_id 对账测试。
   - Beat/arc 中指定 `seed_id` 时，主流程必须按 id deployed。
   - 缺 id 时按 who 匹配必须记录降级风险。
3. 覆盖 dropped 生命周期。
   - pending seed 超过 best_window +10，断言 dropped。
   - 未超窗 seed 保持 pending。
4. 将生命周期写入审计产物。
   - 每章记录 seed 状态变更：deployed/dropped/unchanged 与原因。

## 验收标准

- POV seed 的部署和过期不再只靠 merge 测试间接保证。
- 同角色多 seed 场景不会误标。
- 主流程测试能发现提交尾段副作用漏接。
