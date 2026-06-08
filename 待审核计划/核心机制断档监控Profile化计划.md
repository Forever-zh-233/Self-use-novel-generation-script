# 核心机制断档监控 Profile 化计划

## 结论

BeatPlanner 输入里有“核心机制连续缺席”的兜底监控，但实现写死了当前书的“了愿系统/愿录/面板/青石镇”等内容。它能帮当前书补“系统存在感”，但作为通用小说软件，换书后会把当前书机制误注入新书，或者让新书自己的核心机制完全没有断档监控。

## 当前证据

- `scripts/pipeline/planning.py:1365-1391`：`_system_absence_warning()` 写死关键词 `系统/愿录/面板/了愿/真心愿/奖励/寿命/愿债`。
- `scripts/pipeline/planning.py:1383-1390`：警告正文写死“了愿系统”“青石镇”“系统弹面板”“愿债数字”等当前书机制和地点。
- `scripts/pipeline/planning.py:1476-1482`：该警告会作为 `⚠ 系统了愿断档警告（卷纲要求的核心元素连续缺席）` 注入 BeatPlanner，并且优先级是 `high`、不可压缩。
- `待审核计划/待审核的可换书架构升级计划.md` 已提出 `book.config.json` / profile 化方向，但未单独覆盖这个新增的规划层断档监控入口。

## 根因判断

- “核心机制存在感”是通用能力，但当前实现把“能力”与“本书实例”绑死在同一个函数里。
- 代码用关键词扫描历史 beat 判断核心元素缺席，这个思路可以通用；问题在于关键词、阈值、提示文本、可选补法都应来自 book profile / 故事核 / 卷纲，而不是写在通用管路里。
- 该 warning 直接进入 BeatPlanner 输入，属于未来章节规划前的强影响材料；一旦换书，会把职责污染到规划层。

## 治本方案

1. 在 book profile 中增加 `core_mechanics` 配置。
   - 字段包括 `id/name/aliases/keywords/absence_threshold/why_it_matters/suggested_micro_events/activation_policy`。
   - 当前书的“了愿系统”只是其中一条 profile 数据，不进入通用代码。
2. 将 `_system_absence_warning()` 改为通用 `_core_mechanic_absence_warnings()`。
   - 遍历 profile 中启用的核心机制。
   - 用对应关键词扫描最近 beat / summary / final manifest。
   - 输出“某核心机制缺席”的通用提醒，不写死具体剧情方向。
3. 提示文本模板化。
   - 通用代码只渲染：机制名、缺席章数、上次出现章、profile 给出的“自然小事件类型”。
   - 具体例子放在 profile，而不是 `planning.py`。
4. 增加换书测试。
   - 临时 workspace 配置一本没有系统面板的新书，断言 BeatPlanner 输入不出现“了愿/愿债/青石镇”。
   - 配置另一本有核心机制的新书，断言连续缺席后注入该书自己的机制提醒。

## 验收标准

- 通用管路代码中不再出现当前书专属核心机制词作为默认逻辑。
- BeatPlanner 仍能收到“核心机制断档”提醒，但提醒内容来自 profile。
- 换书时只改 profile，不改 `scripts/pipeline/planning.py`。
- 测试覆盖“当前书机制生效”和“新书不被当前书机制污染”两个方向。
