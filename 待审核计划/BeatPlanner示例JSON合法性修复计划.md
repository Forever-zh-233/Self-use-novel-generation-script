# BeatPlanner 示例 JSON 合法性修复计划

## 结论

`prompts/beat_planner.md` 的示例 JSON 存在未转义 ASCII 双引号，严格来说不是合法 JSON。虽然当前解析器有容错，但提示词示例本身不合法，会增加模型输出坏 JSON 的风险。

## 当前证据

`prompts/beat_planner.md:55-59` 示例字段中有未转义引号：

- `没有就写"无"`
- `有什么"处理方式出乎意料"的点`
- `没有写"无"`

这些内容位于 ```json 代码块里，按 JSON 语法应写成：

- `没有就写\"无\"`
- 或改用中文引号 `“无”`
- 或移出 JSON 示例，放到字段说明正文中。

## 影响

- 模型可能模仿示例输出不合法 JSON。
- `extract_json_object()` 虽然有 sanitizer，但不应把 prompt 协议建立在容错上。
- 这会加重 beat 生成失败、重试、断点续跑的不确定性。
- 当前 debug raw beat 已出现真实坏 JSON：第 3、14、18、97 章 raw 输出严格 `json.loads()` 失败，主要是字符串内未转义中文引号，见 `beats/_debug/第003章/beat_raw.md:16`、`beats/_debug/第014章/beat_raw.md:8`、`beats/_debug/第018章/beat_raw.md:8`、`beats/_debug/第097章/beat_raw.md:23`。这与 `prompts/beat_planner.md:25` 的“不要在 JSON 字符串里放未转义的中文引号”要求相冲突。
- `scripts/run_pipeline.py:310` 直接把 `extract_json_object(raw)` 交给 `normalize_beat()`，如果 sanitizer 修出了可解析对象，raw 的原始违法状态不会作为 schema failure 阻断；`scripts/run_pipeline.py:367-368` 虽然记录 raw/retry，但缺少 raw/repair/formal 的来源关系和修复原因。

## 修复建议

1. 修正 `prompts/beat_planner.md` JSON 示例：
   - JSON 字符串内部的 ASCII 双引号全部转义。
   - 或将内部提示改为中文引号。
2. 增加 prompt JSON 示例检查：
   - 抽取 ```json 代码块。
   - 对看起来应该是 JSON 的示例执行 `json.loads()`。
   - 对确实不是完整 JSON 的片段，标注为 `jsonc` 或普通代码块，避免误检。
3. 保留当前 sanitizer，但把它作为兜底，不作为常态。
4. 增加 raw strict parse 门禁。
   - BeatPlanner raw 输出先执行标准 JSON 解析。
   - 严格解析失败时应按 `parse_error` 重试；重试仍失败不得静默进入正式 beat。
   - 若使用 sanitizer 修复，manifest 必须记录 `raw_parse_error`、`repair_rule`、`raw_hash`、`formal_hash`，方便断点续跑判断正式 beat 是原始输出还是修复产物。

## 验收标准

- `prompts/beat_planner.md` 的主 JSON 示例可被标准 JSON 解析。
- `scripts/run_tests.py check` 能覆盖 prompt JSON 示例合法性。
- 历史第 3/14/18/97 章这类 raw JSON 失败样本能进入测试夹具；严格解析失败时不会被误认为“BeatPlanner 成功”。
