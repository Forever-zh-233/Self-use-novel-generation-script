# Archivist 技能库与可用技能清单同步修复计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

Archivist 当前有多套技能落盘口径：`technique_new/technique_updates` 写技能细节卡，`update_entities.skills_add` 写角色已学技能，`inventory_update.add(category=techniques)` 写可用技能清单。它们没有统一提交契约，导致新技能可能“有细节卡、无可用事实”，后续规划、写作和核查不一定知道角色已经掌握该技能。

## 当前证据

- `prompts/archivist.md:60-61`：要求已有技能新细节用 `technique_updates`，全新技能用 `technique_new`。
- `prompts/archivist.md:387`：角色实体还有 `skills_add` 字段。
- `scripts/pipeline/archivist.py:379-393`：`technique_updates/technique_new` 主要写入 `ledger.technique_library`。
- `prompts/archivist.md:202`：示例里 `skills_add` 是另一套入口。
- `scripts/pipeline/archivist.py:271-273`：`skills_add` 写入实体技能。
- `scripts/pipeline/context.py:498`：技能库只在 beat 命中特定技能名时注入完整卡。
- `scripts/pipeline/context.py:374-379`：Writer 角色卡技能来自实体 `skills`，不是 `technique_library`。

## 根因判断

- “技能定义卡”和“角色已掌握技能”是不同概念，但当前 prompt 没要求二者成对提交。
- `technique_library` 更像技能百科，不能单独证明某角色可用。
- 规划层和核查层主要看可用事实，未必看技能细节卡。

## 影响

- 新学技能可能不会进入角色卡和可用技能列表。
- BeatPlanner 设计冲突时不知道主角已有技能。
- FactChecker/Reviewer 可能无法判断“未获技能却使用”或“已有技能被无视”。

## 治本方案

1. 明确技能对象分层。
   - `technique_library`：技能定义、限制、使用细节。
   - `entities[*].skills`：某角色是否已掌握、等级、获得章。
   - `inventory.techniques`：如仍保留，必须定义是否是镜像或旧兼容层。
2. 统一提交契约。
   - `technique_new` 若表示角色首次学会，必须同时提交 owner/learned_by 或对应 `skills_add`。
   - 只新增世界技能设定时，必须标明 `not_learned_yet`。
3. 增加合并对账。
   - 技能库新增可用技能但没有 owner 时警告。
   - 角色技能引用不存在的技能库卡时警告。
4. 调整下游读取。
   - Writer、BeatPlanner、FactChecker 使用同一个“角色当前可用技能摘要”。
   - 技能细节卡按需补充，不替代可用事实。
5. 增加测试。
   - Archivist 新增技能后，断言角色可用技能摘要能看到。
   - 只新增技能库卡但未标 owner，断言触发校验。

## 验收标准

- 技能定义和角色可用事实不再断链。
- BeatPlanner/Writer/FactChecker 对“主角已会什么”看到同一份摘要。
- 新技能落盘不会只停留在 technique_library。
