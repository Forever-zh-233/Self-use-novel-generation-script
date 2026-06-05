# -*- coding: utf-8 -*-
"""Phase 1: Map — 从每章正文提取结构化 fact sheet。"""

import hashlib
import json
import os
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from .llm import BASE_DIR, call_llm, parse_json_response

FACTS_DIR = BASE_DIR / "consistency" / "facts"
ARTICLE_DIR = BASE_DIR / "输出" / "文章"
BEATS_DIR = BASE_DIR / "beats"
PROMPTS_DIR = Path(__file__).parent / "prompts"

FINGERPRINT = "<<CONSISTENCY-MAP v1>>"
ROLE = "consistency_mapper"


def fact_path(chapter: int) -> Path:
    return FACTS_DIR / f"chapter_{chapter:03d}.json"


def _text_hash(text: str) -> str:
    """正文内容哈希。用于判断章节是否被重写。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def _manuscript_path(chapter: int) -> Path:
    return ARTICLE_DIR / f"第{chapter:03d}章.md"


def _load_beat_slim(chapter: int) -> Dict[str, Any]:
    """加载 beat 精简版：只取 Map 需要的字段。"""
    beat_file = BEATS_DIR / f"chapter_{chapter}.json"
    if not beat_file.exists():
        return {}
    try:
        with open(beat_file, encoding="utf-8") as f:
            beat = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        "视角角色": beat.get("视角角色", "沈安"),
        "时间锚点": beat.get("时间锚点", ""),
        "叙事手法": beat.get("叙事手法", "顺叙"),
        "出场角色": beat.get("出场角色", []),
        "场景类型": beat.get("场景类型", ""),
    }


def _load_map_prompt() -> str:
    prompt_file = PROMPTS_DIR / "map_agent.md"
    return _read_text(prompt_file)


def _read_fingerprint(path: Path) -> Optional[str]:
    """读取 fact sheet 首行的指纹行，返回原始字符串（不含 '// '）。不存在返回 None。"""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            first_line = f.readline().strip()
        if first_line.startswith("// "):
            return first_line[3:]
        return None
    except OSError:
        return None


def _fact_valid(chapter: int, current_text: str) -> bool:
    """检查已有 fact sheet 是否仍然有效。

    有效条件：指纹版本匹配 AND 内容哈希匹配当前正文。
    内容哈希不匹配 = 文章被重写/重生成 → 缓存失效，需重跑。
    """
    fp = _read_fingerprint(fact_path(chapter))
    if fp is None:
        return False
    # 指纹格式: "<<CONSISTENCY-MAP v1>> hash=<16hex>"
    if not fp.startswith(FINGERPRINT):
        return False
    m = re.search(r"hash=([0-9a-f]+)", fp)
    if not m:
        return False  # 旧格式无哈希，视为失效（强制重跑）
    return m.group(1) == _text_hash(current_text)


def _save_fact(chapter: int, data: Dict[str, Any], text_hash: str):
    """原子写入 fact sheet，指纹行嵌入正文内容哈希。"""
    FACTS_DIR.mkdir(parents=True, exist_ok=True)
    path = fact_path(chapter)
    content = f"// {FINGERPRINT} hash={text_hash}\n" + json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(str(tmp), str(path))


def load_fact(chapter: int) -> Optional[Dict[str, Any]]:
    """加载 fact sheet（仅供 Check/Report 读取，不校验正文哈希）。

    Check 阶段读取的是 Map 阶段已落盘的结果，此时正文哈希校验已在 Map 阶段做过。
    这里只校验指纹版本，读出 JSON 主体。
    """
    path = fact_path(chapter)
    fp = _read_fingerprint(path)
    if fp is None or not fp.startswith(FINGERPRINT):
        return None
    try:
        text = path.read_text(encoding="utf-8")
        json_start = text.find("\n")
        if json_start < 0:
            return None
        return json.loads(text[json_start + 1:])
    except (json.JSONDecodeError, OSError):
        return None


def map_one_chapter(chapter: int, timeout: int = 180) -> Dict[str, Any]:
    """为一章提取 fact sheet。若已有缓存且正文未变则跳过。"""
    manuscript = _manuscript_path(chapter)
    if not manuscript.exists():
        raise FileNotFoundError(f"第{chapter}章正文不存在: {manuscript}")

    text = _read_text(manuscript)
    if len(text) < 100:
        raise ValueError(f"第{chapter}章正文过短({len(text)}字)")

    text_hash = _text_hash(text)

    # 缓存有效（正文哈希匹配）且解析成功则直接复用
    if _fact_valid(chapter, text):
        cached = load_fact(chapter)
        if cached and not cached.get("_parse_error"):
            return cached

    beat_slim = _load_beat_slim(chapter)
    system_prompt = _load_map_prompt()

    user_input = f"## Beat 信息\n```json\n{json.dumps(beat_slim, ensure_ascii=False)}\n```\n\n## 正文\n{text}"

    # 截断重试：fact sheet 字段多，初始预算 8000；若被 max_tokens 截断则加倍再试，最多到 16000
    budget = 8000
    raw = ""
    for attempt in range(3):
        raw, finish_reason = call_llm(
            ROLE, system_prompt, user_input,
            max_tokens=budget, timeout=timeout, return_finish_reason=True,
        )
        if finish_reason != "length":
            break  # 正常完成，没被截断
        if budget >= 16000:
            break  # 已到上限，接受现状
        budget = min(budget * 2, 16000)

    try:
        data = parse_json_response(raw)
    except (json.JSONDecodeError, ValueError):
        # 解析失败时保留完整原始输出，便于排查（不再截到500字符）
        data = {"chapter": chapter, "_parse_error": True, "_raw": raw}

    data.setdefault("chapter", chapter)
    _save_fact(chapter, data, text_hash)
    return data


def _needs_map(chapter: int) -> bool:
    """判断某章是否需要（重新）跑 Map。"""
    manuscript = _manuscript_path(chapter)
    if not manuscript.exists():
        return False
    if not _fact_valid(chapter, _read_text(manuscript)):
        return True
    # 哈希匹配但解析失败的也要重跑
    cached = load_fact(chapter)
    return cached is None or bool(cached.get("_parse_error"))


def run_map_phase(
    chapters: List[int],
    concurrency: int = 4,
    timeout: int = 180,
    dry_run: bool = False,
) -> Dict[int, Dict[str, Any]]:
    """批量运行 Map 阶段。返回 {chapter: fact_sheet}。"""
    FACTS_DIR.mkdir(parents=True, exist_ok=True)
    results: Dict[int, Dict[str, Any]] = {}

    # 过滤出有正文的章节
    valid_chapters = [ch for ch in chapters if _manuscript_path(ch).exists()]

    if dry_run:
        to_run = [ch for ch in valid_chapters if _needs_map(ch)]
        skipped = len(valid_chapters) - len(to_run)
        rewritten = [ch for ch in to_run if fact_path(ch).exists()]
        est_tokens = len(to_run) * 6500  # ~4000 input + ~2500 output
        print(f"[dry-run] 共 {len(valid_chapters)} 章，缓存命中 {skipped} 章，需跑 {len(to_run)} 章")
        if rewritten:
            print(f"[dry-run] 其中 {len(rewritten)} 章正文已变更需重跑: {rewritten}")
        print(f"[dry-run] 预估消耗: ~{est_tokens:,} tokens ≈ ${est_tokens * 0.000008:.2f}")
        return results

    # 清理陈旧 fact sheet：正文已删除的章节，其缓存作废（防止删档重生成后乱分析）。
    # 基于全局所有存在的正文判断，不受 --chapters 范围影响。
    purge_orphan_facts()

    # 分流：缓存命中的直接读出，正文变更/新增的进待跑队列
    to_run = [ch for ch in valid_chapters if _needs_map(ch)]
    cached = [ch for ch in valid_chapters if ch not in to_run]
    for ch in cached:
        f = load_fact(ch)
        if f:
            results[ch] = f
    if cached:
        print(f"  缓存命中 {len(cached)} 章，跳过")
    if not to_run:
        print(f"\n  Map 完成: 全部 {len(results)} 章已是最新")
        return results
    rewritten = [ch for ch in to_run if fact_path(ch).exists()]
    if rewritten:
        print(f"  检测到 {len(rewritten)} 章正文已变更，将重跑: {rewritten}")
    print(f"  需跑 {len(to_run)} 章")

    # Canary: 先跑待跑队列的第一章确认 prompt 正常
    first = to_run[0]
    print(f"  [canary] 第{first}章...")
    try:
        results[first] = map_one_chapter(first, timeout)
        print(f"  [canary] 第{first}章完成")
    except Exception as e:
        print(f"  [canary] 第{first}章失败: {e}")
        raise RuntimeError(f"Canary 失败，中止 Map 阶段: {e}")
    time.sleep(1)

    # 并行处理剩余待跑章节
    remaining = [ch for ch in to_run if ch != first]
    failed = []

    def _worker(ch: int) -> tuple:
        try:
            data = map_one_chapter(ch, timeout)
            return ch, data, None
        except Exception as e:
            return ch, None, str(e)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_worker, ch): ch for ch in remaining}
        for future in as_completed(futures):
            ch, data, error = future.result()
            if error:
                print(f"  [FAIL] 第{ch}章: {error}")
                failed.append(ch)
            else:
                if data and not data.get("_parse_error"):
                    print(f"  [OK] 第{ch}章")
                elif data and data.get("_parse_error"):
                    print(f"  [WARN] 第{ch}章: JSON 解析失败，下次 map 自动重跑")
                results[ch] = data

    if failed:
        print(f"\n  共 {len(failed)} 章失败: {failed}")
    print(f"\n  Map 完成: {len(results)} 章可用（本次新跑 {len(to_run)} 章）")

    # 自动检测 _parse_error 并重跑（最多1轮，JSON截断用更高 token 预算重试）
    _retry_parse_errors(timeout)
    return results


def _retry_parse_errors(timeout: int = 180):
    """扫描所有 _parse_error=True 的 fact sheet，删掉重跑。"""
    if not FACTS_DIR.exists():
        return
    bad = []
    for p in FACTS_DIR.glob("chapter_*.json"):
        try:
            text = p.read_text(encoding="utf-8")
            json_start = text.find("\n")
            data = json.loads(text[json_start + 1:] if json_start >= 0 else text)
            if data.get("_parse_error"):
                bad.append(int(p.stem.replace("chapter_", "")))
        except Exception:
            pass
    if not bad:
        return
    print(f"\n  检测到 {len(bad)} 章 JSON 解析失败，删除后重跑: {sorted(bad)}")
    for ch in bad:
        fact_path(ch).unlink(missing_ok=True)
    # 串行重跑（失败章节通常只有几章，避免并发掩盖错误）
    for ch in sorted(bad):
        try:
            map_one_chapter(ch, timeout)
            f = load_fact(ch)
            if f and not f.get("_parse_error"):
                print(f"  [RETRY-OK] 第{ch}章")
            else:
                print(f"  [RETRY-FAIL] 第{ch}章: 仍有问题")
        except Exception as e:
            print(f"  [RETRY-ERR] 第{ch}章: {e}")


def purge_orphan_facts() -> List[int]:
    """删除正文已不存在的章节对应的 fact sheet。返回被清理的章节号列表。

    场景：用户删了第101-130章重新只生成到第100章，旧的 101-130 fact sheet
    必须清掉，否则 Check 阶段会把不存在的章节也算进去。

    基于全局所有存在的正文判断（扫整个文章目录），不受 --chapters 范围限制——
    否则跑 `--chapters 101-109` 会误删 1-100 的缓存。
    """
    purged = []
    if not FACTS_DIR.exists():
        return purged
    # 全局现存正文章节
    existing = set()
    for p in ARTICLE_DIR.glob("第*章.md"):
        stem = p.stem.replace("第", "").replace("章", "")
        if stem.isdigit():
            existing.add(int(stem))
    for p in FACTS_DIR.glob("chapter_*.json"):
        stem = p.stem.replace("chapter_", "")
        if not stem.isdigit():
            continue
        ch = int(stem)
        if ch not in existing:
            try:
                p.unlink()
                purged.append(ch)
            except OSError:
                pass
    if purged:
        print(f"  清理已删除章节的陈旧 fact sheet: {sorted(purged)}")
    return purged
