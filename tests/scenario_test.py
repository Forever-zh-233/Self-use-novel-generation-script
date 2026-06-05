# -*- coding: utf-8 -*-
"""Scenario tests using a temporary Novel workspace."""

from __future__ import annotations

import json
import importlib
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
        _write(rp.role_artifact("writer", 2, "draft.md"), draft)
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

    with isolated_workspace() as tmp:
        _seed_workspace(tmp)
        rp = _import_run_pipeline()
        _patch_fast_gates(rp)
        beat = _basic_beat(2)
        _write(rp.role_artifact("writer", 2, "draft.md"), _cache_text("已有初稿"))
        _write(rp.role_artifact("reviewer", 2, "review.md"), """```json
{"needs_revision": false, "total": 49, "blockers": []}
```""")
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
        edited = _cache_text("已有修稿")
        _write(rp.role_artifact("writer", 2, "draft.md"), _cache_text("已有初稿"))
        _write(rp.role_artifact("reviewer", 2, "review.md"), """```json
{"needs_revision": true, "total": 35, "blockers": ["需修稿"]}
```""")
        _write(rp.role_artifact("editor", 2, "edited.md"), edited)
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
        # cleanup 不碰 beats/_debug:模拟清理后留档仍在
        core.cleanup_chapter_artifacts(15, {"artifact_retention": "clean"})
        h.check("cleanup 后调试留档仍在", (folder / "beat_input.md").exists(), "")

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
