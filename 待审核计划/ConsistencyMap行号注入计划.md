# Consistency MAP 行号注入计划

## 结论

一致性 MAP 提示词要求事实提取员给每个事实标注 `L1/L12/L150` 行号，但 mapper 实际把正文原样塞进输入，没有预先加行号。模型只能自行估算行号，证据定位不稳定，后续 Check/Report 的可追溯性会被削弱。

## 当前证据

- `scripts/consistency/prompts/map_agent.md:9`：要求每个事实标注来源行号。
- `scripts/consistency/prompts/map_agent.md:117-118`：说明行号可粗略，但仍以 `L1/L50/L150` 作为定位方式。
- `scripts/consistency/mapper.py:151`：user_input 为 `## 正文\n{text}`，没有给正文每行加 `Lxxx:` 前缀。
- `scripts/consistency/mapper.py:153-156`：后续只处理输出截断重试，没有对行号来源做格式保障。

## 根因判断

- prompt 把“行号证据”当作模型输出职责，但输入没有提供稳定行号坐标系。
- 没有 map 输出校验去检查 line 字段是否来自输入中的有效行号。
- consistency 系统本意是审计和追溯，证据定位却依赖模型估算。

## 影响

- 同一事实多次重跑可能给出不同位置，难以人工复查。
- Check 阶段发现冲突时，报告里的行号可能对不上正文。
- 后续想做自动摘录、定位上下文、最小修复时缺少可靠坐标。

## 治本方案

1. mapper 在拼接正文前加行号。
   - 例如 `L001: # 第87章 打听`。
   - 空行可保留编号或折叠，但规则要固定。
2. prompt 改成要求只引用输入中已有的 `Lxxx`。
3. map 输出校验。
   - `line` 字段必须是存在的行号或 `"全章"`。
   - 无效行号进入 `_parse_error` 或 warnings，触发重跑/修复。
4. fact sheet 保存正文 hash 与行号版本。
   - 防止正文改写后旧行号继续被复用。
5. 增加测试。
   - mapper dry input 中正文必须带 `L001` 前缀。
   - fake 输出无效行号时标记解析风险。

## 验收标准

- MAP 输入提供稳定行号坐标系。
- 输出行号可回查到当前正文。
- 一致性报告不再依赖模型自行数行。
