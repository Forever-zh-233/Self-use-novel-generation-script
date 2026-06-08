# Summarizer Schema 类型校验与降级修复计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

Summarizer 当前只保证 LLM 输出能解析成 JSON 对象，不校验字段类型。后续 `anti_repeat_for_writer()` 直接把字段当 list/dict 使用；如果模型返回合法 JSON 但字段类型错了，防重复输入会崩或静默产生错误提示。

## 当前证据

- `scripts/pipeline/summarizer.py:22-27`：prompt 定义 `signature_actions`、`sentence_patterns` 等为数组，`recurring_verbs` 为 `{角色名: string[]}`。
- `scripts/pipeline/summarizer.py:77-83`：`_parse_summary()` 只 `setdefault` 补默认值，没有校验已有字段类型。
- `scripts/pipeline/summarizer.py:116-118`：`anti_repeat_for_writer()` 直接 `extend(s.get("sentence_patterns") or [])`，并对 `recurring_verbs` 调 `.items()`。
- `scripts/pipeline/summarizer.py:119`：默认把 `verbs` 当可迭代列表扩展。

## 根因判断

- “JSON 可解析”被误当成“schema 合法”。
- Summarizer 是非关键路径，解析失败会回退空摘要；但类型错属于“半坏数据”，既不会触发回退，也会流入消费者。
- 生产者和消费者之间没有共享 schema / normalizer。

## 影响

- `recurring_verbs` 如果是数组/字符串，`.items()` 会报错，影响后续 writer/reviewer 输入构造。
- `sentence_patterns` 如果是字符串，`extend()` 会按字符拆散，生成无意义禁用句式。
- 摘要缓存一旦落盘为坏类型，会持续污染最近 N 章防重复逻辑。

## 治本方案

1. 为 Summarizer 建立 schema normalizer。
   - 顶层必须是 dict，否则回退空摘要。
   - `chapter` 强制 int。
   - `signature_actions/sentence_patterns/imagery_used/emotional_moves` 强制为 `list[str]`，非列表则清空或包成单元素需有明确策略。
   - `recurring_verbs` 强制为 `dict[str, list[str]]`，非 dict 则清空；value 非 list 则清空该角色。
   - `plot_digest` 强制 string。
2. 消费端也做防御。
   - `anti_repeat_for_writer()` 读取缓存摘要时再次走 normalizer，避免旧坏缓存崩溃。
3. 落盘审计。
   - 如果字段被降级，记录 `schema_warnings` 或日志，方便发现模型输出漂移。
4. 增加测试。
   - 合法 JSON 但 `recurring_verbs=[]`，断言不崩且降级为空 dict。
   - `sentence_patterns="X没Y"`，断言不会按字符拆分。
   - 旧缓存坏类型被读取时，断言 writer 防重复仍能生成或安全为空。

## 验收标准

- Summarizer 落盘摘要始终符合消费者预期类型。
- 坏类型 JSON 不会让防重复模块崩溃。
- 测试覆盖“可解析但类型错”的半坏输出。
