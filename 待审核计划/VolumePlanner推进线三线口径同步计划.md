# VolumePlanner 推进线三线口径同步计划

> 状态：待审核。  
> 范围：只治理规划层同名字段口径，不修改已落盘卷纲或正文。

## 现网证据

- `prompts/volume_planner.md:58` 的阶段规划表包含同名字段 `推进的线`。
- `prompts/volume_planner.md:60-63` 示例仍使用 `主线+副线1`、`主线`、`主线+长线伏笔`。
- `prompts/beat_planner.md:50` 已将 `推进的线` 定义为 `道途线/情义线/天地线`。
- `config/strand_weave.json:5` 运行配置也以 `道途线/情义线/天地线` 为权威三线。

## 根因

上游 VolumePlanner 和下游 BeatPlanner 对同名字段 `推进的线` 使用不同语义。VolumePlanner 继续播种“主线/副线”旧口径，会让卷纲、弧线、beat 对同一字段理解不一致，后续三线节奏统计和补线指令也会失真。

## 治本动作

1. 将三线维度配置化为规划层权威。
   - VolumePlanner、ArcPlanner、BeatPlanner 都从同一三线配置或同一 prompt 常量派生。
2. VolumePlanner 示例改为三线口径。
   - 示例只能使用 `道途线/情义线/天地线` 或 profile 中定义的等价维度。
   - `主线/副线` 可作为自然语言解释，但不得作为机器字段值。
3. 弧线与 beat 消费端增加别名归一。
   - 若旧卷纲仍出现 `主线/副线`，转换成三线或标记为待人工审核，不静默混用。
4. 测试覆盖上游播种。
   - 不只测 BeatPlanner 字段，还要测 VolumePlanner 输出模板和卷纲解析。

## 验收

- VolumePlanner prompt 的 `推进的线` 示例与 `config/strand_weave.json` 一致。
- 新生成卷纲不会在机器字段里输出 `主线+副线1` 这类旧口径。
- ArcPlanner / BeatPlanner 输入中同一字段不会同时出现旧口径和三线口径。
- 换书时三线名称来自 profile/config，不写死当前书维度。
