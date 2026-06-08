# StoryDirector 任务维度入口对齐计划

## 结论

StoryDirector 的系统 prompt 已扩展为 10 个判断维度，但主流程注入的任务文案仍把审核口径收窄成旧的“五个维度”。这会让模型在运行时优先服从用户任务区块，忽略主题论证、升级难度、行为级成长、线索揭示节奏、世界重量等后续维度。

## 当前证据

- `prompts/story_director.md:15`：系统 prompt 定义“判断维度（按重要性排序）”。
- `prompts/story_director.md:35-50`：系统 prompt 包含第 6-10 项，包括主题论证、升级难度、行为级成长、线索揭示节奏、世界重量。
- `scripts/pipeline/planning.py:215`：运行时任务区块仍写“按卷纲兑现度、核心叙事模式、推进vs打转、重复模式、节奏冷热五个维度判断”。
- `prompts/story_director.md:91`、`prompts/story_director.md:106`：输出 `reason` 被要求指出具体判断维度；因此任务区块的“五个维度”会直接影响可引用维度集合。

## 根因判断

- Prompt 角色职责扩展后，`build_story_director_input()` 的任务文案没有同步。
- 系统 prompt 与用户任务区块都在定义审核维度，缺少单一来源。
- 没有测试扫描 StoryDirector 维度标题与运行时任务文案是否一致。

## 治本方案

1. 将 StoryDirector 判断维度设为单一来源。
   - 要么运行时任务写“按系统 prompt 定义的判断维度判断”。
   - 要么从同一配置/解析结果生成系统 prompt 和任务文案。
2. 如果某些维度因输入不足暂不启用，任务区块必须显式列出“禁用/软参考”维度和原因。
3. 增加回归测试。
   - 扫描 `prompts/story_director.md` 的维度标题。
   - 断言 `build_story_director_input()` 不再出现过期的“五个维度”收窄口径。
   - reason 中引用的维度必须属于当前维度集合。

## 验收标准

- StoryDirector 系统职责和运行时任务不再互相打架。
- 新增/删除判断维度时，测试能提示入口文案同步。
- 主题论证、升级难度、行为级成长、线索揭示节奏、世界重量不会被旧任务口径降权。
