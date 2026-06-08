# Reviewer 正文不可压缩契约修复计划

## 结论

这是 reviewer 职责与上下文压缩策略冲突。Reviewer prompt 要求“对照 beat 评文”，精读刚写出的正文，判断句式、节奏、AI 腔、段落注水、beat 执行偏差等问题；但 `make_review_input()` 把“待评审正文”标记为可压缩。超预算时正文可能被 compressor 摘要，reviewer 就不再是在评原文。

## 当前证据

- `prompts/reviewer.md:4`：Reviewer 职责是对照 beat 评文。
- `prompts/reviewer.md:37-38`：明确要求读取写手产出的正文。
- `prompts/reviewer.md:143`、`270-277`：需要检查句式、不信任读者、beat 忠诚度、空间穿帮、正文事实矛盾等原文级问题。
- `scripts/pipeline/gates.py:468`：`make_review_input()` 构造 reviewer 输入。
- `scripts/pipeline/gates.py:494`：`待评审正文` 使用 `make_section("待评审正文", text, "high", True)`，即 `compressible=True`。
- `scripts/pipeline/context.py:799-802`：压缩逻辑会把可压缩段落交给 compressor。
- 同类风险还存在于 editor：`scripts/run_pipeline.py:752-755` 给 editor 的 `评审` section 使用 `make_section("评审", review, "high", True)`，可被压缩；而 editor 的职责正是按评审给出的段落级建议做局部手术。

## 根因判断

- reviewer 的核心材料“正文”被当作普通 high priority 可压缩材料，而不是 critical / non-compressible。
- 压缩器适合摘要背景，不适合替代待评审原文。
- 对 editor 来说，评审意见也不是普通背景；压缩后可能丢失“哪段哪行怎么改”的操作指令。
- 测试只检查 reviewer input 包含正文，没有覆盖“接近预算时正文是否仍完整保留”。

## 影响

- AI 腔、重复句式、段落拖沓、视角微跳、beat 细节漏写等问题会在摘要中消失。
- Editor 收到的评审意见可能是基于摘要，而不是基于真实正文。
- 评审分数和 blockers 失去可审计性，因为它们可能没有看过原文。

## 治本方案

1. 将“待评审正文”标为不可压缩。
   - priority=`critical`
   - compressible=`False`
2. 若正文过长超预算，采用正文专用裁剪策略，而不是摘要替代。
   - 保留全文优先。
   - 极端情况下分段评审或多轮 reviewer map/reduce。
   - 每个分段仍给原文，不给摘要。
3. 压缩只用于背景材料。
   - 故事核、卷纲、台账、重复摘要可压缩。
   - beat、正文、editor 需要执行的评审修改意见不可压缩。
4. 增加测试。
   - 构造超长背景 + 正文，断言 reviewer input 中正文原文完整存在。
   - 断言 compressor 不接管“待评审正文”区块。
   - 构造超长背景 + 段落级评审意见，断言 editor input 中 `评审` 原文完整存在。

## 验收标准

- Reviewer 永远评原文，不评正文摘要。
- 超预算处理不会牺牲待评审正文完整性。
- 测试覆盖 reviewer 正文不可压缩契约。
