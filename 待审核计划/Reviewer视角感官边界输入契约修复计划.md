# Reviewer 视角感官边界输入契约修复计划

## 结论

Reviewer 被要求判断主角感官限制、授权 POV 章知识边界、是否泄露不该知道的信息，但实际 reviewer 输入没有稳定注入这些边界材料。结果是评审职责比输入材料更宽，容易漏掉视角穿帮，或只能凭常识猜。

## 当前证据

- `prompts/reviewer.md:54`：要求检查主角感官限制，例如视力受限却看清精细细节。
- `prompts/reviewer.md:56`：授权 POV 章要按视角角色的感知和知识边界判断泄露。
- `scripts/pipeline/gates.py:480-494`：`make_review_input()` 主要注入 beat、故事总监批注、风格指南、AI 黑名单、硬检查、极简角色核实清单、近期摘要、正文，没有感官限制/知识边界专段。
- `scripts/run_pipeline.py:707-713`：POV 授权只说明“按某角色感知判断”，没有注入该角色的 `ignorant_of/known_facts/allowed_reveal`。

## 根因判断

- Writer/POV writer 和 Reviewer 没有共享同一份视角边界记录。
- Reviewer prompt 把“视角/知识边界”当硬评审项，但主流程只给了抽象授权说明。
- `POV来源知识边界统一修复计划` 解决 writer 侧边界来源，本计划补 Reviewer 输入与验收侧接线。

## 影响

- 非沈安 POV 可能提前泄露系统、暗线、弧线全貌，Reviewer 却没有依据判断。
- 普通沈安章可能出现感官穿帮，但 Reviewer 未必拿到主角当前限制和例外能力。
- 后续修复多角度短切后，Reviewer 仍缺每个短切角色的知识边界。

## 治本方案

1. 定义 Reviewer 视角边界 section。
   - 主角当前感官限制与例外能力。
   - POV 章的 `pov_voice/ignorant_of/known_facts/allowed_reveal`。
   - 章内短切角色的公开信息、禁止泄露项、允许外显项。
2. 该 section 标为 critical 且不可压缩。
3. 缺边界时采用保守策略。
   - POV 章缺 boundary：阻断或降级为严格公开信息视角。
   - 普通章缺主角感官状态：Reviewer 只按正文和已知公开设定判断，并记录证据不足。
4. 增加 scenario 测试。
   - 三类 POV 来源都有 Reviewer boundary。
   - 沈安感官限制能进入 reviewer_input。
   - 章内短切授权与知识边界能进入 reviewer_input。

## 验收标准

- Reviewer 不再被要求检查看不到的知识边界。
- Writer 和 Reviewer 使用同一份 POV/视角边界记录。
- 缺边界不会被默认解释成“无特殊限制”。
