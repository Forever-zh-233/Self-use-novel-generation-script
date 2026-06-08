# Legacy Chunk 生成器退役与待审核草案计划

> 状态：待审核。  
> 范围：只治理旧资产生成脚本的入口边界，不修改现有 chunks 或手法卡内容。

## 现网证据

- `scripts/split_docs.py:114-116` 会删除 `chunks/` 下已有 `chunk_*.md`。
- `scripts/split_docs.py:239` 重写 `chunks/index.json`。
- `scripts/split_docs.py:26` 将卷纲源指向根目录 `10-卷纲.md`，而现用正式卷纲在 `卷纲/10-卷纲.md`。
- `chunks/index.json:272` 起已包含卷纲 chunk；后续还包含 analyst/手写升级资产和多类手法卡。

## 根因

`split_docs.py` 仍按旧的一次性拆文档方式重建 chunks，将 `chunks/` 当可全量覆盖的工作目录。但当前 chunks 已经成为手法卡、结构参考、分析产物、卷纲切片混合资产库，直接删除再重写会破坏已有资产和 index。

## 治本动作

1. 旧生成器退役或降级为只读诊断。
   - 默认不得写 `chunks/` 正式目录。
   - 如需继续使用，只能输出到 `待审核计划` 或 `runtime/drafts/chunks` 这类草案目录。
2. 新 chunk 生成必须走 merge。
   - 保留现有 `index.json` 项。
   - 新增/更新条目必须带 namespace、source、digest、review_status。
3. 卷纲源路径改为权威路径。
   - 不能再读取根目录旧 `10-卷纲.md`。
4. 手法卡与正典分域。
   - craft chunk、book canon、runtime canon、reference evidence 分 namespace 管理。

## 验收

- 运行旧脚本不会删除正式 `chunks/chunk_*.md` 或重写正式 `chunks/index.json`。
- 新生成 chunk 默认进入待审核草案目录。
- `chunks/index.json` 中已有 analyst/手写升级资产不会因重建丢失。
- 卷纲 chunk 的来源指向当前权威卷纲路径。
