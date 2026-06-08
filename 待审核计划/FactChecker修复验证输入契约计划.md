# FactChecker 修复验证输入契约计划

## 结论

FactChecker 第一次核查拿到的是事实材料 + 正文，但修复验证阶段复用完整 `fact_checker.md` prompt，却只给原始问题、修改说明和局部片段，第二次验证甚至没有修改后正文。验证职责和验证输入不匹配。

## 当前证据

- `prompts/fact_checker.md:7-13`：FactChecker 声明会拿到正文、角色卡、资源账、关系账、约束账、上一章摘要。
- `scripts/run_pipeline.py:841-847`：第一次修复验证只给原始穿帮报告、修改说明、修改后前 3000 字片段。
- `scripts/run_pipeline.py:877-880`：第二次验证只给穿帮条目和修改说明，没有修改后正文。
- `scripts/run_pipeline.py:849-884`：验证仍使用完整 fact_checker prompt，而不是专用 verify prompt。
- `scripts/run_pipeline.py:822-837`：FactChecker 点对点修复直接调用 writer，并要求“正文末尾另起一行写 `## 修改说明`”，随后用 `re.split(r"^## 修改说明", ...)` 切正文和修改说明。
- `prompts/writer_pov.md:59`：POV 写手明确要求“不要标题，不要分隔线，不要元信息”。当 FactChecker 修复发生在 POV 章时，主流程要求 writer 输出元信息，writer prompt 又禁止元信息，输出契约自相矛盾。

## 根因判断

- “初查事实一致性”和“验证指定问题是否修复”是两个任务，但共用一个 prompt 和解析口径。
- “章节正文写手”和“事实点修复员”也是两个任务，但主流程复用 writer/writer_pov prompt 并临时追加 `## 修改说明`，导致正文格式契约与修复 changelog 契约互撞。
- 验证阶段为了省 token 缩窄输入，却没有定义最低证据包。
- 验证结果没有 `insufficient_evidence` 状态，证据不足可能被误当通过或误报。

## 影响

- FactChecker 可能在没有账本/正文依据时确认修复。
- 第二轮验证只看修改说明，无法判断正文是否真的改了。
- 与“残留穿帮阻断”和“修后再门禁”计划联动时，证据包不足会让阻断理由不可靠。

## 治本方案

1. 新建专用 `fact_checker_verify` prompt。
   - 只验证已列问题是否修复。
   - 不寻找新问题。
   - 允许输出 `passed / failed / insufficient_evidence`。
2. 定义验证最低输入包。
   - 原始穿帮条目。
   - 相关角色/资源/关系/约束事实。
   - 修改前相关片段。
   - 修改后相关片段或完整修后正文。
3. 第二轮验证不得只给修改说明。
4. 新建专用 `fact_checker_fix` 或 `writer_fix` prompt。
   - 输出结构分离为 `{revised_text, changelog}` 或双文件产物，不靠正文里的 `## 修改说明` 分隔。
   - POV 章也不能复用“不要元信息”的正文写手契约来承担修复报告职责。
5. 解析器识别 `insufficient_evidence`。
   - 不得当作通过。
   - 进入再取证、再验证或停机。
6. 增加 scenario 测试。
   - 修改说明声称已修但正文未改，验证必须失败。
   - 缺修改后正文，验证必须返回证据不足。
   - POV writer 严格遵守“不要元信息”时，FactChecker 修复链仍能拿到结构化 changelog，不能依赖正文标题切分。

## 验收标准

- 修复验证有独立 prompt 和输入 schema。
- 证据不足不会被默认为通过。
- 每个通过的修复都有正文依据。
