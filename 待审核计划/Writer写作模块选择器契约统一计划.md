# Writer 写作模块选择器契约统一计划

## 结论

`writer_focus_modules()` 已经承担“按 beat 字段选择写作模块”的职责，但它的触发条件、别名归一、负值哨兵和模块内容校验都分散实现，和 chunk 选择器、prompt 禁令、角色别名表存在不一致。问题不在某个模块文本，而在模块选择器缺少统一契约。

## 当前证据

- `scripts/pipeline/context.py:1195-1199`：只要 `场景类型` 含“日常”就注入 `对话.md`。
- `prompts/writer_modules/对话.md:3`：模块文本前提是“本章有对话场景”。
- `prompts/beat_planner.md:175`：`日常推进/铺垫/酿/缓冲/余波` 是平档张力语义，不等同于有对话。
- `scripts/pipeline/context.py:871-874`：chunk 侧 `潜台词` 触发条件是 `subtext_opp != "无"`。
- `scripts/pipeline/context.py:1196-1203`：writer module 侧 `潜台词` 触发条件是 `not qtc.startswith("无")`。
- `scripts/pipeline/state.py:345-352`：别名表把 `阿墨 -> 黑子`，`tests/quick_test.py:149-151` 也固定了该别名。
- `scripts/pipeline/context.py:1204-1206`：黑子模块只按字面“黑子”判断，没有复用别名归一。
- `prompts/writer.md:10`：明禁“不是A，是B/不是A——是B”句式。
- `prompts/writer_modules/张力.md:3`、`prompts/writer_modules/盲感官.md:3`、`prompts/writer_modules/黑子.md:5` 等模块自身仍含“不是……是……”式正向文本。

## 根因判断

- 模块触发条件是随需求逐条追加的，没有集中定义“字段值何为有效/无效”。
- `select_chunks()`、`writer_focus_modules()`、别名解析各自做判断，没有共享工具函数。
- 模块文件被当成 prompt 文案管理，缺少“模块文本也必须服从 writer 总禁令”的静态检查或人工清单。

## 影响

- 无对话或弱对话日常章可能被注入对话硬提示，导致 writer 强行加对话。
- `潜台词机会` 的同一个值可能出现 chunk 已注入、writer module 未注入，或反过来的半接入状态。
- 旧名/别名进入 beat 时，角色 chunk 能归一，但角色专属 writer module 漏接。
- 模块文本把禁用句式当正向示范喂给 writer，会弱化总 prompt 的风格约束。

## 治本方案

1. 建立共享字段判定工具。
   - `is_active_field(value)`：统一处理空值、`无`、`无，本章...`、`None`、`积累中，未触发` 等哨兵。
   - `normalize_role_name(name)`：复用 `chunk_aliases()` 或抽出统一 alias resolver。
2. 收窄对话模块触发。
   - 只在 `场景类型` 明确为 `对话/日常对话/审问/问询`，或 beat 有明确 `潜台词机会` 时注入。
   - 不把宽泛的“日常推进”自动等同于对话场景。
3. 统一 `潜台词` chunk 与 writer module 的触发口径。
   - 两处都调用同一个 `is_active_field(beat["潜台词机会"])`。
4. 角色模块选择走别名归一。
   - `阿墨`、`黑子` 都能注入黑子模块。
   - 未来角色改名不需要在模块选择器里再写一套字面判断。
5. 增加模块文本静态/半静态检查。
   - 对 `prompts/writer_modules/*.md` 扫描 writer 明禁句式。
   - 对命中的模块走人工改写，而不是把禁用表达继续作为正向指令。
6. 增加 scenario/quick 测试。
   - 对话触发正负样例。
   - 潜台词 chunk/module 同步样例。
   - `阿墨` 触发黑子模块样例。
   - 模块文本禁句式检查样例。

## 验收标准

- writer 模块选择条件集中、可复用、可测试。
- chunk 注入和 writer module 注入对同一 beat 字段不再分叉。
- 模块文件本身不再和 writer 总禁令自相矛盾。
