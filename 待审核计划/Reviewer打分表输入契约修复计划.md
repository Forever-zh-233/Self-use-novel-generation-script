# Reviewer 打分表输入契约修复计划

## 结论

Reviewer prompt 声称评审会拿到“风格指南、打分表、AI腔黑名单”，但实际 `make_review_input()` 没有注入 `06-验证打分表.md`。这是提示词输入契约与主流程接线不一致。治本方向不是简单塞文件，而是确定“唯一权威评分表”到底在 reviewer.md 内，还是外部 `06-验证打分表.md`。

## 当前证据

- `prompts/reviewer.md:6-9`：声明会拿到 beat、风格指南、打分表、AI腔黑名单和正文。
- `prompts/reviewer.md:34-35`：工作流程要求读取“风格指南、打分表、AI腔黑名单”。
- `scripts/pipeline/gates.py:479-495`：`make_review_input()` 注入 beat、故事总监、风格指南、AI 腔黑名单、硬检查、出场角色核实、近期表达摘要、正文，没有打分表 section。
- 根目录存在 `06-验证打分表.md`，但当前 reviewer 输入未读取它。
- `TESTING.md` 当前倾向把“不读取分数表”作为防污染边界，但 `prompts/reviewer.md:6`、`prompts/reviewer.md:34-35` 仍声明会拿到打分表；这属于文案漂移还是接线缺失，必须定口径。

## 根因判断

- 评分标准有两处来源：`reviewer.md` 内置十二维评分，和根目录 `06-验证打分表.md`。
- 主流程没有声明哪个是权威 rubric，prompt 仍保留“会拿到打分表”的旧契约。
- 测试只覆盖 reviewer 输入包含诊断和正文，不覆盖“prompt 声明的固定输入材料是否实际接入”。

## 影响

- Reviewer 可能按 prompt 期待外部打分表，但输入没有，造成标准漂移。
- 维护者修改 `06-验证打分表.md` 时，以为会影响 reviewer，实际不会。
- 如果两份评分表口径不同，系统没有机制发现矛盾。

## 治本方案

1. 决定唯一权威 rubric。
   - 方案 A：`reviewer.md` 内置评分表是唯一权威，删除 prompt 对外部打分表的输入承诺。
   - 方案 B：`06-验证打分表.md` 是权威，`make_review_input()` 必须注入并测试。
   - 若选择 A，应同步测试维护文档，明确 reviewer 不读取外部打分表是刻意设计，不是漏接。
   - 若选择 B，应增加防污染测试，避免外部打分表把源书人物/术语带回正文评审。
2. 如果保留两份，建立一致性检查。
   - 维度数量、总分、低分返工规则必须一致。
3. 增加 scenario/check 测试。
   - prompt 声明的固定输入材料必须被 `make_review_input()` 注入。
   - 或 prompt 不再声明未注入材料。
4. 更新测试维护指南中的 reviewer 输入契约索引。

## 验收标准

- Reviewer prompt 不再承诺不存在的输入。
- 评分标准只有一个权威来源，或两处有自动一致性检查。
- 测试能捕捉“prompt 输入清单与实际 section 不一致”。
