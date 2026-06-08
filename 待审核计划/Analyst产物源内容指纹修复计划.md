# Analyst 产物源内容指纹修复计划

## 结论

Analyst MAP / MERGE 产物复用指纹只包含格式版本、batch 预算和 analyst prompt hash，没有包含当前源文本分批内容 hash 或 merge 分组内容 hash。源文内容变化、分批内容变化但预算和 prompt 不变时，旧 `map_*.md` / `merge_L*_G*.md` 仍可能被当成有效产物复用。

## 当前证据

- `scripts/run_pipeline.py:1144-1176`：`analyst_fingerprint()` 只由 `ANALYST_ARTIFACT_VERSION`、`batch_budget`、`analyst_prompt_hash()` 组成。
- `scripts/run_pipeline.py:1184-1188`：`fingerprint_ok()` 只比较首行指纹是否等于当前版本/预算/prompt。
- `scripts/run_pipeline.py:1229-1238`：MAP 单批复用旧产物时只检查 `fingerprint_ok(existing, batch_budget)`，没有比对该批源文本内容 hash。
- `scripts/run_pipeline.py:1293-1297`：`run_analyst()` 每次会重新读取源文并分批，但分批后的 batch 内容没有进入旧产物有效性判断。
- `scripts/run_pipeline.py:1567-1584`：MERGE 缓存也只检查同一个 `fingerprint_ok()`，没有包含当前 merge group 内容 hash。

## 根因判断

- 当前指纹证明“同一套 prompt / 预算 / 格式版本”，但不证明“同一份输入内容”。
- MAP 产物的最小依赖应该是 `source_batch_hash`；MERGE 产物的最小依赖应该是 `group_input_hash`。
- 源文路径已经可配置，未来换书或修订源文时，这个缓存会把旧书/旧批次分析结果混入新分析。

## 影响

- 重跑 Analyst 时可能复用旧源文的手法观察。
- MERGE 层可能把旧分组摘要混入新分组，最终 chunk 看起来格式正确但内容来源错位。
- 后续 writer / planner 读到的手法卡可能与当前源文不匹配，排查时只看 prompt hash 会误以为缓存可靠。

## 治本方案

1. 升级 MAP 指纹。
   - 指纹字段包含 `schema_version`、`batch_budget`、`prompt_hash`、`source_path`、`source_file_hash`、`batch_index`、`batch_hash`。
   - 复用前必须比对当前 batch 文本 hash。
2. 升级 MERGE 指纹。
   - 指纹字段包含 `merge_level`、`group_index`、`prompt_hash`、`group_input_hash`、`child_output_hashes`。
   - 任一子产物变化，merge 缓存失效。
3. 将指纹从单行字符串升级为 sidecar 或结构化首行。
   - 旧首行可兼容读取，但缺内容 hash 的旧产物默认失效。
4. 增加测试。
   - 同 prompt / 同 budget / 改源文内容：MAP 不得复用旧产物。
   - 同 prompt / 同 budget / 改分组输入：MERGE 不得复用旧产物。
   - prompt 不变且 batch hash 相同：仍可复用，保证断点续跑收益。

## 验收标准

- Analyst 缓存复用能证明输入内容一致。
- 换源文、修源文、改分批内容都会使旧 MAP/MERGE 失效。
- 手法卡不会由旧源文缓存静默污染。
