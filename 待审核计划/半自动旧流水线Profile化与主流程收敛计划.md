# 半自动旧流水线 Profile 化与主流程收敛计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

`scripts/pipeline.py` 仍是一个可执行的半自动旧流水线入口，并且自带当前书默认主角和线名。即使主流程完成 profile 化，用户或维护脚本误用旧入口时，缺字段 beat 仍会被拉回当前书角色和旧线名。

## 当前证据

- `scripts/pipeline.py:104`：缺少出场角色时默认 `["沈安"]`。
- `scripts/pipeline.py:158`：缺少推进线时默认 `"主线"`。
- `scripts/pipeline.py:160`：任务摘要再次默认 `["沈安"]`。

## 根因判断

- 旧半自动入口没有纳入主流程 profile 化边界。
- 缺字段 fallback 写在入口内部，而不是从 book profile 或统一 normalizer 读取。
- 可执行旧入口缺少退役/转发/警告机制。

## 影响

- 换书后使用半自动 prompt 生成会污染新书主角。
- 主流程修复无法覆盖旁路入口。
- 测试若只覆盖 `run_pipeline.py`，会漏掉旧入口的硬编码。

## 治本方案

1. 对所有可执行入口建注册表。
   - 标记 `active/deprecated/migration-only/test-only`。
   - 入口启动时必须声明 profile 来源。
2. 半自动入口收敛到主流程 helper。
   - beat normalizer、角色默认值、线名默认值从同一 profile 读取。
   - 旧入口若保留，只做薄封装，不保留独立默认值。
3. 增加退役保护。
   - deprecated 入口运行时要求显式 `--allow-deprecated`。
   - 默认输出迁移指引，不继续生成。
4. 增加换书测试。
   - 临时 profile 主角不是当前书角色，断言旧入口不输出当前书主角名。
   - 缺字段 beat 的默认角色来自 profile。

## 验收标准

- 所有可执行生成入口都走同一 profile 默认值。
- 旧半自动入口不会绕过主流程 profile 化。
- 测试能发现新入口重新写死角色默认值。
