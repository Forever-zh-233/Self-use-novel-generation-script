# FactChecker 残留穿帮阻断修复计划

## 结论

这是事实核查守门语义断链：`fact_checker.md` 把“穿帮问题”定义为必须修正，但主流程在第二轮修复后如果最终验证仍有残留，只写 `residual_issues.md` 并“接受现状”继续推进。事实核查从硬门禁退化成记录日志。

## 当前证据

- `prompts/fact_checker.md:4`：事实核查员唯一职责是核对正文有没有穿帮。
- `prompts/fact_checker.md:87`：输出格式中“穿帮问题（必须修正）”。
- `prompts/fact_checker.md:107`：穿帮编号格式是脚本解析依据。
- `scripts/run_pipeline.py:810-817`：主流程解析事实核查报告中的穿帮条目。
- `scripts/run_pipeline.py:856-875`：验证仍有问题时会再让 writer 修一次。
- `scripts/run_pipeline.py:887-891`：第二次验证仍有残留时，只打印“接受现状”，写 `residual_issues.md`。
- `scripts/run_pipeline.py:914-915`：随后仍将当前 final 写入 `writer/final.md` 和正式文章路径。
- `scripts/run_pipeline.py:950-998`：后续仍会进入 summarizer 与 archivist。
- 当前 fact checker 报告是 Markdown 文本解析，主流程没有沉淀 `{passed, issues, residual, waived}` 结构化状态，导致“残留问题是否阻断”只能靠局部 if 分支和日志理解。

## 根因判断

- fact_checker 的提示词是硬门禁语义，但主流程实现是“有限自动修复后放行”。
- `residual_issues.md` 只是旁路产物，不会阻断 summary、archivist 或下一章。
- 测试只覆盖纯函数 `fact_check_against_ledger()` 的若干判断，没有覆盖“残留穿帮是否阻断主流程”。

## 影响

- 已确认的事实穿帮会进入正式正文。
- summarizer / archivist 会把有穿帮的正文写入后续记忆，污染下一章上下文。
- 使用者看到“事实核查”阶段可能误以为穿帮已被硬性清除，实际只是被记录。

## 治本方案

1. 明确 fact_checker hard issue 的策略。
   - 默认：残留穿帮阻断推进。
   - 如需临时放行：必须显式配置 `allow_fact_checker_residual=true`，并写人工豁免原因。
   - 豁免必须绑定 final hash、问题编号、原因和有效范围，不能用全局开关静默放行。
2. 将残留问题接入主流程状态。
   - progress 写为 `blocked_on_fact_check` 或 `chapter_error`。
   - 不进入 summarizer。
   - 不进入 archivist。
   - 不推进下一章。
   - 写入 `fact_check_status.json`，包含 `passed/residual/waived/final_hash`。
3. 与 `max_revisions` 统一。
   - fact_checker 修复轮次计入章节修复预算。
   - 达上限仍失败时停机，不静默接受。
4. 增加 scenario 测试。
   - fake fact_checker 第一轮报穿帮，writer 修复后 verify 仍报残留。
   - 断言不会写 summary / archivist，不推进 progress 到下一章。
   - 断言 `residual_issues.md` 与阻断状态都存在。

## 验收标准

- “穿帮问题（必须修正）”不再被默认接受现状。
- 残留穿帮不能进入章节记忆链路。
- 测试覆盖最终验证仍失败的主流程分支。
