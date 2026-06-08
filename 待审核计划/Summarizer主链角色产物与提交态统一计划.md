# Summarizer 主链角色产物与提交态统一计划

## 结论

Summarizer 虽然被设计成“失败不阻断正文”的辅助角色，但它已经是主链上下文供给者：后续 writer/reviewer 会读取近期 summary。当前 summary 写入 `runtime/summaries`，不走统一角色产物路径，也没有 pending/committed 屏障、输入 hash、正文 hash 或审计 manifest。结果是：它失败时像辅助角色，成功时却像已提交历史。

## 当前证据

- `scripts/run_pipeline.py:949-955`：summary 在 Archivist 前生成，失败只打印“不影响正文”。
- `scripts/run_pipeline.py:957-998`：Archivist 在 summary 之后才更新 ledger/state 并推进提交水位。
- `scripts/pipeline/summarizer.py:16`：summary 写入 `runtime/summaries`。
- `scripts/pipeline/summarizer.py:32`：文件名是 `chapter_NNN.json`，没有走 `role_artifact()`。
- `scripts/pipeline/core.py:101`：`role_output_dir()` 没有 summarizer 角色。
- `scripts/pipeline/core.py:355`、`scripts/pipeline/core.py:379`：空目录清理与章节清理没有把 summarizer 作为角色产物处理。
- `scripts/pipeline/summarizer.py:105`、`scripts/pipeline/summarizer.py:155`：后续 writer/reviewer 会读取最近 summary。

## 根因判断

- “失败不阻断”被误扩展成“成功即可对后续可见”。
- summary 是实现态派生产物，但缺少和正文、beat、Archivist commit 的事务关系。
- summarizer 没纳入角色产物/审计留痕体系，无法回答“摘要基于哪一版 final、哪一版 beat、是否已经提交”。
- 后续消费者按路径存在读取 summary，而不是按章节提交水位和提交状态读取。

## 治本方案

1. 把 summary 写入 pending。
   - `runtime/summaries_pending/chapter_NNN.json`
   - Archivist commit 成功后再移动到 `runtime/summaries/chapter_NNN.json`。
2. 或在 summary JSON 内加入提交态。
   - `commit_status: pending|committed|stale|rejected`
   - `chapter`
   - `final_text_hash`
   - `beat_hash`
   - `summary_input_hash`
   - `model/provider/prompt_hash`
   - `committed_after_latest_chapter`
3. 后续消费者只读 committed。
   - `load_recent_summaries()`、writer/reviewer repetition context 必须过滤 `chapter <= state.latest_chapter` 且 `commit_status=committed`。
   - 对缺提交态的旧 summary 标为 legacy，默认不进入高权重上下文。
4. 纳入章节审计 manifest。
   - 即使不走 `role_artifact("summarizer")`，也必须记录 summary 输入/输出 hash、可见性状态、失败原因。
   - clean 模式不得删除唯一可证明 summary 来源的轻量凭证。
5. 明确失败语义。
   - summarizer 失败可不阻断正文提交，但应写 `summary_status=failed` 到章节 manifest。
   - summarizer 成功但 Archivist 失败时，summary 必须保持 pending，不得对下一章可见。

## 测试要求

- mock summary 成功、Archivist 连续失败，断言下一章 writer/reviewer 读取不到该 summary。
- Archivist 成功后，summary 才从 pending 变为 committed。
- clean 模式后仍能在 audit manifest 中看到 summary 的输入/输出 hash。
- 旧无提交态 summary 默认不作为 committed 高权重上下文读取，除非显式迁移。

## 验收标准

- summary 的可见性与章节提交水位一致。
- Summarizer 作为主链上下文供给者有产物身份、提交态和审计凭证。
- “失败不阻断正文”不再等于“成功可绕过提交屏障”。
