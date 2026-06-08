# 长线伏笔 Touch-Reveal 落点统一修复计划

## 结论

Archivist prompt 让模型输出 `long_foreshadowing_touches[].id`、`status`、`warning`，但 reveal ledger 以 `topic` 建账，merge 查不到就跳过，查到了也只写 touch/new_information，警告和状态没有落点；下游规划又不读 touches。长线伏笔 touch 管路写了但不闭环。

## 当前证据

- `prompts/archivist.md:137`：`long_foreshadowing_touches` 使用 `id = LF-001`，并包含 `status/warning`。
- `prompts/archivist.md:431`：`reveal_ledger_update` 按 `topic` 建账，没有稳定 `lf_id`。
- `scripts/pipeline/archivist.py:126`：merge touch 用 `id or topic` 查 reveal 节点，查不到就 `continue`。
- `scripts/pipeline/archivist.py:126`：merge 只写 `chapter/touch/new_information`，不消费 `status/warning`。
- `scripts/pipeline/planning.py:407`：长线伏笔进度读取 topic/revealed_level/last_reveal_chapter/plan_next_level_in，不读取 touches。

## 根因判断

- LF 资产库、reveal ledger、touch 记录缺少同一个稳定主键。
- Prompt 要求输出诊断 warning，但提交系统没有诊断落点。
- 下游规划读取 reveal 进度时忽略 touch 历史，touch 对后续没有效果。

## 影响

- 正文外显 LF 后可能写入 touches，但 planner 仍看不到最近触碰。
- 提前揭真相的 warning 可能只停在报告里，甚至报告 clean 后不可追踪。
- LF id 写错或未建账时不会阻断，长线伏笔进度静默断链。

## 治本方案

1. 给 reveal ledger 增加稳定 `lf_id`。
2. `long_foreshadowing_touches` 必须匹配已有 `lf_id`。
   - 未匹配时 validate 阻断或生成待人工处理诊断。
3. 定义 `status/warning` 落点。
   - warning 进入章节提交报告或 gate 诊断。
   - status 更新 reveal 节点或 LF 资产进度。
4. `long_foreshadowing_progress()` 显示最近 touch。
5. 增加测试。
   - touch 匹配 LF 后，下游规划输入能看到最近触碰。
   - touch 未匹配时不得静默跳过。
   - warning 不会因 clean 模式丢失。

## 验收标准

- LF touch、reveal ledger、planner progress 使用同一主键。
- warning/status 有提交落点。
- touch 写入后能影响后续规划输入。
