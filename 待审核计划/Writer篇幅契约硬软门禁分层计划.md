# Writer 篇幅契约硬软门禁分层计划

## 结论

Writer prompt 要求正文 2500-3500 字，自然不足也允许低到约 2200 字；但代码客观下限只在低于 1800 字时报 warning，并且作为 satisfaction warnings 并不会直接阻断主流程。篇幅契约目前是 prompt 侧硬口径、代码侧软诊断，层级不清。

## 当前证据

- `prompts/writer.md:148-150`：要求正文 2500-3500 字，若自然支撑不足允许低于目标，但不应低到注水之外的程度。
- `scripts/pipeline/context.py:1129-1134`：`chapter_satisfaction_check()` 只有中文字符低于 1800 才报告“疑似被截断”。
- `scripts/run_pipeline.py:677-684`：该检查结果被放进 `satisfaction_check`。
- `scripts/run_pipeline.py:739`：Editor 触发只看 gate 是否失败或 reviewer 是否要求修；而 satisfaction 被作为 warnings 汇总时不一定触发硬修。

## 根因判断

- 系统没有定义“截断硬失败”和“篇幅偏短但可审美判断”的分界。
- prompt 的 2500-3500 是创作目标，1800 是截断安全线，两者没有在配置里分层表达。
- 测试没有覆盖“低于 writer 目标但高于 1800 时如何处理”的主流程行为。

## 影响

- 1900-2200 字的偏短章节可能稳定放行，只靠 reviewer 主观发现。
- 维护者看到 prompt 会以为篇幅目标被系统守住，实际只有极低截断线。
- 如果供应商输出半截但超过 1800 字，可能进入后续记忆。

## 治本方案

1. 配置化篇幅层级。
   - `hard_min_chars`：截断/异常硬失败，例如 1800 或按配置。
   - `target_min_chars`：创作目标下限，例如 2500。
   - `soft_min_chars`：自然不足可接受线，例如 2200。
2. 明确行为。
   - 低于 hard：阻断或重写。
   - hard 到 soft：强制 reviewer/editor 关注，必要时修。
   - soft 到 target：仅诊断，不作为硬失败。
3. gate JSON 中区分 `issues` 与 `warnings`。
4. reviewer 输入中明确展示篇幅诊断。
5. 增加测试。
   - 1700 字：硬失败。
   - 2000 字：非硬失败但必须进入 reviewer 诊断。
   - 2600 字：不触发篇幅警告。

## 验收标准

- 篇幅目标、软警告、硬截断线不再混在一起。
- 使用者能从配置看懂每条线的后果。
- 测试覆盖三段阈值行为。
