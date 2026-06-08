# Provider ExtraBody 作用域契约计划

## 结论

配置说明把 `extra_body` 描述成“服务商固定请求体参数”的通用能力，但代码只在 `openai_chat` 分支合并 `extra_body`。`openai_responses` 和 `anthropic` 分支不会使用该字段。当前是文档契约和实际 provider 行为不一致。

## 当前证据

- `config/配置说明.md:71-77`：泛称服务商需要固定请求体参数时可以加 `extra_body`。
- `scripts/pipeline/api.py:187-205`：`openai_responses` 请求体没有合并 `configured_extra_body(cfg)`。
- `scripts/pipeline/api.py:207-218`：只有 `openai_chat` 分支执行 `body.update(configured_extra_body(cfg))`。
- `scripts/pipeline/api.py:231-249`：`anthropic` 请求体没有合并 `extra_body`。
- `tests/quick_test.py:94-131`：只测配置合并/key 顺序，没有测试不同 provider type 的请求体行为。

## 根因判断

- `extra_body` 最初服务 OpenAI-compatible chat/completions 场景。
- 文档后来写成 provider 通用能力，但代码没有定义各 provider 是否支持、如何合并、哪些字段禁止覆盖。

## 影响

- 用户给 Responses 或 Anthropic provider 配 `extra_body`，会以为生效但实际被忽略。
- 如果未来直接给所有 provider 合并，也可能覆盖 `messages/max_tokens/system` 等核心字段，造成新风险。

## 治本方案

1. 明确 `extra_body` 作用域。
   - 方案 A：文档写清仅 `openai_chat` 支持。
   - 方案 B：为各 provider 显式实现并测试。
2. 若选择通用化，增加 provider-specific 合并白名单/黑名单。
   - 禁止覆盖核心字段。
   - 对 Responses/Anthropic 使用各自命名。
3. 增加 quick 测试。
   - `openai_chat` extra_body 生效。
   - `openai_responses/anthropic` 若不支持，应报配置提示或在文档中明确。
   - 若支持，断言请求体合并结果。

## 验收标准

- 用户能从配置说明准确知道 extra_body 对哪些 provider 生效。
- 不存在“配置了但静默无效”的 provider 参数。
- 请求体扩展不会覆盖核心调用字段。
