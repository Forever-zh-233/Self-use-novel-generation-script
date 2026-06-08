# FinalGate 失败仍推进主流程修复计划

## 结论

这是一个主流程门禁断链：`final_gate` 已经能识别正文硬问题，但默认配置下失败不会阻断章节落盘、archivist、summary 与下一章推进。结果是“明知不合格”的正文仍会进入后续记忆和连续生成链路。

## 当前证据

- `scripts/run_pipeline.py:773-794` 会在 editor 之后计算 `final_gate` 并写入结果；当 `passed=false` 时只记录日志。
- 同一段逻辑只有在 `run_cfg.get("fail_on_final_gate", False)` 为真时才抛错中断。
- `config/run.json` 没有配置 `fail_on_final_gate`，因此默认值是 `False`。
- `scripts/pipeline/gates.py:448-465` 的 `combine_checks()` 只用各子检查的 `issues` 决定 `passed`，所有 `warnings` 都不会阻断。
- `scripts/pipeline/context.py:1129-1135` 的 `chapter_satisfaction_check()` 会把“正文过短，疑似被截断”作为 issues 返回，但 `scripts/run_pipeline.py:779-786` 又把它包装成 `{"issues": [], "warnings": final_satisfaction}`，导致正文截断类客观问题不会让 `final_gate.passed=false`。
- `scripts/pipeline/gates.py:569-577` 的 `type_guard_check()` 名为 gate，但始终返回 `passed=True`，story_director 偏航只进入 warning。
- 第 83 章当前正文被 `pipeline.gates.hard_gate()` 判定失败：
  - `passed=false`
  - 硬问题：`AI腔'不是A是B'句式在叙述中出现2次（已全禁）`
  - 命中句：
    - `输出/文章/第083章.md:139`：`不是放松，是没力气了`
    - `输出/文章/第083章.md:283`：`不是刨地，是换了个重心`
  - 另有视觉穿帮 warning：
    - `输出/文章/第083章.md:113`：白天强光环境下仍出现主角顺方向“看了一眼”的精细视觉动作。
- `runtime/progress.json` 已推进到第 84 章 reviewer，说明第 83 章 final gate 失败没有阻断后续主流程。

## 影响

- 硬门禁变成“提示日志”，不能保证正文质量底线。
- 正文过短/疑似截断这类客观提交失败会被降级成 warning，可能生成 `final_gate.passed=true` 的假通过。
- `type_guard_check()` 的命名和行为不一致，维护者容易误以为 story_director 偏航会阻断。
- 不合格正文会进入：
  - `输出/文章/第NNN章.md`
  - chapter summary
  - archivist 台账与状态更新
  - 下一章上下文
- 后续章节可能继续继承已经被 gate 判定有问题的表达、视觉动作或设定事实。
- 测试如果只验证 `hard_gate()` 能识别问题，而不验证主流程是否中断，就会漏掉这个关键断链。

## 修复建议

1. 默认让 `final_gate` 的 hard issue 阻断推进。
   - warnings 可继续只记录，hard issues 必须阻断。
   - 若需要临时放行，应显式配置 `fail_on_final_gate=false`，并在日志中标记为人工豁免。
   - `fail_on_final_gate` 不应控制客观硬伤是否阻断，只控制软问题是否严格化。
   - “正文过短/疑似截断”、内部编号泄露、hard_gate、连续性断裂必须默认阻断。
2. 将 final gate 放在所有后续状态提交之前。
   - `passed=false` 时不要调用 summarizer。
   - 不要调用 archivist。
   - 不要更新 latest chapter / progress 到下一章。
3. 支持自动修复回路。
   - editor 输出后若 final gate 失败，可带 gate issues 再走一次 editor。
   - 达到重试上限后停在当前章，并保留失败报告供人工处理。
4. 增加主流程 scenario 测试。
   - 构造一个 fake editor 输出，包含硬禁句。
   - 断言 `final_gate.passed=false`。
   - 断言主流程不会进入 summarizer / archivist。
   - 断言不会推进到下一章。
   - 断言失败报告被落盘。
   - 构造一个少于 1800 字的 final，断言 `satisfaction_check` 以 hard issue 进入 final_gate，而不是 warning。
   - 构造 story_director severity=3 且 beat/final 未执行纠偏，断言要么明确诊断为非阻断项，要么按 hard policy 阻断，不能名字叫 gate 但永远通过。

## 验收标准

- hard issue 出现时，章节生成停在当前章。
- `runtime/progress.json` 不会进入下一章角色。
- 不会生成该章 summary 与 archivist 提交。
- 日志与 `final_gate` JSON 明确展示阻断原因。
- 对应 scenario 测试纳入测试文件维护清单并通过。
