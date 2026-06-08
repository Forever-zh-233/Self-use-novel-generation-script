# 伏笔 Upsert 非破坏式合并计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

Archivist prompt 要求“没有变化的字段直接省略”，但 merge 端对 `foreshadowing.upsert` 使用整条替换。模型如果只提交变化字段，旧条目的 `promise/type/strength/planted_chapter/remaining_promise` 等字段可能被覆盖丢失。

## 当前证据

- `prompts/archivist.md:90`：明确要求没有变化的字段省略。
- `prompts/archivist.md:117`：`foreshadowing.upsert` 是结构化更新入口。
- `scripts/pipeline/archivist.py:106-109`：merge 端读取 `foreshadowing.upsert`。
- `scripts/pipeline/archivist.py:109-113`：每条 upsert 只补 `last_advanced` 后执行 `table[str(item["id"])] = item`，没有与旧值深合并。

## 根因判断

- prompt 采用 patch 语义，代码采用 replace 语义。
- 伏笔条目是长期债务对象，字段可能跨几十章逐步补充；整条替换会破坏历史字段。
- 当前校验只检查 JSON 可解析，没有检查 upsert 后关键字段是否丢失。

## 影响

- 伏笔 ID 仍存在，但承诺文本、强度、埋设章、计划回收信息可能消失。
- 后续规划无法判断伏笔重要性和剩余债务。
- “部分回收”这类只更新状态的操作尤其容易把旧承诺清空。

## 治本方案

1. 明确 upsert 语义。
   - 新 ID 使用 create。
   - 已存在 ID 使用 patch/merge，不允许整条替换。
2. 实现非破坏式深合并。
   - 旧字段默认保留。
   - 新字段覆盖同名字段。
   - 空串和空数组默认不覆盖旧值，除非显式 `clear_fields`。
3. 增加合并后校验。
   - 已存在伏笔合并后必须保留 `id/status/promise/planted_chapter/strength` 等核心字段。
   - 字段被清空时输出具体路径。
4. 调整 prompt 示例。
   - 明确 `upsert` 是 patch，不是完整对象替换。
   - 若要删除字段，必须走显式删除语义。
5. 增加测试。
   - 旧条目有完整 promise，新 update 只给 `status=部分回收`，断言 promise 保留。
   - update 给空串，断言不会清空旧字段。

## 验收标准

- Archivist 的省略字段策略和 merge 行为一致。
- 伏笔条目不会因为局部更新而丢失历史承诺。
- 测试能捕捉整条替换式 upsert 的回归。
