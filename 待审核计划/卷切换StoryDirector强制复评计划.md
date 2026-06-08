# 卷切换 StoryDirector 强制复评计划

## 结论

主流程在顺序上确实把 StoryDirector 放在 BeatPlanner 之前，但这不等于卷切换章一定会重新审核。`run_story_director()` 默认允许复用上一轮缓存，只把 `chapter` 改成当前章；如果卷纲刚被替换、卷号变化或跨卷边界发生，但没有强制复评信号，BeatPlanner 仍可能收到旧卷方向批注或默认放行批注。

## 当前证据

- `scripts/run_pipeline.py:1731-1734`：主循环先运行 VolumePlanner，再调用 `run_story_director(chapter, run_cfg, timeout)`。
- `scripts/pipeline/planning.py:244-249`：StoryDirector 是否真实调用模型取决于 `force / not previous / interval / needs_arc_planning(chapter)`。
- `scripts/pipeline/planning.py:250-254`：不满足调用条件时，直接沿用 previous，只覆盖 `chapter` 后保存。
- `scripts/run_pipeline.py:1734`：主流程没有在卷切换后传 `force=True`，也没有把“卷纲 hash 变化 / 卷号变化 / 目标章越过旧卷 end”作为强制复评条件。
- 第 101 章现场样本显示 StoryDirector 纠偏发生太晚：
  - `beats/_debug/第101章/beat_input.md:19-23`：第 101 章输入中 StoryDirector 仍是“尚未触发故事总监审核”。
  - `runtime/story_director.md:3,7,10`：到第 102 章才把第 101 章解释为“第二卷开篇 / 过渡”，这是事后解释，不是第 101 章 BeatPlanner 前的边界判断。

## 根因判断

- 调度层把“调用 StoryDirector 函数”误当成“完成了本章方向复评”。
- StoryDirector 缓存缺少依赖指纹，无法判断当前卷纲、active arcs、故事水位是否已经变化。
- 卷切换是方向语义的高风险边界，但目前没有独立事件通知，VolumePlanner 成功提交后不会驱动 StoryDirector 强制复评。
- BeatPlanner 把 `story_director_context(chapter)` 作为 critical 输入消费，却无法知道这份批注是当前卷新鲜生成、缓存沿用，还是默认放行。

## 治本方案

1. VolumePlanner 成功提交新卷纲后返回结构化结果。
   - `volume_switched: true`
   - `target_chapter`
   - `target_volume`
   - `validated_range`
   - `volume_plan_hash`
2. 主流程在卷切换章强制复评。
   - 当 `volume_switched=true` 或 `volume_plan_hash` 变化时，调用 `run_story_director(..., force=True)`。
   - 若 StoryDirector 失败，按关键规划角色处理：重试或阻断，不得默认沿用旧卷批注。
3. StoryDirector 缓存增加依赖指纹。
   - `volume_plan_hash`
   - `active_arcs_hash`
   - `latest_committed_chapter`
   - `target_chapter`
   - `story_director_prompt_hash`
4. 缓存复用条件显式排除卷边界。
   - 卷号变化不得复用。
   - 当前章越过上一卷 end 不得复用。
   - active arcs 已过期或换批不得复用。
5. BeatPlanner 使用前校验批注鲜度。
   - `story_director.chapter == target_chapter`
   - `story_director.volume_plan_hash == current_volume_plan_hash`
   - severity>=2 的批注必须已进入 beat 输入并被方向校验确认吸收。

## 测试要求

- 构造第 101 章越过旧卷 end 且 VolumePlanner 成功提交新卷纲，断言 StoryDirector 用 `force=True` 真实调用模型。
- 构造上一轮 StoryDirector 未过期但卷纲 hash 变化，断言不得复用 previous。
- 构造 StoryDirector 在卷切换章失败，断言主流程停在规划阶段，不调用 `ensure_beat()`。
- 构造第 101 章已有 beat 文件但 StoryDirector 指纹不匹配，断言已有 beat 不得直接复用。

## 验收标准

- 卷切换章进入 BeatPlanner 前，必有针对当前卷纲和当前章的新鲜 StoryDirector 批注。
- StoryDirector 缓存复用有依赖指纹，不再只看间隔章数。
- 卷切换后的方向判断不会在下一章才事后补解释。
