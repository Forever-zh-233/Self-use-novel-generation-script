# -*- coding: utf-8 -*-
"""Scenario tests using a temporary Novel workspace."""

from __future__ import annotations

import json
import importlib
import sys
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
  "canon": {
    "update_entities": [
      {"name": "沈安", "add_facts": ["听见门外脚步"], "realm_change": "叩门"}
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

        new_ledger = json.loads((tmp / "runtime/ledger.json").read_text(encoding="utf-8"))
        h.check("ledger merge adds new entity", "叩门客" in new_ledger["entities"], new_ledger)
        h.check("ledger merge appends facts", "听见门外脚步" in new_ledger["entities"]["沈安"]["facts"], new_ledger["entities"]["沈安"])

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
