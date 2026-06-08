# 主角身份配置化与 POV 路由解耦计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

主流程把“沈安”写成默认视角角色和 POV 路由边界：`视角角色 != 沈安` 就走 POV 写手。作为通用小说软件，主角名一换，正常主角章会被误判为非主角 POV 章；同时默认出场角色还会注入沈安/黑子。

## 当前证据

- `scripts/run_pipeline.py:93`：`normalize_beat()` 默认 `视角角色` 为 `沈安`。
- `scripts/run_pipeline.py:110`：默认 `出场角色` 为 `["沈安", "黑子"]`。
- `scripts/run_pipeline.py:628-630`：POV 路由注释和判断写死“视角角色非沈安时走 POV 分支”。
- `scripts/run_pipeline.py:641-644`：根据是否等于沈安选择 `build_pov_writer_input()` 或 `build_writer_input()`。
- `scripts/run_pipeline.py:928`：Archivist 阶段再次默认 POV 角色为沈安。
- `prompts/writer.md:105-111`：写手 prompt 也把“本书以沈安为主视角”作为默认职责。

## 根因判断

- “主角是谁”是 book profile 事实，却被通用主流程硬编码。
- POV 路由用人名判断，而不是用 beat 的结构化字段或 profile 的 `protagonist.name`。
- 默认 cast 也没有从 profile 读取，导致缺字段时自动回到当前书。

## 影响

- 换书后，正常主角章可能走 `writer_pov.md`，导致视角、输入材料、Reviewer 标准全部错位。
- BeatPlanner 如果缺字段，后续会自动注入沈安/黑子，污染新书。
- 当前书之外的多主角/群像小说无法表达“主视角集合”或“本章是否 POV 章”。

## 治本方案

1. 在 book profile 中定义视角身份。
   - `protagonist.name`
   - `default_cast`
   - 可选 `primary_pov_characters`
   - 可选 `pov_mode`: `single_protagonist` / `multi_primary` / `ensemble`
2. 路由从 profile 和结构化字段判断。
   - 默认视角角色来自 `profile.protagonist.name`。
   - 是否 POV 章优先读 `beat["是否POV章"]` 或 `beat["pov_type"]`，其次才比较是否属于主视角集合。
3. `normalize_beat()` 禁止回退到沈安。
   - 缺 `视角角色` 时用 profile 主角。
   - 缺 `出场角色` 时用 profile default_cast。
   - profile 缺失则报错或使用测试专用 fixture，不使用当前书人名。
4. Prompt 模板参数化。
   - `writer.md` 中“沈安主视角”改为 `{protagonist}` / `{primary_pov}` 渲染。
   - 非主角 POV 规则以“本章视角角色与主视角集合关系”表达。
5. 增加测试。
   - 假书主角为“林岚”，Beat `视角角色=林岚`，断言走主 writer。
   - Beat `视角角色=配角甲` 且标 POV，断言走 POV writer。
   - 缺 cast 时默认注入假书 default_cast，不出现沈安/黑子。

## 验收标准

- 通用主流程不再用“沈安”判断 POV 路由。
- 换书只改 profile 就能正确选择主角 writer / POV writer。
- 测试覆盖主角章、配角 POV 章、缺字段兜底三种场景。
