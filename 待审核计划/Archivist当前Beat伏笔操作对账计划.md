# Archivist 当前 Beat 伏笔操作对账计划

## 结论

Archivist 只按正文抽取事实，没有逐项对账当前 beat 的 `伏笔操作`、章末钩子和关键预期。结果是计划中的 F-ID 可能没有兑现却静默消失，正文计划外新增伏笔又被另起新条，缺少“计划项兑现/跳过/计划外新增”的机器账。

## 当前证据

- `beats/chapter_92.json:30`：第 92 章 beat 写 `伏笔操作: 无`。
- `输出/文章/第092章.md:89`、`输出/文章/第092章.md:325`：正文实际写了远志试探和铜牌磕痕。
- `08-期待账本.md:959`：台账把 F-210 标成部分回收，说明实现态有伏笔动作但 beat 计划字段没记录。
- `beats/chapter_93.json:28`：第 93 章 beat 计划 `酿[F-173]`。
- `08-期待账本.md:969`、`runtime/active_threads.md:345`：实际新增 F-225/F-226，F-173 未见对应推进。
- `beats/chapter_95.json:7`、`beats/chapter_95.json:34`：第 95 章 beat 计划“回收 F-184（周济认朱砂印）、F-185（小满感知能力外显）”。
- `08-期待账本.md:824-825`、`runtime/active_threads.md:300-301`：canonical F-184/F-185 实际分别是“药方折痕”和“碎屑对窑厂/药方两个方向共鸣”，不是 beat 括号里的“周济认朱砂印/小满外显”。相关语义更接近 F-190、F-198、F-210，见 `runtime/active_threads.md:308`、`runtime/active_threads.md:316`、`runtime/active_threads.md:328`。
- 第 95 章 Archivist 没有把 F-184/F-185 标回收，而是新增 F-230/F-231/F-232，见 `runtime/active_threads.md:350-352`、`08-期待账本.md:986-988`。其中 F-232“前门灰蓝布衣”与已有 F-229“后门/前门有人”高度重叠，见 `runtime/active_threads.md:349`、`08-期待账本.md:979`。
- 第 96 章 beat 计划韩铮出场并写 `收[F-186]/酿[F-218]`，但 final 只写匿名“东门哨所/靴声转向往里走”，见 `输出/文章/第096章.md:57,69,75`；`runtime/state.md:207` 又明确写“但这次不是韩铮”；最终新增 F-234，见 `runtime/active_threads.md:354`、`08-期待账本.md:997`。这应被对账为 `id_semantic_mismatch + missing_from_final + extra_in_final`。
- 第 97 章已有 F-227“药包硬棱”，正文只给出触觉疑似“像……铜片？”且没拆，summary 也记录“未解之谜”，见 `runtime/summaries/chapter_097.json:8,55`；但 state 升级成“是铜片”，见 `runtime/state.md:9,202,213`，Archivist 又新增 F-235。这里缺少 `fact_strength` 与 `evidence_quote`，导致疑似事实被提交成确定事实。

## 根因判断

- Beat 的伏笔计划态没有进入 Archivist 对账输入。
- Archivist prompt 强调“只记事实”，没有要求输出每个计划 F-ID 的兑现状态。
- 计划内未兑现和计划外新增都没有结构化差异报告。
- Beat/Archivist 对 F-ID 只做字符串级引用，没有先解析到 canonical 描述；模型可以在括号释义里把 F-184/F-185 临时改义，后续角色也不会阻断。
- 新增伏笔前缺少相似未回收旧伏笔检索，导致“前门灰蓝布衣”这类已在 F-229 承诺里的事项被另开 F-232。

## 影响

- 弧线规划安排的伏笔操作可能被正文绕过，系统仍推进。
- 新增伏笔越来越多，旧伏笔不收，债务膨胀。
- 人类只能靠读正文和台账发现错位。

## 治本方案

1. `make_archive_input()` 注入当前 beat 伏笔最小清单。
   - `伏笔操作`
   - 章末钩子
   - 关键预期
   - 相关 F/LF/EA ID
2. Archivist 输出增加 `beat_plan_reconciliation`。
   - `fulfilled`
   - `partial`
   - `skipped`
   - `extra_in_final`
   - `needs_human_review`
   - `fact_strength`
   - `evidence_quote`
   - `canonical_id_checked`
3. 对 F-ID 做硬对账。
   - beat 提到的 F-ID 必须出现在 reconciliation。
   - 正文新增 F-ID 或新伏笔必须标计划外新增。
   - beat 提到的 F-ID 必须先展开 canonical 描述；括号释义与 canonical 承诺不一致时，标为 `id_semantic_mismatch` 并阻断或要求重写。
   - Archivist 新开 F-ID 前先检索 active_threads/08 中相似未回收项，相似度高时必须选择“推进旧项/部分回收/拆分原因”，不能直接新增。
4. 与 Beat-Final-Summary 差异审计联动。
   - 差异报告进入章节 manifest 或 audit trail。
5. 增加 scenario 测试。
   - beat 计划 F-173，正文没有兑现，必须记录 skipped。
   - beat 无伏笔，正文新增伏笔，必须记录 extra_in_final。
   - beat 写 `收[F-184]` 但括号释义与 F-184 canonical 描述不一致时，必须失败或进入人工复核。
   - 正文出现“前门灰蓝布衣”且已有 F-229 未回收时，Archivist 不得静默新增重复 F-ID。
   - 正文只写“像铜片？”且明确没拆时，不得提交为“确认是铜片”；只能标 `uncertain/partial` 并关联旧 F-227。

## 验收标准

- 当前 beat 的伏笔计划不会静默丢失。
- 计划外伏笔新增有明确记录。
- 普通伏笔债务能区分“计划未兑现”和“正文新增”。
