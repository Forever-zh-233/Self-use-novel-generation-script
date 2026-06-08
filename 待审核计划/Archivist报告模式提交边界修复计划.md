# Archivist 报告模式提交边界修复计划

## 结论

这是章节完成状态与记忆写入耦合过深的问题。配置说明允许 `apply_archivist_updates=false`，表示“只看记录员报告不改台账”；但章节完成提交标记 `latest_chapter` 只在 `apply_archivist_update()` 内推进。关闭台账写入后，主流程可以生成正文和记录员报告，却没有独立的“报告模式已完成本章”提交语义。

## 当前证据

- `config/配置说明.md:86`：说明 `apply_archivist_updates=false` 用于“只看报告不改台账”。
- `config/run.json:9`：该开关是正式运行配置项。
- `scripts/run_pipeline.py:960-987`：`apply_archivist_updates=true` 时，记录员报告通过 `apply_archivist_update()` 写入记忆；失败则停章。
- `scripts/run_pipeline.py:988-997`：`apply_archivist_updates=false` 时，只调用 archivist 生成报告。
- `scripts/run_pipeline.py:998`：false 分支之后仍标记 archivist 阶段完成。
- `scripts/run_pipeline.py:1028`：随后仍会清理章节过程产物。
- `scripts/pipeline/archivist.py:999-1000`：`apply_archivist_update()` 的设计说明是“最后才推进 latest_chapter”。
- `scripts/pipeline/archivist.py:1034-1035`：`latest_chapter` 只在 `apply_archivist_update()` 内更新。
- `scripts/run_pipeline.py:196-201`：启动恢复用“正文已落盘但 latest_chapter 落后”判断缺失章节。

## 根因判断

- 系统把“章节完成提交标记”和“台账写入提交”绑定在同一个函数里。
- `apply_archivist_updates=false` 是合法模式，但没有对应的只读报告模式 commit。
- 恢复逻辑不知道“这章是有意不写台账，只生成报告”，会一直把正文超前于 `latest_chapter` 当成待恢复缺口。

## 影响

- 报告模式下，已生成正文和记录员报告的章节无法稳定标记为已完成。
- 下次启动可能反复识别同一批章节为“正文已落盘但记忆未补”，造成重复调用 archivist 或重复清理现场。
- `completed` 进度与 `runtime/state.json.latest_chapter` 表达不同事实，运行状态可审计性下降。

## 治本方案

1. 拆分提交标记。
   - `latest_chapter` 保留为“正典记忆已提交到第 N 章”。
   - 新增 `latest_reported_chapter` 或 `chapter_artifact_commits` 表示“正文/报告模式已完成到第 N 章”。
2. 恢复逻辑按模式判断。
   - `apply_archivist_updates=true`：正文超前于 `latest_chapter` 需要补台账。
   - `apply_archivist_updates=false`：正文和 archive report 已存在且完整时，视为报告模式完成，不重复补台账。
3. 报告模式也要校验 archive report 完整性。
   - 生成报告后跑 `validate_archivist_report()`。
   - 报告不完整仍停章，不把坏报告当完成。
4. progress 中明确写模式。
   - `archivist_mode=apply`
   - `archivist_mode=report_only`
5. 增加 scenario 测试。
   - `apply_archivist_updates=false`，生成正文和完整 archive report。
   - 断言不会推进 `latest_chapter`。
   - 断言会写报告模式完成标记。
   - 再次启动恢复时不会重复调用 archivist。

## 验收标准

- “只看报告不改台账”模式有独立、可恢复的完成语义。
- `latest_chapter` 不再被迫同时表达“记忆提交”和“章节报告完成”。
- 恢复逻辑能区分报告模式缺口和真正记忆缺口。
