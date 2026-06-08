# POV 影响种子 best_window 生命周期契约修复计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

`impact_seeds.best_window` 被主流程生命周期清理逻辑消费，但 Archivist 的主 STRUCTURED_UPDATE 示例没有这个字段，只有后文细则才提到。模型按主示例输出时，pending 影响种子会缺失 best_window，过期清理无法生效，长期污染 POV 候选池。

## 当前证据

- `prompts/archivist.md:163-170`：主示例里的 `impact_seeds` 包含 `id/who/what/pov_voice/directions/ignorant_of`，未展示 `best_window`。
- `prompts/archivist.md:306-318`：后文细则中的示例才包含 `best_window` 和 `status`。
- `scripts/run_pipeline.py:1010-1020`：主流程清理 pending seed 时读取 `s.get("best_window", "")`，解析窗口上限并在超期后 dropped。

## 根因判断

- prompt 示例与代码生命周期契约不一致。
- `best_window` 是状态机字段，不是可选文案；但 schema 没有把它列为必填。
- 清理逻辑缺少“缺 best_window 的 pending seed 是坏数据”的处理。

## 影响

- 模型按主示例产出的 seed 没有生命周期上限。
- 过期 POV 候选会长期 pending，被后续规划反复看见。
- POV 回响可能在不合适的章节被翻出来，造成节奏拖尾。

## 治本方案

1. 统一 Archivist impact_seeds schema。
   - 主示例和细则都列出 `best_window`、`status`。
   - 明确 `best_window` 格式，例如 `第X-Y章` 或结构化 `{start,end}`。
2. 代码提交前校验。
   - pending seed 缺 `best_window` 时不直接入账，要求 Archivist 重试或自动标 `needs_window`。
   - 已入账旧 seed 缺窗口时，按保守策略 dropped 或进入人工审计队列。
3. 改为结构化窗口。
   - 长期方案用 `best_window_start` / `best_window_end`，减少正则解析中文文本。
4. 增加测试。
   - Archivist 输出缺 best_window，断言不会作为正常 pending 入账。
   - 超过窗口 +10 章，断言 pending 自动 dropped。
   - 主示例 schema 与代码必填字段快照一致。

## 验收标准

- 所有 pending impact seed 都有可机器解析的生命周期窗口。
- 主示例、细则、代码消费字段一致。
- 过期 seed 不会长期污染 POV 候选池。
