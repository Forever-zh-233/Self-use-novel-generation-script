# Novel 1 测试系统说明

这套测试系统借鉴 `E:\莲莲Bot` 的测试维护方式，但按小说工作台的 `agent.md` 做了收敛：**代码测试只对客观错误有牙齿**，不把创意、节奏、情绪强弱、句段比例变成硬门禁。

## 入口

推荐使用项目固定 Python：

```powershell
& "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe" "E:\Novel 1\scripts\run_tests.py" all
```

也可以只跑某一层：

```powershell
& "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe" "E:\Novel 1\scripts\run_tests.py" check
& "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe" "E:\Novel 1\scripts\run_tests.py" quick
& "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe" "E:\Novel 1\scripts\run_tests.py" scenario
```

## 三层职责

| 入口 | 职责 | 适用场景 |
|---|---|---|
| `check` | Python 语法、关键文件存在、JSON 配置、chunk 索引、`.gitignore` 隐私/运行态边界、Agent 守则存在 | 新增/移动脚本、prompt、chunk、配置后必须跑 |
| `quick` | 纯函数、硬门禁、Review JSON 解析、API 配置读取、状态默认值 | 改 `pipeline/*.py` 的函数、硬检查规则、模型配置逻辑后跑 |
| `scenario` | 临时工作区里的真实小链路：写手上下文、衔接检查、记录员结构化合并、评审输入 | 改 writer/reviewer/archivist/context/state 链路后跑 |
| `all` | `check + quick + scenario` | 交付前跑 |

## 维护准则

一句话判断：

```text
项目结构变了 -> 改 check
客观规则/纯函数变了 -> 改 quick
角色链路/上下文/台账写入变了 -> 改 scenario
创意审美判断变了 -> 不写硬测试，把材料给 reviewer
```

### 可以硬失败的测试

- 源文专名污染、内部编号泄露、系统元信息泄露。
- 角色名混用、JSON 解析失败、配置缺失、chunk 索引指向不存在文件。
- 真实链路中的客观写入错误，例如记录员更新没有落到 `state.json` / `ledger.json`。
- 隐私/运行态边界错误，例如 `.env.local`、源文全文、`runtime/`、`输出/`、`beats/` 没有被忽略或被跟踪。

### 不要写成硬失败的测试

- 句长、段长、短句比例、对话比例、场景节奏、情绪强弱。
- “这一章不够爽”“转折不够”“留白不够”“人物声音不够好”。
- 任何模型可以通过删内容、写得更平、减少表达来讨好测试的规则。

这些只能作为 `style_gate` 的 metrics 或 diagnostics 传给 reviewer，由 reviewer/人类判断。

## 新增测试 checklist

新增 `scripts/pipeline/*.py` 模块时：

- [ ] `tests/checks_test.py` 的 `REQUIRED_FILES` 如有必要加入新模块。
- [ ] 新模块会被 `scripts/*.py` 或 `scripts/pipeline/*.py` glob 自动做语法检查。
- [ ] 如果有导出函数契约，在 `tests/quick_test.py` 加纯函数测试。
- [ ] 如果会写状态、构造 prompt、影响角色链路，在 `tests/scenario_test.py` 用 `isolated_workspace()` 加场景测试。
- [ ] 跑 `scripts/run_tests.py all`。

新增 prompt 或 chunk 时：

- [ ] prompt 是固定角色入口，就加入 `tests/checks_test.py` 的 `REQUIRED_PROMPTS`。
- [ ] chunk 必须在 `chunks/index.json` 里声明 `file/tokens/category`，且 `file` 指向真实文件。
- [ ] 不要把 `输出/分数表/` 或源文全文注入 writer/reviewer/editor/archivist。

改硬门禁时：

- [ ] `quick` 里至少放一个“应拦截”的真实失败输入。
- [ ] 同时放一个“应放行”的安全样例，防止误伤。
- [ ] 如果规则可能诱导模型删内容或写平庸，不能做硬门禁。

改上下文/台账链路时：

- [ ] `scenario` 必须用临时 `NOVEL_WORKSPACE`，不得写真实 `runtime/`、`输出/`、`beats/`。
- [ ] 测试要断言真实落盘结果，而不是只看函数返回值。
- [ ] 涉及 API 调用时不要打真实 API；mock `call_role` 或测试 API 之前的输入构造。

## 测试报告四问

每次说“已验证修复”时，报告必须回答：

1. 复现了哪条真实失败输入？
2. 断言了哪个失败现象不会再出现？
3. 哪些依赖被 mock 或隔离了？
4. 因为 mock/隔离，哪些真实链路仍未覆盖？

当前测试系统的默认隔离范围：

- `scenario` 使用临时 `NOVEL_WORKSPACE`，不会写真实工作台运行态。
- 不调用真实 LLM API。
- 不验证真实长篇输出质量，只验证客观结构、上下文与落盘契约。

## 当前覆盖索引

- `tests/checks_test.py`：结构、配置、chunk、忽略规则、Agent 守则。
- `tests/quick_test.py`：`hard_gate`、`style_gate`、review verdict 解析、API key/config helper、JSON 提取、状态默认值。
- `tests/scenario_test.py`：writer 上下文、writer 账本视图、相邻章节衔接、archivist 结构化更新合并、reviewer 输入不读取分数表。

## 常见陷阱

- Windows 下 `python -m py_compile` 会写 `__pycache__`，可能污染或被权限挡住。本测试系统用 `compile()` / `ast.parse()` 做语法门卫，不生成 `.pyc`。
- `pipeline.core.BASE_DIR` 在 import 时读取 `NOVEL_WORKSPACE`。场景测试必须先进 `isolated_workspace()` 再 import pipeline 模块。
- 不要在测试里读取 `.env.local` 的密钥值，也不要 echo API key。
- 不要为了让测试好写而把 `style_gate` 指标升级成硬失败。那会违反反 Goodhart 第一原则。
