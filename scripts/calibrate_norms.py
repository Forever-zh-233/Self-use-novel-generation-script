# -*- coding: utf-8 -*-
"""calibrate_norms.py —— 据 analyst 校准报告自动重填 config/structure_norms.json(项目三 D 第二步)。

换书流程:换源文+设定 → 跑 --analyst 出 _structure_calibration.md → 跑本脚本 → 全绿自动更新 JSON。
人只在护栏报警时介入。**绝不碰 prompt**(原理永不自动改,是 D 的根基)。

职责链:读报告 → LLM 抽数字填 JSON → 4 道确定性护栏 → 全绿才原子覆写,否则拿报错当反馈重抽(最多 3 次)。
agent 不被信任,护栏才是关口:任何一道不过就拒绝覆写、保留旧 JSON。

铁律:校准报告含真名(举证用),但抽出的 JSON 只许有数字+抽象标签,真名扫描是死线护栏。
"""

import json
import os
import re
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from pipeline.core import (  # noqa: E402
    BASE_DIR as CORE_BASE, ANALYST_DIR, cli_print, read_text, write_text,
    load_json, dump_json, load_env_local, extract_json_object,
)
from pipeline.api import call_model, role_max_output_tokens  # noqa: E402

REPORT_PATH = ANALYST_DIR / "_structure_calibration.md"
NORMS_PATH = BASE_DIR / "config" / "structure_norms.json"
MAX_RETRIES = 3

# JSON 必须含的 8 个顶层结构组(与 structure_norms_digest 的 emit_group 一一对应)。
REQUIRED_KEYS = [
    "弧长分级章数", "节点间距随进程章数", "伏笔回收窗口章数", "憋占比按弧型",
    "反差窗口章数", "物件复现间距章数", "闭环率分布", "呼吸cadence",
]
# 区间类组(值应为 [下限,上限] 或字符串说明);百分比类组(值应为含%的字符串)。
PERCENT_GROUPS = {"憋占比按弧型", "闭环率分布"}
CHAPTER_MAX = 200  # 章数 sanity 上限:超过视为离谱


def load_realname_probes() -> list:
    """源文真名探针:从 分析草稿/style_metrics.json 高频词取像专名的(与 run_pipeline 同源)。
    JSON 命中任一探针 = 真名泄漏 = 死线破,拒绝。"""
    probes = []
    metrics = load_json(BASE_DIR / "分析草稿" / "style_metrics.json")
    freq = (metrics or {}).get("high_freq_words") or []
    stop = {"什么", "这时", "起来", "一声", "点头", "于是", "不过", "然而", "很快",
            "出来", "过来", "下来", "一下", "来了", "事情", "口气", "的人", "一笑",
            "说道", "了笑", "这时候", "的时候", "起头", "一口气"}
    for item in freq:
        if isinstance(item, list) and len(item) == 2:
            w, c = item
            if isinstance(w, str) and isinstance(c, int) and c >= 80 and 2 <= len(w) <= 4 and w not in stop:
                probes.append(w)
    return probes


def _flatten_strings(obj) -> list:
    """递归收集 JSON 里所有字符串(键+值),供真名扫描。"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            out.extend(_flatten_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_flatten_strings(v))
    elif isinstance(obj, str):
        out.append(obj)
    return out


def guard_realname(norms: dict, probes: list) -> list:
    """护栏1(死线):JSON 里不许出现任何源文真名。命中即拒。"""
    issues = []
    blob = "\n".join(_flatten_strings(norms))
    for p in probes:
        if p in blob:
            issues.append(f"JSON 含疑似源文真名「{p}」——结构数字绝不该带真名(死线)")
    return issues


def guard_schema(norms: dict) -> list:
    """护栏2:必须含全部 8 个顶层 key,每个值是 dict。"""
    issues = []
    if not isinstance(norms, dict):
        return ["顶层不是 JSON 对象"]
    for k in REQUIRED_KEYS:
        if k not in norms:
            issues.append(f"缺顶层结构组「{k}」")
        elif not isinstance(norms[k], dict):
            issues.append(f"「{k}」的值不是对象")
    return issues


def _check_value(group: str, key: str, val, is_percent: bool) -> list:
    """单条值的范围 sanity。区间 [a,b] 要求 0<a<=b<=CHAPTER_MAX;百分比字符串要含%且数字0-100;
    纯说明字符串放行(如'不设上限,每15-20章...')。"""
    issues = []
    if isinstance(val, list):
        if len(val) != 2 or not all(isinstance(x, (int, float)) for x in val):
            issues.append(f"「{group}.{key}」区间格式应为 [下限,上限] 两个数,得到 {val}")
            return issues
        a, b = val
        if a <= 0 or b <= 0:
            issues.append(f"「{group}.{key}」区间出现非正数 {val}")
        if a > b:
            issues.append(f"「{group}.{key}」区间下限>上限 {val}")
        if not is_percent and b > CHAPTER_MAX:
            issues.append(f"「{group}.{key}」章数 {b} 超过 sanity 上限 {CHAPTER_MAX}")
    elif isinstance(val, (int, float)):
        if val <= 0 or (not is_percent and val > CHAPTER_MAX):
            issues.append(f"「{group}.{key}」数值 {val} 越界")
    elif isinstance(val, str):
        if is_percent:
            nums = [int(n) for n in re.findall(r"\d+", val)]
            if any(n > 100 for n in nums):
                issues.append(f"「{group}.{key}」百分比 {val} 出现 >100")
        # 纯说明字符串(章数类的'不设上限...')放行,但若声称是数字范围却没%也没数字则可疑——宽松放过
    else:
        issues.append(f"「{group}.{key}」值类型异常:{type(val).__name__}")
    return issues


def guard_ranges(norms: dict) -> list:
    """护栏3:每条数值的范围 sanity(负数/上限<下限/离谱大数/百分比>100)。"""
    issues = []
    for group in REQUIRED_KEYS:
        data = norms.get(group)
        if not isinstance(data, dict):
            continue
        is_percent = group in PERCENT_GROUPS
        for key, val in data.items():
            if str(key).startswith("_"):
                continue
            issues.extend(_check_value(group, str(key), val, is_percent))
    return issues


def guard_digest_renders(norms: dict) -> list:
    """护栏4a:新 JSON 喂给 structure_norms_digest 必须能正常渲染(不抛错、非空)。
    临时把 norms 写到候选路径,让 digest 读它——但 digest 读的是固定路径,故这里直接复用其格式化逻辑做轻校验。"""
    issues = []
    try:
        import importlib
        P = importlib.import_module("pipeline.planning")
        # digest 读固定文件;为不污染正式文件,这里只验"至少有一个组能格式化出非下划线键"
        rendered_any = False
        for group in REQUIRED_KEYS:
            data = norms.get(group) or {}
            if any(not str(k).startswith("_") for k in data):
                rendered_any = True
                break
        # 顺带确认 _fmt_range 不抛错
        for group in REQUIRED_KEYS:
            for k, v in (norms.get(group) or {}).items():
                if not str(k).startswith("_"):
                    P._fmt_range(v)
        if not rendered_any:
            issues.append("所有结构组都为空(或只有下划线说明键),digest 会渲染为空")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"digest 渲染校验抛错:{exc}")
    return issues


def run_all_guards(norms: dict, probes: list) -> list:
    """跑全部护栏,汇总 issues(空 = 全过)。"""
    issues = []
    issues.extend(guard_realname(norms, probes))
    issues.extend(guard_schema(norms))
    issues.extend(guard_ranges(norms))
    issues.extend(guard_digest_renders(norms))
    return issues


AGENT_INSTRUCTIONS = """你是结构参数抽取器。输入是一份"结构校准报告"(分析某本小说原文得出)。
你的唯一任务:从报告里抽出结构【参考分布】数字,填进一个固定 schema 的 JSON。

**铁律:**
1. **绝不输出任何人名/地名/物件名/门派名等专名。** 报告里的举证表格含真名(如某某@第N章),那些只是举证,你要的是它们归纳出的【数字分布】,不是真名。JSON 里只许有数字和抽象类型标签(如"单元任务弧""高频伴行物")。
2. 优先读报告里每节的 **【可入 prompt】** 段和第五节"给规划层的具体改动建议"——那里是已洗净真名的抽象结论,数字都在里面。
3. 区间写成 [下限,上限] 两个整数(章数);百分比写成带%的字符串(如"50-60%");确实不设上限的写说明字符串。
4. 只输出 JSON,不要解释。严格用下面的 key(一个都不能少):

{
  "_说明": "本书结构参考分布(非KPI)。换书时据校准报告自动重填。",
  "_来源": "据 _structure_calibration.md 自动抽取",
  "弧长分级章数": {"单元任务弧": [下,上], "角色成长弧": [下,上], "大战决战弧": [下,上], "命运信物弧": "不设上限的说明字符串"},
  "节点间距随进程章数": {"前期(全书前30章左右)": [下,上], "中期": [下,上], "后期": [下,上]},
  "伏笔回收窗口章数": {"任务即时类(委托/危机/小疑问)": [下,上], "关系成长类": [下,上], "信物命运级": [下,上]},
  "憋占比按弧型": {"单元任务弧": "百分比字符串", "角色成长弧": "...", "大战决战弧": "...", "命运信物弧": "..."},
  "反差窗口章数": {"主角短距反差": [下,上], "配角长距记忆维护间隔": [下,上]},
  "物件复现间距章数": {"高频伴行物(随身物/伙伴)": [下,上], "中频功能物(武器/法宝/信物)": [下,上], "低频意象物(首尾呼应象征)": "说明字符串"},
  "闭环率分布": {"彻底闭环": "百分比", "留尾巴(需15-25章内给侧写提示)": "百分比", "半收(了结核心留余韵)": "百分比", "留白容忍": "说明字符串"},
  "呼吸cadence": {"连续高强度上限章数": 数字, "高强度后缓冲章数": [下,上], "连续低强度上限章数": 数字}
}
"""


def extract_norms_from_report(report: str, prev_issues: list, timeout: int) -> dict:
    """调 LLM 从报告抽 JSON。prev_issues 非空时把上次护栏报错当反馈附在输入末尾,引导重抽。"""
    user_input = report
    if prev_issues:
        fb = "\n".join(f"- {x}" for x in prev_issues)
        user_input = report + f"\n\n=== 上一次抽取被护栏打回,请修正这些问题后重新输出完整 JSON ===\n{fb}"
    raw = call_model("analyst", AGENT_INSTRUCTIONS, user_input,
                     role_max_output_tokens("analyst", 8000), timeout)
    return extract_json_object(raw)


def main() -> None:
    import argparse
    load_env_local()
    parser = argparse.ArgumentParser(description="据校准报告自动重填 structure_norms.json")
    parser.add_argument("--report", help="校准报告路径,默认 runtime/analyst/_structure_calibration.md")
    parser.add_argument("--dry-run", action="store_true", help="只抽+校验+打印,不写任何文件")
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    report_path = Path(args.report) if args.report else REPORT_PATH
    if not report_path.exists():
        cli_print(f"[calibrate] 校准报告不存在:{report_path}。请先跑 --analyst 生成报告。")
        sys.exit(1)
    report = read_text(report_path)
    probes = load_realname_probes()
    cli_print(f"[calibrate] 读报告 {report_path}（{len(report)} 字符），真名探针 {len(probes)} 个。")

    norms = None
    issues = []
    for attempt in range(1, MAX_RETRIES + 1):
        cli_print(f"[calibrate] 第 {attempt}/{MAX_RETRIES} 次抽取…")
        try:
            candidate = extract_norms_from_report(report, issues, args.timeout)
        except Exception as exc:  # noqa: BLE001
            issues = [f"LLM 输出无法解析为 JSON:{exc}"]
            cli_print(f"[calibrate] 抽取失败:{exc}")
            continue
        issues = run_all_guards(candidate, probes)
        if not issues:
            norms = candidate
            cli_print(f"[calibrate] 第 {attempt} 次抽取通过全部护栏 ✓")
            break
        cli_print(f"[calibrate] 第 {attempt} 次未过护栏（{len(issues)} 项），将带报错重抽:")
        for x in issues:
            cli_print(f"    ✗ {x}")
        time.sleep(2)

    if norms is None:
        cli_print(f"[calibrate] {MAX_RETRIES} 次均未过护栏,放弃。**旧 {NORMS_PATH.name} 保持不动**,需人工检查报告/手填。")
        sys.exit(2)

    if args.dry_run:
        cli_print("[calibrate] dry-run:校验通过,但不写文件。抽取结果:")
        print(json.dumps(norms, ensure_ascii=False, indent=2))
        return

    # 原子覆写:先备份旧的,再写候选,全过才 replace
    NORMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if NORMS_PATH.exists():
        bak = NORMS_PATH.with_suffix(".json.bak")
        write_text(bak, read_text(NORMS_PATH))
        cli_print(f"[calibrate] 旧文件已备份 → {bak.name}")
    dump_json(NORMS_PATH, norms)  # dump_json 内部用 write_text 原子写
    cli_print(f"[calibrate] 已更新 {NORMS_PATH}（过全部护栏）。规划层下次跑即用上新书的结构分布。")


if __name__ == "__main__":
    main()

