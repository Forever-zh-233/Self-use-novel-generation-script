# POV 来源知识边界统一修复计划

## 结论

这是 POV 来源与知识边界落点不一致。Arc planner 允许三类合法 POV：影响回响、暗流涌动、人物铺垫；但 POV writer 输入只从 `impact_seeds` 查 `pov_voice/ignorant_of`。如果 POV 来源不是 impact_seed，系统就写“无特殊限制”，容易把暗流或人物铺垫 POV 写成全知视角。

## 当前证据

- `prompts/arc_planner.md:182-185`：POV 有三种合法来源：影响回响、暗流涌动、人物铺垫。
- `prompts/writer_pov.md:29`：POV 写手需要 `pov_voice`。
- `prompts/writer_pov.md:33`：`ignorant_of` 是硬约束，违反等于穿帮。
- `scripts/pipeline/context.py:1352-1356`：`build_pov_writer_input()` 只从 `ledger.impact_seeds` 找 seed，取 `ignorant_of/pov_voice`。
- `scripts/pipeline/context.py:1372-1377`：没有 seed 时知识边界写“无特殊限制”。
- `scripts/run_pipeline.py:628-642`：任何 `视角角色 != 沈安` 都会进入 POV 分支，不区分 POV 来源。

## 根因判断

- `impact_seeds` 同时承担“影响回响 POV 来源”和“POV 知识边界”的职责，但另外两类合法 POV 不进入 impact_seeds。
- `active_arcs.pov` 的 purpose/character 没有被转换成 POV writer 所需的 boundary record。
- 缺省“无特殊限制”过于危险，应当缺知识边界时阻断或降级为严格公开信息视角。

## 影响

- 暗流涌动 POV 可能知道主角秘密、系统秘密或不该知道的弧线全貌。
- 人物铺垫 POV 可能提前泄露尚未正典公开的信息。
- reviewer 虽有“授权 POV 章”说明，但如果 writer_input 本身没有知识边界，reviewer 也难以判断泄露。

## 治本方案

1. 建立统一 POV boundary registry。
   - 每个 POV 节点必须生成 `{character, purpose, source, pov_voice, ignorant_of, known_facts, allowed_reveal}`。
2. Arc planner 输出 POV 时必须给知识边界依据。
   - 影响回响可引用 impact_seed。
   - 暗流涌动从 side_character knowledge_boundary / hidden_agenda 生成。
   - 人物铺垫从新角色初始知识边界生成。
3. `build_pov_writer_input()` 不再只查 impact_seeds。
   - 先查 POV boundary registry。
   - 再查 impact_seed。
   - 仍缺失时阻断，不写“无特殊限制”。
4. Reviewer POV 授权说明也带上 boundary。
   - reviewer 对照同一份 `ignorant_of/known_facts` 检查泄露。
5. 增加测试。
   - 三类 POV 各构造一个样本。
   - 非 impact_seed POV 缺 boundary 时断言阻断。
   - 有 boundary 时断言 writer/reviewer input 都包含同一份知识边界。

## 验收标准

- 所有合法 POV 来源都有知识边界。
- “无特殊限制”不再作为缺省安全策略。
- POV writer 和 reviewer 使用同一份 boundary。
