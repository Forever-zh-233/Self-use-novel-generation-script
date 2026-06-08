# 一次性迁移脚本归档与 Fixture 隔离计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

`scripts/migrate_ledger.py` 是一次性迁移脚本，但仍作为普通脚本留在 `scripts/`，且写死当前书绝对路径和正典内容。误运行会直接把当前书资产写入 runtime ledger，污染未来项目。

## 当前证据

- `scripts/migrate_ledger.py:4`：写死 `E:\Novel 1\runtime\ledger.json`。
- `scripts/migrate_ledger.py:28`：注入“通行令(巡夜司铜牌)”。
- `scripts/migrate_ledger.py:31`：注入“了愿奖励技能”。
- `scripts/migrate_ledger.py:43`：注入 `liaoYuan_log`。
- `scripts/migrate_ledger.py:52`：注入“沈安身份标识”意象。

## 根因判断

- 一次性历史迁移没有和通用工具、fixture、示例数据隔离。
- 迁移脚本缺少 idempotency marker、目标项目校验和显式确认。
- `scripts/` 目录本身被视为可运行工具集合，误用概率高。

## 影响

- 新书或测试环境误运行会写入当前书角色、势力、系统机制。
- 迁移脚本可能覆盖真实 ledger 字段，造成难以追踪的正典污染。
- 后续 profile 化不能覆盖已经写进 runtime 的污染数据。

## 治本方案

1. 迁移脚本分级归档。
   - 一次性历史迁移移入 `scripts/migrations/archive/` 或 `fixtures/current_book/`。
   - 默认不可直接运行。
2. 加目标校验。
   - 检查 project id/book id/runtime marker。
   - 不匹配时拒绝执行。
3. 加 dry-run 和显式确认。
   - 默认只输出将写入的字段。
   - 写盘需 `--apply --book-id <id>`。
4. fixture 隔离。
   - 当前书样本数据放入 fixture，不作为通用迁移逻辑。
5. 增加测试。
   - 无 book marker 时迁移拒绝。
   - 非当前书 profile 下不会写入当前书资产。

## 验收标准

- 一次性迁移不会作为普通通用脚本误运行。
- 所有写 runtime 的迁移都有目标项目校验。
- 当前书数据只存在于 fixture/profile，不进入通用迁移默认路径。
