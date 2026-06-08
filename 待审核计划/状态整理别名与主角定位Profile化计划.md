# 状态整理别名与主角定位 Profile 化计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

`scripts/compact_state.py` 把当前书别名归一和主角定位规则写死在通用状态整理逻辑中。换书或整理 runtime 时，脚本可能静默改名、错认主角，并把错误位置写回当前状态。

## 当前证据

- `scripts/compact_state.py:162-164`：硬编码 `沈归舟→沈安`、`黑子→阿墨`、`方绾→方青瓷`。
- `scripts/compact_state.py:170-174`：`canonical_name()` 内再次写死同一组别名。
- `scripts/compact_state.py:269`：只有 `name == "沈安"` 时才更新 `state["current_location"]`。

## 根因判断

- 别名归一是通用能力，但别名表属于 book profile。
- “谁是主角、谁的位置代表当前地点”也是 profile/叙事配置，不应写在整理脚本里。
- 状态整理脚本会直接改 runtime，污染风险高于普通 prompt。

## 影响

- 新书角色名可能被当前书别名规则误改。
- 当前地点可能只跟踪错误主角或不更新真实主角位置。
- 正典状态一旦被整理脚本污染，后续规划和写作都会继承错误。

## 治本方案

1. 把别名表迁入 book profile。
   - `aliases: {canonical: [...aliases]}` 或等价结构。
   - 通用脚本只读取 profile，不内置当前书名字。
2. 主角定位配置化。
   - 使用 `profile.protagonist.id/name` 或 `narrative.current_location_owner`。
   - 支持多主角/队伍位置策略。
3. 增加整理前审计。
   - 将要归一的别名和主角定位 owner 输出到 dry-run 报告。
   - 未加载 profile 时拒绝执行写盘。
4. 增加测试。
   - 非当前书 profile 下运行 compact，不应出现当前书角色名。
   - 多别名归一只按 profile 生效。

## 验收标准

- 状态整理脚本不再内置当前书角色别名。
- current_location 的 owner 来自 profile。
- 误运行脚本不会静默把新书 runtime 改成当前书正典。
