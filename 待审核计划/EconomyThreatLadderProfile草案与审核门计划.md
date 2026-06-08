# Economy / ThreatLadder Profile 草案与审核门计划

> 状态：待审核。  
> 范围：只治理经济模型和威胁阶梯的资产来源、profile 化与审核门，不修改现有配置。

## 现网证据

- `待审核计划/待审核的可换书架构升级计划.md:40` 将 `economy/threat_ladder/power_scaling/travel_matrix` 简单归为“换书换数据”。
- `待审核计划/自动精品小说生成系统治本总计划.md:318` 的新书 profile 自动播种字段没有经济、物价、威胁阶梯。
- `config/economy.json:45` 包含当前书专名口径 `游医(沈安级别)`。
- `scripts/pipeline/context.py:1321-1324` 在交易相关场景会向 Writer 注入 `config/economy.json`。
- `config/threat_ladder.json:12` 起包含当前书卷数、敌人、事件和专名。
- `scripts/pipeline/planning.py:1454` 会将 threat ladder 注入 BeatPlanner。

## 根因

经济模型和威胁阶梯已经是会进入 Writer / BeatPlanner 的 book-profile 级资产，但目前仍停留在手写配置，未纳入新书自动草案、待审核门和命名空间隔离。换书时“换数据”不是足够的治本方案，因为未审核配置会直接影响生成职责。

## 治本动作

1. profile seed 增加经济和威胁阶梯草案。
   - `economy_model`
   - `pricing_reference`
   - `profession_income_ranges`
   - `threat_ladder`
   - `power_scaling`
2. 自动生成但默认待审核。
   - 未审核不得注入 Writer / BeatPlanner。
   - 审核后才进入 book profile 权威层。
3. 配置不得写死当前书专名。
   - 示例值进入 fixture 或当前书 profile，不进入通用默认。
4. 消费端保留按需注入。
   - Economy 只在交易、酬劳、成本相关场景注入。
   - ThreatLadder 只给规划层，且按当前卷/当前阶段窗口化。

## 验收

- 新书初始化会生成待审核的经济模型和威胁阶梯草案。
- 未审核的 `economy.json` / `threat_ladder.json` 不进入 Writer / BeatPlanner。
- 通用配置不包含当前书专名或当前书卷数默认。
- 交易章节能按需获得经济摘要，非交易章节不被经济表撑大 token。
