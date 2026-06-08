# Analyst 主链闭环场景测试计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

Analyst 现有测试覆盖了 MAP 切段、结构 reduce、并发和指纹片段等子步骤，但缺少 `run_analyst()` 从源文切批到 MAP、REDUCE、写 chunk、更新 index 的端到端闭环测试。子函数绿不代表入口闭环真正把手法卡产出并接入。

## 当前证据

- `scripts/run_pipeline.py:1286-1309`：`run_analyst()` 负责全量扫读入口、源文读取、切批和 dry-run。
- `scripts/run_pipeline.py:1629-1634`：`split_and_write_technique_chunks()` 写 chunks 并登记 index。
- Turing 审计确认：现有测试覆盖 MAP 切段/结构 reduce/MAP 并发/指纹片段，但没有证明 `run_analyst()` 全链路最终写出可检索 chunk/index。

## 根因判断

- Analyst 是一次性预处理管线，测试容易停在函数级，不跑真实入口。
- MAP、REDUCE、写文件、index 更新属于跨阶段副作用，缺少统一 manifest 验证。
- 如果入口漏调用某个 reduce 或写出的 chunk 类别错，局部测试无法发现。

## 影响

- 用户以为 Analyst 已能生成可用手法卡，实际可能只产出中间稿。
- chunk 写入成功但 index 没更新时，后续 writer selector 无法注入。
- index 类别错会让通用手法卡/正典卡隔离失效。

## 治本方案

1. 建立 Analyst 小样本闭环 fixture。
   - 使用极短源文，mock `call_role()` 返回固定 MAP/REDUCE。
   - 在临时 chunks/index 里验证写入。
2. 验证完整阶段顺序。
   - source -> split -> MAP batch outputs -> REDUCE -> chunk files -> index entries。
3. 增加产物契约。
   - 每个写出的 chunk 必须有 index 记录。
   - index 记录必须有类别/namespace/book_id 等元数据。
   - REDUCE 未产生 `=== FILE:` 标记时必须失败或明确告警。
4. 将 `--analyst --dry-run` 与真实 mock-run 分开测试。
   - dry-run 只允许写 prompt 预览。
   - mock-run 必须写 chunk/index。

## 验收标准

- `run_analyst()` 入口闭环被测试覆盖。
- 子步骤绿但入口漏接时测试会失败。
- Analyst 产出的 chunk 能被后续 selector 发现，而不是只落中间文件。
