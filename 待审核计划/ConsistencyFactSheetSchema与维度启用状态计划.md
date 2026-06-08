# Consistency FactSheet Schema 与维度启用状态计划

## 结论

Consistency Map 只要解析出 JSON 就保存为 fact sheet，缺少字段完整性校验；Check 又把缺失字段当空数组/空对象处理。同时入口宣称“20维度比对”，但部分维度是占位或直接返回空结果，报告没有告诉用户哪些维度真实启用。

## 当前证据

- `scripts/consistency/llm.py:167-169`：截断 JSON 会尝试修复并返回可解析对象。
- `scripts/consistency/mapper.py:167-174`：`parse_json_response()` 成功后直接 `setdefault("chapter")` 并保存，没有 schema 校验。
- `scripts/consistency/mapper.py:185-187`：重跑判据只看 `_parse_error`，不看字段缺失。
- `scripts/consistency/scan.py:68-70`：Check 阶段输出“20维度比对”。
- `scripts/consistency/checker.py:465`：行为习惯相关检查命中后 `pass`，没有产生 issue。
- `scripts/consistency/checker.py:664`：世界观/距离类检查直接 `return []`。

## 根因判断

- Map 输出 schema 没有版本化必填字段表。
- “可解析”被等同于“可用于一致性检查”。
- 检查维度没有 `enabled / disabled / placeholder / not_applicable` 状态，导致报告层无法说明实际覆盖范围。

## 影响

- LLM 截断后修复出的半份 JSON 可能静默通过，缺失维度被 checker 当作“没有问题”。
- 用户看到“20维度”会高估扫描覆盖面。
- 后续新增维度时，如果只写占位函数，不容易被测试和报告发现。

## 治本方案

1. 定义 fact sheet schema。
   - 为每个 schema_version 列出必填顶层字段、关键子字段、类型要求。
   - 缺字段、类型错、空到不可用时标记 `_schema_error`。
2. Map 保存前校验 schema。
   - schema 不合格时不覆盖旧有效 fact，或保存为 invalid 并要求重跑。
   - `run_map_phase()` 汇总 invalid 章节。
3. Check 加载时拒绝 invalid fact。
   - 不把缺失字段当“没有矛盾”。
   - 报告中列出跳过章节和原因。
4. 给每个检查维度注册状态。
   - `enabled`：真实参与并可能产出 issue。
   - `diagnostic_only`：只统计不阻断。
   - `placeholder`：尚未实现，不计入已覆盖维度。
   - `disabled`：配置关闭。
5. Report 输出维度覆盖表。
   - 明确本次启用多少维，哪些只是占位。

## 验收标准

- 截断/缺字段 fact 不会静默参与 check。
- “20维度”口径变成真实启用维度清单。
- 新增占位维度必须在报告中显示为 placeholder，不能伪装成已检查。
