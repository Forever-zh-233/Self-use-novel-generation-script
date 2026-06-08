# Consistency 只读审计模式计划

## 结论

Consistency 的 check/report 入口同时承担“查看问题”和“提交扫描状态”两个职责。即使用户只想审计，`run_check_phase()` 和 `run_report_phase()` 也会写 `issues_raw.json`、推进 watermark、生成 latest report。这和主项目测试指南要求的临时 workspace/只读审计边界不一致。

## 当前证据

- `scripts/consistency/checker.py:762` 附近：check 会写 `consistency/issues_raw.json`。
- `scripts/consistency/checker.py:767` 附近：check 默认会更新 `watermark.json`。
- `scripts/consistency/reporter.py:71` 附近：report 会写时间戳报告和 `latest.md`。
- `scripts/consistency/scan.py:68-75`：`--check` 会连跑 check + report，没有只读查看模式。
- `scripts/consistency/llm.py:18`：consistency 根目录固定为脚本相对路径，不读取 `NOVEL_WORKSPACE`。
- `scripts/pipeline/core.py:16`：主流水线支持 `NOVEL_WORKSPACE`。
- `测试文件维护指南.md:123-125`：会写文件的测试必须使用临时 `NOVEL_WORKSPACE`，测试不能调用真实 LLM。

## 根因判断

- consistency 是独立工具实现，未复用主流水线的 workspace root、审计 manifest、读写模式约定。
- check/report 没有把 dry-run、read-only、commit 三种语义分开。

## 影响

- “只看一眼”也会改变 consistency 状态，影响下次新旧问题判定。
- 测试很难安全覆盖 consistency 主入口，因为它默认写真实工作区。
- 多次人工审计会污染 watermark，使真实新增问题被误归类。

## 治本方案

1. 统一 workspace root。
   - consistency 读取 `NOVEL_WORKSPACE`，默认回落到项目根。
   - 路径常量集中到一个可测试模块。
2. 拆分 check/report 模式。
   - `read_only=True`：只返回内存结果，不写 issues、watermark、report。
   - `write_report=True`：写报告但不推进 watermark。
   - `commit=True`：明确提交本次扫描，才推进 watermark。
3. CLI 增加明确参数。
   - `--check --read-only`
   - `--report-only`
   - `--commit-watermark`
4. 测试覆盖。
   - 临时 `NOVEL_WORKSPACE` 中跑 read-only check，断言真实工作区不变。
   - read-only 不生成 `latest.md`、不更新 `watermark.json`。
   - commit 模式才更新 watermark。

## 验收标准

- 审计命令可以不改变任何 consistency 状态。
- consistency 测试可以安全跑在临时 workspace。
- watermark 只在明确提交时变化。
