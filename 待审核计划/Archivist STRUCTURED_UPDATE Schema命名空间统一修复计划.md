# Archivist STRUCTURED_UPDATE Schema 命名空间统一修复计划

## 结论

Archivist prompt 示例把部分字段放在 `STRUCTURED_UPDATE` 顶层，但合并器只从 `canon` 或 `ledger` 命名空间读取。模型按 prompt 示例输出时，JSON 能通过解析，却会静默丢失技能更新、影响种子等字段。

## 当前证据

- `prompts/archivist.md:147`、`prompts/archivist.md:163`：示例把 `technique_updates`、`technique_new`、`impact_seeds` 放在顶层。
- `scripts/pipeline/archivist.py:160`：`merge_ledger_update()` 使用 `block = update.get("canon") or update.get("ledger")`。
- `scripts/pipeline/archivist.py:380`、`scripts/pipeline/archivist.py:427`：后续从 `block` 读取技能、影响种子等字段。
- `tests/scenario_test.py:1567`、`tests/scenario_test.py:1648`：现有测试覆盖的是放进 `canon` 的情况，没有覆盖 prompt 示例形态。

## 根因判断

- Prompt schema 和 merge schema 分叉维护。
- `validate_archivist_report()` 只检查 JSON 能解析，没有检查字段命名空间是否被消费。
- 顶层字段既不报错，也不落盘，是最危险的“看似成功”。

## 影响

- 新技能、影响种子、资源更新可能被提交阶段静默忽略。
- POV 影响回响链路拿不到 seed。
- 测试会绿，因为测试样本没有覆盖 prompt 示例形态。

## 治本方案

1. 统一 schema。
   - 方案 A：prompt 全部改为 `canon`/`ledger` 内字段。
   - 方案 B：merge 兼容顶层字段，但 validate 要禁止同字段双写冲突。
2. 增加 schema 预检。
   - 未知顶层字段报警或阻断。
   - 已知字段落在错误命名空间时给可修复错误。
3. 从同一 schema 生成 prompt 示例和测试样本。
4. 增加 scenario 测试。
   - prompt 示例形态必须被正确消费，或必须被 validate 拒绝。
   - 顶层和 `canon` 双写冲突必须阻断。

## 验收标准

- 模型按 prompt 示例输出不会静默丢字段。
- 所有可消费字段都有明确命名空间。
- 未知/错位字段在提交前被发现。
