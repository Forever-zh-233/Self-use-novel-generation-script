# Analyst REDUCE 输出预算契约计划

## 结论

Analyst REDUCE prompt 要求最终产出 8 个 chunk，且每个 chunk 控制在 800-1200 字；但最终归并调用只给 analyst 默认 7000 output tokens。按最低 8×800 字计算，正文就约 6400 中文字，还没算文件分隔符、标题、规则编号和说明；按高端则约 9600 字。输出预算与 prompt 规模目标打架，容易导致截断、压缩违约或内容变薄。

## 当前证据

- `prompts/analyst_reduce.md:19-25`：要求本次产出多个固定手法 chunk。
- `prompts/analyst_reduce.md:76-84`：示例覆盖到 8 个 chunk，并要求每个 chunk 800-1200 字。
- `scripts/run_pipeline.py:1588-1594`：最终 prose REDUCE 调用 `role_max_output_tokens("analyst", 7000)`。
- `scripts/run_pipeline.py:1579-1584`：中间 merge 层也使用 `role_max_output_tokens("analyst", 7000)`。

## 根因判断

- Prompt 的产物规模是按“文件数量 × 每文件字数”定义的，但代码输出预算是固定兜底值，没有从目标产物规模推导。
- `role_max_output_tokens()` 只看角色默认值，不知道这次 REDUCE 需要产出多少 chunk。
- 现有截断重试能处理供应商 max_tokens 截断，但不能解决 prompt 自己把模型逼到“必须少写才不截断”的矛盾。

## 影响

- Analyst 最终 chunk 可能缩水，写手读到的手法卡变空泛。
- 模型为了塞进预算会牺牲具体规则，违背“宁可具体扎实，不要笼统空泛”的 prompt 要求。
- 若发生截断，后续 split/calibrate 可能吃到半截 chunk 或格式不完整输出。

## 治本方案

1. 给 Analyst REDUCE 定义产物规模契约。
   - 读取目标 chunk 数和每 chunk 字数区间。
   - 根据中文 token 估算加安全系数计算 `max_output_tokens`。
2. 区分 merge 层和 final reduce 层预算。
   - merge 层可以摘要化。
   - final reduce 必须满足完整 chunk 产出预算。
3. 增加输出完整性校验。
   - 必须出现全部 `=== FILE: chunk_xxx.md ===` 分隔符。
   - 每个 chunk 字数低于下限时标记为不完整，而不是默默接受。
4. 截断重试时不仅加预算，还要把“缺哪些 chunk/哪些 chunk 太短”反馈给 REDUCE。
5. 增加测试。
   - prompt 目标为 8 个 chunk 时，预算函数不得低于最低估算。
   - fake reduce 缺 chunk 或 chunk 太短时校验失败。

## 验收标准

- REDUCE 输出预算与 prompt 产物规模一致。
- 缺 chunk、半截 chunk、过短 chunk 不会被当作有效分析成果。
- 写手手法卡不会因为预算矛盾系统性变薄。
