# Archivist 必填字段提交校验修复计划

## 结论

记录员 prompt 明确要求 `dominant_strand`、`cultivation_active`、`timeline_update` 每章必填，但提交前完整性校验只检查 `STRUCTURED_UPDATE` 是否可解析和报告长度。模型漏填这些字段时，主流程仍会提交，三线节奏、修炼实质含量和时间线会静默停更。

## 当前证据

- `prompts/archivist.md:328-335`：`dominant_strand` 每章必填，code 靠它更新三线节奏。
- `prompts/archivist.md:337-342`：`cultivation_active` 每章必填，用来拆分道途线里的修炼实质含量。
- `prompts/archivist.md:412-417`：`timeline_update` 每章必填。
- `scripts/pipeline/archivist.py:149-151`：三线/修炼只在字段存在时消费。
- `scripts/pipeline/archivist.py:795-810`：时间线只在 `timeline_update` 存在且为 dict 时更新。
- `scripts/pipeline/archivist.py:975-995`：`validate_archivist_report()` 只检查报告非空、`STRUCTURED_UPDATE` 存在且 JSON 可解析、报告长度，不检查这些必填字段。

## 影响

- 章节可以“成功完成”，但节奏统计和时间线没有推进。
- Story director 后续看到的三线配比、修炼活跃度和时间状态会滞后或出现问号。
- 这类问题不会触发重试，属于静默数据丢失。

## 修复建议

1. 在 `validate_archivist_report()` 中解析 `STRUCTURED_UPDATE` 后检查必填字段：
   - `dominant_strand` 必须是 `道途线/情义线/天地线` 之一。
   - `cultivation_active` 必须是 `none/trace/active` 之一。
   - `timeline_update` 必须是 dict，至少包含 `day_advance` 或 `time_of_day`。
2. 字段缺失时拒绝提交并触发上层重试；两次仍失败则停章，避免记忆污染。
3. 对历史兼容：
   - 只对新章节严格校验。
   - 旧报告恢复时如果缺字段，可要求重调 archivist，而不是用旧坏报告提交。
4. 增加 scenario 测试：
   - 缺 `dominant_strand` 拒绝提交。
   - 缺 `cultivation_active` 拒绝提交。
   - 缺 `timeline_update` 拒绝提交。
   - 三字段完整时允许提交并推进 `latest_chapter`。

## 验收标准

- 记录员漏填每章必填字段时不会静默提交。
- 三线节奏、修炼实质含量、时间线至少每章有明确记录。
- `scripts/run_tests.py scenario` 覆盖成功与失败路径。

