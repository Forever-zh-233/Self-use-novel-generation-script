# Archivist Merge 类型预检与异常重试修复计划

## 结论

Archivist 失败重试主要覆盖 `RuntimeError`，但合并阶段存在 `int()`、`float()` 等类型转换和复杂结构写入；如果 merge 后半段抛出非 RuntimeError，可能不重试，还可能留下 state/threads 已写、ledger 未写的半提交。

## 当前证据

- `scripts/run_pipeline.py:965`：Archivist 重试分支只捕获 `RuntimeError`。
- `scripts/pipeline/archivist.py:1009-1013`：`apply_archivist_update()` 先 `merge_state_update()`，再 `merge_ledger_update()`。
- `scripts/pipeline/archivist.py:153`：`merge_state_update()` 会直接写 `state.json` / `active_threads.json`。
- `scripts/pipeline/archivist.py:735`、`scripts/pipeline/archivist.py:800`：merge 中存在 `revealed_level -> int`、`day_advance -> float` 等未预校验转换。

## 根因判断

- 校验阶段只验证 JSON 可解析，没有做 schema/type 预检。
- 写入不是 staging 后一次性提交，而是多文件顺序写。
- 异常分类没有统一包装成可重试的 Archivist 提交错误。

## 影响

- 类型错误可能绕过重试。
- 半提交会造成 state、active_threads、ledger 不一致。
- 断点恢复可能面对“部分文件已经写了、latest_chapter 未推进”的复杂状态。

## 治本方案

1. 在 validate 阶段做 schema/type 预检。
   - 数字字段必须可转换。
   - 数组/对象字段必须符合预期形态。
   - 关键 ID 字段必须是字符串。
2. merge 异常统一包装为 Archivist 可重试错误。
   - 保留原异常类型和字段路径。
3. 引入 staging。
   - 先在内存或临时文件生成新 state/threads/ledger。
   - 全部成功后原子替换。
4. 与幂等提交计划共享 commit marker。
   - 半提交可检测、可恢复、可拒绝重复应用。
5. 增加 scenario 测试。
   - `revealed_level: "二"` 这类类型错误应在 validate 阶段失败。
   - merge 后半段故障不应留下部分文件提交。
   - 可重试错误应触发 Archivist 重调。

## 验收标准

- 类型错误在写盘前发现。
- Archivist merge 不留下不可识别半提交。
- 非 RuntimeError 合并失败也进入正确重试/阻断路径。
