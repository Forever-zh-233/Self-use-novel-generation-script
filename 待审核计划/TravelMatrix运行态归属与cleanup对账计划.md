# TravelMatrix 运行态归属与 cleanup 对账计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

Archivist 会把章节运行中发现的 `travel_update` 追加进 `config/travel_matrix.json`，但清理脚本不会重置它。这个文件名义上属于配置，实际又承载运行态距离事实；换书或清空生成产物后，旧书路线仍会留在配置里污染下一轮。

## 当前证据

- `scripts/pipeline/archivist.py:819-833`：`travel_update` 会追加到 `BASE_DIR / "config" / "travel_matrix.json"` 的 `distances`。
- `scripts/pipeline/archivist.py:826-832`：仅按 `from+to` 去重并截断 80 条，没有 book/run 身份或章节提交状态。
- `scripts/clean_chapter_artifacts.py:53-63`：会清空输出、beats、runtime/summaries 等章节产物。
- `scripts/clean_chapter_artifacts.py:65-74`：会删除卷纲和部分 runtime 文件，但没有处理 `config/travel_matrix.json`。
- 当前 `config/travel_matrix.json` 已包含大量青石镇路线，说明运行事实已经进入配置层。

## 根因判断

- `travel_matrix.json` 同时扮演两种角色：初始规则配置 + 运行中积累的事实缓存。
- cleanup 的归属模型认为 `config/` 是静态配置，因此不清；但 Archivist 的写入行为又把它变成了动态产物。
- 该管路缺少 run/book 身份、章节来源、提交幂等键和清理策略。

## 影响

- 清空章节产物后重跑，旧路线仍会被 Writer/Planner 当作既有空间事实。
- 换书时如果没有手动清理 `config/travel_matrix.json`，上一本文的地名会进入新书上下文。
- 运行中追加的路线无法区分“人工设定的权威距离”和“模型从某章报告里抽取的临时事实”。

## 治本方案

1. 拆分静态配置与运行事实。
   - `config/travel_matrix.json` 只保留人工设定的规则、基础地点和可复用约束。
   - 章节中新增的 `travel_update` 写入 `runtime/travel_matrix.generated.json` 或 ledger 的 travel 子账。
2. 为运行事实增加元数据。
   - 字段包括 `from/to/distance/source_chapter/source_article_hash/committed_at/run_id/book_id`。
   - 去重键至少包含 `book_id + normalized_from + normalized_to`。
3. cleanup 与换书流程显式处理。
   - 清章节运行态时必须清 `runtime/travel_matrix.generated.json`。
   - 如果继续允许写入 config，则 cleanup 必须支持保留人工规则、删除 generated entries 的分层清理。
4. 输入装配层按优先级合并。
   - 人工规则优先，运行事实次之。
   - 同一 from/to 冲突时输出告警，不静默覆盖。
5. 增加测试。
   - Archivist 提交 travel_update 后，断言写入运行态而非静态 config。
   - cleanup 后断言运行态路线被清理、人工规则仍保留。
   - 换书 profile 后断言旧 book_id 的路线不会注入。

## 验收标准

- 运行中生成的路线事实不再写进无身份的静态配置。
- cleanup 能完整清掉章节运行态空间事实。
- TravelMatrix 输入能说明每条路线来自人工配置还是哪一章运行提交。
