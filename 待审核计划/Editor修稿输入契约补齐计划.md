# Editor 修稿输入契约补齐计划

## 结论

Editor 被要求“不新增 beat/评审里没提到的新信息”，还被允许在评审指出时增加配角视角短切，但实际输入只给初稿、检查结果、评审三段，没有 beat、角色知识边界、章节授权的多角度指令或状态材料。也就是说，Editor 要遵守的边界里有一部分它看不到。

## 当前证据

- `prompts/editor.md:5`：Editor 声明只拿到“初稿 + 门禁检查结果 + 评审意见”，并要求不新增世界观、不改变核心事件。
- `prompts/editor.md:12`：禁止添加 `beat/评审` 里没提到的新情节、新设定、新角色反应。
- `prompts/editor.md:46`：如果评审指出“缺少多角度”，Editor 可以加 50-200 字配角视角短切，但需满足触发条件。
- `scripts/run_pipeline.py:752-757`：实际传给 Editor 的 section 只有“初稿”“硬检查/风格检查/连续性检查”“评审”。
- `scripts/run_pipeline.py:758-765`：Editor 调用没有附带 beat 原文、POV 来源知识边界、active arcs 或角色卡摘要。
- `scripts/run_pipeline.py:773-794`：Editor 修后只进入代码门禁/final_gate，没有再做一次 beat 忠实度或“是否新增 beat 外信息”的语义验收。
- `scripts/run_pipeline.py:752-757`：editor 输入 section 实际只有初稿、gate JSON、reviewer 报告；这与 `prompts/editor.md:12` 的“不能添加 beat/评审里没提到的新情节、新设定、新角色反应”不匹配，因为 beat 边界没有给到 Editor。

## 根因判断

- prompt 把 Editor 定义成“边界内局部手术”，但主流程没有把边界材料交给它。
- 多角度叙事授权在 beat/writer/reviewer/editor 之间已经存在冲突风险；Editor 这条路径又额外缺少“本章是否允许补配角视角”的判定依据。
- 输入契约没有结构化声明哪些材料是 Editor 的只读边界，哪些是可修改目标。
- 修稿后验收仍偏代码规则，无法稳定发现“修稿新增了 beat 没授权的信息”这类语义越界。

## 影响

- Editor 在修方向偏航时可能无意添加 beat 未授权的新信息。
- Reviewer 若提出“缺少多角度”，Editor 可能凭空选择配角、知识、暗线，造成 POV 知识边界或伏笔泄露。
- 修稿后的正文会进入 final_gate/fact_checker，但许多“是否新增了 beat 外信息”的语义边界不是代码门禁能稳定发现的。
- 如果 Editor 为了修评审意见引入新角色反应、新地点状态或配角短切，后续没有专门的二次语义验收记录。

## 治本方案

1. 定义 Editor 输入契约。
   - 必给：标准化 beat、评审意见、gate 诊断、初稿。
   - 条件给：本章多角度授权、POV 知识边界、出场角色摘要、不可新增信息清单。
2. Editor prompt 改成严格使用这些 section。
   - “不能添加 beat/评审里没提到的新信息”应有对应的 beat section。
   - 多角度只能在 beat 或 reviewer 明确授权时补。
3. 主流程构建 `editor_input` 时补齐只读边界。
   - 不需要给全量台账，给本章相关最小摘要即可。
   - 标清“不可新增”“可局部调整”“可补短切”的范围。
   - 至少提供 beat 最小摘要：核心事件、出场角色、POV/多角度授权、知识边界、不可新增事实清单。
   - 若 reviewer 要求补多角度，Editor input 必须同时携带本章多角度授权；没有授权时明确禁止新增配角视角。
4. 增加 Editor 修后语义验收。
   - 轻量版：对比 beat / editor_input 边界 / edited 正文，生成 `editor_delta.json`。
   - LLM 版：只问“是否新增 beat/评审未授权的新事实或视角”，不评价文笔。
   - 有越界时进入同一修稿预算或停机，不直接沉淀到 summary/archive。
   - final_gate 通过不等于 beat 忠实度通过；需要单独记录 editor_delta 或复用 reviewer 的 beat 忠实度小检查。
5. 增加 scenario 测试。
   - 评审要求修方向偏航时，Editor input 必含 beat 核心事件和禁止新增边界。
   - 评审要求多角度时，Editor input 必含多角度授权与知识边界。
   - 未授权多角度时，Editor input 应明确禁止新增配角视角。
   - fake Editor 输出新增 beat 未授权角色/事实，断言 `editor_delta` 能记录并阻断或要求再修。

## 验收标准

- Editor 不再被要求遵守自己看不到的 beat 边界。
- 多角度修稿路径有明确授权和知识边界。
- Editor 修稿后的语义越界有可追踪验收结果。
- 测试覆盖 Editor input 的关键 section，而不是只测 Editor 被调用。
