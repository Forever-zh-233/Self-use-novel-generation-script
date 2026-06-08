# 主流程测试统一 LLM Mock 装配器计划

> 状态：待审核。  
> 范围：只治理测试 harness 的真实覆盖能力，不修改生产逻辑或运行产物。

## 现网证据

- `scripts/run_pipeline.py:32` 通过 `from pipeline.api import *`、`from pipeline.planning import *` 将函数绑定进 `run_pipeline`。
- `scripts/pipeline/planning.py:20` 自己导入 `call_role`，StoryDirector / ArcPlanner 调用的是 `pipeline.planning.call_role`。
- `scripts/pipeline/summarizer.py:40` 在函数内部重新导入 `pipeline.api.call_role`，patch `run_pipeline.call_role` 拦不住。
- `tests/scenario_test.py:408` 有场景只 patch `rp.call_role`。
- `scripts/run_pipeline.py:949` 仍会尝试 summarizer；`scripts/run_pipeline.py:954` 将异常吞掉为“不影响正文”。
- `TESTING.md:82` 只写 mock `call_role`，没有说明需要 patch 多个绑定点。

## 根因

主流程测试把“mock 了 `run_pipeline.call_role`”误当作“mock 了全部 LLM 入口”。但模块内绑定、函数内导入、压缩器、summarizer、planning/context 子模块都会形成旁路，导致主流程调度测试可能假绿，甚至在配置有效时误打真实 API。

## 治本动作

1. 建立统一 LLM mock 装配器。
   - 同时替换 `run_pipeline.call_role`、`pipeline.api.call_role`、`pipeline.api.call_model`、`pipeline.planning.call_role`、`pipeline.context.call_role`。
   - summarizer 要么显式 mock `generate_chapter_summary`，要么测试配置必须设置 `skip_summarizer=true`。
2. 主流程场景测试禁止手写零散 patch。
   - 调度层测试统一通过 helper 进入。
   - helper 记录每个 role 调用，测试可以断言没有漏网调用。
3. 测试维护文档同步更新。
   - `TESTING.md` 和测试维护指南明确：patch `rp.call_role` 不等于主流程 LLM 全隔离。
4. 加一个故意漏 patch 的负样本测试。
   - 若某模块新增独立 LLM 入口而 helper 未覆盖，测试必须失败。

## 验收

- 主流程 harness 能证明所有 LLM 调用都被统一 mock 捕获。
- StoryDirector、ArcPlanner、Summarizer、Compressor、Writer、Reviewer、Archivist 场景不会因绑定点不同绕过 mock。
- 新增 `call_role` / `call_model` 入口未纳入 helper 时，测试失败而不是假绿。
- 测试文档不再只笼统写“mock `call_role`”。
