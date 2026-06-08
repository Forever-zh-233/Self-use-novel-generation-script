# Summary 事实强度与境界词汇校验计划

## 结论

章节 summary 会被后续防重复、评审重复检查以及部分近期回顾链路读取，但当前 schema 没有事实强度、否定约束、境界进展状态。第 93 章样本中，beat/正文/state 都是“息坎松动但没突破”，summary 却写成“突破息坎”，说明摘要会把弱进展升级成既成事实。

## 当前证据

- `beats/chapter_93.json:7`、`beats/chapter_93.json:25`：第 93 章 beat 明确“第四息坎松动但没破”“虽然没突破”。
- `输出/文章/第093章.md:23`、`输出/文章/第093章.md:35`：正文写“丝线没弹回来”“息坎松了”，不是正式突破。
- `runtime/summaries/chapter_093.json:37`、`runtime/summaries/chapter_093.json:41`：summary 写“修炼的艰难与突破”“突破‘息坎’”。
- `runtime/state.md:8`、`runtime/state.md:244`：state 更谨慎地写“息坎松了”。
- 需要收窄影响表述：代码直接消费 `runtime/summaries` 的主要是普通 writer 防重复和 reviewer 重复检查，见 `scripts/pipeline/summarizer.py:105,155`、`scripts/pipeline/context.py:1260`、`scripts/pipeline/gates.py:476`；beat/story_director 的近期回顾主要来自 `state.recent_events`、recent beats、上一章正文片段和规划输入，而不是所有规划链路都直接读 summarizer。

## 根因判断

- Summarizer schema 偏表达防重复，不适合承载强事实态；即便主要消费者是防重复/评审上下文，事实化措辞仍会污染后续判断。
- 没有区分 `未突破 / 松动 / 小突破 / 境界突破`。
- 没有对“没破、没突破、临界、松动”等否定/弱化词做校验。

## 影响

- 后续 planner/writer 可能把“松动”当“突破”。
- 近期事实回顾源切换后，若 summary 被当事实源，会放大错误。
- 修炼线和境界账可能被摘要误导。

## 治本方案

1. 扩展 summary schema。
   - `cultivation_progress_state`
   - `fact_strength`
   - `negative_constraints`
   - `uncertain_or_partial_progress`
2. 增加摘要事实强度校验。
   - 正文含“没突破/没破/尚未”等，summary 不得写成已突破。
   - beat 明确“未突破”，summary 必须保留否定约束。
3. 不通过的 summary 不进入 committed 可见区。
   - 标记 `summary_fact_check: failed`。
   - 后续消费者过滤或降权。
4. 增加 scenario 测试。
   - 正文“息坎松了但没破”，summary 写“突破”必须被拦截。
   - 正文正式突破且有代价，summary 才允许写突破。
5. 增加 quick 级 parser/schema 测试。
   - `_parse_summary()` 新增字段默认值必须稳定，旧 summary JSON 仍兼容。
   - `fact_strength`、`cultivation_progress_state`、`negative_constraints` 缺失时要有明确默认值或失败分类，不能静默变成“强事实”。
   - 解析失败降级时必须标记 `summary_fact_check: failed` 或等价状态，后续消费者不得把空摘要当可信事实。

## 验收标准

- Summary 不再把弱进展升级成既成事实。
- 修炼/境界相关摘要有事实强度字段。
- 事实强度失败的 summary 不作为后续事实回顾源。
- quick 与 scenario 两层测试同时覆盖：纯解析默认值不漂移，端到端消费不再把“未突破”读成“突破”。
