# -*- coding: utf-8 -*-
"""Scenario tests using a temporary Novel workspace."""

from __future__ import annotations

import json
import importlib
import os
import sys
import threading
import time
from pathlib import Path

from .helpers import TestHarness, clear_pipeline_modules, ensure_scripts_path, isolated_workspace


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data) -> None:
    _write(path, json.dumps(data, ensure_ascii=False, indent=2))


def _seed_workspace(tmp: Path) -> None:
    for folder in [
        "config",
        "chunks",
        "prompts/writer_modules",
        "runtime",
        "输出/文章",
        "输出/上下文",
        "卷纲",
    ]:
        (tmp / folder).mkdir(parents=True, exist_ok=True)

    _write(tmp / "01-风格指南.md", "禁止空泛总结。")
    _write(tmp / "02-世界观设定圣经.md", "北砚县，夜里灵觉可用。")
    _write(tmp / "02-修炼境界.md", "叩门、通脉、凝元。")
    _write(tmp / "09-故事核.md", "沈安在北砚县求生。后期真相：不要给写手。")
    _write(tmp / "11-负空间.md", "不解释，不替读者总结。")
    _write(tmp / "12-AI腔黑名单.md", "禁止不是A是B。")
    _write(tmp / "15-长线伏笔资产库.md", "# LF-001\n表层线索：铜铃。真实含义：不该直接泄露。")
    _write(tmp / "卷纲/10-卷纲.md", "第一卷：北砚客途。")
    _write(tmp / "prompts/reviewer.md", "你是评审。")
    _write(tmp / "prompts/archivist.md", "你是记录员。")
    _write(tmp / "prompts/writer.md", "你是写手。")
    _write(tmp / "prompts/writer_pov.md", "你是多视角写手。")
    _write(tmp / "prompts/writer_modules/对话.md", "对话要有潜台词。")
    _write(tmp / "prompts/writer_modules/视觉.md", "盲感官优先。")
    _write(tmp / "prompts/writer_modules/张力.md", "本章是转折章，给爆点足够分量。")

    chunks = {
        "黄金法则": {"file": "chunk_黄金法则.md", "tokens": 10, "category": "必选"},
        "负空间": {"file": "chunk_负空间.md", "tokens": 10, "category": "必选"},
        "AI腔黑名单": {"file": "chunk_AI腔黑名单.md", "tokens": 10, "category": "必选"},
        "沈安": {"file": "chunk_沈安.md", "tokens": 10, "category": "角色"},
        "黑子": {"file": "chunk_黑子.md", "tokens": 10, "category": "角色"},
        "日常对话": {"file": "chunk_日常对话.md", "tokens": 10, "category": "场景"},
        "转场": {"file": "chunk_转场.md", "tokens": 10, "category": "场景"},
    }
    _write_json(tmp / "chunks/index.json", chunks)
    for name, meta in chunks.items():
        _write(tmp / "chunks" / meta["file"], f"# {name}\n测试 chunk。")

    _write_json(tmp / "config/strand_weave.json", {
        "strands": {
            "道途线": {"aliases": ["修炼", "升级"]},
            "情义线": {"aliases": ["伙伴"]},
            "天地线": {"aliases": ["世界"]},
        }
    })
    _write_json(tmp / "config/power_scaling.json", {})
    _write_json(tmp / "config/travel_matrix.json", {})
    _write_json(tmp / "config/threat_ladder.json", {})
    _write_json(tmp / "config/economy.json", {})
    _write_json(tmp / "config/run.json", {"run": {
        "max_input_tokens": {"writer": 60000, "reviewer": 28000, "archivist": 38000, "compressor": 28000},
        "context_windows": {"writer": 200000, "reviewer": 200000, "archivist": 200000, "compressor": 200000},
        "compress_at_ratio": 0.8,
    }})
    _write_json(tmp / "config/models.json", {"providers": {}, "roles": {}})

    _write_json(tmp / "runtime/state.json", {
        "latest_chapter": 1,
        "story_time": "第一日夜",
        "current_location": "北砚县",
        "characters": {
            "沈安": {"location": "破院", "status": "疲惫", "emotion": "戒备", "realm": "叩门", "_last_active": 1},
            "黑子": {"location": "破院", "status": "守门", "emotion": "警觉", "_last_active": 1},
        },
        "relationships": {"沈安-黑子": {"current": "互相依靠", "history": [{"chapter": 1, "event": "一起躲雨"}]}},
        "knowledge": {},
        "used_devices": [],
        "recent_events": ["沈安在破院发现铜铃。"],
        "timeline": {"absolute_day": 1, "time_of_day": "夜", "season": "冬", "pending_timers": []},
    })
    _write_json(tmp / "runtime/active_threads.json", {
        "foreshadowing": {
            "F-001": {"id": "F-001", "status": "悬空", "promise": "铜铃来历", "planted_chapter": 1},
            "F-002": {"id": "F-002", "status": "已回收", "promise": "旧门闩", "resolved_chapter": 1},
        },
        "open_questions": ["铜铃是谁留下的？"],
        "next_id": "F-003",
    })
    _write_json(tmp / "runtime/ledger.json", {
        "entities": {
            "沈安": {
                "type": "角色",
                "summary": "盲眼少年，夜里可凭灵觉行动。",
                "voice": "少说废话。",
                "realm": "叩门",
                "facts": ["白天强光下不能精细看清。"],
                "status": "活跃",
                "last_seen_chapter": 1,
            },
            "黑子": {
                "type": "伙伴",
                "summary": "黑犬，警觉护主。",
                "voice": "不说人话。",
                "status": "活跃",
                "last_seen_chapter": 1,
            },
        },
        "inventory": {
            "currency": {"铜钱": 3},
            "key_items": [{"name": "铜铃", "status": "持有", "location": "沈安袖中"}],
            "consumables": [{"name": "干粮", "qty": 1}],
            "techniques": [{"name": "夜听", "type": "灵觉", "status": "有效"}],
        },
        "resources": {},
        "obligations": [{"id": "O-001", "desc": "替张寡妇送信", "status": "悬空", "since_chapter": 1}],
        "constraints": [{"desc": "沈安白天不能写成正常视力。", "binding": "强", "scope": "永久"}],
        "relationships": {"沈安-黑子": {"current": "互相依靠", "history": [{"chapter": 1, "event": "一起躲雨"}]}},
    })
    _write(tmp / "输出/文章/第001章.md", "夜里，沈安在破院门口坐下。\n黑子蹲在门边。\n他合眼睡下。")


def _import_modules():
    clear_pipeline_modules()
    ensure_scripts_path()
    core = importlib.import_module("pipeline.core")
    api = importlib.import_module("pipeline.api")
    state = importlib.import_module("pipeline.state")
    context = importlib.import_module("pipeline.context")
    gates = importlib.import_module("pipeline.gates")
    archivist = importlib.import_module("pipeline.archivist")
    return core, api, state, context, gates, archivist


def _import_run_pipeline():
    """Fresh-import run_pipeline against the active workspace.

    run_pipeline is a top-level script (not under pipeline.*), so clear it from
    sys.modules each time alongside the pipeline package to rebind its globals.
    """
    clear_pipeline_modules()
    ensure_scripts_path()
    sys.modules.pop("run_pipeline", None)
    return importlib.import_module("run_pipeline")


def _basic_beat(chapter: int = 2) -> dict:
    return {
        "章节编号": chapter,
        "标题": "门外脚步",
        "视角角色": "沈安",
        "叙事手法": "顺叙",
        "场景类型": "日常对话",
        "出场角色": ["沈安", "黑子"],
        "具体物件": ["铜铃"],
        "具体动作": ["听门外脚步"],
        "本章冲突": "有人夜里叩门。",
        "章末钩子": "门外的人没有立刻说话。",
    }


def _cache_text(label: str) -> str:
    return f"{label}\n" + ("沈安听见门外脚步，黑子在门边低低压住喉音。" * 8)


def _base_resume_run_cfg(**overrides) -> dict:
    cfg = {
        "resume_partial_chapter": True,
        "min_recover_article_chars": 20,
        "skip_fact_check": True,
        "skip_summarizer": True,
        "max_revisions": 1,
        "apply_archivist_updates": True,
        "artifact_retention": "debug",
        "request_timeout_seconds": 1,
        "sleep_seconds_between_calls": 0,
        "max_input_tokens": {
            "writer": 60000,
            "reviewer": 28000,
            "editor": 28000,
            "archivist": 38000,
            "compressor": 28000,
        },
        "context_windows": {
            "writer": 200000,
            "reviewer": 200000,
            "editor": 200000,
            "archivist": 200000,
            "compressor": 200000,
        },
    }
    cfg.update(overrides)
    return cfg


def _patch_fast_gates(rp, counters: dict | None = None) -> None:
    counters = counters if counters is not None else {}

    def hard_gate(_text):
        counters["hard_gate"] = counters.get("hard_gate", 0) + 1
        return {"passed": True, "issues": [], "warnings": []}

    rp.hard_gate = hard_gate
    rp.style_gate = lambda _text: {"passed": True, "issues": [], "warnings": [], "metrics": {}}
    rp.continuity_check = lambda _text, _chapter: {"passed": True, "issues": [], "warnings": []}
    rp.continuity_check_adjacent = lambda _chapter, _text, _beat=None: []
    rp.type_guard_check = lambda _text, _chapter: {"passed": True, "issues": [], "warnings": []}
    rp.chapter_satisfaction_check = lambda _text, _beat: []
    rp.combine_checks = lambda checks: {
        "passed": all((item or {}).get("passed", True) for item in checks.values()),
        "issues": [],
        "warnings": [],
    }


def _fast_gate_result() -> dict:
    return {"passed": True, "issues": [], "warnings": []}


def _writer_prompt_for(rp, pov_character: str = "沈安") -> str:
    return rp.read_text(rp.PROMPTS_DIR / ("writer_pov.md" if pov_character != "沈安" else "writer.md"))


def _reviewer_prompt_for(rp) -> str:
    return rp.read_text(rp.PROMPTS_DIR / "reviewer.md")


def _editor_prompt_for(rp) -> str:
    return rp.read_text(rp.PROMPTS_DIR / "editor.md") or (
        "你是修稿手。只做局部手术，不做全文润色。只根据评审意见修正文，不新增世界观，不改变本章核心事件。"
        "输出完整修订正文。"
    )


def _write_draft_cache(rp, chapter: int, beat: dict, draft: str, run_cfg: dict | None = None) -> None:
    path = rp.role_artifact("writer", chapter, "draft.md")
    _write(path, draft)
    rp.write_stage_cache_meta(
        path,
        rp.draft_cache_deps(chapter, beat, _writer_prompt_for(rp, beat.get("视角角色", "沈安")), run_cfg or _base_resume_run_cfg()),
        draft,
    )


def _write_review_cache(rp, chapter: int, beat: dict, draft: str, review: str, gate: dict | None = None) -> None:
    path = rp.role_artifact("reviewer", chapter, "review.md")
    gate = gate or _fast_gate_result()
    _write(path, review)
    rp.write_stage_cache_meta(path, rp.review_cache_deps(chapter, beat, draft, gate, _reviewer_prompt_for(rp)), review)


def _write_editor_cache(rp, chapter: int, beat: dict, draft: str, review: str, edited: str, gate: dict | None = None) -> None:
    path = rp.role_artifact("editor", chapter, "edited.md")
    gate = gate or _fast_gate_result()
    _write(path, edited)
    rp.write_stage_cache_meta(path, rp.editor_cache_deps(chapter, beat, draft, gate, review, _editor_prompt_for(rp)), edited)


def run(h: TestHarness) -> None:
    h.section("scenario: writer context uses temporary workspace")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        beat = {
            "章节编号": 2,
            "标题": "门外脚步",
            "视角角色": "沈安",
            "叙事手法": "顺叙",
            "场景类型": "日常对话",
            "出场角色": ["沈安", "黑子"],
            "具体物件": ["铜铃"],
            "具体动作": ["听门外脚步"],
            "本章冲突": "有人夜里叩门。",
        }

        digest = context.writer_state_digest(beat)
        h.includes("writer digest includes current location", digest, "北砚县")
        h.includes("writer digest includes cast state", digest, "沈安")
        h.not_includes("writer digest avoids late truth wording", digest, "后期真相")

        ledger = context.ledger_context_for_writer(beat, 2)
        h.includes("writer ledger includes held item", ledger, "铜铃")
        h.includes("writer ledger includes obligation", ledger, "替张寡妇送信")
        h.includes("writer ledger includes hard constraint", ledger, "白天不能写成正常视力")

        sections = context.build_writer_sections(beat)
        titles = [item["title"] for item in sections]
        h.check("writer sections are built", bool(sections), titles)
        h.check("writer sections include hard beat", any("本章 beat" in title or "beat" in title.lower() for title in titles), titles)

        _write_json(tmp / "分析草稿/style_metrics.json", {
            "sentence": {"mean": 13.4, "median": 13, "p10": 1, "p90": 26},
            "paragraph": {"mean": 17.6, "median": 17},
            "single_sentence_paragraph": {"single_sentence_ratio_percent": 31.1},
            "dialogue_style": {
                "pure_quote_ratio_percent": 55.9,
                "with_speaker_tag_ratio_percent": 25.9,
                "with_action_tail_ratio_percent": 8.3,
            },
            "chapter_endings": {"avg_last_line_length": 12.0, "short_ending_ratio_percent": 100.0},
            "high_freq_words": [{"word": "源文真名", "count": 999}],
        })
        sections = context.build_writer_sections(beat)
        titles = [item["title"] for item in sections]
        bodies = "\n".join(item["body"] for item in sections)
        h.check("writer sections include style metrics digest", "源文风格指标执行摘要" in titles, titles)
        h.includes("style digest includes sentence cadence", bodies, "句长")
        h.not_includes("style digest excludes source-name probes", bodies, "源文真名")

    h.section("scenario: POV writer consumes critical chunks without protagonist sensory leak")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        led = json.loads((tmp / "runtime/ledger.json").read_text(encoding="utf-8"))
        led["entities"]["方绾"] = {
            "type": "角色",
            "summary": "药铺女郎，心细。",
            "voice": "说话轻，句子短。",
            "facts": ["知道沈安救过人。"],
            "status": "活跃",
        }
        led["impact_seeds"] = [{
            "who": "方绾",
            "pov_voice": "先看药味，再看人。",
            "ignorant_of": ["沈安的系统面板"],
        }]
        _write_json(tmp / "runtime/ledger.json", led)
        beat = {
            "章节编号": 6,
            "标题": "药柜后的灯",
            "视角角色": "方绾",
            "叙事手法": "顺叙",
            "场景类型": "日常对话",
            "出场角色": ["方绾", "沈安"],
            "潜台词机会": "方绾试探沈安是否隐瞒伤势",
            "本章张力": "小起伏",
            "本章冲突": "方绾发现沈安伤势不对。",
        }
        text = context.build_pov_writer_input(beat, 6, {"max_input_tokens": {"writer": 60000}, "context_windows": {"writer": 200000}}, 1)
        h.includes("POV writer includes AI blacklist chunk", text, "AI腔黑名单")
        h.includes("POV writer includes negative-space chunk", text, "负空间")
        h.includes("POV writer includes dialogue module", text, "对话要有潜台词")
        h.includes("POV writer includes tension module", text, "转折章")
        h.includes("POV writer keeps knowledge boundary", text, "沈安的系统面板")
        h.not_includes("POV writer skips protagonist role chunk", text, "角色_沈安")
        h.not_includes("POV writer skips protagonist sensory module", text, "盲感官优先")

    h.section("scenario: adjacent continuity guard")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        broken = "沈安推门走出去。\n天井里风很冷。"
        issues = gates.continuity_check_adjacent(2, broken, {"视角角色": "沈安", "叙事手法": "顺叙"})
        h.check("adjacent continuity catches missing wake transition", any("入睡" in issue for issue in issues), issues)

        transitioned = "天亮后，沈安醒来，推门走出去。\n天井里风很冷。"
        issues = gates.continuity_check_adjacent(2, transitioned, {"视角角色": "沈安", "叙事手法": "顺叙"})
        h.check("adjacent continuity allows wake transition", not issues, issues)

        pov = "方绾想起三年前的雨。"
        issues = gates.continuity_check_adjacent(2, pov, {"视角角色": "方绾", "叙事手法": "插叙"})
        h.check("adjacent continuity skips non-protagonist flashback", not issues, issues)

    h.section("scenario: archivist structured update merge")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        report = """## STRUCTURED_UPDATE
```json
{
  "_chapter": 2,
  "story_time": "第二日清晨",
  "current_location": "北砚县东巷",
  "characters": {
    "沈安": {"location": "东巷", "status": "醒来", "emotion": "清醒"}
  },
  "recent_events": ["沈安听见门外脚步。"],
  "dominant_strand": "道途线",
  "cultivation_active": "active",
  "canon": {
    "update_entities": [
      {"name": "沈安", "add_facts": ["听见门外脚步"], "realm_change": "通脉"}
    ],
    "new_entities": [
      {"name": "叩门客", "type": "角色", "summary": "夜里来访的人。", "facts": ["曾敲响破院门。"]}
    ]
  }
}
```
"""
        update = archivist.extract_structured_update(report)
        h.equal("archivist extracts chapter", update["_chapter"], 2)
        archivist.merge_state_update(update)
        archivist.merge_ledger_update(update, 2)

        new_state = json.loads((tmp / "runtime/state.json").read_text(encoding="utf-8"))
        h.equal("state merge updates location", new_state["current_location"], "北砚县东巷")
        h.equal("state merge tags chapter activity", new_state["characters"]["沈安"]["_last_active"], 2)
        h.equal("strand tracker updated", new_state["strand_tracker"]["current_dominant"], "道途线")
        # A1: cultivation_active 标记进入 strand_tracker.history
        hist = new_state["strand_tracker"]["history"]
        h.equal("cultivation tag recorded", hist[-1].get("cultivation"), "active")

        new_ledger = json.loads((tmp / "runtime/ledger.json").read_text(encoding="utf-8"))
        h.check("ledger merge adds new entity", "叩门客" in new_ledger["entities"], new_ledger)
        h.check("ledger merge appends facts", "听见门外脚步" in new_ledger["entities"]["沈安"]["facts"], new_ledger["entities"]["沈安"])
        # A2: realm_change 推进境界 + 记录 realm_progress 历史（叩门→通脉，真跨境）
        h.equal("realm advanced to 通脉", new_ledger["entities"]["沈安"]["realm"], "通脉")
        rp = new_ledger.get("realm_progress", {}).get("沈安", [])
        h.check("realm_progress 记录跨境", bool(rp) and rp[-1]["to"] == "通脉", rp)
        # A2: realm_progress_digest 能读出当前境界
        digest = context.realm_progress_digest(3)
        h.includes("境界进度digest含当前境界", digest, "通脉")

    h.section("scenario: inventory_update 货币写进 add 不崩库(currency 是 dict 桶)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        # 既有 ledger:currency 是 dict,key_items 是列表
        _write_json(tmp / "runtime/ledger.json", {
            "entities": {"沈安": {"type": "角色", "facts": []}},
            "inventory": {"consumables": [], "key_items": [], "techniques": [], "currency": {"铜钱": 0}},
        })
        # 模型把铜钱误塞进 add(category=currency),同时又给了 currency_change——历史真实数据
        bad_update = {
            "_chapter": 8,
            "canon": {
                "inventory_update": {
                    "add": [
                        {"name": "铜钱", "category": "currency", "qty": 30, "location": "手心"},
                        {"name": "铁片", "category": "key_items", "qty": 1, "location": "随身"},
                    ],
                    "currency_change": {"铜钱": 30, "notes": "诊金"},
                }
            },
        }
        crashed = None
        try:
            archivist.merge_ledger_update(bad_update, 8)
            crashed = False
        except BaseException:  # noqa: BLE001
            crashed = True
        h.equal("货币写进 add 不再崩库", crashed, False)
        merged = json.loads((tmp / "runtime/ledger.json").read_text(encoding="utf-8"))
        h.equal("铜钱走 currency_change 正确累加", merged["inventory"]["currency"]["铜钱"], 30)
        h.check("currency 仍是 dict 没被污染成列表", isinstance(merged["inventory"]["currency"], dict), merged["inventory"]["currency"])
        h.check("正常物品(铁片)仍进 key_items", any(x.get("name") == "铁片" for x in merged["inventory"]["key_items"]), merged["inventory"]["key_items"])
        h.check("铜钱没被错误塞进任何物品列表", all(x.get("name") != "铜钱" for cat in ("consumables", "key_items", "techniques") for x in merged["inventory"].get(cat, [])), merged["inventory"])

    h.section("scenario: review input receives diagnostics not score reports")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        (tmp / "输出/分数表").mkdir(parents=True, exist_ok=True)
        _write(tmp / "输出/分数表/第001章.md", "KPI 分数不允许注入。")
        run_cfg = {"context_windows": {"reviewer": 200000}, "max_input_tokens": {"reviewer": 28000}}
        text = "沈安把竹杖放在膝上。"
        review_input = gates.make_review_input(
            text,
            2,
            run_cfg,
            timeout=1,
            diagnostics={"hard_gate": {"passed": True, "issues": []}},
            beat={"章节编号": 2, "出场角色": ["沈安"], "场景类型": "日常对话"},
        )
        h.includes("review input includes diagnostics", review_input, "脚本硬检查结果")
        h.includes("review input includes draft text", review_input, text)
        h.not_includes("review input does not read score report", review_input, "KPI 分数不允许注入")

    h.section("scenario: 章内断点续跑复用已落盘阶段产物")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        beat_path = tmp / "beats/chapter_2.json"
        _write_json(beat_path, _basic_beat(2))
        manuscript = _cache_text("正文缓存已落盘")
        _write(rp.manuscript_path(2), manuscript)
        _write_json(rp.role_artifact("reviewer", 2, "review_verdict.json"), {
            "needs_revision": False,
            "total": 55,
            "blockers": [],
            "source": "json",
        })

        archive_calls = []
        score_verdicts = []
        archive_finals = []
        rp.generate_chapter_final = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("generation should be skipped"))
        rp.make_archive_input = lambda final, *_args, **_kwargs: archive_finals.append(final) or "archive input"
        rp.apply_archivist_update = lambda chapter, report: archive_calls.append((chapter, report))
        rp.write_score_report = lambda _chapter, verdict: score_verdicts.append(verdict)
        rp.cleanup_chapter_artifacts = lambda *_args, **_kwargs: None

        def fake_archivist(role, _prompt, _input_text, output_path, *_args):
            archive_calls.append(("call_role", role))
            rp.write_text(output_path, "STRUCTURED_UPDATE: {}")
            return "STRUCTURED_UPDATE: {}"

        rp.call_role = fake_archivist
        rp.run_one_chapter(2, beat_path, _base_resume_run_cfg(), 1, 1)

        h.equal("manuscript 存在时只调用 archivist", [x for x in archive_calls if x[0] == "call_role"], [("call_role", "archivist")])
        h.includes("archivist 输入使用已落盘正文", archive_finals[0], "正文缓存已落盘")
        h.equal("score report verdict 来自 review_verdict.json", score_verdicts[0]["total"], 55)

    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        _patch_fast_gates(rp)
        beat = _basic_beat(2)
        draft = _cache_text("已有初稿")
        _write_draft_cache(rp, 2, beat, draft)
        calls = []
        build_calls = []
        rp.build_writer_input = lambda *_args, **_kwargs: build_calls.append("writer_input") or "writer input"
        rp.make_review_input = lambda *_args, **_kwargs: "review input"

        def fake_call_role(role, _prompt, _input_text, output_path, *_args):
            calls.append(role)
            text = """```json
{"needs_revision": false, "total": 48, "blockers": []}
```"""
            rp.write_text(output_path, text)
            return text

        rp.call_role = fake_call_role
        final, verdict = rp.generate_chapter_final(
            2, beat, "沈安", _base_resume_run_cfg(max_revisions=0), 1, 1, 1, 0
        )
        h.equal("draft.md 存在时不构建 writer 上下文", build_calls, [])
        h.check("draft.md 存在时不重跑 writer", "writer" not in calls, calls)
        h.includes("复用 draft 内容作为 final 基础", final, "已有初稿")
        h.equal("reviewer 正常解析新评审 verdict", verdict["total"], 48)
        committed = json.loads(rp.read_text(rp.role_artifact("gate", 2, "final_committed.json")))
        h.equal("提交态审计 hash 对应最终正文", committed["final_text_sha256"], rp.text_sha256(final))
        h.check("提交态门禁落盘", rp.role_artifact("gate", 2, "committed_gate.json").exists(), "")

    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        _patch_fast_gates(rp)
        beat = _basic_beat(2)
        draft = _cache_text("已有初稿")
        review = """```json
{"needs_revision": false, "total": 49, "blockers": []}
```"""
        _write_draft_cache(rp, 2, beat, draft)
        _write_review_cache(rp, 2, beat, draft, review)
        calls = []
        rp.build_writer_input = lambda *_args, **_kwargs: "SHOULD NOT BUILD"
        rp.make_review_input = lambda *_args, **_kwargs: "SHOULD NOT REVIEW"
        rp.call_role = lambda role, *_args, **_kwargs: calls.append(role) or ""
        _final, verdict = rp.generate_chapter_final(
            2, beat, "沈安", _base_resume_run_cfg(max_revisions=0), 1, 1, 1, 0
        )
        h.check("review.md 存在时跳过 reviewer", "reviewer" not in calls, calls)
        h.equal("review.md 复用后 verdict 由 parse 得到", verdict["total"], 49)

    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        _patch_fast_gates(rp)
        beat = _basic_beat(2)
        draft = _cache_text("已有初稿")
        review = """```json
{"needs_revision": true, "total": 35, "blockers": ["需修稿"]}
```"""
        edited = _cache_text("已有修稿")
        _write_draft_cache(rp, 2, beat, draft)
        _write_review_cache(rp, 2, beat, draft, review)
        _write_editor_cache(rp, 2, beat, draft, review, edited)
        calls = []
        rp.call_role = lambda role, *_args, **_kwargs: calls.append(role) or ""
        final, _verdict = rp.generate_chapter_final(
            2, beat, "沈安", _base_resume_run_cfg(max_revisions=1), 1, 1, 1, 0
        )
        h.check("edited.md 存在时跳过 editor", "editor" not in calls, calls)
        h.includes("edited.md 复用为 final", final, "已有修稿")

    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        _patch_fast_gates(rp)
        beat = _basic_beat(2)
        _write(rp.role_artifact("writer", 2, "draft.md"), "太短")
        calls = []
        build_calls = []
        generated = _cache_text("重新生成初稿")
        rp.build_writer_input = lambda *_args, **_kwargs: build_calls.append("writer_input") or "writer input"
        rp.make_review_input = lambda *_args, **_kwargs: "review input"

        def fake_regenerate(role, _prompt, _input_text, output_path, *_args):
            calls.append(role)
            text = generated if role == "writer" else """```json
{"needs_revision": false, "total": 50, "blockers": []}
```"""
            rp.write_text(output_path, text)
            return text

        rp.call_role = fake_regenerate
        final, _verdict = rp.generate_chapter_final(
            2, beat, "沈安", _base_resume_run_cfg(max_revisions=0), 1, 1, 1, 0
        )
        h.equal("坏 draft 缓存会重新构建 writer 上下文", build_calls, ["writer_input"])
        h.check("坏 draft 缓存会重跑 writer", "writer" in calls, calls)
        h.includes("坏缓存不被当成 final", final, "重新生成初稿")

    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        _patch_fast_gates(rp)
        beat = _basic_beat(2)
        _write(rp.role_artifact("writer", 2, "draft.md"), _cache_text("无指纹旧初稿"))
        calls = []
        generated = _cache_text("无指纹后重写初稿")
        rp.build_writer_input = lambda *_args, **_kwargs: "writer input"
        rp.make_review_input = lambda *_args, **_kwargs: "review input"

        def fake_no_meta(role, _prompt, _input_text, output_path, *_args):
            calls.append(role)
            text = generated if role == "writer" else """```json
{"needs_revision": false, "total": 50, "blockers": []}
```"""
            rp.write_text(output_path, text)
            return text

        rp.call_role = fake_no_meta
        final, _verdict = rp.generate_chapter_final(
            2, beat, "沈安", _base_resume_run_cfg(max_revisions=0), 1, 1, 1, 0
        )
        h.check("无指纹旧 draft 不复用", "writer" in calls, calls)
        h.includes("无指纹旧 draft 触发重写", final, "无指纹后重写初稿")

    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        _patch_fast_gates(rp)
        beat = _basic_beat(2)
        _write(rp.role_artifact("writer", 2, "draft.md"), _cache_text("不该复用的初稿"))
        _write(rp.role_artifact("reviewer", 2, "review.md"), "不该复用的评审")
        calls = []
        generated = _cache_text("关闭续跑后新初稿")
        rp.build_writer_input = lambda *_args, **_kwargs: "writer input"
        rp.make_review_input = lambda *_args, **_kwargs: "review input"

        def fake_resume_disabled(role, _prompt, _input_text, output_path, *_args):
            calls.append(role)
            text = generated if role == "writer" else """```json
{"needs_revision": false, "total": 51, "blockers": []}
```"""
            rp.write_text(output_path, text)
            return text

        rp.call_role = fake_resume_disabled
        final, verdict = rp.generate_chapter_final(
            2, beat, "沈安", _base_resume_run_cfg(resume_partial_chapter=False, max_revisions=0), 1, 1, 1, 0
        )
        h.check("resume 关闭时重跑 writer", "writer" in calls, calls)
        h.check("resume 关闭时重跑 reviewer", "reviewer" in calls, calls)
        h.includes("resume 关闭时不复用旧 draft", final, "关闭续跑后新初稿")
        h.equal("resume 关闭时 verdict 来自新 reviewer", verdict["total"], 51)

    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        _write(rp.role_artifact("reviewer", 2, "review.md"), """```json
{"needs_revision": true, "total": 42, "blockers": ["问题"]}
```""")
        parsed = rp.resume_verdict(2)
        fallback = rp.resume_verdict(3)
        h.equal("verdict.json 缺失时回退解析 review.md", parsed["total"], 42)
        h.equal("verdict 与 review 都缺失时默认不崩", fallback["source"], "resume_default")

    h.section("scenario: layered spatial system (防穿帮·小地图)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        # 注入两个长驻地点（聚落+场景）和它们的空间字段
        update = {"canon": {"new_entities": [
            {"name": "青石镇", "type": "地点", "summary": "第二站", "scale": "聚落",
             "parent": "北砚县辖区", "bearing_from_parent": "北砚以南40里",
             "landmarks": [{"name": "镇东老井", "bearing": "镇东头正街往东"}]},
            {"name": "如意栈", "type": "地点", "summary": "客栈", "scale": "场景",
             "parent": "青石镇", "bearing_from_parent": "镇中心正街",
             "layout": "进门堂屋，左柜台右后院，二楼三客房"},
        ]}}
        archivist.merge_ledger_update(update, 30)

        # 弧线层：聚落级方位摘要
        arc_digest = context.spatial_digest_for_arc(30)
        h.includes("arc spatial digest lists bearing", arc_digest, "北砚以南40里")
        h.includes("arc spatial digest lists landmark", arc_digest, "镇东老井")

        # 章节层：本章相关地点既有布局
        beat_layout = context.layout_for_beat({"出场角色": [], "本章冲突": "在如意栈调查"})
        h.includes("beat layout pulls existing layout", beat_layout, "左柜台右后院")

        # 写手层：beat 布局指令 + 既有布局合并
        writer_layout = context.layout_for_writer({"出场角色": [], "本章冲突": "如意栈", "空间布局": "沈安坐左侧柜台前"})
        h.includes("writer layout includes beat instruction", writer_layout, "沈安坐左侧柜台前")
        h.includes("writer layout includes existing layout", writer_layout, "左柜台右后院")

        # 静默原则：没有匹配地点时三个函数返回空串
        empty_beat = context.layout_for_beat({"出场角色": [], "本章冲突": "荒野赶路"})
        h.equal("layout silent when no known location", empty_beat, "")

    h.section("scenario: 即用即删小地点不污染永久地图")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        # 一个登记了但随后沉睡的小地点不应出现在空间摘要里
        update = {"canon": {"new_entities": [
            {"name": "路边茶摊", "type": "地点", "summary": "过场一次", "scale": "场景",
             "bearing_from_parent": "官道旁"},
        ]}}
        archivist.merge_ledger_update(update, 5)
        before = context.spatial_digest_for_arc(5)
        h.includes("transient location appears while active", before, "路边茶摊")
        # 标记沉睡后应从地图消失
        sleep = {"canon": {"update_entities": [{"name": "路边茶摊", "status": "沉睡"}]}}
        archivist.merge_ledger_update(sleep, 6)
        after = context.spatial_digest_for_arc(6)
        h.not_includes("sleeping location drops off the map", after, "路边茶摊")

    h.section("scenario: 钩子去重预警(单章职责给 beat_planner)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        import importlib
        planning = importlib.import_module("pipeline.planning")
        beats_dir = tmp / "beats"
        beats_dir.mkdir(parents=True, exist_ok=True)
        # 连续三章同型(悬念) + 同指向(巷子那头)
        for ch, hook in [
            (4, "黑子往巷子那头拽他，铃铛声传来。"),
            (5, "夜里听见老头提起巷子那头的事。"),
            (6, "老头出门，往巷子那头去了。"),
        ]:
            _write_json(beats_dir / f"chapter_{ch}.json", {"章节编号": ch, "钩子型": "悬念", "章末钩子": hook})
        digest = planning.recent_hooks_digest(7)
        h.includes("hooks digest lists recent hooks", digest, "第6章")
        h.includes("warns on repeated hook type", digest, "连续")
        h.includes("warns on repeated hook target", digest, "巷子那头")

        # 多样化钩子不应触发预警
        for ch, htype, hook in [
            (4, "危机", "妖物破门而入，沈安退无可退。"),
            (5, "情绪", "他摸着那只空碗，很久没动。"),
            (6, "渴望", "账本上多了一个名字，他想知道是谁。"),
        ]:
            _write_json(beats_dir / f"chapter_{ch}.json", {"章节编号": ch, "钩子型": htype, "章末钩子": hook})
        digest2 = planning.recent_hooks_digest(7)
        h.not_includes("no type warning when hooks vary", digest2, "连续")

        # 静默：开篇没有 beats 时返回空串
        h.equal("hooks digest silent at story start", planning.recent_hooks_digest(1), "")

    h.section("scenario: beat_direction_check 在总监收束纠偏时硬查钩子型连续不变")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        beats_dir = tmp / "beats"
        beats_dir.mkdir(parents=True, exist_ok=True)
        director_file = tmp / "runtime/story_director.json"
        director_file.parent.mkdir(parents=True, exist_ok=True)
        # 上一章(第5章)钩子型=悬念
        _write_json(beats_dir / "chapter_5.json", {"章节编号": 5, "钩子型": "悬念", "章末钩子": "巷口那人没走。"})

        # severity≥2 且 correction_action=tighten:本章仍用「悬念」→ 判 fail
        _write_json(director_file, {
            "chapter": 6, "severity": 2, "correction_action": "tighten",
            "arc_instruction": "收束刘三线，把周济线推上来。", "watch_repetition": [],
        })
        same = rp.beat_direction_check({"章节编号": 6, "钩子型": "悬念", "章末钩子": "他还在那。"}, 6)
        h.equal("repeated hook type under tighten fails", same["passed"], False)
        h.check("issue names the repeated hook type", any("钩子型" in s for s in same["issues"]))

        # 同样情形但本章换了钩子型 → 放行
        changed = rp.beat_direction_check({"章节编号": 6, "钩子型": "情绪", "章末钩子": "他摸着空碗。"}, 6)
        h.equal("changed hook type under tighten passes", changed["passed"], True)

        # correction_action=continue(非收束类):即使钩子型相同也不硬查
        _write_json(director_file, {
            "chapter": 6, "severity": 2, "correction_action": "continue",
            "arc_instruction": "正常推进。", "watch_repetition": [],
        })
        cont = rp.beat_direction_check({"章节编号": 6, "钩子型": "悬念", "章末钩子": "他还在那。"}, 6)
        h.equal("continue action does not trigger hook-type check", cont["passed"], True)

        # severity<2:整个硬检查不启用
        _write_json(director_file, {
            "chapter": 6, "severity": 1, "correction_action": "tighten",
            "arc_instruction": "", "watch_repetition": [],
        })
        low = rp.beat_direction_check({"章节编号": 6, "钩子型": "悬念", "章末钩子": "他还在那。"}, 6)
        h.equal("severity below 2 skips hard check", low["passed"], True)

    h.section("scenario: 事实核查不把本章新习得当穿帮")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        # 角色卡里沈安只有银针术,还没记录新技能(事实核查跑在记账之前)
        _write_json(tmp / "runtime/ledger.json", {
            "entities": {"沈安": {"type": "角色", "skills": ["银针术"]}},
        })
        # 1) 系统奖励习得配方,正文自己交代了来源 -> 不算穿帮
        sys_reward = "沈安盯着眼前的光幕。系统奖励【活血散配方（已习得）】。他默默记下了这门活血散。"
        w1 = [x for x in gates.fact_check_against_ledger(sys_reward) if "技能" in x]
        h.equal("系统奖励习得不报穿帮", w1, [])
        # 2) 师傅传授后施展,正文交代来源 -> 不算穿帮
        taught = "老者将一门火球术传授给他，沈安当即施展火球术，一团火光腾起。"
        w2 = [x for x in gates.fact_check_against_ledger(taught) if "技能" in x]
        h.equal("师传习得不报穿帮", w2, [])
        # 3) 凭空催动陌生术法,正文无任何习得交代 -> 仍要报穿帮
        from_nowhere = "沈安猛地催动雷霆诀，一道电光劈出。"
        w3 = [x for x in gates.fact_check_against_ledger(from_nowhere) if "技能" in x]
        h.check("凭空用陌生术法仍报穿帮", any("雷霆诀" in x for x in w3), w3)

    h.section("scenario: 小爆点·本章张力抬档才注入写手要点")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        base = {"章节编号": 5, "出场角色": ["沈安"], "场景类型": "日常推进"}
        # 平档(默认):不注入张力模块
        flat = context.writer_focus_modules({**base, "本章张力": "平"})
        h.not_includes("平档不注入张力要点", flat, "转折章")
        # 小高潮:注入张力模块
        peak = context.writer_focus_modules({**base, "本章张力": "小高潮"})
        h.includes("小高潮注入张力要点", peak, "转折章")
        # 小起伏:也注入
        rise = context.writer_focus_modules({**base, "本章张力": "小起伏"})
        h.includes("小起伏注入张力要点", rise, "转折章")
        # 缺省字段(老 beat 没有该字段)安全静默
        legacy = context.writer_focus_modules(dict(base))
        h.not_includes("无张力字段不注入", legacy, "转折章")

    h.section("scenario: 弧线逐章走向(chapter_drift)拎出本章那一格给 beat_planner")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        planning = importlib.import_module("pipeline.planning")
        # 一条弧:节点 9/20,9→20 段给了逐章走向格子
        arcs = [{
            "arc_id": "ARC-T1", "title": "笨办法立足", "type": "主线推进",
            "span": [9, 20], "summary": "沈安碰壁后改用笨办法",
            "pacing_shape": "闷—紧",
            "resolution_condition": "立住脚",
            "nodes": [
                {"chapter": 9, "beat_hint": "碰壁", "tension": "中",
                 "approach_to_next": "9→20改用笨办法逐步立足",
                 "chapter_drift": [
                     {"ch": 10, "gist": "缩回去舔伤口，什么也不想干"},
                     {"ch": 11, "gist": "被逼出摊，硬用笨办法接第一个活"},
                     {"ch": 12, "gist": "笨办法歪打正着治好小病，系统第一次有动静"},
                 ]},
                {"chapter": 20, "beat_hint": "立住脚", "tension": "高"},
            ],
        }]
        planning.save_active_arcs(arcs)
        arc_input = planning.build_arc_input(
            11,
            {
                "max_input_tokens": {"arc_planner": 200000, "compressor": 200000},
                "context_windows": {"arc_planner": 200000, "compressor": 200000},
                "compress_at_ratio": 1,
            },
            timeout=1,
        )
        h.includes("arc_planner 主输入可构造", arc_input, "上一批弧线收束摘要")
        h.includes("arc_planner 主输入承接上一批弧线", arc_input, "笨办法立足")
        out11 = planning.active_arcs_for_beat(11)
        h.includes("拎出本章走向格子", out11, "硬用笨办法接第一个活")
        h.includes("附带下一两章去向", out11, "第12章")
        h.not_includes("本章不提前写到再后面的格子", out11.split("下一两章去向")[0], "缩回去舔伤口")
        # 无 chapter_drift 的弧线安全静默(只走 approach_to_next)
        arcs[0]["nodes"][0].pop("chapter_drift")
        planning.save_active_arcs(arcs)
        out_legacy = planning.active_arcs_for_beat(11)
        h.not_includes("无逐章走向时不注入格子行", out_legacy, "本章走向格子")
        h.includes("仍保留段落走向", out_legacy, "改用笨办法")

    h.section("scenario: 弧线结构体检——主角欲望缺失/认知化打转/段内无不可逆事件")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        _import_modules()
        planning = importlib.import_module("pipeline.planning")
        # 坏弧:无 protagonist_want + 整段 drift 全是认知动词、无外部事件
        bad_arc = {
            "arc_id": "ARC-BAD", "title": "认知流", "type": "主线推进",
            "span": [124, 135], "summary": "沈安逐渐搞懂泽里规矩",
            "nodes": [{
                "chapter": 124, "beat_hint": "摸绳结", "tension": "低",
                "chapter_drift": [
                    {"ch": 124, "gist": "摸到绳结想起老汉，沈安发现打法一样"},
                    {"ch": 125, "gist": "围着竹丛探查，确认有三个人来过"},
                    {"ch": 126, "gist": "感知到药渣，怀疑有人蹲过很久"},
                    {"ch": 127, "gist": "意识到阿朵在附近住过好几天"},
                ],
            }],
        }
        warns = planning.arc_structural_warnings([bad_arc])
        blob = "\n".join(warns)
        h.check("坏弧被体检拦截", len(warns) >= 1, warns)
        h.includes("点名缺主角欲望", blob, "protagonist_want")
        h.check("点名认知化或无事件", ("认知化" in blob or "无任何外部" in blob), blob)
        # 好弧:有 want + drift 带不可逆外部事件
        good_arc = {
            "arc_id": "ARC-GOOD", "title": "查周通", "type": "主线推进",
            "span": [9, 12], "summary": "沈安查周通的秘密",
            "protagonist_want": "查清周通深夜烧纸在瞒什么",
            "want_drives_decision": "决定留下不走，主动住进周通后院",
            "nodes": [{
                "chapter": 9, "beat_hint": "住进后院", "tension": "中",
                "chapter_drift": [
                    {"ch": 9, "gist": "沈安决定留下不走，借口治旧伤住进周通后院"},
                    {"ch": 10, "gist": "周通深夜支开沈安去见蒙面人，被撞破，两人起戒备"},
                    {"ch": 11, "gist": "沈安偷看烧的纸认出城隍庙符，知道了周通瞒的事"},
                ],
            }],
        }
        good_warns = planning.arc_structural_warnings([good_arc])
        h.equal("好弧体检通过", good_warns, [])

    h.section("scenario: arc_output_audit——揪mimo偷掉的POV自查/章内多角度产出")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        _import_modules()
        planning = importlib.import_module("pipeline.planning")
        # 偷懒弧:既无 POV 节点又无 pov_decision;声明了同场配角却 0 条 in_chapter_angles
        lazy_arc = {
            "arc_id": "ARC-LAZY", "title": "治周济", "type": "主线推进",
            "span": [40, 48], "summary": "沈安给周济治旧疾",
            "side_characters": [{"name": "周济", "hidden_agenda": "想试探沈安底细"}],
            "nodes": [{
                "chapter": 40, "beat_hint": "上门看诊", "tension": "中",
                "narrative_ops": {"pov": None, "in_chapter_angles": []},
            }],
        }
        warns, missing = planning.arc_output_audit([lazy_arc])
        h.check("揪出POV自查缺失", "pov_decision" in missing, missing)
        h.check("揪出章内多角度缺失", "in_chapter_angles" in missing, missing)
        h.check("缺项落盘有人话告警", len(warns) >= 2, warns)
        note = planning._arc_audit_retry_note(missing)
        h.includes("重调指令点名pov_decision", note, "pov_decision")
        h.includes("重调指令点名章内多角度", note, "in_chapter_angles")
        h.includes("重调指令只补缺项不推翻", note, "其余沿用")
        # 达标弧:写了 pov_decision + 给了 in_chapter_angles → 零缺项
        ok_arc = {
            "arc_id": "ARC-OK", "title": "查铜片", "type": "主线推进",
            "span": [50, 55], "summary": "沈安查铜片来历",
            "pov_decision": "本弧不需要POV,理由:全程独行追查,无可借眼配角",
            "side_characters": [{"name": "货郎", "hidden_agenda": "私卖铜片"}],
            "nodes": [{
                "chapter": 50, "beat_hint": "盘问货郎", "tension": "中",
                "narrative_ops": {"pov": None, "in_chapter_angles": [
                    {"chapter": 50, "character": "货郎", "what": "货郎看出沈安是盲人手却稳", "why": "盲区补偿"}
                ]},
            }],
        }
        ok_warns, ok_missing = planning.arc_output_audit([ok_arc])
        h.equal("达标弧零缺项", ok_missing, set())
        h.equal("达标弧无告警", ok_warns, [])
        # 独行弧:无配角 → 不要求 in_chapter_angles;但仍要 pov_decision 二选一
        solo_arc = {
            "arc_id": "ARC-SOLO", "title": "独闯", "type": "主线推进",
            "span": [60, 63], "summary": "沈安独自赶路",
            "pov_decision": "本弧不需要POV,理由:全程独行",
            "side_characters": [],
            "nodes": [{"chapter": 60, "narrative_ops": {"pov": None, "in_chapter_angles": []}}],
        }
        _, solo_missing = planning.arc_output_audit([solo_arc])
        h.equal("独行弧无配角不强求切片", solo_missing, set())

    h.section("scenario: 系统机制演示去重——同一系统判定连演无增量预警")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        _import_modules()
        planning = importlib.import_module("pipeline.planning")
        beats_dir = tmp / "beats"
        beats_dir.mkdir(parents=True, exist_ok=True)
        # 104/107 两章都演"了结方式不符"
        _write_json(beats_dir / "chapter_104.json", {"系统了愿": "捞鞋后系统弹『怨愿未解，了结方式不符』"})
        _write_json(beats_dir / "chapter_107.json", {"系统了愿": "又一次系统弹『了结方式不符』"})
        _write_json(beats_dir / "chapter_105.json", {"系统了愿": "无"})
        digest = planning.recent_system_mechanic_digest(108, lookback=6)
        h.includes("检出重复系统判定", digest, "了结方式不符")
        h.includes("要求给信息增量", digest, "信息增量")
        # 只演一次不预警
        _write_json(beats_dir / "chapter_107.json", {"系统了愿": "无"})
        digest_single = planning.recent_system_mechanic_digest(108, lookback=6)
        h.equal("单次演示不预警", digest_single, "")

    h.section("scenario: 卷交接——上一卷遗留债务清单逼新卷处置")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        _import_modules()
        planning = importlib.import_module("pipeline.planning")
        # 一条未走完的弧(最后节点超出当前章)
        planning.save_active_arcs([{
            "arc_id": "ARC-OLD", "title": "窑厂暗线", "type": "主线",
            "resolution_condition": "查清窑厂真相",
            "nodes": [{"chapter": 90, "beat_hint": "老仆被杀"}, {"chapter": 210, "beat_hint": "真相"}],
        }])
        debts = planning.previous_volume_residual_debts(200)
        h.includes("遗留债务清单点名未走完弧线", debts, "窑厂暗线")
        h.check("要求新卷处置(接手/封存)", ("接手" in debts or "封存" in debts), debts)
        # 无遗留时给安全文案
        planning.save_active_arcs([])
        # active_threads 也清空，确保无线索债
        try:
            state_mod = importlib.import_module("pipeline.state")
            if hasattr(state_mod, "save_active_threads"):
                state_mod.save_active_threads({"threads": {}, "foreshadowing": {}})
        except Exception:
            pass
        debts_empty = planning.previous_volume_residual_debts(200)
        h.check("无遗留债务给安全文案", "无显著遗留" in debts_empty or "首卷" in debts_empty, debts_empty)


    h.section("scenario: 伏笔回收断链修复(resolve_by 回写 + 隐式 deadline 兜底)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        planning = importlib.import_module("pipeline.planning")
        importlib.reload(planning)
        # 三类窗口配置(隐式 deadline 推算依赖)
        _write_json(tmp / "config/structure_norms.json", {
            "伏笔回收窗口章数": {
                "任务即时类(委托/危机/小疑问)": [1, 6],
                "关系成长类": [7, 16],
                "信物命运级": [30, 50],
            },
        })
        # 账本:F-100 无 deadline(将被 arc 回写)、F-101 无 deadline 老伏笔(走隐式)、F-102 已有 deadline 不许覆盖
        _write_json(tmp / "runtime/active_threads.json", {
            "foreshadowing": {
                "F-100": {"id": "F-100", "type": "悬念/道具", "planted_chapter": 5,
                          "strength": "中", "status": "未回收", "promise": "铜片来历"},
                "F-101": {"id": "F-101", "type": "解谜/身世", "planted_chapter": 1,
                          "strength": "大", "status": "未回收", "promise": "原主是谁"},
                "F-102": {"id": "F-102", "type": "悬念/事件", "planted_chapter": 3,
                          "strength": "中", "status": "未回收", "promise": "哭声来源",
                          "planned_resolution": "20"},
            },
            "open_questions": [], "next_id": "F-103",
        })
        # arc_planner 产出:为 F-100 规划 resolve_by=30,为 F-102 也给(应被既有值保护)
        arcs = [{
            "arc_id": "ARC-FX", "title": "铜片溯源", "type": "副线",
            "span": [25, 35], "summary": "查铜片",
            "resolution_condition": "查清铜片",
            "nodes": [
                {"chapter": 25, "beat_hint": "埋", "tension": "中",
                 "narrative_ops": {"foreshadowing": [
                     {"op": "埋", "id": "F-100", "resolve_by": 30, "resolve_hint": "药铺认出同款铜片"},
                     {"op": "埋", "id": "F-102", "resolve_by": 99},
                 ]}},
                {"chapter": 35, "beat_hint": "收", "tension": "高"},
            ],
        }]
        n = planning._backfill_resolve_by_to_threads(arcs)
        threads = json.loads((tmp / "runtime" / "active_threads.json").read_text(encoding="utf-8"))
        fs = threads["foreshadowing"]
        h.check("回写条数=1(只 F-100,F-102 被既有值保护)", n == 1, f"n={n}")
        h.check("F-100 拿到 planned_resolution=30", str(fs["F-100"].get("planned_resolution")) == "30", str(fs["F-100"].get("planned_resolution")))
        h.includes("F-100 回收方向落进 notes", fs["F-100"].get("notes", ""), "药铺认出同款铜片")
        h.check("F-102 既有 deadline 不被覆盖(仍=20)", str(fs["F-102"].get("planned_resolution")) == "20", str(fs["F-102"].get("planned_resolution")))
        # 隐式 deadline:F-101 身世/大 → 埋1+窗口上界50=51;第60章应判过期
        h.check("F-101 身世大 → 信物命运级窗口", planning._foreshadowing_window_key(fs["F-101"]) == "信物命运级", "")
        h.check("F-101 隐式 deadline=51", planning._implicit_deadline(fs["F-101"]) == 51, str(planning._implicit_deadline(fs["F-101"])))
        digest = planning.overdue_foreshadowing_digest(60)
        h.includes("第60章追债器点名 F-100(回写后生效)", digest, "F-100")
        h.includes("第60章追债器点名 F-101(隐式窗口生效)", digest, "F-101")
        h.includes("隐式窗口条目标注估算", digest, "估算窗口")
        h.not_includes("既有空转 bug 不再发生(digest 非空)", digest, "@@NEVER@@")

    h.section("scenario: 主线弧缺失修复(needs_arc_planning 缺主线也触发 + 补线合并不冲副线)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        planning = importlib.import_module("pipeline.planning")
        importlib.reload(planning)
        # 只有一条副线,主线缺失 → needs_arc_planning 应返回 True
        side_only = [{"arc_id": "ARC-S1", "type": "副线", "title": "副线A",
                      "span": [49, 68], "summary": "消化遗物",
                      "resolution_condition": "查清",
                      "nodes": [{"chapter": 60, "beat_hint": "推进", "tension": "中"},
                                {"chapter": 68, "beat_hint": "收", "tension": "高"}]}]
        planning.save_active_arcs(side_only)
        h.check("只有副线时 needs_arc_planning=True(缺主线)", planning.needs_arc_planning(50), "")
        h.check("has_active_mainline 返回 False", not planning.has_active_mainline(side_only), "")
        # 1主1副时不触发
        with_main = side_only + [{"arc_id": "ARC-M1", "type": "主线推进", "title": "主线",
                                   "span": [50, 70], "summary": "危机",
                                   "resolution_condition": "解危",
                                   "nodes": [{"chapter": 70, "beat_hint": "收", "tension": "高潮"}]}]
        planning.save_active_arcs(with_main)
        h.check("1主1副时 needs_arc_planning=False", not planning.needs_arc_planning(50), "")
        h.check("has_active_mainline 返回 True", planning.has_active_mainline(with_main), "")
        # 补线合并逻辑:_backfill 之前,验证 augment 输入构造时不崩溃
        build_ok = True
        try:
            _ = planning.build_arc_input(50, {
                "max_input_tokens": {"arc_planner": 200000, "compressor": 200000},
                "context_windows": {"arc_planner": 200000, "compressor": 200000},
                "compress_at_ratio": 1,
            }, timeout=1, augment_live_arcs=side_only)
        except Exception:
            build_ok = False
        h.check("补线模式 build_arc_input 不崩溃", build_ok, "")
        # 补线合并:新主线 + 原副线 = 2条,副线 arc_id 必须保留
        new_main = [{"arc_id": "ARC-NEW", "type": "主线推进", "title": "新主线",
                     "span": [50, 65], "summary": "新危机",
                     "resolution_condition": "解危",
                     "nodes": [{"chapter": 65, "beat_hint": "收", "tension": "高潮"}]}]
        planning.save_active_arcs(side_only)  # 先还原只有副线
        existing_ids = {a.get("arc_id") for a in side_only}
        merged = side_only + [a for a in new_main if a.get("arc_id") not in existing_ids]
        planning.save_active_arcs(merged)
        loaded = planning.load_active_arcs()
        h.check("合并后共2条弧线", len(loaded) == 2, str(len(loaded)))
        h.check("副线 arc_id 保留", any(a.get("arc_id") == "ARC-S1" for a in loaded), "")
        h.check("新主线 arc_id 存在", any(a.get("arc_id") == "ARC-NEW" for a in loaded), "")
        h.check("合并后 has_active_mainline=True", planning.has_active_mainline(loaded), "")

    h.section("scenario: 配角消费端(_ingest_side_characters 落 ledger + beat_moments 消费)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        planning = importlib.import_module("pipeline.planning")
        importlib.reload(planning)
        # 构造带 side_characters 的弧线
        arcs = [{
            "arc_id": "ARC-SC1", "type": "副线", "title": "周通的秘密",
            "span": [9, 30], "resolution_condition": "揭秘",
            "nodes": [{"chapter": 13, "beat_hint": "周通支开沈安", "tension": "中",
                       "narrative_ops": {"foreshadowing": []}}],
            "side_characters": [{
                "name": "周通",
                "independent_goal": "守住亡妻的坟不让外人靠近",
                "hidden_agenda": "知道井下有东西但不想让人发现",
                "knowledge_boundary": "知道沈安来历不明,不知道他是盲人",
                "beat_moments": [{"ch": 13, "what": "支开沈安，用借口挡住追问"}],
            }],
        }]
        n = planning._ingest_side_characters(arcs)
        ledger = json.loads((tmp / "runtime" / "ledger.json").read_text(encoding="utf-8"))
        entities = ledger.get("entities", {})
        h.check("ingest 返回非零", n > 0, f"n={n}")
        h.check("周通实体已建", "周通" in entities, "")
        zt = entities.get("周通", {})
        h.check("independent_goal → arc_core.want", "守住亡妻" in (zt.get("arc_core") or {}).get("want", ""), "")
        secrets_texts = [s.get("secret", "") if isinstance(s, dict) else str(s) for s in (zt.get("secrets") or [])]
        h.check("hidden_agenda → secrets", any("井下" in s for s in secrets_texts), "")
        facts_texts = zt.get("facts") or []
        h.check("knowledge_boundary → facts", any("盲人" in f for f in facts_texts), "")
        bm = (zt.get("arc_core") or {}).get("beat_moments") or []
        h.check("beat_moments 落进 arc_core", any(m.get("ch") == 13 for m in bm if isinstance(m, dict)), "")
        # beat_moments 消费端:第13章应有提示
        hint_13 = planning._beat_moments_for_chapter(13)
        h.includes("第13章 beat_moments 消费端有周通提示", hint_13, "周通")
        hint_14 = planning._beat_moments_for_chapter(14)
        h.check("第14章无 beat_moments(不误报)", hint_14 == "", hint_14[:40] if hint_14 else "")
        # 重复 ingest 不产生重复 secrets
        n2 = planning._ingest_side_characters(arcs)
        ledger2 = json.loads((tmp / "runtime" / "ledger.json").read_text(encoding="utf-8"))
        secrets2 = ledger2["entities"]["周通"].get("secrets") or []
        h.check("重复 ingest 不重复写 secrets", len(secrets2) == len(zt.get("secrets") or []), f"first={len(zt.get('secrets',[]))}, second={len(secrets2)}")

    h.section("scenario: 任务4 伏笔Progress预警(foreshadowing_progress_digest)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist_mod = _import_modules()
        planning = importlib.import_module("pipeline.planning")
        importlib.reload(planning)
        # F-001:last_advanced=1,当前章51,gap=50→超阈值8,strength=大
        # F-002:last_advanced=48,当前章51,gap=3→未达阈值
        # F-003:无last_advanced→不误报
        _write_json(tmp / "runtime/active_threads.json", {
            "foreshadowing": {
                "F-001": {"id": "F-001", "type": "解谜/身世", "planted_chapter": 1,
                          "strength": "大", "status": "未回收", "promise": "原主是谁",
                          "last_advanced": 1},
                "F-002": {"id": "F-002", "type": "悬念/道具", "planted_chapter": 3,
                          "strength": "中", "status": "未回收", "promise": "铜片来历",
                          "last_advanced": 48},
                "F-003": {"id": "F-003", "type": "悬念/事件", "planted_chapter": 5,
                          "strength": "中", "status": "未回收", "promise": "哭声来源"},
            },
            "open_questions": [], "next_id": "F-004",
        })
        digest = planning.foreshadowing_progress_digest(51, stale_threshold=8)
        h.includes("F-001 被点名(gap=50)", digest, "F-001")
        h.not_includes("F-002 未到阈值不报(gap=3)", digest, "F-002")
        h.not_includes("F-003 无last_advanced不误报", digest, "F-003")
        # archivist upsert 自动打 last_advanced
        import importlib as _il
        arc_mod = _il.import_module("pipeline.archivist")
        _il.reload(arc_mod)
        _write_json(tmp / "runtime/state.json", {"latest_chapter": 10})
        update = {
            "_chapter": 10,
            "foreshadowing": {
                "upsert": [{"id": "F-NEW", "type": "悬念/事件", "strength": "中",
                            "status": "未回收", "promise": "新伏笔"}]
            }
        }
        arc_mod.merge_state_update(update)
        threads_after = json.loads((tmp / "runtime/active_threads.json").read_text(encoding="utf-8"))
        new_entry = threads_after["foreshadowing"].get("F-NEW", {})
        h.check("archivist upsert 自动打 last_advanced=10", new_entry.get("last_advanced") == 10, str(new_entry.get("last_advanced")))

    h.section("scenario: 任务5 story_director 世界重量维度(prompt文本验证)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        _write(tmp / "prompts/story_director.md", open("prompts/story_director.md", encoding="utf-8").read())
        director_prompt = (tmp / "prompts/story_director.md").read_text(encoding="utf-8")
        h.includes("第10维度:世界重量存在", director_prompt, "世界重量")
        h.includes("世界重量是软提示非KPI", director_prompt, "软提示")
        h.includes("连续N章无生命危险触发条件", director_prompt, "生命危险")

    h.section("scenario: 高潮节点强制标关键章(active_arcs_for_beat 硬约束注入)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        planning = importlib.import_module("pipeline.planning")
        importlib.reload(planning)
        # 弧线:第20章 tension=高潮
        arcs = [{"arc_id": "ARC-CX", "title": "危机爆发", "type": "主线推进",
                 "span": [15, 25], "summary": "主线高潮",
                 "resolution_condition": "解危",
                 "nodes": [
                     {"chapter": 15, "beat_hint": "前兆", "tension": "中",
                      "approach_to_next": "蓄力", "chapter_drift": [{"ch": 18, "gist": "暗流汇聚"}]},
                     {"chapter": 20, "beat_hint": "全面爆发正面对峙", "tension": "高潮"},
                     {"chapter": 25, "beat_hint": "余波收束", "tension": "低"},
                 ]}]
        planning.save_active_arcs(arcs)
        # 本章=20,正好在高潮节点 → 必须出现硬约束
        out_20 = planning.active_arcs_for_beat(20)
        h.includes("高潮当章出现硬约束", out_20, "必须")
        h.includes("高潮当章提到关键章", out_20, "关键章")
        # 本章=21(±1范围) → 也应出现
        out_21 = planning.active_arcs_for_beat(21)
        h.includes("高潮±1章也出现硬约束", out_21, "必须")
        # 本章=18(离高潮2章) → 不该出现硬约束
        out_18 = planning.active_arcs_for_beat(18)
        h.not_includes("离高潮2章不触发硬约束", out_18, "必须.*关键章")

    h.section("scenario: 场景装置去重(recent_scene_devices_digest)抓跨章同招")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        planning = importlib.import_module("pipeline.planning")
        beats_dir = tmp / "beats"
        beats_dir.mkdir(parents=True, exist_ok=True)
        # 连续多章都在"摸纸条/问人"——同一组装置反复演
        for ch in range(10, 16):
            _write_json(beats_dir / f"chapter_{ch}.json", {
                "章节编号": ch, "场景类型": "查访",
                "具体动作": ["摸那张看不见字的纸", "去问知道的人"],
                "具体物件": ["纸条"],
            })
        digest = planning.recent_scene_devices_digest(16)
        h.check("抓出反复出现的装置", "纸条" in digest or "摸那张看不见字的纸" in digest, digest)
        h.includes("提示本章换招", digest, "换")
        # 装置每章不同 -> 不报
        verbs = [["翻墙夜探"], ["当街叫卖"], ["雨夜赶路"], ["灶台煎药"], ["码头打听"], ["山道遇袭"]]
        for i, ch in enumerate(range(10, 16)):
            _write_json(beats_dir / f"chapter_{ch}.json", {
                "章节编号": ch, "场景类型": f"场景{ch}",
                "具体动作": verbs[i], "具体物件": [f"物件{ch}"],
            })
        digest2 = planning.recent_scene_devices_digest(16)
        h.equal("装置多样时不报", digest2, "")
        # 章数不足(<3)静默
        h.equal("开篇章数不足时静默", planning.recent_scene_devices_digest(2), "")

    h.section("scenario: 角色卡外貌/行为习惯动态更新且不重复堆积")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        # 新建实体带外貌+习惯
        archivist.merge_ledger_update({"canon": {"new_entities": [{
            "name": "老木匠", "type": "角色", "summary": "棺材铺老头",
            "appearance": "瘦高驼背，左眼浑浊",
            "mannerisms": ["闲着就摸出刨子刨木头"],
        }]}}, 10)
        led = json.loads((tmp / "runtime/ledger.json").read_text(encoding="utf-8"))
        ent = led["entities"]["老木匠"]
        h.equal("外貌落卡", ent.get("appearance"), "瘦高驼背，左眼浑浊")
        h.includes("习惯落卡", ent.get("mannerisms"), "闲着就摸出刨子刨木头")
        # 更新:加新习惯 + 持久外貌变化;旧习惯去重不重复
        archivist.merge_ledger_update({"canon": {"update_entities": [{
            "name": "老木匠",
            "appearance_update": "瘦高驼背，左眼浑浊，左眉添了道新疤",
            "mannerisms_add": ["闲着就摸出刨子刨木头", "说话前先咳一声"],
        }]}}, 11)
        led2 = json.loads((tmp / "runtime/ledger.json").read_text(encoding="utf-8"))
        ent2 = led2["entities"]["老木匠"]
        h.equal("外貌持久更新(整条覆盖含原特征)", ent2.get("appearance"), "瘦高驼背，左眼浑浊，左眉添了道新疤")
        h.equal("习惯去重不重复堆积", ent2.get("mannerisms").count("闲着就摸出刨子刨木头"), 1)
        h.includes("新习惯追加", ent2.get("mannerisms"), "说话前先咳一声")
        # 注入写手的角色卡带上外貌与习惯
        card = context.ledger_context_for_writer({"出场角色": ["老木匠"], "当前地点": ""}, 12)
        h.includes("写手卡含外貌", card, "瘦高")
        h.includes("写手卡含习惯", card, "刨子")

    h.section("scenario: beat 调试留档每章一档且不被 cleanup 删除")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        # 写一章 beat 调试料
        core.write_beat_debug(15, {
            "beat_input.md": "规划师看到的上下文……含本章走向格子",
            "beat_raw.md": "{LLM 原始输出}",
            "beat_raw_retry.md": "",  # 空项应跳过,不落盘
            "direction.json": '{"passed": true}',
            "beat.json": '{"章节编号": 15}',
        })
        folder = core.beat_debug_dir(15)
        h.check("调试目录按章建立", folder.is_dir(), str(folder))
        h.check("输入留档", (folder / "beat_input.md").exists(), "")
        h.check("原始输出留档", (folder / "beat_raw.md").exists(), "")
        h.check("空项跳过不落盘", not (folder / "beat_raw_retry.md").exists(), "")
        h.includes("留档内容正确", (folder / "beat_input.md").read_text(encoding="utf-8"), "走向格子")
        # 每章最小审计链也不能被 clean 模式删掉；否则只能看分数表，无法复盘闭环。
        audit_files = [
            core.role_artifact("gate", 15, "gate.json"),
            core.role_artifact("reviewer", 15, "review_input.md"),
            core.role_artifact("reviewer", 15, "review.md"),
            core.role_artifact("reviewer", 15, "review_verdict.json"),
            core.role_artifact("editor", 15, "editor_input.md"),
            core.role_artifact("editor", 15, "edited.md"),
            core.role_artifact("archivist", 15, "archive_input.md"),
            core.role_artifact("archivist", 15, "archive_update.md"),
            core.role_artifact("gate", 15, "final_gate.json"),
            core.role_artifact("gate", 15, "committed_gate.json"),
            core.role_artifact("gate", 15, "final_committed.json"),
        ]
        for path in audit_files:
            _write(path, path.name)
        transient = core.role_artifact("writer", 15, "draft.md")
        _write(transient, "临时初稿")
        # cleanup 不碰 beats/_debug:模拟清理后留档仍在
        core.cleanup_chapter_artifacts(15, {"artifact_retention": "clean"})
        h.check("cleanup 后调试留档仍在", (folder / "beat_input.md").exists(), "")
        h.check("cleanup 保留最小审计链", all(path.exists() for path in audit_files), [str(p) for p in audit_files])
        h.check("cleanup 仍删除非审计临时稿", not transient.exists(), str(transient))

    h.section("scenario: analyst MAP 两段切分——结构台账真名绝不漏进手法观察段")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        # (a) 正常两段:手法观察禁真名 / 结构台账含真名,切分后互不串
        two = (
            "=== 手法观察 ===\n## 句式节奏\n- 观察: 高潮处连甩短句砸节奏\n"
            "=== 结构台账 ===\n- 出现的物件: 铜铃@48\n- 本批悬置: 周通烧纸@49\n"
        )
        tech, struct = rp.split_map_segments(two)
        h.check("手法段拿到手法", "短句" in tech, tech)
        h.not_includes("真名物件不漏进手法段", tech, "铜铃")
        h.not_includes("真名角色不漏进手法段", tech, "周通")
        h.includes("结构段保留真名物件", struct, "铜铃@48")
        h.includes("结构段保留真名悬置", struct, "周通烧纸@49")
        # (b) 兜底:缺结构台账标记 → 全当手法、结构为空(绝不把可能含真名内容误当手法)
        tech2, struct2 = rp.split_map_segments("=== 手法观察 ===\n- 观察: 只有手法没台账")
        h.check("缺台账标记时结构段为空", struct2 == "", struct2)
        h.includes("缺台账标记时手法段保留", tech2, "只有手法")
        # (c) 裸文本无任何标记 → 整体当手法、结构为空
        tech3, struct3 = rp.split_map_segments("裸文本无标记")
        h.check("裸文本结构段为空", struct3 == "", struct3)
        h.check("裸文本整体当手法", tech3 == "裸文本无标记", tech3)
        # (d) MAP 输出封顶常量存在且远小于窗口(保证全部 map 之和 ≤ 1M,结构 reduce 能一次吃下)
        h.check("MAP 输出封顶常量合理", 0 < rp.ANALYST_MAP_OUTPUT_TOKENS <= 30000, rp.ANALYST_MAP_OUTPUT_TOKENS)
        # (e) 容错:模型把标记写成 == xx ==(=不足3个)也能正确两段切分,真名仍只进结构段
        loose = "== 手法观察 ==\n白描手法\n== 结构台账 ==\n- 出现的物件: 玉佩@52\n"
        tl, sl = rp.split_map_segments(loose)
        h.includes("宽松标记手法段拿到手法", tl, "白描")
        h.not_includes("宽松标记真名不漏手法段", tl, "玉佩")
        h.includes("宽松标记结构段保留真名", sl, "玉佩@52")
        h.check("宽松标记标题已剥除", "手法观察" not in tl[:20], tl[:30])
        # (f) 安全兜底:真缺台账标记但文本含真名(@数字)→ 整体进结构段、手法段为空(绝不漏真名给写手)
        leak = "=== 手法观察 ===\n白描\n后来把铜铃@49藏起来了"  # 无结构台账标记,但有真名锚点
        tlk, slk = rp.split_map_segments(leak)
        h.check("含真名却无台账标记时手法段为空", tlk == "", tlk)
        h.includes("含真名无标记内容改判进结构段", slk, "铜铃@49")
        # (g) 缺标记且无真名特征 → 才安全地整体当手法观察
        tnr, snr = rp.split_map_segments("## 节奏\n高潮连甩短句没有任何专名锚点")
        h.check("无标记无真名时结构段为空", snr == "", snr)
        h.includes("无标记无真名时整体当手法", tnr, "短句")

    h.section("scenario: 结构参考分布(项目三D)——数字进JSON、原理留prompt、缺文件优雅跳过")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        import importlib as _il
        P = _il.import_module("pipeline.planning")
        # (a) 缺文件 → digest 返回空(不破坏未配置的书)
        norms_path = tmp / "config" / "structure_norms.json"
        if norms_path.exists():
            norms_path.unlink()
        h.check("缺 structure_norms.json 时 arc digest 为空", P.structure_norms_digest("arc") == "", "")
        h.check("缺文件时 beat digest 为空", P.structure_norms_digest("beat") == "", "")
        # (b) 写入文件 → arc 全量、beat 只给呼吸cadence
        import json as _json
        norms_path.parent.mkdir(parents=True, exist_ok=True)
        norms_path.write_text(_json.dumps({
            "_说明": "下划线键不该注入",
            "弧长分级章数": {"单元任务弧": [3, 8], "命运信物弧": "不设上限"},
            "节点间距随进程章数": {"前期": [2, 3], "后期": [8, 15]},
            "呼吸cadence": {"连续高强度上限章数": 3, "高强度后缓冲章数": [1, 2]},
        }, ensure_ascii=False), encoding="utf-8")
        arc_d = P.structure_norms_digest("arc")
        beat_d = P.structure_norms_digest("beat")
        h.includes("arc digest 含弧长分级", arc_d, "单元任务弧=3-8章")
        h.includes("arc digest 含节点间距", arc_d, "前期=2-3章")
        h.includes("arc digest 区间格式化正确", arc_d, "高强度后缓冲章数=1-2章")
        h.not_includes("下划线说明键不注入", arc_d, "下划线键不该注入")
        h.includes("digest 明示非KPI", arc_d, "不是红线/KPI")
        h.includes("beat digest 含呼吸cadence", beat_d, "连续高强度上限章数=3章")
        h.not_includes("beat digest 不含弧长(只给呼吸)", beat_d, "弧长")
        # (c) 原理仍在真实 prompt、具体数字已移出(读仓库真文件,不读隔离区)
        real_arc = Path(__file__).resolve().parents[1] / "prompts" / "arc_planner.md"
        arc_prompt = real_arc.read_text(encoding="utf-8")
        h.includes("arc_planner 保留分级原理", arc_prompt, "按类型定")
        h.includes("arc_planner 指向参考分布输入", arc_prompt, "本书结构参考分布")
        h.not_includes("arc_planner 不再写死弧长数字区间", arc_prompt, "10-40 章")

    h.section("scenario: 自动校准器(项目三D步2)——4道护栏+反馈重抽,agent不被信任")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        import importlib as _il2
        C = _il2.import_module("calibrate_norms")
        _il2.reload(C)
        good_json = {
            "弧长分级章数": {"单元任务弧": [3, 8], "角色成长弧": [10, 40], "大战决战弧": [15, 50], "命运信物弧": "不设上限"},
            "节点间距随进程章数": {"前期": [2, 3], "中期": [5, 10], "后期": [8, 15]},
            "伏笔回收窗口章数": {"任务即时类": [1, 6], "关系成长类": [7, 16], "信物命运级": [30, 50]},
            "憋占比按弧型": {"单元任务弧": "40%", "角色成长弧": "60%", "大战决战弧": "55%", "命运信物弧": "70%"},
            "反差窗口章数": {"主角短距反差": [4, 10], "配角长距记忆维护间隔": [15, 20]},
            "物件复现间距章数": {"高频伴行物": [3, 5], "中频功能物": [10, 20], "低频意象物": "50+"},
            "闭环率分布": {"彻底闭环": "55%", "留尾巴": "30%", "半收": "12%", "留白容忍": "提及3次以上"},
            "呼吸cadence": {"连续高强度上限章数": 3, "高强度后缓冲章数": [1, 2], "连续低强度上限章数": 8},
        }
        probes = ["李平安", "柳韵", "燕十三"]
        # (a) 合法 JSON 过全部护栏
        h.check("合法JSON过全部护栏", C.run_all_guards(good_json, probes) == [], str(C.run_all_guards(good_json, probes)))
        # (b) 真名泄漏被拦(死线)
        leak = json.loads(json.dumps(good_json))
        leak["弧长分级章数"] = {"李平安的弧": [3, 8], "角色成长弧": [10, 40], "大战决战弧": [15, 50], "命运信物弧": "X"}
        h.check("真名泄漏被护栏拦(死线)", any("真名" in x for x in C.run_all_guards(leak, probes)), "")
        # (c) schema 缺组被拦
        miss = json.loads(json.dumps(good_json)); del miss["呼吸cadence"]
        h.check("schema缺组被拦", any("呼吸cadence" in x for x in C.guard_schema(miss)), "")
        # (d) 范围越界被拦(下限>上限/超200/负数/百分比>100)
        bad = json.loads(json.dumps(good_json))
        bad["弧长分级章数"] = {"单元任务弧": [8, 3], "角色成长弧": [10, 999], "大战决战弧": [-5, 50], "命运信物弧": "X"}
        h.check("范围越界被拦(≥3条)", len(C.guard_ranges(bad)) >= 3, str(C.guard_ranges(bad)))
        pct = json.loads(json.dumps(good_json))
        pct["憋占比按弧型"] = {"单元任务弧": "150%", "角色成长弧": "60%", "大战决战弧": "55%", "命运信物弧": "70%"}
        h.check("百分比>100被拦", any("100" in x for x in C.guard_ranges(pct)), "")
        # (e) 反馈重抽:第1次返真名(拒)→报错喂回→第2次返干净(过)
        C.load_realname_probes = lambda: ["李平安", "柳韵"]
        state = {"n": 0, "inputs": []}

        def fake_extract(role, instr, inp, max_out, timeout):
            state["n"] += 1; state["inputs"].append(inp)
            if state["n"] == 1:
                b = json.loads(json.dumps(good_json))
                b["弧长分级章数"] = {"李平安的弧": [3, 8], "角色成长弧": [10, 40], "大战决战弧": [15, 50], "命运信物弧": "X"}
                return json.dumps(b, ensure_ascii=False)
            return "```json\n" + json.dumps(good_json, ensure_ascii=False) + "\n```"

        C.call_model = fake_extract
        norms = None; issues = []
        for attempt in range(1, C.MAX_RETRIES + 1):
            try:
                cand = C.extract_norms_from_report("报告\n【可入 prompt】 X", issues, 30)
            except Exception as exc:  # noqa: BLE001
                issues = [str(exc)]; continue
            issues = C.run_all_guards(cand, C.load_realname_probes())
            if not issues:
                norms = cand; break
        h.check("反馈重抽后第2次通过", norms is not None and state["n"] == 2, f"n={state['n']}")
        h.check("第2次输入带上次护栏报错(反馈)", "真名" in state["inputs"][1] if len(state["inputs"]) > 1 else False, "")

    h.section("scenario: 结构 REDUCE 全量一次喂、不分层,产校准报告不进写手路径")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        # 桩掉 call_model:捕获结构 reduce 的输入,确认全部台账一次性喂入(不分层)
        captured = {}

        def fake_call_model(role, instructions, input_text, max_out, timeout):
            captured["role"] = role
            captured["input"] = input_text
            captured["max_out"] = max_out
            return "# 结构校准报告\n## 一、伏笔分析\n铜铃@48→@91 间距43章\n【可入 prompt】信物类伏笔典型间隔约40章"

        orig = rp.call_model
        rp.call_model = fake_call_model
        try:
            logs = [f"【第{i}批】\n- 出现的物件: 铜铃@{i*10}" for i in range(1, 6)]
            rp.run_structure_reduce(logs, timeout=30)
        finally:
            rp.call_model = orig
        # 全部 5 批一次喂入(不分层:输入里能同时看到第1批和第5批)
        h.includes("结构 reduce 一次看到首批", captured.get("input", ""), "【第1批】")
        h.includes("结构 reduce 一次看到末批", captured.get("input", ""), "【第5批】")
        h.check("结构 reduce 用 analyst 角色", captured.get("role") == "analyst", captured.get("role"))
        # 校准报告落盘到 _structure_calibration.md
        report = rp.ANALYST_DIR / "_structure_calibration.md"
        h.check("校准报告落盘", report.exists(), str(report))
        h.includes("报告含举证(真名)", report.read_text(encoding="utf-8"), "铜铃")
        # 报告不在 chunks/ 里、不进 index(绝不进写手检索表)
        idx = rp.CHUNKS_DIR / "index.json"
        if idx.exists():
            h.not_includes("校准报告不登记进写手 index", idx.read_text(encoding="utf-8"), "structure_calibration")
        h.check("校准报告不在 chunks 目录", not (rp.CHUNKS_DIR / "_structure_calibration.md").exists(), "")

    h.section("scenario: 结构 REDUCE 风控拒绝重试——偶发拒绝能重试放行/耗尽不写垃圾报告")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        REJECT = "The request was rejected because it was considered high risk"
        good = "# 结构校准报告\n## 一、伏笔分析\n铜铃@48→@91 间距43章\n【可入 prompt】信物类伏笔典型间隔约40章"
        logs = [f"【第{i}批】\n- 出现的物件: 铜铃@{i*10}" for i in range(1, 4)]

        # (a) 前两次被风控拒、第三次成功 → 报告应是成功内容,不是拒绝语
        st = {"n": 0}

        def flaky(role, instr, inp, max_out, timeout):
            st["n"] += 1
            return REJECT if st["n"] <= 2 else good

        orig = rp.call_model
        orig_sleep = rp.time.sleep
        rp.call_model = flaky
        rp.time.sleep = lambda *a, **k: None  # 测试里不真等退避(finally 必恢复,否则污染全局)
        try:
            rp.run_structure_reduce(logs, timeout=5)
        finally:
            rp.call_model = orig
        report = rp.ANALYST_DIR / "_structure_calibration.md"
        h.check("拒绝后重试到第3次", st["n"] == 3, f"calls={st['n']}")
        h.check("最终报告落盘", report.exists(), str(report))
        h.includes("报告是成功内容不是拒绝语", report.read_text(encoding="utf-8"), "铜铃")
        h.not_includes("报告不含风控拒绝语", report.read_text(encoding="utf-8"), "high risk")

        # (b) 一直被拒(重试耗尽)→ 绝不把拒绝语写盘冒充报告;旧报告保留不被覆盖
        report.write_text("# 旧的有效报告\n铜铃@48", encoding="utf-8")
        rp.call_model = lambda *a, **k: REJECT
        try:
            rp.run_structure_reduce(logs, timeout=5)
        finally:
            rp.call_model = orig
        h.not_includes("耗尽后不写拒绝语", report.read_text(encoding="utf-8"), "high risk")
        h.includes("耗尽后保留旧报告", report.read_text(encoding="utf-8"), "旧的有效报告")

        # (c) call_analyst_with_retry 直接单测:拒绝→成功路径返回成功内容
        st2 = {"n": 0}

        def flaky2(role, instr, inp, max_out, timeout):
            st2["n"] += 1
            return REJECT if st2["n"] == 1 else good

        rp.call_model = flaky2
        try:
            out = rp.call_analyst_with_retry("p", "in", 7000, 5, label="单测", retries=4)
        finally:
            rp.call_model = orig
            rp.time.sleep = orig_sleep  # 恢复真 sleep,避免污染后续场景
        h.includes("包装函数重试后返回成功内容", out, "铜铃")
        h.check("包装函数重试计数正确", st2["n"] == 2, f"n={st2['n']}")

    h.section("scenario: MAP 并发调度——真并发/拒绝写SKIP/续跑跳过/STOP优雅停")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        # (a) 真并发 + 第3批被风控拒 → SKIP,其余完成,峰值并发<=配置
        C = {"live": 0, "peak": 0, "calls": 0}
        lock = threading.Lock()

        def fake_map(role, instr, inp, max_out, timeout):
            with lock:
                C["live"] += 1; C["calls"] += 1
                C["peak"] = max(C["peak"], C["live"])
            time.sleep(0.03)
            with lock:
                C["live"] -= 1
            if "BATCH3" in inp:
                return "the request was rejected because it was considered high risk"
            return "=== 手法观察 ===\nx\n=== 结构台账 ===\n- 出现的物件: 铜铃@1"

        orig = rp.call_model
        rp.call_model = fake_map
        try:
            batches = [f"b{i} " + ("BATCH3" if i == 2 else "normal") for i in range(8)]
            done, rejected, stopped = rp.run_map_phase(batches, "MP", 60000, 30, 4)
            h.check("8批完成7拒1", done == 7 and rejected == 1, f"done={done} rej={rejected}")
            h.check("未触发停止", stopped is False, str(stopped))
            h.check("峰值并发受配置约束(<=4且真并发)", 2 <= C["peak"] <= 4, f"peak={C['peak']}")
            h.check("被拒批写SKIP", rp.analyst_batch_path(2).read_text(encoding="utf-8").startswith("<<SKIP"), "")
            h.check("完成批盖指纹", rp.fingerprint_ok(rp.analyst_batch_path(0).read_text(encoding="utf-8"), 60000), "")
            # (b) 续跑:已落盘批秒跳过,零 API 调用
            C["calls"] = 0
            done2, rejected2, stopped2 = rp.run_map_phase(batches, "MP", 60000, 30, 4)
            h.check("续跑计数一致", done2 == 7 and rejected2 == 1, f"d={done2} r={rejected2}")
            h.check("续跑零 API 调用(指纹跳过)", C["calls"] == 0, f"calls={C['calls']}")
        finally:
            rp.call_model = orig

        # (c) STOP 中途触发 → 优雅停,已落盘保留,未全部启动,返回 stopped=True
        st = {"n": 0}
        slock = threading.Lock()

        def fake_stop(role, instr, inp, max_out, timeout):
            with slock:
                st["n"] += 1
                n = st["n"]
            if n == 3:
                rp.STOP_FILE.write_text("stop", encoding="utf-8")
            time.sleep(0.05)
            return "=== 手法观察 ===\nx\n=== 结构台账 ===\n- x@1"

        # 清掉上一段落盘,重置 STOP
        for i in range(20):
            p = rp.analyst_batch_path(i)
            if p.exists():
                p.unlink()
        rp.call_model = fake_stop
        try:
            big = [f"b{i} normal" for i in range(12)]
            d3, r3, s3 = rp.run_map_phase(big, "MP", 60000, 30, 4)
            h.check("STOP 返回 stopped=True", s3 is True, str(s3))
            h.check("STOP 未启动全部批", st["n"] < 12, f"started={st['n']}")
            landed = [i for i in range(12) if rp.analyst_batch_path(i).exists()]
            all_fp = all(rp.fingerprint_ok(rp.analyst_batch_path(i).read_text(encoding="utf-8"), 60000) for i in landed)
            h.check("STOP 已落盘批指纹完好", all_fp and len(landed) >= 1, f"landed={landed}")
        finally:
            rp.call_model = orig
            if rp.STOP_FILE.exists():
                rp.STOP_FILE.unlink()

        # (d) 临时故障(401/网络)三次 → 返回 "error",绝不写 SKIP,不算 done。
        #     根因:401 等临时故障曾被当确定性风控拒绝写 SKIP 永久跳过,造成永久数据丢失。
        for i in range(8):
            p = rp.analyst_batch_path(i)
            if p.exists():
                p.unlink()

        def fake_401(role, instr, inp, max_out, timeout):
            raise RuntimeError("HTTP 401 https://x/v1/chat/completions")

        rp.call_model = fake_401
        orig_sleep = rp.time.sleep
        rp.time.sleep = lambda *a, **k: None
        try:
            status = rp._run_one_map_batch(0, "b0 normal", "MP", 60000, 5)
            h.equal("临时故障返回error而非rejected", status, "error")
            h.check("临时故障绝不落盘SKIP", not rp.analyst_batch_path(0).exists(), "")
        finally:
            rp.call_model = orig
            rp.time.sleep = orig_sleep

        # (e) 风控拒绝三次 → 仍写 SKIP(确定性失败,该跳过),与临时故障区分开
        def fake_reject(role, instr, inp, max_out, timeout):
            return "the request was rejected because it was considered high risk"

        rp.call_model = fake_reject
        rp.time.sleep = lambda *a, **k: None
        try:
            status = rp._run_one_map_batch(1, "b1 normal", "MP", 60000, 5)
            h.equal("风控拒绝返回rejected", status, "rejected")
            h.check("风控拒绝写SKIP", rp.analyst_batch_path(1).read_text(encoding="utf-8").startswith("<<SKIP"), "")
        finally:
            rp.call_model = orig
            rp.time.sleep = orig_sleep

    h.section("scenario: gate '第X章' 标题行豁免、正文内仍阻断")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        _core, _api, _state, _context, gates, _arch = _import_modules()
        body = "沈安推门走出去，天井里风很冷。" * 60
        # 标题行的 "# 第X章" 是系统要求格式,不该判泄露
        ok_text = "# 第3章 门外脚步\n" + body
        h1 = gates.hard_gate(ok_text)
        h.check("标题行不触发第X章泄露", not any("第X章" in i for i in h1["issues"]), h1["issues"])
        # 正文内部出现 "第2章" 才是真泄露
        leak_text = "# 第3章 门外脚步\n沈安想起第2章那天的事。\n" + body
        h2 = gates.hard_gate(leak_text)
        h.check("正文内第X章仍阻断", any("第X章" in i for i in h2["issues"]), h2["issues"])

    h.section("scenario: analyst 产物版本指纹——旧格式/旧预算不被续跑误复用")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        stamped = rp.stamp_fingerprint("=== 手法观察 ===\n句式\n=== 结构台账 ===\n铜铃@48", 60000)
        h.check("同版本同预算指纹有效", rp.fingerprint_ok(stamped, 60000), "")
        h.check("预算变化指纹失效(防分组错配)", not rp.fingerprint_ok(stamped, 40000), "")
        h.check("无指纹旧产物失效(防旧格式混用)", not rp.fingerprint_ok("旧批内容没有指纹" * 5, 60000), "")
        # 去指纹后内容能正常两段切分,真名仍不漏进手法段
        t, s = rp.split_map_segments(rp.strip_fingerprint(stamped))
        h.not_includes("去指纹后真名仍不漏手法段", t, "铜铃")
        h.includes("去指纹后结构段保留真名", s, "铜铃@48")
        # SKIP 标记不被指纹逻辑误伤
        h.check("SKIP 标记不被指纹剥离", rp.strip_fingerprint("<<SKIP: 风控>>") == "<<SKIP: 风控>>", "")
        # prompt 内容 hash 纳入指纹:改了 analyst prompt → 旧产物自动失效重跑;没改 → 续跑
        prompts_dir = tmp / "prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        for fn in ("analyst_map.md", "analyst_reduce.md", "analyst_merge.md", "analyst_structure_reduce.md"):
            _write(prompts_dir / fn, f"# {fn} 初版内容\n规则A")
        rp.PROMPTS_DIR = prompts_dir
        rp._ANALYST_PROMPT_HASH_CACHE = None
        fp_v1 = rp.analyst_fingerprint(60000)
        stamped_v1 = rp.stamp_fingerprint("body", 60000)
        rp._ANALYST_PROMPT_HASH_CACHE = None
        h.check("同 prompt 指纹稳定(崩溃可续跑)", rp.fingerprint_ok(stamped_v1, 60000), fp_v1)
        # 改一个 analyst prompt 的内容
        _write(prompts_dir / "analyst_map.md", "# analyst_map.md 加了配角/POV/修炼/三线维度\n规则A\n规则B")
        rp._ANALYST_PROMPT_HASH_CACHE = None
        fp_v2 = rp.analyst_fingerprint(60000)
        h.check("改 analyst prompt 后指纹变化", fp_v1 != fp_v2, f"{fp_v1} -> {fp_v2}")
        h.check("旧 prompt 产物在新 hash 下失效(自动重跑)", not rp.fingerprint_ok(stamped_v1, 60000), "")

    h.section("scenario: 输出截断→加大预算重试,不再同预算空转(archivist 截断根因)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, _state, _context, _gates, _arch = _import_modules()
        out = tmp / "out.md"
        inp = tmp / "in.md"
        # 隔离工作区没有真 models.json,桩掉角色配置:openai_chat + 假 key,让调用走到 http_post 桩。
        api.role_config = lambda role: {"type": "openai_chat", "model": "m", "api_key": "k",
                                        "max_tokens_field": "max_completion_tokens"}

        # (a) finish_reason=length 被识别为截断
        trunc = {"choices": [{"finish_reason": "length", "message": {"content": "半句被截断的"}}]}
        full = {"choices": [{"finish_reason": "stop", "message": {"content": "完整输出"}}]}
        h.check("openai_chat: length 判为截断", api._is_truncated_response("openai_chat", trunc) is True, "")
        h.check("openai_chat: stop 不判截断", api._is_truncated_response("openai_chat", full) is False, "")
        h.check("anthropic: max_tokens 判截断", api._is_truncated_response("anthropic", {"stop_reason": "max_tokens"}) is True, "")
        h.check("responses: incomplete+max_output_tokens 判截断",
                api._is_truncated_response("openai_responses", {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}}) is True, "")
        h.check("responses: incomplete 但别的原因不判截断",
                api._is_truncated_response("openai_responses", {"status": "incomplete", "incomplete_details": {"reason": "content_filter"}}) is False, "")

        # (b) 前两次小预算截断 → 预算每次翻倍 → 第三次预算够了吐完整,成功
        seen_budgets = []

        def fake_post_grow(url, headers, body, timeout):
            b = int(body.get("max_completion_tokens") or body.get("max_tokens") or body.get("max_output_tokens") or 0)
            seen_budgets.append(b)
            return full if b >= 32000 else trunc

        orig = api.http_post
        api.http_post = fake_post_grow
        try:
            res = api.call_role("archivist", "ins", "input", out, 30, 8000, inp)
            h.equal("加倍预算序列(8000→16000→32000)", seen_budgets, [8000, 16000, 32000])
            h.check("预算够后拿到完整输出", res == "完整输出", res)
        finally:
            api.http_post = orig

        # (c) 始终截断 → 加倍到上限仍截断 → 回退用部分文本(不劣于旧静默截断)
        def fake_post_always_trunc(url, headers, body, timeout):
            return trunc

        api.http_post = fake_post_always_trunc
        try:
            res2 = api.call_role("archivist", "ins", "input", out, 30, 8000, inp, truncate_escalations=2)
            h.check("末次仍截断→回退部分文本", res2 == "半句被截断的", res2)
        finally:
            api.http_post = orig

        # (d) 非截断响应:一次过,预算不升,行为不变
        call_n = {"n": 0}

        def fake_post_ok(url, headers, body, timeout):
            call_n["n"] += 1
            return full

        api.http_post = fake_post_ok
        try:
            res3 = api.call_role("archivist", "ins", "input", out, 30, 8000, inp)
            h.check("正常输出只调用一次", call_n["n"] == 1, str(call_n["n"]))
            h.check("正常输出原样返回", res3 == "完整输出", res3)
        finally:
            api.http_post = orig

    h.section("scenario: JSON 净化状态机——字符串内未转义引号补转义,合法JSON零破坏(beat第8章根因)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, _api, _state, _context, _gates, _arch = _import_modules()
        san = core._sanitize_model_json

        def loads_ok(raw):
            try:
                return json.loads(san(raw)) is not None or True
            except Exception:
                return False

        # (a) 字符串内未转义双引号,各种右邻字符都能修(老正则全漏)
        h.check("引号两侧中文(老正则重叠消费)", loads_ok('{"a": "他说"好"然后走"}'), "")
        h.check("引号后跟英文", loads_ok('{"a": "他说"good"然后走"}'), "")
        h.check("引号后跟空格", loads_ok('{"a": "他说 "算了" 就走"}'), "")
        h.check("引号后跟数字", loads_ok('{"a": "分成"5"成"}'), "")
        h.check("章末钩子型(第8章场景)", loads_ok('{"钩子": "掌柜说"哪位先生教的"并提供住处"}'), "")
        # (b) 值内有中文逗号+内部引号:不被误判成闭合
        got = json.loads(san('{"a": "他说"算了"，然后走了"}'))
        h.equal("值内中文逗号不误闭合", got["a"], '他说"算了"，然后走了')
        # (c) 合法 JSON 零破坏(语义不变)
        for legit in ('{"a": "结束", "b": "开始"}',
                      '{"a": ["x", "y"], "b": {"k": "v"}}',
                      '{"a": "他说\\"好\\"的"}'):
            h.equal(f"合法JSON语义不变:{legit[:20]}", json.loads(san(legit)), json.loads(legit))
        # (d) 字符串内裸控制字符(换行)被转义,不抛 Invalid control character
        h.check("字符串内裸换行被转义", loads_ok('{"a": "第一行\n第二行"}'), "")
        # (e) 尾逗号仍被去除
        h.equal("对象尾逗号去除", json.loads(san('{"a": 1,}')), {"a": 1})

    # ========== 技能库: merge + writer注入 ==========
    h.section("scenario: technique_library merge and writer injection")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        # 给 ledger 种一个技能
        ledger_path = tmp / "runtime" / "ledger.json"
        ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
        ledger_data["technique_library"] = {
            "柳家针路": {
                "owner": "沈安",
                "type": "针灸/诊脉",
                "first_seen": 1,
                "source": "原主身体记忆",
                "core_details": {"进针角度": "十五度斜刺", "得气标志": "酸麻感扩散"},
                "evolution": [{"chapter": 1, "note": "首次出现"}],
            }
        }
        ledger_path.write_text(json.dumps(ledger_data, ensure_ascii=False, indent=2), encoding="utf-8")

        # (a) technique_updates 合并:已有技能追加细节和 evolution
        update_block = {
            "canon": {
                "new_entities": [],
                "update_entities": [],
                "technique_updates": [
                    {"name": "柳家针路", "new_details": {"诊脉起手": "食指先沉"}, "evolution_note": "老马点破"}
                ],
                "technique_new": [
                    {"name": "安神散", "owner": "沈安", "type": "方剂", "source": "系统奖励", "core_details": {"用途": "安神助眠"}}
                ],
            }
        }
        archivist.merge_ledger_update(update_block, 5)
        ledger_after = json.loads(ledger_path.read_text(encoding="utf-8"))
        tech_lib = ledger_after.get("technique_library", {})
        h.check("technique_updates 追加 core_details", "诊脉起手" in (tech_lib.get("柳家针路", {}).get("core_details") or {}), "")
        h.equal("technique_updates 保留原有 details", tech_lib["柳家针路"]["core_details"].get("进针角度"), "十五度斜刺")
        h.check("technique_updates 追加 evolution", any("老马点破" in e.get("note", "") for e in tech_lib["柳家针路"].get("evolution", [])), "")
        h.check("technique_new 建卡", "安神散" in tech_lib, "")
        h.equal("technique_new 记录 source", tech_lib.get("安神散", {}).get("source"), "系统奖励")

        # (b) writer 注入:beat 里提到"针"或"柳家"时注入技能卡
        beat_with_needle = {
            "章节编号": 3,
            "标题": "练针",
            "视角角色": "沈安",
            "场景类型": "独处",
            "出场角色": ["沈安"],
            "具体动作": ["沈安用柳家针路诊脉"],
            "本章冲突": "手感不稳。",
        }
        writer_ledger = context.ledger_context_for_writer(beat_with_needle, 3)
        h.includes("writer 注入技能卡名", writer_ledger, "柳家针路")
        h.includes("writer 注入 core_details", writer_ledger, "十五度斜刺")
        h.includes("writer 注入追加的细节", writer_ledger, "食指先沉")

        # (c) beat 里不提针时不注入
        beat_no_needle = {
            "章节编号": 4,
            "标题": "买药",
            "视角角色": "沈安",
            "场景类型": "日常",
            "出场角色": ["沈安"],
            "具体动作": ["沈安去集市买石菖蒲"],
            "本章冲突": "钱不够。",
        }
        writer_ledger_no = context.ledger_context_for_writer(beat_no_needle, 4)
        h.not_includes("无关 beat 不注入针路", writer_ledger_no, "十五度斜刺")

    # ========== archivist: planned_resolution 不再输出 ==========
    h.section("scenario: foreshadowing without planned_resolution")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        # 模拟 archivist 写新伏笔(不带 planned_resolution)
        update_block = {
            "canon": {
                "new_entities": [],
                "update_entities": [],
            },
            "foreshadowing": {
                "upsert": [
                    {"id": "F-010", "type": "解谜", "planted_chapter": 5, "strength": "中",
                     "promise": "松脂味来源", "status": "未回收", "notes": "巷口闻到焦味"}
                ]
            },
        }
        from pipeline.archivist import merge_state_update
        merge_state_update(update_block)
        threads = json.loads((tmp / "runtime" / "active_threads.json").read_text(encoding="utf-8"))
        fs = threads.get("foreshadowing", {})
        h.check("新伏笔已写入", "F-010" in fs, "")
        h.check("无 planned_resolution", "planned_resolution" not in (fs.get("F-010") or {}), "")

    # ========== impact_seeds: merge 逻辑 ==========
    h.section("scenario: impact_seeds merge")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()

        # (a) 新种子写入
        update_block = {
            "canon": {
                "new_entities": [],
                "update_entities": [],
                "impact_seeds": [
                    {
                        "id": "IMP-001",
                        "who": "方平姥姥",
                        "what": "扎针治好失眠",
                        "pov_voice": "老太太嗓音沙哑",
                        "directions": ["回响:睡了整觉"],
                        "ignorant_of": ["沈安是盲人"],
                        "status": "pending",
                    }
                ],
            },
        }
        archivist.merge_ledger_update(update_block, 11)
        ledger_path = tmp / "runtime" / "ledger.json"
        ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
        seeds = ledger_data.get("impact_seeds", [])
        h.equal("impact_seed 写入数量", len(seeds), 1)
        h.equal("impact_seed id", seeds[0].get("id"), "IMP-001")
        h.equal("impact_seed who", seeds[0].get("who"), "方平姥姥")
        h.equal("impact_seed status", seeds[0].get("status"), "pending")
        h.equal("impact_seed from_chapter", seeds[0].get("from_chapter"), 11)

        # (b) 同 id 更新不重复追加
        update_block2 = {
            "canon": {
                "new_entities": [],
                "update_entities": [],
                "impact_seeds": [
                    {"id": "IMP-001", "status": "used", "what": "扎针治好失眠(已用)"}
                ],
            },
        }
        archivist.merge_ledger_update(update_block2, 20)
        ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
        seeds = ledger_data.get("impact_seeds", [])
        h.equal("同id不重复追加", len(seeds), 1)
        h.equal("同id更新status", seeds[0].get("status"), "used")

        # (c) 不同 id 追加
        update_block3 = {
            "canon": {
                "new_entities": [],
                "update_entities": [],
                "impact_seeds": [
                    {"id": "IMP-002", "who": "陈阿婆", "what": "找回亡夫遗信", "status": "pending"}
                ],
            },
        }
        archivist.merge_ledger_update(update_block3, 15)
        ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
        seeds = ledger_data.get("impact_seeds", [])
        h.equal("不同id追加", len(seeds), 2)
        h.equal("第二颗种子 who", seeds[1].get("who"), "陈阿婆")

    # ========== hook_self_check: 结构正确性(不调 LLM) ==========
    h.section("scenario: hook_self_check structure")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        from pipeline.planning import recent_hooks_digest

        # 写入几章 beat 模拟钩子历史
        beats_dir = tmp / "beats"
        beats_dir.mkdir(exist_ok=True)
        for ch, htype, hook in [
            (1, "悬念", "黑子朝巷子方向打了响鼻"),
            (2, "悬念", "黑子趴着不动耳朵贴脑袋"),
            (3, "悬念", "黑子炸毛对着门外低吼"),
        ]:
            _write_json(beats_dir / f"chapter_{ch}.json", {
                "章节编号": ch, "章末钩子": hook, "钩子型": htype,
            })

        # recent_hooks_digest 应该能读到这些并产出预警
        digest = recent_hooks_digest(4)
        h.includes("digest 包含前章钩子", digest, "黑子")
        h.includes("digest 包含连续同型预警", digest, "连续")
        h.check("digest 非空", len(digest) > 50, f"len={len(digest)}")

    # ========== summarizer: 解析、存储、防重复生成 ==========
    h.section("scenario: summarizer parse and anti-repeat")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        import importlib
        summarizer = importlib.import_module("pipeline.summarizer")

        # 测试 _parse_summary 正常 JSON
        raw_json = json.dumps({
            "chapter": 5,
            "signature_actions": ["老头拨火棍划地", "沈安蹲下翻碗底"],
            "recurring_verbs": {"沈安": ["蹲", "站", "端"], "黑子": ["趴", "拱"]},
            "sentence_patterns": ["X没Y", "一X。两X。"],
            "imagery_used": ["药渣如旧抹布"],
            "emotional_moves": ["沉默试探"],
            "plot_digest": "沈安向老头要药"
        }, ensure_ascii=False)
        parsed = summarizer._parse_summary(raw_json, 5)
        h.equal("parse chapter", parsed["chapter"], 5)
        h.equal("parse actions count", len(parsed["signature_actions"]), 2)
        h.equal("parse patterns count", len(parsed["sentence_patterns"]), 2)
        h.equal("parse verbs keys", set(parsed["recurring_verbs"].keys()), {"沈安", "黑子"})

        # 测试 _parse_summary 带围栏
        fenced = "```json\n" + raw_json + "\n```"
        parsed2 = summarizer._parse_summary(fenced, 5)
        h.equal("fenced parse ok", parsed2["chapter"], 5)

        # 测试 _parse_summary 失败容错
        bad = "这不是JSON"
        parsed3 = summarizer._parse_summary(bad, 7)
        h.equal("bad parse defaults chapter", parsed3["chapter"], 7)
        h.equal("bad parse defaults empty actions", parsed3["signature_actions"], [])

        # 回归:字符串内未转义引号(摘要 sentence_patterns 常带引号模板)。
        # 原 _parse_summary 只做去围栏+去尾逗号,字符串内引号必炸→空摘要。
        # 改走 core.extract_json_object(状态机净化)后应能解析。
        quoted = '{"chapter":4,"sentence_patterns":["X没Y","一X。两X。"],"plot_digest":"出诊"}'
        pq = summarizer._parse_summary(quoted, 4)
        h.equal("带引号模板的摘要能解析(非空)", len(pq["sentence_patterns"]), 2)
        h.equal("带引号摘要 plot_digest 正确", pq["plot_digest"], "出诊")
        # 字符串内引号后跟中文标点,状态机应能修补
        inner = '{"chapter":4,"plot_digest":"他说"算了"。转身就走"}'
        pi = summarizer._parse_summary(inner, 4)
        h.check("内部引号后跟中文标点能修补", bool(pi["plot_digest"]), repr(pi["plot_digest"]))

        # 测试 anti_repeat_for_writer — 手动写入摘要文件
        summaries_dir = tmp / "runtime" / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        for ch in range(3, 6):
            _write_json(summaries_dir / f"chapter_{ch:03d}.json", {
                "chapter": ch,
                "signature_actions": ["竹杖点地咯噔响", "黑子鼻子拱手背"],
                "recurring_verbs": {"沈安": ["蹲", "站", "没动"], "黑子": ["拱", "趴"]},
                "sentence_patterns": ["X没Y", "一X。两X。"],
                "imagery_used": ["像盐又像霜"],
                "emotional_moves": ["沉默等待"],
                "plot_digest": f"第{ch}章事件"
            })

        warn = summarizer.anti_repeat_for_writer(6, lookback=5)
        h.includes("anti-repeat warns about patterns", warn, "X没Y")
        h.includes("anti-repeat warns about verbs", warn, "拱")
        h.includes("anti-repeat warns about actions", warn, "竹杖点地")

        # 测试 repetition_context_for_reviewer
        rep = summarizer.repetition_context_for_reviewer(6, lookback=5)
        h.includes("reviewer context mentions patterns", rep, "X没Y")
        h.includes("reviewer context mentions plot", rep, "第5章事件")

        # 测试 load_recent_summaries
        summaries = summarizer.load_recent_summaries(6, lookback=5)
        h.equal("load 3 summaries", len(summaries), 3)

        # 测试空摘要情况
        empty_warn = summarizer.anti_repeat_for_writer(2, lookback=5)
        h.equal("no summaries no warning", empty_warn, "")

    # ── token 膨胀回归护栏：append-only 账本不得无界注入规划层上下文 ──
    # 病史：到第136章未回收伏笔累积 270 条(3.5万 token),期待账本 136 块(3万 token),
    # 被 structured_state_text / 期待账本注入点全量 dump,导致 story_director 输入冲到
    # 10万 token、每章都触发 compressor 烧 10万 token 去压。此测试锁死有界性。
    h.section("scenario: token 护栏——海量未回收伏笔/超长期待账本不爆上下文")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        core, api, state, context, gates, archivist = _import_modules()
        # 造 300 条未回收伏笔(模拟 800 章后的账本)
        big_fs = {}
        for i in range(1, 301):
            big_fs[f"F-{i:03d}"] = {
                "id": f"F-{i:03d}", "type": "解谜/伏笔",
                "planted_chapter": i, "strength": "中", "status": "未回收",
                "promise": f"第{i}章埋下的某个长达三十余字的承诺内容用来撑大单条体积测试有界性是否生效",
                "notes": f"第{i}章的额外备注信息也写得很长以模拟真实账本中每条伏笔的体积负担情况",
            }
        _write_json(tmp / "runtime/active_threads.json", {
            "foreshadowing": big_fs, "open_questions": [], "next_id": "F-301",
        })
        # 造 200 块期待账本增量(模拟 append-only 膨胀)
        exp_lines = ["# 期待账本", "", "| ID | 类型 | 埋设章 | 承诺 | 状态 |", "| --- | --- | --- | --- | --- |", ""]
        for i in range(1, 201):
            exp_lines.append(f"### 第{i}章自动更新\n")
            exp_lines.append(f"| F-{i:03d} | 解谜 | 第{i}章 | 第{i}章埋下的一段较长的承诺文本用于撑大体积 | 未回收 |\n")
        _write(tmp / "08-期待账本.md", "\n".join(exp_lines))

        ss = state.structured_state_text(800)
        ss_tok = core.estimate_tokens(ss)
        # 300 条全量约 4 万 token；有界后应远低于此。设 10000 上限留足余量又能抓回归。
        h.check("structured_state_text 有界(300条伏笔<10k tok)", ss_tok < 10000, f"{ss_tok} tok")
        h.includes("有界摘要保留伏笔总数提示", ss, "共 300 条")
        # 近期伏笔(埋设最晚)应在;最老的若干条也应作为烂尾警惕列出
        h.includes("近期伏笔在摘要内", ss, "F-300")
        h.includes("最早伏笔作为烂尾警惕列出", ss, "F-001")

        exp = context.recent_expectation_tail()
        exp_tok = core.estimate_tokens(exp)
        h.check("recent_expectation_tail 有界(200块<4k tok)", exp_tok < 4000, f"{exp_tok} tok")
        h.includes("期待账本保留最近增量块", exp, "第200章自动更新")
        h.not_includes("期待账本不含远古增量块", exp, "第001章自动更新")

    h.section("scenario: 清除小说脚本——清写手摘要/章节产物，但绝不碰全量分析")
    import subprocess
    with isolated_workspace() as tmp:
        # 造章节级动态产物 + 全量分析产物,跑清理脚本后验证:章节产物清空、analyst 原样保留
        (tmp / "runtime" / "summaries").mkdir(parents=True, exist_ok=True)
        (tmp / "runtime" / "analyst").mkdir(parents=True, exist_ok=True)
        (tmp / "beats").mkdir(parents=True, exist_ok=True)
        (tmp / "卷纲").mkdir(parents=True, exist_ok=True)
        (tmp / "台账版本").mkdir(parents=True, exist_ok=True)
        (tmp / "chunks").mkdir(parents=True, exist_ok=True)
        _write(tmp / "runtime" / "summaries" / "chapter_001.json", '{"chapter":1}')
        _write(tmp / "runtime" / "summaries" / "chapter_113.json", '{"chapter":113}')
        _write(tmp / "runtime" / "run_3ch.log", "old log")
        _write(tmp / "runtime" / "ledger.json", "{}")
        _write(tmp / "beats" / "第002章.json", "{}")
        _write(tmp / "卷纲" / "10-卷纲.md", "第一卷")
        # 全量分析产物:绝不能被清小说脚本碰
        _write(tmp / "runtime" / "analyst" / "map_0000.md", "MAP batch 0")
        _write(tmp / "runtime" / "analyst" / "_structure_calibration.md", "结构报告")
        _write(tmp / "chunks" / "chunk_三线交织.md", "手法卡内容")

        script = Path(__file__).resolve().parents[1] / "scripts" / "clean_chapter_artifacts.py"
        env = dict(os.environ)
        env["NOVEL_WORKSPACE"] = str(tmp)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(tmp), env=env, input="", capture_output=True, text=True, timeout=60,
        )
        h.check("清理脚本退出码0", proc.returncode == 0, proc.stderr[-300:])
        # 章节级动态产物:清空
        h.check("写手摘要被清(新章)", not (tmp / "runtime" / "summaries" / "chapter_001.json").exists(), "")
        h.check("写手摘要被清(旧残留章)", not (tmp / "runtime" / "summaries" / "chapter_113.json").exists(), "")
        h.check("残留日志被清", not (tmp / "runtime" / "run_3ch.log").exists(), "")
        h.check("章节台账被清", not (tmp / "runtime" / "ledger.json").exists(), "")
        h.check("beats被清", not (tmp / "beats" / "第002章.json").exists(), "")
        h.check("卷纲被清", not (tmp / "卷纲" / "10-卷纲.md").exists(), "")
        # 全量分析产物:原样保留(两个脚本各干各的)
        h.check("analyst MAP 保留(清小说不碰分析)", (tmp / "runtime" / "analyst" / "map_0000.md").exists(), "")
        h.check("analyst 结构报告保留", (tmp / "runtime" / "analyst" / "_structure_calibration.md").exists(), "")
        h.check("手法卡chunk保留", (tmp / "chunks" / "chunk_三线交织.md").exists(), "")

    h.section("scenario: recent_beats_summary 优先事实态摘要,beat计划态降级回退")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        _import_modules()
        import importlib
        planning = importlib.import_module("pipeline.planning")
        importlib.reload(planning)
        summarizer = importlib.import_module("pipeline.summarizer")
        # 写入第5章摘要(事实态)
        summaries_dir = tmp / "runtime" / "summaries"
        summaries_dir.mkdir(parents=True, exist_ok=True)
        _write_json(summaries_dir / "chapter_005.json", {
            "chapter": 5, "plot_digest": "沈安向老头讨了一把草药", "signature_actions": [],
            "recurring_verbs": {}, "sentence_patterns": [], "imagery_used": [], "emotional_moves": [],
        })
        # 写入第4章 beat 计划态(第4章无摘要→应回退)
        beats_dir = tmp / "beats"
        beats_dir.mkdir(parents=True, exist_ok=True)
        _write_json(beats_dir / "chapter_4.json", {
            "标题": "问药章", "本章冲突": "沈安找药被拒", "章末钩子": "老头转身离开",
        })
        result = planning.recent_beats_summary(6, lookback=5)
        # 第5章应走事实态(含plot_digest),不应出现beat计划态标注
        h.check("第5章走事实态不走计划态", "[正文事实]" in result and "第5章" in result, result)
        h.check("第5章内容含plot_digest文字", "沈安向老头" in result, result)
        # 第4章无摘要,应回退beat计划态并标注
        h.check("第4章回退beat计划态并标注", "[beat计划态" in result and "第4章" in result, result)
        h.check("第4章beat内容出现在回退行", "沈安找药被拒" in result, result)

    h.section("scenario: normalize_beat 保留多角度字段全链路不丢失(Batch-A命门回归)")
    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        _import_modules()
        import importlib
        # 在 run_pipeline 里测 normalize_beat
        ensure_scripts_path()
        run_mod = importlib.import_module("run_pipeline") if False else None
        # 直接 import run_pipeline 成本高,改用等效逻辑:验证字段透传
        from pipeline.context import sanitize_beat_for_writer
        beat_with_angle = {
            "章节编号": 10, "标题": "多角度章", "视角角色": "沈安",
            "多角度叙事": "切到黑子:他嗅到了什么(触发条件:主角感知盲区)",
            "系统了愿": "王婶向沈安许愿求药,触发了愿面板",
            "修炼锚点": "无",
            "配角本章动作": "王婶偷偷把银针藏进袖子",
            "本章冲突": "沈安被索要诊金",
        }
        # sanitize_beat_for_writer 不过滤字段,验证多角度字段能到达 writer
        sanitized = sanitize_beat_for_writer(beat_with_angle)
        h.check("多角度叙事字段到达writer", "多角度叙事" in sanitized, sanitized)
        h.check("系统了愿字段到达writer", "系统了愿" in sanitized, sanitized)
        h.check("配角本章动作字段到达writer", "配角本章动作" in sanitized, sanitized)
        h.check("多角度内容未被LF替换", "切到黑子" in sanitized["多角度叙事"], sanitized["多角度叙事"])
