# POV Writer 写作模块接入计划

## 结论

POV 分支为知识隔离单独构造了 writer 输入，但没有接回普通 writer 已经在用的安全写作模块。结果是 POV 章即使 beat 标了 `内在转变`、`潜台词机会`、`本章张力`、`困境/两难` 等字段，也只把字段原文交给模型，不会得到对应的模块级写法约束。

## 当前证据

- `scripts/run_pipeline.py:628-644`：`视角角色 != 沈安` 时走 `build_pov_writer_input()`，沈安章才走 `build_writer_input()`。
- `scripts/pipeline/context.py:1233-1255`：普通 writer 输入会调用 `writer_focus_modules()` 并注入【本章写作要点】。
- `scripts/pipeline/context.py:1395-1406`：POV writer 输入只包含视角角色、角色信息、知识边界、beat、时间、公开事件、世界观，没有【本章写作要点】。
- `prompts/beat_planner.md:95-103`：POV 章要求 `内在转变` 必填，并围绕 POV 角色安排冲突、钩子和情绪弧线。
- `prompts/writer_pov.md:59`：POV prompt 本身比较短，只要求直接输出正文，不承诺接收普通 writer 的附加模块。

## 根因判断

- POV 分支为了防止沈安秘密和主角内心泄露，复制了一条更窄的输入管路。
- 这条管路只处理“知识隔离”，没有定义哪些写作模块是角色无关、可安全复用的。
- 普通 writer 的模块选择和 POV writer 的输入构造没有共享同一份“安全模块白名单/上下文契约”。

## 影响

- POV 章最需要写出角色内在位移，但 `内在转变` 模块不会接入。
- 非主角视角里的潜台词、张力、困境主题容易只停在 beat 字段层，缺少执行提示。
- Reviewer 仍会按 beat 检查 POV 章是否兑现，但 writer 侧没有拿到同等执行材料，容易形成“下游扣分、上游没料”的错位。

## 治本方案

1. 把 writer 模块分为两类。
   - 主角专属：视觉、盲感官、沈安相关特殊限制。
   - 角色无关：对话、潜台词、情绪裂缝、内在转变、困境主题、张力。
2. 新增 `writer_focus_modules(beat, mode="main|pov")` 或等价白名单机制。
   - POV 模式只注入角色无关模块。
   - 禁止把沈安盲感官、主角秘密、主角内心专属提示带入 POV 分支。
3. `build_pov_writer_input()` 在 beat 之后注入【本章写作要点】。
   - section 名称与普通 writer 保持一致，降低 prompt 分叉。
4. Reviewer 的 POV 授权说明继续只负责视角标准，不承担补写 writer 模块的职责。
5. 增加 scenario 测试。
   - POV beat 标 `内在转变/潜台词机会/本章张力` 时，writer input 包含对应安全模块。
   - 同一 POV 输入不包含主角盲感官模块和沈安秘密材料。

## 验收标准

- 非沈安 POV 章能接收到安全写作模块。
- POV 知识隔离不因模块复用被破坏。
- 测试覆盖真实 `generate_chapter_final()` 路由下的 POV writer input，而不是只测局部函数。
