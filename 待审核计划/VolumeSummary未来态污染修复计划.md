# VolumeSummary 未来态污染修复计划

## 结论

`runtime/volume_summaries.json` 已写入多条没有提交态、没有来源 hash、没有事实水位证明的卷摘要，其中既有第 100 章“未来完成态”摘要，也有跨书残留的第 247 章摘要。这个文件不是死文件，VolumePlanner 会把它作为“上卷结构化回顾”注入后续规划。也就是说，预测材料、旧书污染、未验收事实都可能被下一卷规划当成已发生历史。

## 当前证据

- `runtime/state.json:2` 当前 `latest_chapter=99`，`runtime/progress.json:2-9` 已进入第 100 章 writer 阶段；运行水位会变化，不能靠人工读当前文件判断摘要是否可信。
- `runtime/volume_summaries.json:8-9`：`volume_end_chapter=95`，但 digest 明写“卷结束章：第100章”，还写系统 LV2、寿命 56、离开青石镇等完成态。
- `runtime/volume_summaries.json:12-13`：`volume_end_chapter=97`，digest 仍明写“卷结束章：第100章”，并包含“碎屑偿愿债（-12→-11）”“叩门突破”“灰蓝布衣二人现身”等没有绑定正文证据的事实。
- `runtime/volume_summaries.json:4-5`：`volume_end_chapter=1`，digest 却写“第247章《山中无岁月》”，疑似旧书/分析样本污染。
- `runtime/volume_summaries.json:16-17`：`volume_end_chapter=102`，digest 仍声称“卷结束章/第100章”，并混入“修炼突破、系统警告、空镇子、竹杖异象”等与 volume_end 不一致的历史摘要。
- 当前文件同时存在多条第一卷/第100章摘要（`volume_end_chapter=95`、`97`、`102`），且事实口径互相冲突；消费端全量拼接会让 VolumePlanner 同时读到多版历史。
- `runtime/volume_digest_raw.md:3-10,23-30` 同样显示第 100 章未来完成态摘要来源。
- `scripts/pipeline/state.py:501-510` 的 `volume_summary()` 会遍历 `volume_summaries.json` 中所有 volumes 并拼入“全书发展历程”，没有按 `status/source_hash/latest_chapter` 过滤。
- `scripts/pipeline/planning.py:618` 会把 `volume_summary(chapter)` 注入 VolumePlanner 的“上卷结构化回顾(承上启下的关键依据)”。
- `scripts/pipeline/planning.py:596-598` 会向 `runtime/volume_summaries.json` 追加 `{volume_end_chapter, digest}`，但缺少生成来源、提交状态、正文 hash、水位校验和跨书污染校验。

## 根因判断

- Volume summary 没有绑定章节提交水位、正文 hash、生成依据范围和书籍/项目身份。
- Volume digest 生成可以基于卷纲/预测材料写“应发生”，但落盘后与“已发生”摘要共用同一位置。
- VolumePlanner 消费时没有区分 `planned_digest`、`draft_digest`、`committed_digest`。
- `volume_summary()` 消费时全量拼接，不会排除 `volume_end_chapter` 与 digest 明示章节不一致、跨书章节号离谱、或未提交状态的条目。

## 影响

- 下一卷卷纲可能建立在未来幻觉摘要上，而不是第 97-100 真实正文。
- 若第 98-100 实际写法改变，volume summary 仍会把旧未来态输送给规划层。
- 叩门突破、愿债变化、灰蓝布衣等强事实会被提前正典化。

## 治本方案

1. 给 volume summary 增加提交态。
   - `status=pending|committed|stale|rejected|foreign_project`
   - `volume_end_chapter`
   - `source_chapter_range`
   - `source_final_hashes`
   - `generated_from=final_text|outline|mixed`
   - `project_id/book_id`
   - `source_waterline`
2. 生成时做水位校验。
   - `volume_end_chapter` 不得大于当前已提交 final/archivist 水位。
   - digest 内明示“卷结束章：第X章”时，`X` 必须等于 `volume_end_chapter` 或写入明确 `planned_end_chapter`，不得混用。
   - 超出当前全书骨架范围或明显跨书的章节号（如第 247 章）直接标 `foreign_project` 并禁止消费。
   - 若基于卷纲预测生成，只能写入 `planned_volume_digest`，不能写入 committed `volume_summaries.json`。
3. VolumePlanner 消费时只读 committed digest。
   - pending/stale digest 必须被标注为不可作为历史事实。
   - 缺 committed digest 时宁可提示“上卷摘要缺失”，不要回退读未来态。
   - 消费前再次按 `project_id/status/source_hash` 过滤，不信任旧文件裸内容。
4. 增加冲突检测。
   - volume summary 声称的关键事实必须能在对应章节 final/summary/state 中找到证据。
   - 找不到时标 `future_fact_leak`。
5. 增加 scenario 测试。
   - 当前 latest=97，digest 写 volume_end=100，必须拒绝作为 committed。
   - VolumePlanner 输入不得包含 pending future digest。

## 验收标准

- 未完成章节的卷摘要不会污染下一卷规划。
- VolumePlanner 的“上卷回顾”只来自已提交正文。
- 每条卷摘要都能追溯到 source chapter range 和正文 hash。
