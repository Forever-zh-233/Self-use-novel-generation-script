# 小说工作台使用说明

## 当前定位

工作台默认是**原创小说模式**：学习源文本的节奏和写法，不沿用源文本的人名、地名、门派、功法、桥段和台词。

`271824.txt` 只允许分析师或门禁脚本读取。写手、评审、修稿手、记录员都不要读它。

## 手写 Agent 模式

适用于 Codex、Claude Code、OpenCode、QwenPaw 等任意 agent。

你可以这样下指令：

```text
使用 E:\Novel 1 工作台。
你是写手，写第1章。
beat 文件是 E:\Novel 1\beats\chapter_1.json。
不要读取 271824.txt。
```

写手应读取：

- `09-故事核.md` 的明线设定部分，不读后期答案和幕后解释
- `10-卷纲.md`
- `11-负空间.md`
- `12-AI腔黑名单.md`
- `02-修炼境界.md` 的境界表现和升级节奏，不读后期真相相关内容
- `chunks/chunk_黄金法则.md`
- 本章场景 chunk
- 本章角色 chunk
- `07-动态状态台账.md`
- `08-期待账本.md`
- `15-长线伏笔资产库.md` 的安全范围：表层线索、外显条件、外显方式、当前状态；不读完整真实含义
- 本章 beat

写完后把正文放到 `输出/文章/第{N}章.md`。写手草稿、评审、修稿、记录员报告分别放到 `输出/写手/`、`输出/评审/`、`输出/修稿/`、`输出/记录员/`。后续可以让任意 agent 扮演评审、修稿手、记录员，但必须继续使用同一份台账和期待账本。

## 半自动 prompt 模式

生成写手 prompt：

```powershell
$env:PYTHONIOENCODING="utf-8"
& "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe" "E:\Novel 1\scripts\pipeline.py" --chapter 1 --beat "E:\Novel 1\beats\chapter_1.json"
```

脚本会写出：

- `输出/写手/第001章_writer_prompt.md`

你可以把这个 prompt 发给任意 agent 或网页模型。

如果已有正文文件，可以做硬检查并生成评审 prompt：

```powershell
& "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe" "E:\Novel 1\scripts\pipeline.py" --chapter 1 --beat "E:\Novel 1\beats\chapter_1.json" --text "E:\Novel 1\输出\写手\第001章_draft.md"
```

## API 自动模式

最省事的方式：

```text
双击 E:\Novel 1\一键自动写小说.bat
```

脚本会读取：

- `config/models.json`：每个角色用哪个 API 和模型。
- `config/run.json`：从第几章开始、一次生成几章。默认 `start_chapter` 是 `"auto"`，会从已有 `输出/文章/第NNN章.md` 的下一章续写。

默认一次只生成 1 章，且脚本有锁文件，重复双击不会无限启动。

终端里会显示章节、角色、步骤和耗时。运行中可按 `p` 请求暂停/继续，按 `q` 请求停止。暂停和停止会在当前 API 调用结束后的安全点生效。

### 配置模型

打开：

```text
E:\Novel 1\config\models.json
```

最少填写：

- `providers.openai_main.api_key`：OpenAI 官方 Responses API。
- `providers.openai_compatible.api_key` 和 `base_url`：第三方 OpenAI 兼容接口，`base_url` 填服务商给的 `/v1` 地址。
- `providers.anthropic_main.api_key`：Anthropic/Claude 官方接口。
- `roles.writer.provider/model`：写手用哪个供应商和模型。
- `roles.reviewer.provider/model`：评审用哪个供应商和模型。
- `roles.editor.provider/model`：修稿手用哪个供应商和模型。
- `roles.archivist.provider/model`：记录员用哪个供应商和模型。

支持的 provider type：

- `openai_responses`：OpenAI 官方 `/v1/responses`。
- `openai_chat`：OpenAI-compatible `/v1/chat/completions`。
- `anthropic`：Anthropic `/v1/messages`。

也可以不把 key 写进文件，改用环境变量：

```powershell
$env:OPENAI_API_KEY="你的key"
$env:ANTHROPIC_API_KEY="你的key"
```

> **本仓库已采用环境变量方式管理 mimo 密钥（避免密钥进 git 历史）。**
> `config/models.json` 里 `mimo_main.api_key` 已留空、`api_key_env` 设为 `MIMO_API_KEY`。
> 跑管线前必须先设环境变量，否则会报 “角色 X 缺少 API key”。
> 密钥本地存放在 `.env.local`（已被 `.gitignore` 排除，不进仓库）。恢复方式：
>
> ```powershell
> # PowerShell：从 .env.local 读出并设进当前会话
> $env:MIMO_API_KEY = (Get-Content "E:\Novel 1\.env.local" | Select-String '^MIMO_API_KEY=').ToString().Split('=',2)[1]
> ```
> ```bash
> # bash：
> export MIMO_API_KEY=$(grep '^MIMO_API_KEY=' "E:/Novel 1/.env.local" | cut -d= -f2-)
> ```
> 换机器/重置时，把密钥重新填进 `.env.local` 或直接设 `MIMO_API_KEY` 即可。

dry-run 只生成 prompt，不调用 API：

```powershell
& "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe" "E:\Novel 1\scripts\run_pipeline.py" --chapter 1 --beat "E:\Novel 1\beats\chapter_1.json" --dry-run
```

真正自动写：

```powershell
& "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe" "E:\Novel 1\scripts\run_pipeline.py" --chapter 1 --beat "E:\Novel 1\beats\chapter_1.json"
```

默认成功后只保留终稿和状态；过程副产物会自动删除。若在 `config/run.json` 中把 `artifact_retention` 改为 `"reports"` 或 `"debug"`，输出会按职责分目录保留：

异常恢复：如果电脑死机或 bat 被强关，下一次启动会自动检查“正文已落盘但台账没更新”的章节，并优先补台账。若最后一章疑似半截正文，脚本会停下让你检查，不会直接续写。

- `输出/文章/第001章.md`：只放最终正文，方便连续阅读。
- `输出/章纲/第001章_beat_*.md`：自动生成 beat 时的输入和原始输出。
- `输出/写手/第001章_writer_prompt.md`、`第001章_draft.md`、`第001章_final.md`。
- `输出/门禁/第001章_gate.json`。
- `输出/评审/第001章_review.md`。
- `输出/修稿/第001章_edited.md`。
- `输出/记录员/第001章_archive_update.md`。
- `输出/上下文/`：压缩上下文与角色输入快照。

## 多模型配置

编辑：

```text
config/models.json
```

不同角色可以配置不同模型：

```json
{
  "defaultProvider": "openai_main",
  "providers": {
    "openai_main": {
      "type": "openai_responses",
      "base_url": "https://api.openai.com/v1",
      "api_key": ""
    },
    "openai_compatible": {
      "type": "openai_chat",
      "base_url": "https://YOUR_OPENAI_COMPATIBLE_HOST/v1",
      "api_key": ""
    },
    "anthropic_main": {
      "type": "anthropic",
      "base_url": "https://api.anthropic.com",
      "api_key": ""
    }
  },
  "roles": {
    "beat_planner": { "provider": "openai_main", "model": "gpt-5.1-mini" },
    "writer": { "provider": "openai_main", "model": "gpt-5.1" },
    "reviewer": { "provider": "openai_main", "model": "gpt-5.1-mini" },
    "editor": { "provider": "openai_main", "model": "gpt-5.1" },
    "archivist": { "provider": "openai_main", "model": "gpt-5.1-mini" },
    "compressor": { "provider": "openai_main", "model": "gpt-5.1-mini" }
  }
}
```

脚本和手写 agent 共用同一套文件，不会互相冲突。

## 上下文压缩

脚本不会把所有历史无脑塞给每个角色。每个角色有独立上下文预算，接近 `compress_at_ratio` 时会先压缩可压缩材料，保留故事核、本章 beat、硬规则等高优先级内容。

压缩报告会落盘到 `输出/context/`，可以回看模型到底压了什么。
