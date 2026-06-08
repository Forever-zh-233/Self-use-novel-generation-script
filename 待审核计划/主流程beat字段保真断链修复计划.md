# 主流程 beat 字段保真断链修复计划

## 结论

这是一个已经在真实生成物中反复出现的主流程断链：`beat_planner` 按提示词输出了字段，但 `normalize_beat()` 没有保留，正式 `beats/chapter_*.json` 丢失这些字段，writer/reviewer 读不到。

## 当前证据

- `prompts/beat_planner.md` 明确要求输出：
  - `修炼锚点`
  - `配角本章动作`
  - `多角度叙事`
- `prompts/writer.md` 明确要求 writer 执行 beat 里的 `多角度叙事`。
- `scripts/run_pipeline.py:89-134` 的 `normalize_beat()` 只保留基础字段，以及 `主题折射/内在转变/困境/两难/潜台词机会/意外处理/矛盾触发/情绪裂缝/情绪弧线/情绪基调/钩子型/关键章`，没有保留上述三个新字段。
- 对当前已生成 75 章扫描结果：
  - `修炼锚点`：raw 出现 75/75，正式 beat 保留 0/75，非空有效内容 26 次被丢。
  - `配角本章动作`：raw 出现 75/75，正式 beat 保留 0/75，非空有效内容 55 次被丢。
  - `多角度叙事`：raw 出现 56/75，正式 beat 保留 0/75，非空有效内容 56 次被丢。
- 扩展到当前 98 章基线后，问题仍然存在：正式 beat 中 `修炼锚点/配角本章动作/多角度叙事` 仍是 0/98 保留；raw 中非空被丢分别为 `修炼锚点` 39 章、`配角本章动作` 68 章、`多角度叙事` 78 章。第 91 章 raw 已有明确 `配角本章动作` 与 `多角度叙事`，见 `beats/_debug/第091章/beat_raw.md:34-35`，正式 beat 没有对应字段。
- 字段名也存在消费侧漂移：schema 和 `normalize_beat()` 使用 `困境/两难`，但 `ledger_context_for_writer()` 的主题账本 fallback 查的是 `beat.get("困境")`，导致 `主题折射` 为空而 `困境/两难` 有内容时，主题论辩账本可能少注入。
- 第 95 章样本说明断链不只发生在新增顶层字段上，也会发生在 raw beat 到正式 beat 的数组/清单字段里：`beats/_debug/第095章/beat_raw.md:13` 包含“韩铮转身进屋”“沈安没停步”等动作，正式 `beats/chapter_95.json:20-27` 的 `具体动作` 清单已少掉这些动作，但正文仍在 `输出/文章/第095章.md:47-60` 实现了韩铮放行。
- 同一 raw beat 的 `配角本章动作`、`多角度叙事` 在 `beats/_debug/第095章/beat_raw.md:33-34` 有具体内容，正式 beat 未保留，说明字段保真测试要覆盖 raw-formal beat diff，而不只是检查固定字段白名单。
- raw 到正式 beat 还存在静默截断列表元素：`出场角色` 在第 48、49、82、90 章异常，第 48 章 raw 有 7 个角色但正式只剩前 5，和 `scripts/run_pipeline.py:114` 的硬截断一致；`具体动作` 在第 49、50、53、95 章异常，第 53 章 raw 有 7 个动作但正式按 `scripts/run_pipeline.py:118` 的 `[:6]` 丢最后一项；`具体物件` 也有第 49、50、92 章异常。
- 问题延续到最新第二卷章节：
  - `beats/_debug/第104章/beat_raw.md:33-35` 原始输出包含 `修炼锚点`、`配角本章动作`、`多角度叙事`。
  - `beats/chapter_104.json:45` 到文件结束未保留这三项。
  - `beats/_debug/第101章/beat_raw.md:33-35` 同样包含三项，正式 `beats/chapter_101.json` 也未保留。
  - `scripts/run_pipeline.py:89-134` 的 `normalize_beat()` 字段白名单仍未包含这三个字段。
- `prompts/beat_planner.md:26` 要求所有字段都必须填写，`prompts/beat_planner.md:62-64` 已把上述三项列入字段清单；这说明丢失发生在主流程归一层，不是模型没输出。

## 影响

- 修炼线身体锚点写了但 writer 不知道，导致修炼线被削弱或被正文随意发挥。
- 配角独立议程写了但 writer 不知道，导致配角仍可能变成主角背景板。
- 多角度叙事写了但 writer/reviewer 不知道，导致多视角系统实际失效。
- 测试没有覆盖“prompt schema -> normalize_beat -> writer/reviewer 输入”的字段保真链路，所以主流程问题能一路绿灯。
- 测试也没有覆盖“标准字段名 -> 各消费侧字段名一致”的回归，因此字段即使保留下来也可能在某条消费管路里失效。

## 修复建议

1. 在 `normalize_beat()` 中保留 `修炼锚点`、`配角本章动作`、`多角度叙事`。
2. 字段类型按语义保留：
   - 三个字段都是文本，缺省可归一为 `"无"`。
   - 不要在 `sanitize_beat_for_writer()` 中删除。
3. 增加 scenario 测试：
   - 构造 raw beat，包含三个字段。
   - 调用 `normalize_beat()`。
   - 断言正式 beat 中三个字段仍存在。
   - 构造 writer/reviewer 输入，断言三个字段能出现在「本章 beat」区块。
4. 增加 prompt/schema 回归测试：
   - `beat_planner.md` 新增字段时，测试应提醒 `normalize_beat()` 未同步。
   - 以最新章节 raw beat 为回归样本，覆盖第 101-104 章这类新卷章节，避免只拿旧卷样本测绿。
5. 增加 raw-formal beat diff 测试：
   - 对 raw beat 与正式 beat 的核心字段做结构化 diff。
   - 列表字段不能静默丢元素；若确实需要裁剪，必须有明确归一规则和 `dropped_fields/dropped_items` 记录。
   - debug raw、正式 beat、writer 输入三者必须能对同一章的关键动作/角色/伏笔项做对账。
   - 以当前 98 章为历史基线，输出全量 `raw/formal/writer_input` 三方差异报告；新增字段丢失、列表元素截断、字段别名漂移都必须有机器可读原因。
6. 增加字段名一致性检查：
   - 以 beat schema 字段名为唯一来源。
   - 消费侧不得另查旧名或短名，除非在统一 alias 表中声明。
   - `困境/两难` 这类带斜杠字段要有正负样例，确认 writer/reviewer/archive 需要它时都读同一个键。

## 验收标准

- 新 raw beat 中三个字段能进入 `beats/chapter_N.json`。
- writer 输入里的「本章 beat」能看到三个字段。
- reviewer 输入里的「本章 beat」能看到三个字段。
- raw beat 到正式 beat 不会静默丢失关键动作、出场角色、伏笔操作和新增结构字段；允许裁剪时有机器可读记录。
- 消费侧字段名与 schema 对齐，别名只在统一归一层处理。
- `scripts/run_tests.py all` 通过。
