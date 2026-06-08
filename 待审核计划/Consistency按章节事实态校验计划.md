# Consistency 按章节事实态校验计划

## 结论

Consistency Checker 用当前 `runtime/ledger` 的事实态去审全书历史 fact sheets，缺少“第 N 章提交后当时的事实快照”。这会把未来状态套回过去，也会把当前已死亡、已习得、已暴露的状态误用于早期章节。

## 当前证据

- `scripts/consistency/checker.py:46-57`：checker 全量加载所有章节 fact sheets。
- `scripts/consistency/checker.py:380` 附近：死亡角色等判断从当前 ledger 派生后应用到所有章节。
- `scripts/consistency/checker.py:253` 附近：技能/角色状态类检查同样读取当前 ledger。
- `scripts/consistency/mapper.py:151`：Map 输入同时喂 `Beat 信息` 和正文。
- `scripts/consistency/prompts/map_agent.md:8`：Map prompt 要求“只从正文提取”，但输入里存在 beat 默认值。
- `scripts/consistency/mapper.py:55-57`：beat slim 会为缺省字段填 `沈安/顺叙`，这类默认值可能被模型当成事实背景。
- `scripts/consistency/prompts/map_agent.md:8` 同时要求“不要推理、不要补充”，但同一 prompt 的 schema 又要求 `day` “从正文线索推断”、`duration` “时间跨度估计”，见 `scripts/consistency/prompts/map_agent.md:26,29`；行号也允许粗略估计，见 `scripts/consistency/prompts/map_agent.md:118`。这会把 inferred/estimated 信息混成未标记硬事实。

## 根因判断

- 主流水线只有当前正典账本，没有按章节保留提交态 snapshot。
- consistency fact sheet 只记录“正文提取事实”，没有绑定“本章提交时的 ledger/thread/beat 版本”。
- Map 输入的权威层级没有足够显式：正文是事实源，beat 只是辅助定位；默认 beat 值更应避免变成事实。
- Map prompt 对“提取”和“推断/估计”的边界没有结构化标注，导致 checker 无法区分正文硬事实、合理推断、粗估辅助信息。

## 影响

- 某角色第 80 章死亡后，checker 可能误判第 20 章出现该角色为复活。
- 主角后期习得的技能可能被套回早期，或早期使用技能被当前账本误解释。
- beat 计划态字段可能污染 fact sheet，让未发生的角色/POV/时间信息进入一致性检查。

## 治本方案

1. 建立章节提交态快照。
   - 每章 Archivist 成功提交后，保存轻量 `runtime/chapter_snapshots/chapter_NNN.json`。
   - 包含 ledger/thread/state 的关键事实 hash 或精简事实态。
2. Checker 按章节读取对应 snapshot。
   - 审第 N 章时，使用第 N 章提交后的事实态，跨章比较时使用相邻章节各自的事实态。
   - 没有 snapshot 的历史章节标记为 legacy，不做高置信未来态判断。
3. Map 输入权威边界显式化。
   - Beat section 改名为“辅助定位，不能当正文事实”。
   - 缺省值不要填成事实值；缺失就留空或标 `unknown`。
4. fact sheet 记录来源层级。
   - 每条事实标 `source=body|beat_hint|inferred`。
   - Check 默认只用 `body` 和高置信 `inferred`，`beat_hint` 只做解释辅助。
   - 所有 inferred/estimated 字段必须带 `confidence` 和 `evidence_span`；缺证据时不能和正文硬事实同权。
5. 测试覆盖未来态回灌。
   - 构造角色后期死亡、早期出场样本，确保不误报复活。
   - 构造 beat 有默认 POV 但正文无 POV 证据样本，确保不把默认值写成事实。

## 验收标准

- 历史章节不会被当前 ledger 的未来状态误审。
- Map 输出能区分正文事实和 beat 辅助信息。
- 缺少章节快照时，checker 降级而不是高置信误报。
