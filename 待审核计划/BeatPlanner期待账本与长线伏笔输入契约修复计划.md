# BeatPlanner 期待账本与长线伏笔输入契约修复计划

## 结论

BeatPlanner prompt 的输入清单声明会拿到“长线伏笔资产库/动态状态台账/期待账本”，但 `build_beat_input()` 没有直接注入 `08-期待账本.md` 或 `15-长线伏笔资产库.md`。ArcPlanner 有这些材料，BeatPlanner 主要拿到状态摘要、最近台账日志和正典账本摘要。若 BeatPlanner 要负责本章伏笔操作，它的输入契约需要明确：直接给完整资产、给摘要，还是只接受 ArcPlanner 下发的战术化指令。

## 当前证据

- `prompts/beat_planner.md:5`：BeatPlanner 职责是根据故事核、卷纲、状态台账和期待账本生成下一章 beat。
- `prompts/beat_planner.md:11-16`：输入清单列出长线伏笔资产库、动态状态台账、期待账本、最近正文摘要/片段等。
- `scripts/pipeline/planning.py:1394-1405`：`build_beat_input()` 基础 sections 包含目标章节、故事总监、故事核、修炼、卷纲、当前状态摘要、最近台账日志、正典账本摘要、最近正文片段。
- `scripts/pipeline/planning.py:943-958`：ArcPlanner 输入中直接注入“期待账本(未回收伏笔)”和“长线伏笔资产库”。
- `scripts/pipeline/planning.py:1448-1453` 等后续只注入人物债、情感锚点等局部规划材料，不等价于 prompt 声明的完整期待账本/资产库。

## 根因判断

- BeatPlanner 的 prompt 输入清单沿用了“能看到全部上游资料”的说法，但实际为了 token 和职责边界只给了摘要/局部信号。
- 伏笔职责在 ArcPlanner 和 BeatPlanner 之间没有明确分工：谁看全局资产，谁只执行本弧本章指令。
- 测试只关注部分 beat 输入字段，没有覆盖 prompt 输入清单与实际 section 一致性。

## 影响

- BeatPlanner 可能以为自己应该主动管理长线伏笔，但实际看不到完整资产。
- 长线伏笔若没有被 ArcPlanner 战术化下发，BeatPlanner 本章层面可能漏推进。
- 维护者修改 `08-期待账本.md` 或 `15-长线伏笔资产库.md` 时，可能误以为 BeatPlanner 会直接读取。

## 治本方案

1. 明确 BeatPlanner 的伏笔职责。
   - 方案 A：BeatPlanner 直接看精简期待账本和长线资产摘要。
   - 方案 B：BeatPlanner 不看全量，只执行 ArcPlanner 的 `narrative_ops.foreshadowing` 和临期警告。
2. 如果选 A，增加精简 section。
   - “期待账本临期/本章相关条目”
   - “长线伏笔本卷相关条目”
3. 如果选 B，修改 prompt 输入清单。
   - 改为“弧线下发的伏笔操作/临期伏笔警告”，不再承诺完整资产库。
4. 增加测试。
   - prompt 声明的输入材料与 `build_beat_input()` section 一致。
   - 伏笔临期条目能进入 BeatPlanner 输入或被明确声明由 ArcPlanner 处理。

## 验收标准

- BeatPlanner 不再承诺读取实际没接入的资料。
- 本章伏笔操作有清晰上游来源。
- 测试能捕捉 BeatPlanner prompt/input 继续漂移。
