# Consistency 缓存鲜度与章节生命周期修复计划

## 结论

一致性系统的 fact sheet 缓存和章节正文生命周期没有绑定。Map 阶段会检查正文 hash 和清理孤儿缓存，但 `--check` 可以绕过 Map，直接读取磁盘上所有 fact sheet；章节正文被删除、回退或重写后，旧 facts、旧报告和旧 watermark 仍可能参与判断。

## 当前证据

- `scripts/consistency/mapper.py:82-97`：`_fact_valid()` 只在 Map 侧校验正文 hash。
- `scripts/consistency/mapper.py:110-115`：`load_fact()` 明确“不校验正文哈希”，供 Check/Report 读取。
- `scripts/consistency/scan.py:68-75`：`--check` 只跑 `run_check_phase()` 和 report，不跑 Map，也不跑 orphan purge。
- `scripts/consistency/checker.py:46-57`：Check 加载磁盘上全部 fact sheets，不受当前正文目录约束。
- `scripts/consistency/mapper.py:214-216`：`purge_orphan_facts()` 只在 Map 阶段执行。
- 当前只读症状样本：`输出/文章` 为 91 章，`consistency/facts` 为 126 个，`consistency/watermark.json` 的 `last_scanned` 为 126。
- 第 101 章样本显示同章 fact sheet 与当前正文不是同一版：
  - `consistency/facts/chapter_101.json:1` 有 `CONSISTENCY-MAP v1` hash。
  - `consistency/facts/chapter_101.json:315-319` 摘要为“黎明官道、半塌棚子、田埂人形、湿泥呼吸”。
  - `输出/文章/第101章.md:13-29` 当前正文是“三岔路口、挑夫、碎屑方向变弱”。
  - `输出/文章/第101章.md:173,323-329` 当前正文还有“挑夫了愿、竹杖发光/震动”，而 fact sheet 仍记录旧版官道事件。
  - 这说明仅有 map 阶段 hash 校验不够，check/report 阶段也必须重新验证 fact 指纹与当前正文一致。

## 根因判断

- 缓存有效性被放在 Map 阶段，Check 阶段默认信任已落盘缓存。
- consistency 产物被当成独立扫描结果，没有纳入章节生成/清理/回退的动态产物生命周期。
- watermark 用最高章节号表达“新旧”，不能表达“同一章节的正文版本/扫描代际变了”。

## 影响

- 删除后重跑到较低章节时，旧的高章节 fact sheet 仍会参与全局一致性判断。
- `--check` 可能基于不存在的正文生成问题报告。
- 低章重写后，因为 watermark 仍是旧最高章节，新问题可能被压成“存量问题”。
- 用户以为是在审当前书，系统实际可能混入历史生成物。

## 治本方案

1. Check 阶段增加鲜度门禁。
   - 加载 fact 前重新校验对应正文是否存在。
   - 校验 fact 指纹中的正文 hash 是否等于当前正文 hash。
   - 失效 fact 不参与检查，并在报告中列出“需重跑 Map”的章节。
   - 校验正文标题、首尾片段或正文 hash，避免同一章节号被重写后旧 fact 继续参与判断。
2. `--check` 启动前默认执行孤儿 fact 清理，或至少阻断并提示先清理。
3. fact sheet 指纹升级为多源指纹。
   - 包含正文 hash、beat hash、map prompt hash、schema_version、model/provider/version。
   - prompt/schema/model 改动后自动失效。
4. consistency 目录纳入章节清理/回退语义。
   - 主清理脚本或章节回退工具要能同步清理 `consistency/facts/chapter_NNN.json`、issues/report 中对应章节状态。
   - 保留“全量清 consistency”的显式入口，但不再只有独立入口。
5. watermark 版本化。
   - 不只存 `last_scanned`，还存扫描代际、参与章节列表、每章 fact hash。
   - `is_new` 基于 issue id + fact hash/scan generation，而不是只看章节号。

## 验收标准

- 正文目录删到 91 章时，check 不会读取第 126 章 fact。
- 任意正文重写后，对应 fact 自动失效。
- `--check` 对陈旧缓存给出明确阻断/重跑提示，不生成混合时代报告。
- watermark 能识别同一低章重写后的新问题。
