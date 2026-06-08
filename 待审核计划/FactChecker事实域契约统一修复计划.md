# FactChecker 事实域契约统一修复计划

## 结论

这是事实核查职责域、输入域、触发域不一致的问题。`fact_checker.md` 要事实核查员检查角色卡、资源账、关系账、约束账、上一章状态等事实一致性；实际主流程只在任意实体有 `skills/enemies/injuries` 时才启用 fact_checker，并且输入只给 beat 出场角色的部分字段。结果是有资源、关系、约束可查的章节仍可能跳过事实核查。

## 当前证据

- `prompts/fact_checker.md:10-12`：职责输入包含当前资源账、关系账、约束账。
- `prompts/fact_checker.md:13`：职责输入还包含“上一章的状态摘要”。
- `prompts/fact_checker.md:35-50`：事实核查职责包含资源/物品一致性、关系一致性、约束账强约束。
- `prompts/fact_checker.md:53-55`：事实核查职责包含角色位置和时间线连续性。
- `scripts/run_pipeline.py:461-468`：`run_fact_checker()` 实际会拼资源账、约束账、关系账、本章正文。
- `scripts/run_pipeline.py:461-468`：同一输入构造没有上一章状态摘要、上一章地点/伤势变化、上一章角色位置等 section。
- `scripts/run_pipeline.py:801-806`：启用判据却只看实体是否有 `skills/enemies/injuries`，没有这些字段就直接跳过事实核查。
- `scripts/run_pipeline.py:424`：角色卡详细字段只取 `realm/skills/weapons/injuries/secrets/enemies/current_goal/faction/reputation` 等部分字段。
- `config/run.json:37-41` 配置了 `max_input_tokens.fact_checker=30000`，但 `scripts/run_pipeline.py:461-472` 直接手工拼接 `input_sections` 后调用 `call_role()`，没有经过 `compress_sections_if_needed()` 或分段核查，配置语义和执行路径不一致。
- `prompts/fact_checker.md:7-13` 声称会拿到正文、完整角色卡、资源账、关系账、约束账、上一章状态摘要；实际 `scripts/run_pipeline.py:461-468` 没有上一章状态摘要，也没有稳定的上一章地点/伤势/时间线实现态。

## 根因判断

- “是否值得事实核查”的触发条件沿用了技能/伤势/敌人这类战斗向字段，但 fact_checker 的真实职责已经扩展到资源、关系、约束、空间、时间等更广事实域。
- 输入构造和触发判据没有共享同一份事实域 schema。
- prompt 要求检查上一章状态连续性，但输入没有稳定提供上一章实现态摘要，导致时空/伤势连续性只能靠角色卡和正文猜。
- 测试覆盖了规则版 `fact_check_against_ledger()` 的技能样本，但没有覆盖主流程“有资源/关系/约束却被跳过”的分支。

## 影响

- 早期、日常、低战斗章节最容易被跳过事实核查，但这些章节同样会消耗钱物、推进关系、更新约束。
- 已有约束账或关系账时，正文可能违反强约束却不触发 LLM fact_checker。
- 使用者看到 fact_checker 阶段存在，会误以为所有事实域都被守住。

## 治本方案

1. 定义统一事实域 schema。
   - `character_facts`
   - `inventory`
   - `constraints`
   - `relationships`
   - `timeline/location`
   - `previous_chapter_state`
   - `known_entities`
2. FactChecker 启用判据按事实域判断。
   - 任一事实域非空且与本章正文/beat 相关，就运行。
   - 不再只看 `skills/enemies/injuries`。
3. 输入构造按同一 schema 渲染。
   - 每个区块标明来源、权威性、可判定范围。
   - 资源数量、强约束、关系状态不可压缩或摘要失真。
   - 上一章状态摘要优先来自 committed summary / chapter manifest / ledger，而不是 beat 计划态。
4. 接入统一预算/压缩或分段核查。
   - FactChecker 的 max input tokens 配置必须真实生效。
   - 资源/约束/关系等 hard fact section 不可被摘要到失真；超预算时按事实域分批核查，而不是整段截断。
   - 每个 section 记录来源和 hash，进入章节审计 manifest。
5. 增加 scenario 测试。
   - 只有资源账，无 skills/enemies/injuries，正文数量冲突，断言 fact_checker 会运行。
   - 只有关系账，正文关系倒退，断言 fact_checker 会运行。
   - 只有约束账，正文违反约束，断言 fact_checker 会运行。
   - 上一章状态显示角色在 A 地或有伤，本章无交代跳到 B 地/伤势恢复，断言 fact_checker 输入包含上一章状态摘要。
   - 构造超长正文/台账，断言 `max_input_tokens.fact_checker` 会触发压缩或分段策略，且 hard fact section 不被吞掉。

## 验收标准

- fact_checker 的职责域、输入域、触发域一致。
- 有资源/关系/约束事实可查时不会被“角色卡无技能伤势”绕过。
- 时空/伤势连续性检查有上一章实现态摘要可依据。
- 测试覆盖主流程启用判据。
