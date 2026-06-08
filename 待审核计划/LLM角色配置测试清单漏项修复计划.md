# LLM 角色配置测试清单漏项修复计划

## 结论

`config/models.json` 已经配置了 `summarizer` 和 `consistency_mapper` 两个 LLM 角色，代码也会调用它们，但 `tests/checks_test.py` 的角色配置必检列表没有覆盖这两个角色。未来如果这两个角色配置缺失或 model/provider 写错，`check` 仍可能通过。

## 当前证据

- `config/models.json:112-120` 配置了：
  - `summarizer`
  - `consistency_mapper`
- `scripts/run_pipeline.py:949-955`：每章定稿后调用 `generate_chapter_summary()`，用于后续 writer/reviewer 防重复。
- `scripts/pipeline/summarizer.py:45-52`：`generate_chapter_summary()` 通过 `call_role("summarizer", ...)` 调用 LLM。
- 当前真实运行产物证明 summarizer 已生效：
  - `runtime/summaries/chapter_083.json` 已生成。
- `scripts/consistency/mapper.py:22`：一致性扫描工具使用 `ROLE = "consistency_mapper"`。
- `scripts/consistency/llm.py:50-84`：按 role 从 `config/models.json` 解析 provider/model/api key，配置不完整会抛错。
- `tests/checks_test.py:137-150` 的必检角色只包括：
  - `arc_planner/story_director/fact_checker/volume_planner/master_outline/analyst/beat_planner/writer/reviewer/editor/archivist/compressor`
  - 缺少 `summarizer` 和 `consistency_mapper`。

## 影响

- `summarizer` 配置坏掉时，主流程会在 `run_pipeline.py:954-955` 捕获异常并继续，表面不崩，但后续 writer/reviewer 的反重复上下文会退化。
- `consistency_mapper` 配置坏掉时，独立一致性扫描工具会到运行时才失败，结构检查无法提前发现。
- 测试清单与真实 LLM 角色集合不同步，会让维护者误以为所有角色配置都被守住。

## 修复建议

1. 将 `summarizer`、`consistency_mapper` 加入 `tests/checks_test.py` 的角色配置必检列表。
2. 增加“代码中 `call_role("xxx")` / `ROLE = "xxx"` 与 `models.roles` 同步”的轻量检查：
   - `run_pipeline.py`、`pipeline/*.py` 中出现的固定 role 必须有配置。
   - `scripts/consistency/*.py` 的固定 role 必须有配置。
3. 对非主流程可选工具允许显式豁免，但需要在测试里写清楚为什么豁免。

## 验收标准

- 删除或破坏 `models.roles.summarizer` 时，`scripts/run_tests.py check` 失败。
- 删除或破坏 `models.roles.consistency_mapper` 时，`check` 失败。
- 未来新增固定 LLM 角色时，测试能提醒同步配置。

