# 期待账本权威源与 active_threads 同步计划

## 结论

`08-期待账本.md` 和 `runtime/active_threads.md/json` 同时表现普通伏笔债务，但两者并非严格同源渲染。样本中 08 已把 F-210 标成“部分回收”，active_threads 仍显示未明确/未回收语义，说明权威源和 Markdown 镜像同步边界不清。

## 当前证据

- `08-期待账本.md:959`：F-210 被记录为部分回收。
- `runtime/active_threads.md:328`：F-210 仍呈现未明确/未回收语义。
- `scripts/pipeline/archivist.py:1016-1025`：`状态台账增量`/`期待账本增量` 直接追加到 Markdown。
- `scripts/pipeline/archivist.py:690-714`：active threads 另有 JSON merge 和状态淘汰逻辑。

## 根因判断

- Markdown 账本既像输入日志，又像事实账本，和 JSON 线程账职责重叠。
- 记录员报告可以同时更新 JSON 和追加 Markdown，但缺少“同一事实一次提交、两处同步渲染”的契约。
- 后续上下文可能读取 Markdown 摘录，也可能读取 JSON 渲染，造成事实态不一致。

## 影响

- 同一 F-ID 在不同输入源中状态不同。
- planner/writer 可能继续推进已部分回收的伏笔，或漏收未回收伏笔。
- 人类审阅时难以判断哪个文件是真值。

## 治本方案

1. 明确权威源。
   - 建议 `runtime/active_threads.json` 为普通伏笔债务真值。
   - `08-期待账本.md` 作为人类可读提交日志或由 JSON 渲染的镜像。
2. 统一提交路径。
   - 新埋、推进、部分回收、已回收必须先进入 JSON。
   - Markdown 由同一结构化 update 生成。
3. 增加对账器。
   - 同一 F-ID 在 08 和 active_threads 状态不一致时报错。
4. 调整上下文读取。
   - Writer/planner 优先读 JSON 渲染，不读可能滞后的 Markdown 日志。
5. 增加 scenario 测试。
   - F-ID 部分回收后 JSON 和 Markdown 同步。
   - Markdown 追加失败不得造成 JSON 已提交但可读镜像缺失无诊断。

## 验收标准

- 普通伏笔债务只有一个机器真值。
- Markdown 与 JSON 不再出现同 ID 状态冲突。
- 上下文输入使用已提交的同源渲染。
