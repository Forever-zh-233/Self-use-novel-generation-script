# MaxRevisions 配置语义与修稿轮次修复计划

## 结论

这是配置语义与主流程行为不一致：`config/run.json` 配置了 `max_revisions=2`，看起来表示 reviewer/editor 可以最多修两轮；但 `run_chapter_pipeline()` 实际只把它当成“是否允许 editor 跑一次”的开关。大于 0 就最多修一次，没有 reviewer→editor→再评审→再修稿的循环。

## 当前证据

- `config/run.json:8`：当前配置为 `"max_revisions": 2`。
- `scripts/run_pipeline.py:622`：读取 `max_revisions = int(run_cfg.get("max_revisions") or 1)`。
- `scripts/run_pipeline.py:739`：只判断 `max_revisions > 0`。
- `scripts/run_pipeline.py:747-767`：只调用一次 editor，并写入 `edited.md`。
- `scripts/run_pipeline.py:773-794`：editor 后只跑一次 final gate，不再进入 reviewer/editor 循环。
- `tests/scenario_test.py` 只覆盖 `max_revisions=0/1` 的续跑/跳过行为，没有覆盖 `max_revisions=2` 应该触发两轮修稿的语义。

## 根因判断

- 参数名叫 `max_revisions`，但代码实现是布尔开关语义。
- reviewer 的 `needs_revision` 只影响第一次 editor 调用，editor 结果没有再次送 reviewer 判断。
- 测试只验证“有无 editor”，没有验证“最大轮数”。

## 影响

- 配置给使用者错误安全感：以为有 2 轮修稿兜底，实际只有 1 轮。
- editor 修后如果仍不达标，只能依赖 final_gate/fact_checker 的局部检查，reviewer 的综合诊断不会再次生效。
- 复杂问题章节可能被一次 editor 粗修后直接推进到 summarizer / archivist。

## 治本方案

1. 明确参数语义二选一。
   - 若只想开关：改名为 `enable_editor_revision` 或 `editor_enabled`。
   - 若保留 `max_revisions`：实现 reviewer/editor 循环，最多执行 N 轮。
2. 若实现多轮修稿：
   - 每轮 editor 后重新运行 gate + reviewer。
   - 若 gate 通过且 reviewer `needs_revision=false`，提前停止。
   - 到达上限仍未通过时停在当前章或生成人工审核阻断。
3. 把 final_gate 与 fact_checker 纳入轮次策略。
   - final_gate hard issue 也可触发下一轮 editor。
   - fact_checker 残留应进入同一修复预算，而不是单独接受现状。
4. 增加 scenario 测试。
   - `max_revisions=2`，fake reviewer 第一轮仍需修、第二轮通过，断言 editor 被调用两次。
   - `max_revisions=1`，第一轮仍失败，断言主流程停机或输出阻断报告。

## 验收标准

- 配置名与实际行为一致。
- `max_revisions=2` 不再等价于“只修一次”。
- 测试覆盖 0/1/2 三种配置语义。
