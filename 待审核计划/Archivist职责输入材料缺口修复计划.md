# Archivist 职责输入材料缺口修复计划

## 结论

这是记录员职责与输入材料不匹配：`archivist.md` 要求记录员检查长线伏笔资产、判断 LF 外显/提前揭真相，并根据弧线规划、story_director 批注、弧线 JSON 落配角 `arc_core/secrets`。但 `make_archive_input()` 实际只给结构化状态、物品/意象/愿录、最近台账和本章正文，没有给长线伏笔资产库，也没有给当前 active_arcs/story_director 原文。记录员被要求做它看不到依据的事。

## 当前证据

- `prompts/archivist.md:26`：记录员提示词要求读取 `15-长线伏笔资产库.md`。
- `prompts/archivist.md:71-74`：要求记录长线伏笔外显，并在提前揭露长线伏笔真相时输出警告。
- `prompts/archivist.md:360-363`：要求根据输入的弧线规划 / story_director 批注 / 弧线 JSON 中的 `independent_goal`、`hidden_agenda`、`knowledge_boundary` 落配角 `arc_core/secrets`。
- `scripts/run_pipeline.py:377-408`：`make_archive_input()` 只构造结构化当前状态、物品清单、意象、愿录、最近台账日志、本章正文。
- `输出/记录员/第087章_archive_input.md:1`：最新记录员输入从“结构化当前状态”开始。
- `输出/记录员/第087章_archive_input.md:1548`：只有“最近台账日志摘录”。
- `输出/记录员/第087章_archive_input.md:1618`：随后是“本章正文”。
- 最新 archive input 检索不到“长线伏笔资产库 / 当前活跃弧线 / story_director / hidden_agenda / knowledge_boundary”等依据区块。
- `prompts/archivist.md:436`：`emotional_anchor_echoed` 的登记条件依赖“beat 标注了回响 EA-XXX 且正文确实写了”，但记录员输入没有本章标准化 beat 或相关 beat 标注摘要。
- `beats/chapter_93.json:28`：第 93 章 beat 计划 `酿[F-173]`；后续台账新增的是 F-225/F-226，F-173 未被逐项对账，说明记录员没有被要求核对“当前 beat 的伏笔操作是否兑现/跳过/计划外新增”。
- `prompts/archivist.md:16-20`：提示词声称用户会告诉记录员“更新第几章的台账”。
- `prompts/archivist.md:468`、`prompts/archivist.md:498`、`prompts/archivist.md:503`、`prompts/archivist.md:521`、`prompts/archivist.md:533`、`prompts/archivist.md:546`：多处要求记录员输出 `第{N}章`。
- `scripts/run_pipeline.py:400-407`：`make_archive_input()` 没有“目标章节：第N章” section，只给结构化状态、物品、意象、愿录、最近台账和正文。
- `scripts/pipeline/context.py:786-790`：未超预算时 `compress_sections_if_needed()` 直接返回 section 文本，`chapter` 参数不会自动进入模型输入；`scripts/pipeline/context.py:811-812` 的“目标章节”只出现在压缩器输入里。
- `scripts/pipeline/archivist.py:1009-1010`：解析后注入 `_chapter` 只能帮助合并器，不会帮助模型在 Markdown/JSON 正文中正确填写章号。

## 根因判断

- archivist prompt 假设模型能读取本地文件，但实际主流程是把材料拼成输入，不会让模型自行读取路径。
- planning 阶段会给 volume_planner / arc_planner 注入长线伏笔资产库，但 archivist 阶段没有同步注入。
- 弧线规划中的配角隐藏议程有一部分在 `merge_side_characters_from_arcs()` 里进入 ledger，但 archivist 自身被要求做的“本章实质戏份落盘”缺少原始弧线依据。
- 记录员既承担“从正文抽取实现态”，又被要求判定某些计划态字段是否被兑现，但输入只给正文和历史状态，没有给“本章计划态最小清单”。
- 章节号被当成调用参数传给压缩/解析/合并层，却没有作为 critical 业务输入传给模型本身。

## 影响

- 长线伏笔外显可能漏记，提前揭真相也可能漏警告。
- 配角 `arc_core/secrets` 可能继续空着，或者记录员凭正文表层猜测，破坏“只记事实，不创作”的边界。
- 后续 writer 读 ledger 时拿不到配角水面下目标，配角容易退化成工具人。

## 治本方案

1. 重构 archive input 材料包。
   - 加入“目标章节 / 本章元数据”critical section：章节号、标题、POV、正文 hash、beat hash。
   - 加入“长线伏笔资产库摘要 / 当前卷相关 LF”。
   - 加入“当前活跃弧线中本章相关 side_characters / hidden_agenda / knowledge_boundary / beat_moments”。
   - 加入 story_director 当前批注摘要，尤其是本章硬约束和禁令。
   - 加入本章标准化 beat 的最小只读摘要：标题、时间锚点、章末钩子、伏笔操作、情感锚点回响、关键预期、禁止事项。
2. 明确 archivist 的职责边界。
   - 若不给弧线 JSON，就删除 prompt 中“根据弧线 JSON 落配角灵魂”的要求。
   - 若保留该职责，就必须给材料并要求只落盘“正文已实质表现 + 弧线已给依据”的内容。
   - 若要求记录 `emotional_anchor_echoed` 或伏笔兑现，就必须给对应 beat 标注；否则 prompt 不得要求记录员自行推测计划态。
3. 增加输入契约测试。
   - 检查 `make_archive_input()` 包含 archivist prompt 所要求的关键材料。
   - 构造 active_arcs 中配角 hidden_agenda，本章正文有该配角实质戏份，断言 archive input 含依据。
   - 构造 beat 中含 `伏笔操作: 回收[F-XXX]` / `回响[EA-XXX]`，断言 archive input 含这些计划项。
4. 增加长线伏笔外显测试。
   - fake 正文触碰 LF 载体，archive input 含资产库，断言 archivist 能生成外显记录或警告。

## 验收标准

- Archivist 不再被要求读取未注入的本地文件。
- 长线伏笔检查和配角 arc_core/secrets 落盘都有可见输入依据。
- 当前 beat 中需要记录员对账的计划字段有可见输入依据。
- 记录员在不触发压缩时也能明确看到本章章节号。
- 测试能防止 prompt 新增必读材料但 `make_archive_input()` 未同步。
