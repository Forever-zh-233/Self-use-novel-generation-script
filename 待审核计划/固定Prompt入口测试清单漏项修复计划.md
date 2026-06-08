# 固定 Prompt 入口测试清单漏项修复计划

## 结论

测试层的 `REQUIRED_PROMPTS` 没有覆盖当前真实运行会读取的全部固定 prompt，反而保留了一个当前主流程未直接读取的旧入口 `analyst.md`。这会造成“prompt 丢了但 check 仍绿”的假安全感。

## 当前证据

- `scripts/run_pipeline.py:748-751`：Editor 修稿阶段会读取 `prompts/editor.md`；缺失时退回极简 fallback。
- `prompts/editor.md` 已存在，且第83章运行产物证明 editor 正在被真实调用：
  - `输出/修稿/第083章_edited.md`
  - `输出/写手/第083章_draft.md`
  - `输出/评审/第083章_review.md`
- `tests/checks_test.py:51-64` 的 `REQUIRED_PROMPTS` 没有 `editor.md`。
- `scripts/run_pipeline.py:1297-1298`、`1376`、`1502` 实际读取：
  - `analyst_map.md`
  - `analyst_reduce.md`
  - `analyst_merge.md`
  - `analyst_structure_reduce.md`
- `scripts/run_pipeline.py:1150-1169` 还把上述四个 analyst prompt 纳入产物指纹，说明它们是正式输入契约。
- `tests/checks_test.py:52` 只要求 `analyst.md`，但当前主流程和 analyst 管线未直接读取 `prompts/analyst.md`。
- 同类问题还出现在核心模块清单：`scripts/run_pipeline.py:39` 每章会导入并调用 `pipeline.summarizer.generate_chapter_summary`，但 `tests/checks_test.py` 的 `REQUIRED_FILES` 没有 `scripts/pipeline/summarizer.py`。
- 非标准 prompt 入口仍未被覆盖：`scripts/consistency/mapper.py:19` 定义独立 `scripts/consistency/prompts`，`scripts/consistency/mapper.py:64` 读取 `map_agent.md`，不属于根目录 `prompts/*.md` 清单。
- `scripts/pipeline/summarizer.py:18` 使用内联 `SUMMARIZER_PROMPT` 常量，既不在 `REQUIRED_PROMPTS`，也不在“扫描 `PROMPTS_DIR / "xxx.md"`”的同步检查范围内。
- `tests/checks_test.py:15-20` 的 `PYTHON_GLOBS` 只覆盖 `scripts/*.py`、`scripts/pipeline/*.py`、`tests/*.py`，没有覆盖 `scripts/consistency/*.py`；但 consistency 有真实 CLI 和 LLM 入口，见 `scripts/consistency/scan.py:21`、`scripts/consistency/mapper.py:22`。

## 影响

- `editor.md` 丢失或被误删时，测试不会报警，运行会静默退回极简修稿提示词，失去“AI腔识别与修复/多角度保留/最小动刀”等关键职责。
- analyst 四个实际 prompt 任一丢失时，check 不会在结构层提前发现；最坏情况是全量分析用空 prompt 或错误口径继续跑。
- 测试清单守旧入口，会让维护者误以为 prompt 入口已经被完整覆盖。
- 核心模块文件漏出 REQUIRED_FILES 时，删除/移动模块可能只在运行到具体 import/call 时才暴露，而不是结构检查阶段暴露。

## 修复建议

1. 更新 `tests/checks_test.py` 的 `REQUIRED_PROMPTS`：
   - 增加 `editor.md`。
   - 增加 `analyst_map.md`、`analyst_reduce.md`、`analyst_merge.md`、`analyst_structure_reduce.md`。
2. 评估 `analyst.md`：
   - 若已废弃，移出 REQUIRED_PROMPTS 或标注为 legacy 文档。
   - 若仍应使用，明确哪个代码入口读取它。
3. 增加一个“代码读取 prompt 与 REQUIRED_PROMPTS 同步”的轻量检查：
   - 扫描 `PROMPTS_DIR / "xxx.md"` 的字面量。
   - 扫描 `_ANALYST_PROMPT_FILES`。
   - 扫描子目录 prompt 根，如 `scripts/consistency/prompts/*.md`。
   - 扫描明确命名的内联 prompt 常量，如 `SUMMARIZER_PROMPT`；不能文件存在性检查的，至少纳入 prompt 入口登记和快照 hash。
   - 确认固定入口均在 `REQUIRED_PROMPTS` 或显式豁免列表。
4. 同步核心模块清单。
   - 将 `scripts/pipeline/summarizer.py` 纳入 `REQUIRED_FILES`。
   - 将 `scripts/consistency/*.py` 纳入 Python 语法检查范围，或登记为显式豁免并说明原因。
   - 对 `from pipeline.xxx import` 的固定核心模块建立轻量清单或豁免列表。

## 验收标准

- 删除 `prompts/editor.md` 时 `scripts/run_tests.py check` 会失败。
- 删除任一 analyst 实际 prompt 时 `check` 会失败。
- `REQUIRED_PROMPTS` 不再守一个无人读取的旧入口而漏掉真实入口。
- 删除 `scripts/pipeline/summarizer.py` 时 `check` 会失败。
- 破坏 `scripts/consistency/mapper.py` 或删除 `scripts/consistency/prompts/map_agent.md` 时，结构检查能提前失败。
- 新增非根目录 prompt 或内联 prompt 时，必须登记为受管入口或显式豁免。
