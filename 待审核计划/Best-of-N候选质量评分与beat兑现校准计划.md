# Best-of-N 候选质量评分与 beat 兑现校准计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

Best-of-N 当前用免费代码评分选择候选，指标主要是硬伤、风格问题、beat satisfaction、重复度和字数。它没有接入 Reviewer 的读者体验、场景价值转变、内在推进、方向对齐等“好文章”指标。因此关键章多采样也可能选中“干净但平庸”的稿。

## 当前证据

- `scripts/run_pipeline.py:505-528`：`score_candidate()` 只计算 `hard_gate`、`style_gate`、`chapter_satisfaction_check`、`self_repetition_penalty` 和中文字数。
- `scripts/run_pipeline.py:559-584`：`write_best_of_n()` 对每个候选调用 `score_candidate()` 排序，Reviewer/Editor 只对赢家跑一次。
- `prompts/reviewer.md:147-158`：Reviewer 有读者体验、信息密度、钩子具体性等质量标准。
- `prompts/reviewer.md:171-186`：Reviewer 有场景价值转变、内在推进等评分维度。
- `待审核计划/精品逼近升级计划.md` 曾把 Best-of-N 作为逼近模型上限的关键手段，但实现评分目标没有对齐“好文章”。

## 根因判断

- Best-of-N 的采样对象是“文本候选”，但排序器只做廉价硬检查，没有质量裁判。
- Reviewer 的质量判断发生在赢家之后，无法影响候选选择。
- 为省 token 改成 code score 可以理解，但缺少“轻量质量代理指标”或“关键章小型 reviewer judge”。

## 影响

- 关键章花了 N 倍 writer token，却可能只选到最保守、最不出错、最够字数的稿。
- 更有戏剧张力但有轻微风格瑕疵的候选可能被低估。
- Best-of-N 与“稳定生成精品小说”的目标不一致，变成“稳定生成无硬伤正文”。

## 治本方案

1. 拆分评分维度。
   - `safety_score`：硬伤、穿帮、AI 腔、重复。
   - `beat_fidelity_score`：核心事件、转折、钩子、张力档位是否兑现。
   - `quality_score`：场景价值转变、具体选择/代价、读者问题、情绪落点。
2. 增加轻量质量 judge。
   - 仅在 Best-of-N 候选之间做短评，不要求完整 Reviewer 报告。
   - 输入每个候选的摘要/关键段 + beat，输出结构化排序理由。
   - 关键章可烧少量 judge token；普通章仍用 code score。
3. 强制 beat 兑现优先级。
   - 候选若遗漏 beat 核心冲突/转折/钩子，直接降档，不因字数或少硬伤获胜。
4. 写入候选审计。
   - `best_of_n.json` 记录每个候选的安全分、兑现分、质量分、最终胜出理由。
5. 增加测试。
   - 候选 A 字数够且无硬伤但无选择/代价，候选 B 稍有风格小问题但兑现核心戏，断言 B 胜出或进入人工/Reviewer judge。
   - 候选遗漏 beat 核心事件，断言不能胜出。

## 验收标准

- Best-of-N 不再只按“没硬伤、低重复、够长”选稿。
- 关键章候选选择能体现读者体验和 beat 核心戏兑现。
- 候选胜出理由可审计、可复盘、可调权重。
