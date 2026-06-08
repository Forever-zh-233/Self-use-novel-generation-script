# FactChecker 修复后缺少再门禁修复计划

## 结论

这是门禁顺序问题：final_gate 在 editor 后执行，但 fact_checker 发生在 final_gate 之后，并且 fact_checker 可调用 writer 改写正文。改写后的正文没有再次经过 hard_gate/style_gate/continuity/type_guard/final_gate，就会直接写入正式文章。也就是说，事实修复可能引入新的 AI 腔、格式问题、连续性问题或标题问题，而后续没有代码门禁兜底。

## 当前证据

- `scripts/run_pipeline.py:773-794`：editor 后计算 `final_gate`，并按配置决定是否阻断。
- `scripts/run_pipeline.py:798-902`：final_gate 之后才进入 fact_checker。
- `scripts/run_pipeline.py:829-839`：fact_checker 发现穿帮后调用 writer 生成 `fact_fix_1.md`，并用 `fix_body` 替换 `final`。
- `scripts/run_pipeline.py:866-875`：第二轮仍可再次调用 writer 生成 `fact_fix_2.md`，并替换 `final`。
- `scripts/run_pipeline.py:904-912`：事实修复后只做标题清洗/替换。
- `scripts/run_pipeline.py:914-915`：随后直接写入 `writer/final.md` 与正式文章。
- 事实修复后的正文没有再次调用 `hard_gate()`、`style_gate()`、`continuity_check()`、`type_guard_check()` 或 `chapter_satisfaction_check()`。

## 根因判断

- 主流程把 final_gate 当成 editor 后门禁，而不是“所有正文修改后的最终门禁”。
- fact_checker 修复本质上是一次 writer 改写，但没有纳入 gate/reviewer/editor 的统一修复循环。
- 标题清洗只处理格式头，不检查正文内容质量和连续性。

## 影响

- 修穿帮时可能引入新的禁句、AI 腔、视角错误、连续性错误。
- final_gate 报告对应的是 fact_checker 修改前的版本，无法证明最终落盘正文通过门禁。
- 后续 summarizer / archivist 读取的是未经最终门禁验证的版本。

## 治本方案

1. 把 final_gate 移到所有正文改写之后。
   - writer 初稿、editor、fact_checker 修复都只是中间版本。
   - 最后一版正文必须统一跑 final gate。
2. 每次 fact_checker 修复后至少跑轻量代码门禁。
   - hard_gate
   - style_gate
   - continuity_check_adjacent
   - type_guard_check
   - chapter_satisfaction_check
3. 若修复后新增 gate issue，进入同一修复预算或停机。
4. final_gate JSON 应记录所校验正文的 hash/长度。
   - 防止 gate 报告与最终落盘正文不是同一版本。
5. 增加 scenario 测试。
   - fake fact_checker 修复输出新增禁句。
   - 断言修复后 final_gate 能捕获，并阻断 summary/archive。

## 验收标准

- 正式落盘正文一定有对应的最终 gate 报告。
- final_gate 报告所校验文本与 `输出/文章/第NNN章.md` 是同一版本。
- fact_checker 修复不能绕过硬门禁。
