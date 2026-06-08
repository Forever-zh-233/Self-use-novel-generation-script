# POV 写手摘要防重复接入修复计划

## 结论

这是 summarizer 资产接入不完整：普通 writer 输入会注入“近期章节表达摘要·避免重复”，但 POV writer 走单独的 `build_pov_writer_input()`，没有接入同一套防重复摘要。结果 POV 章不受近期表达模式、重复句式、重复结构提醒约束。

## 当前证据

- `scripts/pipeline/summarizer.py:2`：summarizer 是写手摘要系统。
- `scripts/pipeline/summarizer.py:105`：提供 `anti_repeat_for_writer()`。
- `scripts/pipeline/context.py:1259-1263`：普通 writer sections 会调用 `anti_repeat_for_writer()` 并注入“近期章节表达摘要·避免重复”。
- `scripts/run_pipeline.py:641-642`：POV 章走 `build_pov_writer_input()`。
- `scripts/pipeline/context.py:1395-1406`：POV writer sections 只包含视角角色、角色信息、知识边界、本章 beat、最近公开事件、世界观设定等，没有摘要防重复区块。

## 根因判断

- 普通 writer 和 POV writer 使用两套上下文 builder，但通用写作约束没有抽成共享层。
- summarizer 的消费点只接入普通 writer，没有被列为所有 writer 分支的必备材料。
- 测试覆盖 summarizer 自身解析和普通 writer 防重复，但没有覆盖 POV writer input。

## 影响

- POV 章更容易重复近期章节的句式、情绪动作、结构模式。
- reviewer 可以事后指出重复，但 writer 生成时没有预防。
- 多 POV 弧线中，表达重复问题会集中出现在非沈安视角章节。

## 治本方案

1. 抽出 writer 通用 sections。
   - AI 腔黑名单
   - 近期重复动作禁用清单
   - summarizer 防重复摘要
   - 空间布局
   - 必要风格底线
2. 普通 writer 与 POV writer 都调用共享通用层。
   - POV 分支仍保留知识隔离，不注入沈安秘密。
   - 防重复摘要只使用公开表达模式，不泄露秘密。
3. 增加测试。
   - 写入最近 summaries。
   - 构造 POV beat。
   - 断言 `build_pov_writer_input()` 包含“近期章节表达摘要·避免重复”。
   - 断言该摘要不包含 POV 角色不该知道的秘密内容。

## 验收标准

- POV writer 与普通 writer 同样获得防重复摘要。
- 知识隔离不被防重复摘要破坏。
- 测试覆盖 POV writer 的 summarizer 接入。
