# 通用角色职责 Prompt 项目样例隔离计划

## 结论

多个固定角色 prompt 和 writer module 把“通用职责协议”与当前书样例混在一起。当前书运行时可以成立，但用户目标是通用小说软件；如果换书，这些人名、主角限制、三线命名、机制样例会继续影响模型，导致角色职责被本书污染。

## 当前证据

- `prompts/story_director.md:21-22`：虽然写了“以故事核为准”，但紧跟当前书示例“沈安行医/人心的结/愿/案子”。
- `prompts/story_director.md:36-41`：主题问句和升级失败示例写死当前书核心问句、修仙/面板语境。
- `prompts/writer.md:105-136`：主角章多角度规则写成“本书以沈安为主视角”，并用沈安盲人、周济、老头、王二麻子等当前书样例说明。
- `prompts/writer_modules/视觉.md:3-5`、`prompts/writer_modules/盲感官.md:1-21`：默认模块写死沈安盲感官设定；`scripts/pipeline/context.py:1207-1210` 又默认每章注入“视觉”和“盲感官”模块。
- `prompts/archivist.md:331-342`：`dominant_strand/cultivation_active` 说明写死“道途线/情义线/天地线”和当前书的行医、长生、了愿系统语境。
- `prompts/beat_planner.md:34-64`：JSON 示例字段默认 `视角角色=沈安`、`出场角色=["沈安","黑子"]`，空间布局和多角度叙事示例也写死当前书人物。
- `待审核计划/待审核的可换书架构升级计划.md` 已指出 prompt 和卡片中存在沈安耦合；本计划把它收敛成可执行的“职责 prompt 与项目 profile 隔离”专项。

## 根因判断

- 固定 prompt 同时承担两件事：角色职责协议 + 当前书实例教学。前者应该随软件发布，后者应该随 book profile / story bible / generated examples 更换。
- 模型会把 prompt 中的具体样例当作高权重模式。即使写了“换书时替换”，只要替换动作不是自动化机制，就会在新书中残留旧书方向。
- 默认注入的 writer modules 风险更高：即便新书主角不盲，写手仍会每章收到“沈安盲感官”。

## 治本方案

1. 拆分固定职责 prompt 与项目 profile。
   - `prompts/*.md` 只保留通用职责、输出 schema、边界、反污染规则。
   - 当前书的人名、核心机制、主角特殊限制、三线名称、示例动作，移入 `book.config.json` / `story_profile.md` / 书内设定文档。
2. 示例参数化。
   - 用 `{protagonist}`、`{default_companion}`、`{core_mechanic}`、`{strand_names}` 等占位符生成运行时 prompt。
   - 如果没有对应 profile 字段，则不渲染该示例，而不是回退到沈安。
3. writer module 按 profile 开关注入。
   - `视觉/盲感官` 改为“主角特殊感知模块”，由 profile 声明 `enabled`、禁用感官、替代感官和检查规则。
   - 非盲主角不注入该模块，也不运行沈安视觉门禁。
4. 角色职责测试。
   - 静态扫描固定 prompt：不得出现当前书专名，或必须在明确的 profile template 目录中。
   - 临时新书 profile 生成 writer/beat/story_director 输入，断言不含沈安、黑子、了愿、青石镇等当前书词。
   - 当前书 profile 仍能渲染出当前书所需特殊约束。

## 验收标准

- 固定职责 prompt 不再携带当前书具体人名、地点、机制作为默认示例。
- 当前书样例只从当前书 profile 渲染，换书时随 profile 自动替换或消失。
- writer module 注入由 profile 控制，不再无条件注入沈安盲感官。
- 新书 smoke 测试能证明“换书不串味”：核心角色输入中没有当前书专名残留。
