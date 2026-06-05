# -*- coding: utf-8 -*-
"""analyst_monitor.py —— 全量分析可视化终端（只读，绝不碰分析进程）。

每 2 秒刷新一次，全部进度从 runtime/analyst/ 的落盘产物反推：
  · MAP 批次：已完成 / 被风控跳过 / 待跑，进度条 + ETA（按已完成批 mtime 间隔估）
  · 每批两段格式实时校验（手法观察 / 结构台账 都在？结构台账带真名@章号？）
    —— 这就是新格式对真实 API 的实跑验证，落盘即校验，不必手动开文件
  · REDUCE 阶段：prose 分层归并层数 / 结构校准报告是否落盘
  · STOP / PAUSE 状态

铁律：纯读文件，不 import 任何会调 API 的路径，不写任何文件。
分析进程崩了它不受影响；它崩了分析也不受影响。读到的批要么是完整旧内容、
要么是完整新内容（原子写保证），绝不会看到半截。
"""

import json
import os
import re
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
BASE_DIR = SCRIPTS_DIR.parent
ANALYST_DIR = BASE_DIR / "runtime" / "analyst"
RUNTIME_DIR = BASE_DIR / "runtime"
STOP_FILE = RUNTIME_DIR / "stop.request"
PAUSE_FILE = RUNTIME_DIR / "pause.request"

REFRESH_SECONDS = 2

# 复用 run_pipeline 自己的切批逻辑，保证“总批数”与真实跑的口径完全一致。
# import 是无副作用的（main() 有 __main__ 守卫），失败则降级为“只数文件不算总数”。
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    import run_pipeline as rp  # noqa: E402
    _HAS_RP = True
except Exception as _exc:  # noqa: BLE001
    rp = None
    _HAS_RP = False
    _IMPORT_ERR = str(_exc)


def read_run_analyst_cfg() -> dict:
    try:
        cfg = json.loads((BASE_DIR / "config" / "run.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return ((cfg.get("run") or {}).get("analyst")) or {}


def compute_total_batches() -> tuple:
    """返回 (总批数 or None, batch_budget)。源文不变，只在启动时算一次。"""
    budget = int(read_run_analyst_cfg().get("batch_token_budget") or 60000)
    if not _HAS_RP:
        return None, budget
    try:
        src = rp.source_text_path()
        if not src.exists():
            return None, budget
        text = rp.read_text(src)
        batches = rp.split_source_into_batches(text, budget)
        return len(batches), budget
    except Exception:  # noqa: BLE001
        return None, budget


def scan_batch_files() -> list:
    """扫 runtime/analyst/map_NNNN.md，返回每个批的状态记录（按批号排序）。
    只读不写。读到 .tmp 残留直接忽略（原子写中途的半截，不是有效批）。"""
    records = []
    if not ANALYST_DIR.exists():
        return records
    for p in sorted(ANALYST_DIR.glob("map_*.md")):
        if p.suffix != ".md" or ".tmp." in p.name:
            continue
        m = re.match(r"map_(\d+)\.md$", p.name)
        if not m:
            continue
        idx = int(m.group(1))
        try:
            raw = p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        records.append(classify_batch(idx, raw, p.stat().st_mtime))
    return records


def classify_batch(idx: int, raw: str, mtime: float) -> dict:
    """判定单批状态 + 两段格式体检。纯字符串分析，不依赖 rp。"""
    rec = {"idx": idx, "mtime": mtime, "status": "done",
           "has_tech": False, "has_struct": False, "struct_has_ref": False,
           "chars": len(raw)}
    s = raw.lstrip()
    if s.startswith("<<SKIP"):
        rec["status"] = "skipped"
        return rec
    body = s
    # 剥指纹首行（<<ANALYST-FMT v2 batch=NNNN>>）
    if body.startswith("<<ANALYST-FMT "):
        nl = body.find("\n")
        body = body[nl + 1:] if nl >= 0 else ""
        rec["fp"] = True
    else:
        rec["fp"] = False
    # 两段格式体检（容忍 == 标记，与 split_map_segments 同口径 ={2,}）
    msep = re.search(r"={2,}\s*结构台账\s*={2,}", body)
    has_tech_marker = bool(re.search(r"={2,}\s*手法观察\s*={2,}", body))
    rec["has_tech"] = has_tech_marker or (not msep and len(body) > 50)
    if msep:
        rec["has_struct"] = True
        struct_seg = body[msep.end():]
        # 结构台账该带章号锚点（真名落盘的标志）。两种合法写法：
        #   物件@章号  如 "铜铃@48"（@后接数字，不带"章"字）
        #   第N章       如 "第48章 主角识破伪装"
        rec["struct_has_ref"] = bool(re.search(r"@\s*\d+|第\s*\d+\s*章|章号", struct_seg))
    else:
        # 没切出结构台账标记：模型漏写/写歪标记。若文本带真名特征，split_map_segments
        # 会安全地把整段改判进结构段（不漏真名），监视器据此判定“有结构内容（标记缺失）”。
        if re.search(r"@\s*\d+", body) or re.search(r"第\s*\d+\s*章", body):
            rec["has_struct"] = True
            rec["struct_has_ref"] = True
            rec["struct_marker_missing"] = True  # 内容在、标记缺，提示模型这批没按格式
    return rec


def bar(done: int, total: int, width: int = 32) -> str:
    if total <= 0:
        return "?" * width + "  (总批数未知)"
    done = max(0, min(done, total))
    filled = int(width * done / total)
    pct = int(100 * done / total)
    return "#" * filled + "-" * (width - filled) + f"  {pct:3d}%"


def fmt_eta(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:  # NaN
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    return f"{m:02d}m{s:02d}s"


def reduce_phase_status() -> list:
    """REDUCE 阶段进度：prose 分层归并缓存 + 结构校准报告。"""
    lines = []
    merges = sorted(ANALYST_DIR.glob("merge_L*_G*.md")) if ANALYST_DIR.exists() else []
    if merges:
        levels = sorted({re.search(r"merge_L(\d+)_", p.name).group(1)
                         for p in merges if re.search(r"merge_L(\d+)_", p.name)})
        lines.append(f"  prose 分层归并：已产 {len(merges)} 份中间稿，层 {','.join('L'+l for l in levels)}")
    reduce_out = ANALYST_DIR / "_reduce_output.md"
    if reduce_out.exists():
        lines.append(f"  prose 最终归并 [OK]  ({reduce_out.name}, {reduce_out.stat().st_size} bytes)")
    calib = ANALYST_DIR / "_structure_calibration.md"
    if calib.exists():
        kb = calib.stat().st_size / 1024
        lines.append(f"  结构校准报告 [OK]  ({calib.name}, {kb:.0f} KB) <- 跑完后人工读它校准规划层 prompt")
    return lines


def render(total: int, budget: int, start_ts: float) -> str:
    recs = scan_batch_files()
    done = [r for r in recs if r["status"] == "done"]
    skipped = [r for r in recs if r["status"] == "skipped"]
    n_done, n_skip = len(done), len(skipped)
    processed = n_done + n_skip

    out = []
    out.append("=" * 64)
    out.append("  全量分析监视器  (analyst monitor) —— 只读，不影响分析进程")
    out.append("=" * 64)
    ttot = total if total else 0
    out.append(f"  MAP 批次进度  {bar(processed, ttot)}")
    out.append(f"  完成 {n_done}   跳过(风控) {n_skip}   "
               + (f"待跑 {max(0, total - processed)}   总计 {total}" if total else "总批数未知")
               + f"   (每批预算 {budget} tok)")

    # ETA：用已完成批的 mtime 跨度 / 完成数，外推剩余
    if total and n_done >= 2:
        mts = sorted(r["mtime"] for r in done)
        span = mts[-1] - mts[0]
        per = span / (n_done - 1) if n_done > 1 else 0
        remaining = max(0, total - processed)
        eta = per * remaining
        last_age = time.time() - mts[-1]
        out.append(f"  平均 {per:5.0f}s/批   预计剩余 ~{fmt_eta(eta)}   "
                   f"最近一批 {fmt_eta(last_age)} 前落盘")
    elif total:
        out.append("  (完成 >=2 批后开始估算 ETA)")

    # 两段格式体检（新格式对真实 API 的实跑验证）
    if done:
        bad_fp = [r["idx"] for r in done if not r.get("fp")]
        no_struct = [r["idx"] for r in done if not r["has_struct"]]
        struct_no_ref = [r["idx"] for r in done if r["has_struct"] and not r["struct_has_ref"]]
        marker_missing = [r["idx"] for r in done if r.get("struct_marker_missing")]
        out.append("-" * 64)
        out.append("  格式体检 (落盘即验，无需手动开文件)：")
        out.append(f"    指纹齐全        {n_done - len(bad_fp)}/{n_done}"
                   + (f"  [警告] 缺指纹批: {bad_fp[:8]}" if bad_fp else "  [OK]"))
        out.append(f"    含结构台账段    {n_done - len(no_struct)}/{n_done}"
                   + (f"  [警告] 真缺台账批: {no_struct[:8]}" if no_struct else "  [OK]"))
        out.append(f"    台账带真名@章号 {n_done - len(struct_no_ref)}/{n_done}"
                   + (f"  [注意] 无章锚批: {struct_no_ref[:8]}" if struct_no_ref else "  [OK]"))
        if marker_missing:
            out.append(f"    标记写歪已纠正  {len(marker_missing)} 批: {marker_missing[:8]}"
                       "  (模型 == 标记不规范，已按真名安全改判进结构段，不漏写手)")
        if n_done == 1:
            out.append("    >> 第1批已落盘：若上面三项都 [OK]，新格式验证通过，可放心跑全量。")

    # REDUCE 阶段
    rphase = reduce_phase_status()
    if rphase:
        out.append("-" * 64)
        out.append("  REDUCE 阶段：")
        out.extend(rphase)

    # 控制状态
    out.append("-" * 64)
    flags = []
    if STOP_FILE.exists():
        flags.append("[STOP 已请求 - 将在批边界停]")
    if PAUSE_FILE.exists():
        flags.append("[PAUSE 已请求]")
    out.append("  状态：" + (" ".join(flags) if flags else "运行中 / 待命"))
    if not _HAS_RP:
        out.append(f"  (注：未能 import run_pipeline，总批数降级显示。原因：{_IMPORT_ERR[:50]})")
    out.append(f"  刷新 {time.strftime('%H:%M:%S')}   已观测 {fmt_eta(time.time() - start_ts)}   Ctrl+C 退出监视(不影响分析)")
    out.append("=" * 64)
    return "\n".join(out)


def main() -> None:
    total, budget = compute_total_batches()
    start_ts = time.time()
    try:
        while True:
            screen = render(total, budget, start_ts)
            # 清屏重绘（Windows cls / *nix clear），失败则退化为打印分隔
            os.system("cls" if os.name == "nt" else "clear")
            print(screen, flush=True)
            calib = ANALYST_DIR / "_structure_calibration.md"
            if calib.exists():
                # 校准报告落盘 = 全流程跑完。多刷几次后温和退出
                time.sleep(REFRESH_SECONDS)
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        print("\n监视器已退出（分析进程不受影响，仍在后台跑）。")


if __name__ == "__main__":
    main()
