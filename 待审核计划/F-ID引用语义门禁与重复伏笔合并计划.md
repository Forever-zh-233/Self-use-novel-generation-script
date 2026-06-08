# F-ID 引用语义门禁与重复伏笔合并计划

## 结论

当前管路把 `F-xxx` 当成字符串引用处理，没有强制展开 canonical 承诺文本。结果是 beat 可以写出正确 ID 但在括号里临时改义，Archivist 又可以在已有未回收伏笔附近另起新 ID，造成计划态和台账态都看似合法，实际伏笔语义漂移。

## 当前证据

- `beats/chapter_95.json:7`、`beats/chapter_95.json:34`：第 95 章 beat 写“回收 F-184（周济认朱砂印）、F-185（小满感知能力外显）”。
- `08-期待账本.md:824-825`、`runtime/active_threads.md:300-301`：canonical F-184/F-185 实际是“药方折痕”和“碎屑对窑厂/药方两个方向共鸣”，不是 beat 括号中的释义。
- 括号中的“周济认朱砂印”更接近 F-190，见 `runtime/active_threads.md:308`；“小满感知能力外显”更接近 F-198，见 `runtime/active_threads.md:316`；“远志暗示”更接近 F-210，见 `runtime/active_threads.md:328`。
- `runtime/active_threads.md:349` 已有 F-229“后门/前门有人”；第 95 章后又新增 F-232“前门灰蓝布衣”，见 `runtime/active_threads.md:352`、`08-期待账本.md:988`，语义高度重叠。
- 第 96 章出现同类语义错绑：`beats/chapter_96.json:7,10-11,19,29,30-34` 计划韩铮出场并写 `收[F-186]/酿[F-218]`，`beats/_debug/第096章/beat_input.md:12,21-22` 把 F-186 解释成“韩铮站在走廊里没拦”；但 canonical F-186 在 `08-期待账本.md:826`、`runtime/active_threads.md:302` 实际是“南边闷响”。韩铮“留口子”更接近 F-067/OB-003，见 `08-期待账本.md:385`、`runtime/active_threads.md:119`、`runtime/ledger.md:409`。
- 第 97 章药包硬棱样本显示重复开账和事实强度漂移叠加：已有 F-227“药包硬棱”，见 `08-期待账本.md:977`、`runtime/active_threads.md:347`；正文只写“像……铜片？”且没拆，见 `输出/文章/第097章.md:153-163`，但 Archivist 又新增 F-235“药包铜片”，见 `runtime/active_threads.md:355`、`08-期待账本.md:1008`。
- F-ID 还存在权威源漂移样本：正式 beat 引用的 `F-046/F-047` 在 `08-期待账本.md:308` 存在，但递归扫描 `runtime/active_threads.json` 没有 canonical entry；`runtime/active_threads.md:96` 只在 F-050 备注里提到 F-047。
- ID 解析本身有命名空间风险：`scripts/pipeline/gates.py:376` 使用 `re.findall(r"F-\d{3}", text)`，会把 `LF-002` 内部误命中成 `F-002`；`scripts/consistency/checker.py:239` 也有同类裸 `F-\d{3}` 搜索。

## 根因判断

- BeatPlanner、ArcPlanner、Archivist 没有共享同一个 F-ID resolver。
- 引用 F-ID 时没有进行 “ID -> canonical 描述 -> 本次动作释义” 的一致性校验。
- 新增伏笔前没有近似匹配未回收旧伏笔，导致旧债务没有推进，新债务继续膨胀。

## 治本方案

1. 建立 F-ID resolver。
   - 权威源使用 `runtime/active_threads` 或统一后的期待账本源。
   - 返回 ID、类型、埋设章、canonical 承诺、状态、最近推进记录。
   - resolver 必须严格区分 `F-*`、`LF-*`、`EA-*` 等命名空间，禁止裸 `F-\d+` 正则误吞 `LF-002`。
   - resolver 要对 `08-期待账本.md` 与 `runtime/active_threads.json/md` 做 ID 存在性、状态、canonical 描述一致性对账。
2. 所有规划角色引用 F-ID 时必须注入 canonical 描述。
   - prompt 中禁止只给裸 ID。
   - 模型输出括号释义必须与 canonical 描述相容。
3. 增加 F-ID 语义门禁。
   - 输出中出现 `F-\d+` 时，解析 ID 并比对释义。
   - 不存在、已关闭但被当未回收、释义不一致时阻断或进入人工复核。
4. Archivist 新增伏笔前做相似未回收检索。
   - 相似旧项存在时必须选择推进旧项、部分回收、拆分并说明理由。
   - 新 ID 要记录 `parent_or_related_ids`，避免孤立开账。
5. 增加 scenario 测试。
   - `收[F-184]` 但释义写成“周济认朱砂印”时必须失败。
   - 已有 F-229 时，正文出现“前门灰蓝布衣”不得静默新增 F-232。
   - 文本含 `LF-002` 时不得被 F-ID resolver 误识别为 `F-002`。
   - `08-期待账本.md` 有 F-ID 而 `active_threads.json` 没有 canonical entry 时必须报源漂移。

## 验收标准

- F-ID 不再能被括号释义临时改义。
- 新伏笔不会绕过相似旧伏笔直接膨胀。
- Beat/Arc/Archivist 对同一 F-ID 的理解一致。
