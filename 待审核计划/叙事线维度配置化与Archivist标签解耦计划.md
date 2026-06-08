# 叙事线维度配置化与 Archivist 标签解耦计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

三线节奏已经部分放进 `config/strand_weave.json`，但代码和 Archivist prompt 仍写死“道途线/情义线/天地线”以及当前书“行医/修炼/长生/了愿系统”的解释。结果是配置看似可换，统计 key、标签语义和记录员提交口径仍锁在当前书。

## 当前证据

- `config/strand_weave.json:5-23`：配置中定义三条线：道途线、情义线、天地线。
- `scripts/pipeline/context.py:975`：代码把三线映射写死为 `{"道途线": "last_道途", "情义线": "last_情义", "天地线": "last_天地"}`。
- `scripts/pipeline/context.py:1027-1047`：代码专门拆解“道途线含修炼实质”，并写死行医/修炼判断语义。
- `prompts/archivist.md:331-342`：Archivist 标签说明写死道途/情义/天地以及当前书行医、修炼、长生、了愿系统语境。

## 根因判断

- 配置只覆盖了表层名称/阈值，没有覆盖统计字段、子标签、prompt 说明和提交 schema。
- `cultivation_active` 是当前书“道途线混合袋拆解”的特例，却被嵌入通用 Archivist 角色职责。
- 代码使用中文线名生成内部 key，换线名后会丢历史或读不到 tracker。

## 影响

- 换书即使改 `strand_weave.json`，Archivist 仍会按旧三线打标签。
- 非修炼作品仍会被要求判断“修炼实质”。
- 节奏提示、断档统计、StoryDirector 判断会基于错维度运行。

## 治本方案

1. 重构 strand schema。
   - 每条线使用稳定 `id`，显示名 `name` 可换。
   - 字段包括 `aliases`、`desc`、`max_gap`、`max_consecutive`、`sub_tags`、`enabled`。
2. tracker key 从 strand id 派生。
   - 不再写死 `last_道途` 等中文 key。
   - 历史迁移时把旧 key 映射到当前书 profile。
3. Archivist prompt 动态渲染标签说明。
   - `dominant_strand` 的候选值来自配置。
   - `cultivation_active` 改为可选 sub_tag，只在当前书启用。
4. context 节奏提示通用化。
   - 遍历配置线，而不是特判三线。
   - 子标签统计按 `sub_tags` 配置输出。
5. 增加测试。
   - 假书配置两条线“案件线/关系线”，断言 Archivist 输入和节奏提示只出现这两条。
   - 当前书配置启用 `cultivation_active`，断言仍输出修炼实质拆解。
   - 非修炼书关闭 sub_tag，断言不出现修炼/道途说明。

## 验收标准

- 叙事线名称、数量、子标签完全由配置决定。
- Archivist 输出 schema 与配置同步，不再内置当前书三线。
- 节奏统计使用稳定 id，不因显示名变化丢失历史。
