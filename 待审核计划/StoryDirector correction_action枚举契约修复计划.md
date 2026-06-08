# StoryDirector correction_action 枚举契约修复计划

> 状态：待审核。本文件只记录治本方案，未修改代码或运行产物。

## 结论

StoryDirector prompt 只规定 `severity=0` 时 `correction_action=continue`，没有定义偏航时可选枚举；但 BeatPlanner prompt 又要求按 `tighten/merge/sleep/resolve/pivot` 执行。上游可能输出自由文本动作，下游却按固定动作理解，硬纠偏链路不稳定。

## 当前证据

- `prompts/story_director.md:88-99`：输出 JSON 示例中 `correction_action` 只有 `continue`。
- `prompts/story_director.md:103-108`：字段规则只说“只能选一个”，并规定 `severity=0` 时填 `continue`，没有列出 severity>0 的枚举。
- `prompts/beat_planner.md:91-92`：BeatPlanner 把 `tighten/merge/sleep/resolve/pivot` 及方向批注当成 severity≥2 的硬纠偏动作。

## 根因判断

- StoryDirector 与 BeatPlanner 之间存在隐含枚举契约，但没有在上游 schema 中声明。
- 下游 prompt 比上游 prompt 更具体，导致模型输出可能不在下游可执行集合内。
- 主流程缺少 `correction_action` 枚举校验与非法值重试。

## 影响

- 偏航时 StoryDirector 可能输出“加强主线”“先缓一缓”等自由文本。
- BeatPlanner 看到非枚举动作后，只能凭自然语言猜，硬纠偏可能落空。
- 用户以为总监已经发出强制纠偏，但实际没有可执行动作码。

## 治本方案

1. 定义统一枚举。
   - `continue`：正常推进。
   - `tighten`：收紧主线，减少旁支。
   - `merge`：合并重复债务/线索。
   - `sleep`：将低优先级线索退后台。
   - `resolve`：要求短期兑现/收束。
   - `pivot`：转向指定主线或卷纲目标。
2. StoryDirector prompt 明确枚举与 severity 关系。
   - `severity=0` 固定 `continue`。
   - `severity=1` 可 `continue/tighten/sleep`。
   - `severity>=2` 必须从非 `continue` 枚举中选择，除非 reason 说明只是观察不纠偏。
3. 主流程解析后校验。
   - 非法 `correction_action` 触发 StoryDirector 重试或降级为 `tighten` 并记录警告。
   - severity/action 不匹配时阻断。
4. BeatPlanner 输入结构化。
   - 把 action code、arc_instruction、priority 分开注入，而不是只靠整段批注。
5. 增加测试。
   - StoryDirector 输出非法动作，断言触发重试/校验失败。
   - severity=2 但 action=continue，断言拦截。
   - 合法 action 能进入 BeatPlanner 输入。

## 验收标准

- StoryDirector 和 BeatPlanner 使用同一组 correction_action 枚举。
- 偏航纠偏不再依赖自由文本猜测。
- 测试覆盖非法枚举和 severity/action 不匹配。
