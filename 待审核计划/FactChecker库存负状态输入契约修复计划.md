# FactChecker 库存负状态输入契约修复计划

## 结论

FactChecker 被要求核查资源/物品一致性，但主流程输入只给“正向库存”：仍持有的关键物品、数量大于 0 的消耗品、非过时技能。已经失去、耗尽、过时、位置异常或状态变更的物品不会进入事实核查输入。正文若重新拿出已失去物品或使用已耗尽消耗品，LLM FactChecker 可能看不到判定依据。

## 当前证据

- `prompts/fact_checker.md:35-40`：要求核查资源/物品一致性，包括从未获得、数量不对、已记录物品数量必须一致。
- `scripts/run_pipeline.py:437-445`：FactChecker 输入过滤为 `techniques.status != 过时`、`key_items.status == 持有`、`consumables.qty > 0`。
- `scripts/pipeline/archivist.py:525-568`：库存合并支持 `inventory_update`、状态、位置、数量、currency 变化，说明负状态和状态变更本应存在于 ledger。
- `scripts/run_pipeline.py:461-468`：FactChecker 输入只有渲染后的“资源账”，没有完整 inventory 状态表或负状态摘要。

## 根因判断

- FactChecker 的资源核查职责需要“可用/不可用”两类事实，但输入构造只保留可用事实。
- 过滤逻辑适合 writer 减噪，不适合 fact checker 判定冲突。
- inventory 的状态语义没有分角色视图：writer 可以少看负状态，FactChecker 必须看负状态。

## 影响

- 已耗尽消耗品被正文再次使用时可能漏检。
- 已失去/转交/不在身边的关键物品被正文拿出时可能漏检。
- 技能或物品状态从“过时/损坏/封存”变化后，FactChecker 看不到反例。

## 治本方案

1. 给 FactChecker 单独渲染完整 inventory 事实视图。
   - `available_items`
   - `unavailable_items`
   - `exhausted_consumables`
   - `lost_or_transferred_key_items`
   - `obsolete_or_disabled_techniques`
   - `last_chapter/location/status`
2. 对 writer 和 fact_checker 分开做库存摘要。
   - writer 只看本章相关可用项。
   - FactChecker 看正负状态与最近变化。
3. 增加输入来源和 hash。
   - 记录 inventory snapshot hash，纳入章节审计 manifest。
4. 增加测试。
   - ledger 中消耗品 qty=0，正文“服下/取出”该物，断言 FactChecker 输入包含耗尽状态。
   - key_item status=转交/遗失，正文拿出该物，断言可被核查。
   - technique status=过时/禁用，正文使用该技能，断言可被核查。

## 验收标准

- FactChecker 不再只看正向库存。
- 已失去/耗尽/禁用状态能进入事实核查输入。
- 库存事实域的 writer 视图和 fact_checker 视图职责清晰。
