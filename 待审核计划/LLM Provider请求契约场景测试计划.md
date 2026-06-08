# LLM Provider 请求契约场景测试计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

`call_model()` 支持 `openai_responses`、`openai_chat`、`anthropic` 等 provider 分支，但测试主要覆盖配置 helper 和部分 openai_chat 截断重试，没有覆盖每个 provider 的 URL、header、body、token 字段和响应解析契约。某个 provider 分支坏了，只有真实 API 跑到该角色时才会暴露。

## 当前证据

- `scripts/pipeline/api.py:171-187`：读取角色配置并归一 provider type。
- `scripts/pipeline/api.py:187-206`：`openai_responses` 请求 `/responses`，使用 `instructions/input/max_output_tokens`。
- `scripts/pipeline/api.py:207-230`：`openai_chat` 请求 `/chat/completions`，使用 messages 和可配置 token 字段。
- `scripts/pipeline/api.py:231-240`：`anthropic` 分支使用 `x-api-key`、`system/messages/max_tokens`。
- Turing 审计确认：现有测试未覆盖全部 provider body/header/URL 契约。

## 根因判断

- provider 分支是外部接口契约，不能只靠真实调用验证。
- 角色配置“存在”不等于请求格式正确。
- 新增 provider 或 extra_body 时，缺少 fixture 防止某分支回归。

## 影响

- 某角色切换 provider 后才发现 body 字段不兼容。
- token 字段名、base_url join、header 覆盖等错误可能导致运行中断。
- provider 响应解析变化时，角色输出可能为空或误判截断。

## 治本方案

1. mock `http_post()` 建立 provider 请求快照测试。
   - `openai_responses`：URL、headers、body 必须符合契约。
   - `openai_chat`：messages、token field、extra_body、headers。
   - `anthropic`：system/messages/max_tokens、anthropic headers。
2. 覆盖 provider alias。
   - `openai` -> `openai_responses`。
   - `openai_compatible` -> `openai_chat`。
3. 覆盖响应解析。
   - 每个 provider 返回最小合法响应，断言提取文本正确。
   - 截断/空文本走统一错误或重试策略。
4. 加入角色配置矩阵测试。
   - models.json 中每个启用 provider 至少有一个 mock 请求用例。

## 验收标准

- 每个 provider 分支都有无网 mock 契约测试。
- 切换角色 provider 不会等到真实生成时才发现请求格式错。
- URL、header、body、响应解析变化会被测试捕捉。
