# VolumePlanner 目标卷身份显式化计划

## 结论

VolumePlanner prompt 要求知道“当前是第几卷、即将规划第几卷”，但主流程只显式传入当前章节号和“请为接下来的卷生成卷纲”。目标卷身份靠模型从全书骨架和当前章节推断，缺少结构化卷号、当前卷范围、目标卷范围。

## 当前证据

- `prompts/volume_planner.md:10-13`：输入清单要求当前卷、即将规划卷、上一卷回顾摘要。
- `scripts/pipeline/planning.py:610-618`：run_volume_planner 输入包含全书骨架、当前章节号、正典账本、状态、期待账本、长线伏笔、上卷回顾。
- `scripts/pipeline/planning.py:612`：当前章节号 section 只是“第X章。请为接下来的卷生成卷纲。”，没有当前卷号/目标卷号/目标 chapter_range。
- `scripts/pipeline/planning.py:375`：`current_volume_info()` 主要从 Markdown 正则提取 `章节范围`，失败后兜底找所有“第N章”。
- `scripts/pipeline/planning.py:391`：解析不到 `end` 时 `needs_volume_planning()` 直接不触发。
- `scripts/pipeline/planning.py:637`、`scripts/pipeline/planning.py:644`：新卷纲生成后会直接覆盖 `卷纲/10-卷纲.md`，缺少覆盖前目标卷/章节范围校验。
- 第 101 章现场样本显示卷边界已经失守：
  - `卷纲/10-卷纲.md:1,5,106` 仍是“第一卷：竹杖芒鞋（下）”，章节范围 `第97章 - 第100章`，附注写“第2卷将在下一周期生成”。
  - `输出/章纲/第101章_beat_input.md:1-2` 目标章节是第 101 章，但 `输出/章纲/第101章_beat_input.md:371-477` 注入的仍是第一卷 97-100 章卷纲。
  - `输出/写手/第101章_writer_input.md:472-578` 写手输入同样带着第一卷 97-100 章卷纲；同一输入后段 `输出/写手/第101章_writer_input.md:1460-1464` 的 formal beat 又写“第二卷·开篇”，说明下游在错位上下文中自行拼接第二卷语义。
  - `runtime/volume_planner_output.md:1-6,104-106` 最近一次 VolumePlanner 输出本身仍是第一卷 97-100 章内容，主流程没有在“目标章=101、输出卷纲 end=100”时拒绝提交或阻断 beat 生成。

### 追加审计证据（当前状态）

- 当前正式卷纲已经变成第二卷，但把章节范围写成 `第102章 - 第200章`，见 `卷纲/10-卷纲.md:1-5`。
- `runtime/volume_planner_output.md:1-5` 同样是第二卷且从第 102 章开始，说明 VolumePlanner 输出提交后仍没有校验“触发规划的目标章是否落入输出范围”。
- `beats/chapter_101.json:3,7` 把第 101 章标为“第二卷·开篇”，但当前第二卷卷纲不覆盖第 101 章，形成“第 101 章既不是第一卷范围，也不是第二卷范围”的孤章。
- 这不是要修第 101 章正文，而是证明 VolumePlanner 提交门禁缺少连续卷范围校验：除非显式声明 `transition_chapter=101`，否则卷范围必须连续覆盖所有已生成/待生成章节。

## 根因判断

- 卷身份是结构化调度信息，却被留给模型自行推断。
- 全书骨架里有卷信息，但主流程没有解析后以不可误解的形式传给 VolumePlanner。
- 覆盖卷纲属于高影响写操作，目标身份不显式会增加覆盖错卷风险。
- 当前卷范围解析脆弱，解析失败会导致不触发规划；解析错或模型输出错卷时又可能直接覆盖正式卷纲。
- 即便 `needs_volume_planning(101)` 理论上应触发，当前也缺少“规划完成后再确认目标章已落入新卷纲范围”的提交门禁；因此错误输出、旧输出或未刷新状态都可能继续喂给 BeatPlanner。

## 影响

- 模型可能规划错卷，尤其在卷边界、章节范围重叠或全书骨架格式不稳定时。
- 后续 ArcPlanner/BeatPlanner 会建立在错误卷纲上。
- 第 101 章这类跨卷章会在“目标章已经越过卷纲 end”的状态下继续生成 beat、writer、reviewer，形成旧卷纲 + 新卷标题的混合产物。
- 人工排查时很难判断 VolumePlanner 当时以为自己在写哪一卷。

## 治本方案

1. 从全书骨架解析卷结构。
   - `current_volume`
   - `current_volume_range`
   - `target_volume`
   - `target_volume_range`
   - `target_volume_outline_constraints`
2. run_volume_planner 输入增加“卷身份调度卡”。
   - 标为 critical，不可压缩。
3. 输出后校验。
   - 卷号、章节范围、核心 turning points 必须与目标卷匹配。
   - `target_chapter` 必须落在输出卷纲 `chapter_range` 内；例如第 101 章触发规划后，输出仍为 97-100 章时必须拒绝。
   - 输出卷纲不得制造未声明的孤章；若第二卷从第 102 章开始，而第 101 章已经被系统标为第二卷开篇，必须拒绝提交或要求显式 `transition_chapter` 元数据。
   - 卷范围必须与上一卷连续或有结构化断点说明，不能只靠标题“第二卷开篇”让下游自行解释。
   - 不匹配则拒绝覆盖 `卷纲/10-卷纲.md`。
   - 章节范围解析失败时应停机或要求人工确认，不得静默不规划。
   - 新卷纲先写 staging，校验通过后再替换正式卷纲。
4. BeatPlanner 前增加卷水位硬门。
   - `build_beat_input()` 或 `ensure_beat()` 使用卷纲前先校验 `chapter <= current_volume.end`。
   - 若 `chapter > current_volume.end`，必须先有校验通过的目标卷纲；没有则停在规划阶段，不生成 beat。
   - 该门禁要覆盖 `main()` 调度入口、直接调用 `ensure_beat()`、以及已有 beat 复用入口。
5. 增加 scenario 测试。
   - 当前章在第 1 卷末，目标卷必须是第 2 卷。
   - 模型输出错卷号时不得覆盖现有卷纲。
   - 现有卷纲缺 `章节范围` 时不得静默跳过规划。
   - 第 101 章、当前卷纲 end=100、VolumePlanner 返回第一卷 97-100 章时，断言不生成 `beats/chapter_101.json`，不写 `输出/章纲/第101章_beat_input.md`。

## 验收标准

- VolumePlanner 明确知道当前卷和目标卷。
- 错卷输出不会覆盖正式卷纲。
- 卷纲覆盖前有目标卷/章节范围校验和 staging。
- 任一 beat/writer 输入都不会出现“目标章节 > 当前卷纲 end”且未通过目标卷规划提交的状态。
- 测试覆盖目标卷身份解析与输出校验。
