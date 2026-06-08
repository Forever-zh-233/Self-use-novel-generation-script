# FactChecker 规则门禁 inventory 字段迁移计划

## 结论

规则版 `fact_check_against_ledger()` 仍按旧 `ledger.resources` 做资源核查，而且没有接入当前主流程 gate。与此同时，主流程 LLM FactChecker 和 Archivist 已迁移到 `inventory` / `inventory_update`。这会让维护者误以为规则版事实核查仍在守资源穿帮，实际它既读旧字段，又没有参与当前 `combine_checks()`。

## 当前证据

- `scripts/pipeline/gates.py:59-62`：注释称 `fact_check_against_ledger()` 返回 warnings，提醒 reviewer/editor。
- `scripts/pipeline/gates.py:139-153`：资源核查只读 `ledger.get("resources")`。
- `scripts/run_pipeline.py:683-690`：当前硬检查聚合只包含 `hard_gate/style_gate/continuity/adjacent/type_guard/satisfaction_check`，没有调用 `fact_check_against_ledger()`。
- `scripts/run_pipeline.py:429-447`：LLM FactChecker 输入已改用 `inventory`。
- `scripts/pipeline/archivist.py:525-568`：Archivist 的库存提交主路径是 `inventory_update`。

## 根因判断

- 旧规则核查函数没有随 ledger schema 迁移。
- 主流程已转向 LLM FactChecker，但规则函数注释和测试语义仍像“有效门禁”。
- “保留未接入旧函数”会制造维护错觉：看似有规则兜底，实际当前 gate 不消费它。

## 影响

- 规则版资源核查对当前 inventory 数据无效。
- 测试若只测 `fact_check_against_ledger()` 纯函数，会给出虚假的事实核查覆盖感。
- 后续维护者可能在旧 `resources` 上修补，继续绕开真实主链。

## 治本方案

1. 决定规则版事实核查的身份。
   - 若保留：迁移到 `inventory` schema，并接入 `combine_checks()` 或 reviewer input。
   - 若废弃：删除资源核查部分或标为 legacy，不再作为覆盖依据。
2. 迁移字段。
   - `resources` -> `inventory.currency/key_items/consumables/techniques`
   - 支持 `status/qty/location/last_chapter`
3. 与 LLM FactChecker 分工。
   - 规则版只做高置信硬事实：耗尽仍使用、死亡复活、技能未获得即使用。
   - LLM 负责语义连续性、关系/约束冲突。
4. 增加测试。
   - 当前 ledger 只有 inventory、没有 resources，规则版仍能发现耗尽物品复用。
   - 主流程 gate 聚合中能看到规则版 fact warnings，或明确证明该函数不再属于主流程门禁。

## 验收标准

- 不再存在“读旧 resources 且未接入主链”的事实核查函数。
- 测试覆盖当前 inventory schema，而不是旧账本字段。
- 维护者能清楚知道规则版 FactChecker 是主链门禁、reviewer 辅助，还是 legacy 工具。
