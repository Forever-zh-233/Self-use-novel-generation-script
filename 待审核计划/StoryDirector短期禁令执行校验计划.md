# StoryDirector 短期禁令执行校验计划

## 结论

这是管路级执行问题：story_director 可以给出明确短期禁令，但禁令只以自然语言注入 beat_planner，没有结构化字段、没有 beat 后校验、没有 archive 反查。于是下游可以新增被禁止的信号源，archivist 还会把它登记成新伏笔，系统没有任何一层把“总监禁令被违反”转成阻断或显式告警。

## 当前证据

- `runtime/story_director.md:13`：83 章小满朝南抱头“不需额外加料”。
- `runtime/story_director.md:26`：83-84 章“不再新增伏笔编号”。
- `runtime/story_director.md:27`：明确“不要再引入新的‘南边信号源’”。
- `beats/chapter_83.json:26`：章末钩子改成“院子里多了一串湿脚印，从南墙根一直延伸到水缸边……木瓢……收在了灶台里”。
- `beats/chapter_83.json:28`：伏笔操作仍写“无”，没有把新增信号源作为计划内伏笔处理。
- `输出/文章/第083章.md:293`：正文新增院子石板上的脚印。
- `输出/文章/第083章.md:297`：脚印从南墙根延伸过来。
- `输出/文章/第083章.md:309`：水缸盖子上新增木瓢。
- `输出/文章/第083章.md:313`：木瓢“像有人放好了等着用”。
- `07-动态状态台账.md:2697`：台账新增 F-199 光脚印。
- `07-动态状态台账.md:2698`：台账新增 F-200 木瓢移位。
- `prompts/story_director.md:93`：输出字段包含 `priority/tidy_threads/background_threads/avoid_new_debt/watch_repetition/restraint_note` 等。
- `scripts/pipeline/state.py:441`：这些字段主要被渲染成 Markdown 批注给后续 LLM 看。
- `scripts/run_pipeline.py:138`：代码硬校验主要只覆盖 severity、arc_instruction、watch_repetition、correction_action 等少数点，其他短期约束/优先级缺少结构化执行验收。

## 根因判断

- story_director 输出没有结构化“禁令字段”，只靠 markdown 文本约束模型。
- story_director 多个输出字段处在“渲染给模型”层，没有形成可由 beat/final/archive 校验的结构化执行清单。
- `ensure_beat()` 的方向校验主要看是否吸收批注，没有对“禁止新增 X”做可执行检查。
- hook_self_check 可以改写章末钩子，但缺少对 story_director 禁令的二次校验。
- archivist 能新增 F-XXX，但提交前没有反查“本章是否处在 no_new_foreshadowing 窗口”。

## 影响

- 沉期本该降噪，结果新增一个实体入侵/未知存在债务。
- 84-88 章原本应聚焦碎屑、黑子、韩铮、铜牌、窑厂方向，新增脚印/木瓢会抢走读者注意力。
- story_director 的“禁令”目前只是提示文本，beat_planner/hook_self_check/archivist 都没有阻断或要求人工确认。
- `priority/avoid_new_debt/restraint_note` 等短期约束可能被下游忽略，系统也不会生成“本章是否执行总监短期要求”的结构化报告。
- 伏笔操作写“无”，但正文和台账新增 F-199/F-200，造成“计划无新增 / 产物有新增”的追溯断层。

## 治本方案

1. 给 story_director 的短期禁令增加结构化字段：
   - `no_new_foreshadowing`
   - `forbidden_signal_sources`
   - `no_extra_hook_material`
   - `must_prioritize`
   - `avoid_new_debt`
   - `restraint_rules`
2. 在 beat 生成后做禁令校验：
   - 若 direction 禁止新增南边信号源，beat 的章末钩子、伏笔操作、意外处理不得新增同类实体。
   - 若确需新增，必须写出“覆盖 story_director 禁令的理由”，并触发人工审核。
   - 输出 `story_director_compliance.json`，逐条记录 fulfilled / partial / violated / not_applicable。
3. 在 archivist 提交前做反查：
   - 如果 story_director 禁止新增伏笔编号，但 archivist 报告新增 F-XXX，应阻断提交或至少标红。
4. 增加 scenario 测试：
   - 构造 story_director 禁止新增某类信号源。
   - fake beat_planner 输出新增信号源。
   - 断言主流程要求重生 beat 或生成阻断报告。

## 验收标准

- story_director 明确禁令能被 beat/final/archive 三处检测到。
- story_director 的短期 priority/restraint/avoid_new_debt 能被结构化验收，而不是只渲染给 LLM。
- 第 83 章这类“伏笔操作=无，但正文/台账新增伏笔”的情况会被测试捕获。
- 后续章节不再无提示新增被 story_director 禁止的同类信号源。
