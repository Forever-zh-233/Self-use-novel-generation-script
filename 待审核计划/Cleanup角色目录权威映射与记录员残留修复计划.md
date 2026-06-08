# Cleanup 角色目录权威映射与记录员残留修复计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

清理脚本手写输出子目录列表，漏掉了主流程正式使用的 `输出/记录员`。全量清理后旧 Archivist 报告可能残留；如果同章新正文落盘后崩在 Archivist 前，断点恢复可能复用旧记录员报告，把新正文提交到旧台账更新里。

## 当前证据

- `scripts/pipeline/core.py:101-111`：`role_output_dir("archivist")` 映射到 `输出/记录员`。
- `scripts/clean_chapter_artifacts.py:53-56`：清理列表包括 `文章/分数表/章纲存档/写手/评审/修稿/门禁/章纲/上下文`，没有 `记录员`。
- `scripts/run_pipeline.py:221-250`：断点恢复读取 `role_artifact("archivist", chapter, "archive_update.md")`，存在且通过校验时会复用。

## 根因判断

- 角色目录映射有两个权威源：core 的 `role_output_dir()` 和 cleanup 的手写列表。
- cleanup 没有从主流程角色映射派生，因此新增角色目录时容易漏。
- Archivist 报告是高风险副产物，它既是过程文件，又可能在恢复时被当作提交凭证。

## 影响

- 清理后仍残留旧 `archive_update.md`。
- 恢复链路可能把旧正文对应的 Archivist 报告应用到新正文。
- 用户以为“一键清理”已清空章节产物，实际记录员产物仍在。

## 治本方案

1. 建立角色目录单一权威源。
   - cleanup 从 `role_output_dir()` 或统一 `ROLE_OUTPUT_DIRS` 派生。
   - 禁止手写重复列表。
2. 将 `输出/记录员` 纳入清理。
   - 与 writer/reviewer/editor/gate 同等级清空。
3. 恢复复用报告时增加正文指纹。
   - Archivist 报告必须带 source article hash / chapter manifest id。
   - 指纹不匹配时必须重跑 Archivist。
4. 增加测试。
   - 遍历所有 role_output_dir，断言 cleanup 覆盖。
   - 清理后 `输出/记录员` 为空。
   - 旧报告正文指纹不匹配时不复用。

## 验收标准

- 一键清理覆盖所有主流程角色目录。
- Archivist 报告不会跨正文版本复用。
- 新增角色目录时 cleanup 测试会自动提醒。
