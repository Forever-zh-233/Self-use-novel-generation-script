# Ledger 子账鲜度对账计划

## 结论

Runtime 里的不同账本子系统会记录同一事实的不同侧面，但当前缺少跨子账鲜度对账。第 94 章样本中，铜牌磕痕已经在正文、07/08 和 active_threads 中推进成新伏笔 F-228，但 ledger 的符号/意象子账仍停在第 92 章，说明实现态推进没有同步到所有相关子账。

## 当前证据

- `输出/文章/第094章.md:105`：正文再次写到铜牌钝圆磕痕。
- `08-期待账本.md:977-979`：期待账本新增/推进相关伏笔。
- `runtime/active_threads.json:2135-2160`：active_threads 中出现 F-228 等第 94 章新债务。
- `runtime/ledger.json:3378-3383`：ledger 中“铜牌磕痕”符号仍为 `last_chapter: 92`、`count: 1`。

## 根因判断

- Archivist/merge 可能把伏笔债务写入 active_threads，却没有把同一载体的符号、意象、物件复现鲜度同步到 ledger 子账。
- 07/08 Markdown、active_threads、ledger 子账没有统一的“同一载体复现”对账器。
- 后续 planner/writer 读取不同摘要时，可能看到不同鲜度。

## 影响

- 某个意象/物件明明刚复现，规划层仍可能以为它很久没出现或只出现一次。
- 物件叠义、主题意象回响、伏笔回收窗口会被错误鲜度影响。
- 人类审计时同一事实在不同账本中互相打架。

## 治本方案

1. 定义跨子账对账范围。
   - active_threads F/LF 债务
   - ledger symbols/motifs/key_items/emotional_anchors
   - 07/08 可读日志
2. Archivist 提交时生成 `ledger_freshness_delta`。
   - 本章复现了哪些载体。
   - 写入了哪些子账。
   - 哪些相关子账未更新。
3. 对同一载体建立稳定 key 或 alias。
   - 如“铜牌磕痕”不能在伏笔与符号账中各自漂移。
4. 增加对账测试。
   - 正文/Archivist 报告推进某载体伏笔后，ledger symbol 的 `last_chapter/count` 应同步或明确标记不适用。
   - active_threads 和 ledger 同载体鲜度冲突时输出审计问题。

## 验收标准

- 同一物件/意象/伏笔载体在各子账的章节鲜度一致或有明确豁免。
- 规划层不会基于过期 ledger 子账判断复现间距。
- 第 94 章“铜牌磕痕”这类错位能被自动发现。
