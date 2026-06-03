# -*- coding: utf-8 -*-
"""Fast contract and pure-function tests."""

from __future__ import annotations

import json
import os
import importlib

from .helpers import TestHarness, clear_pipeline_modules, ensure_scripts_path, isolated_workspace


def _import_pipeline_modules():
    clear_pipeline_modules()
    ensure_scripts_path()
    core = importlib.import_module("pipeline.core")
    api = importlib.import_module("pipeline.api")
    gates = importlib.import_module("pipeline.gates")
    state = importlib.import_module("pipeline.state")
    return core, api, gates, state


def run(h: TestHarness) -> None:
    h.section("quick: hard gate objective failures")
    with isolated_workspace() as tmp:
        core, api, gates, state = _import_pipeline_modules()

        polluted = "沈安在大隋边境听见老牛叫了一声。"
        gate = gates.hard_gate(polluted)
        h.check("hard_gate blocks source proper noun pollution", not gate["passed"], gate)
        h.check("hard_gate names pollution issue", any("源文专名污染" in item for item in gate["issues"]), gate)

        meta = "沈安翻开台账，看见 LF-001 写着第12章要回收。"
        gate = gates.hard_gate(meta)
        h.check("hard_gate blocks internal ids and meta leaks", not gate["passed"], gate)
        joined = "\n".join(gate["issues"])
        h.includes("hard_gate reports LF leak", joined, "LF-XXX")
        h.includes("hard_gate reports chapter number leak", joined, "第X章")

        mixed_names = "沈安扶住门框，沈归舟却没有回头。"
        gate = gates.hard_gate(mixed_names)
        h.check("hard_gate blocks character alias mixing", not gate["passed"], gate)
        h.check("hard_gate reports alias mixing", any("角色名不一致" in item for item in gate["issues"]), gate)

        filler = "他想起了很多。院子里很静。"
        gate = gates.hard_gate(filler)
        h.check("hard_gate blocks known filler phrase", not gate["passed"], gate)
        h.check("hard_gate reports filler", any("注水" in item for item in gate["issues"]), gate)

        safe = "沈安把竹杖横在膝上。\n黑子蹲在门槛边，鼻尖沾着一点灰。\n风从院墙上过去，没有人说话。"
        gate = gates.hard_gate(safe)
        h.check("hard_gate allows clean short sample", gate["passed"], gate)

    h.section("quick: style gate is diagnostic except objective bad terms")
    with isolated_workspace() as tmp:
        core, api, gates, state = _import_pipeline_modules()

        text = "沈安停在门口。\n黑子没有叫。\n方绾把灯放低。"
        result = gates.style_gate(text)
        h.check("style_gate passes normal prose sample", result["passed"], result)
        h.check("style_gate returns metrics for reviewer", bool(result.get("metrics")), result)
        h.check("style_gate exposes short_sentence_ratio metric", "short_sentence_ratio" in result["metrics"], result)

        bad = "沈安心中一震。"
        result = gates.style_gate(bad)
        h.check("style_gate blocks unambiguous emotion summary term", not result["passed"], result)
        h.check("style_gate reports emotion summary", any("情绪总结词" in item for item in result["issues"]), result)

    h.section("quick: review parsing and JSON cleanup")
    with isolated_workspace() as tmp:
        core, api, gates, state = _import_pipeline_modules()

        review = """```json
{"needs_revision": true, "total": 41, "blockers": ["角色名混用"],}
```

评审正文。
"""
        verdict = gates.parse_review_verdict(review)
        h.equal("review verdict parses sanitized JSON", verdict["source"], "json")
        h.check("review verdict needs revision", verdict["needs_revision"], verdict)
        h.equal("review verdict total", verdict["total"], 41)

        keyword = "本章不合格，建议重写。"
        verdict = gates.parse_review_verdict(keyword)
        h.equal("review verdict keyword fallback", verdict["source"], "keyword")
        h.check("review keyword fallback needs revision", verdict["needs_revision"], verdict)

        clean = "整体可用，没有硬伤。"
        verdict = gates.parse_review_verdict(clean)
        h.equal("review clean keyword fallback source", verdict["source"], "keyword")
        h.check("review clean fallback allows", not verdict["needs_revision"], verdict)

    h.section("quick: API config helpers")
    with isolated_workspace() as tmp:
        (tmp / "config").mkdir(parents=True, exist_ok=True)
        (tmp / "config" / "models.json").write_text(json.dumps({
            "defaultProvider": "openai_main",
            "providers": {
                "openai_main": {
                    "type": "openai_responses",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "",
                    "api_key_env": "NOVEL_TEST_KEY",
                },
                "compat": {
                    "type": "openai_chat",
                    "base_url": "https://example.test/v1",
                    "api_key": "direct-key",
                },
            },
            "roles": {
                "writer": {"provider": "compat", "model": "writer-model"},
                "reviewer": {"provider": "openai_main", "model": "reviewer-model"},
            },
        }, ensure_ascii=False), encoding="utf-8")
        core, api, gates, state = _import_pipeline_modules()

        cfg = api.role_config("writer")
        h.equal("role_config merges provider model", cfg["model"], "writer-model")
        h.equal("role_config keeps provider type", cfg["type"], "openai_chat")
        h.equal("get_api_key uses direct key first", api.get_api_key(cfg, "writer"), "direct-key")

        os.environ["NOVEL_TEST_KEY"] = "env-key"
        try:
            cfg = api.role_config("reviewer")
            h.equal("get_api_key uses configured env var", api.get_api_key(cfg, "reviewer"), "env-key")
        finally:
            os.environ.pop("NOVEL_TEST_KEY", None)

        h.equal("join_url dedupes v1", api.join_url("https://example.test/v1", "/v1/chat/completions"), "https://example.test/v1/chat/completions")

    h.section("quick: core parsing and token helpers")
    with isolated_workspace() as tmp:
        core, api, gates, state = _import_pipeline_modules()
        obj = core.extract_json_object('模型废话\n```json\n{"对白": "他说\\"好\\""}\n```')
        h.equal("extract_json_object parses fenced JSON", obj["对白"], '他说"好"')
        h.check("estimate_tokens counts Chinese heavier than ascii", core.estimate_tokens("沈安") > core.estimate_tokens("AA"))

    h.section("quick: state defaults and chunk aliases")
    with isolated_workspace() as tmp:
        core, api, gates, state = _import_pipeline_modules()
        default_state = state.default_state()
        default_threads = state.default_active_threads()
        default_ledger = state.default_ledger()
        h.equal("default latest chapter is zero", default_state["latest_chapter"], 0)
        h.equal("default next foreshadowing id", default_threads["next_id"], "F-001")
        h.check("default ledger has entities", isinstance(default_ledger.get("entities"), dict), default_ledger)
        aliases = state.chunk_aliases()
        h.equal("chunk alias maps old protagonist name", aliases["沈归舟"], "沈安")
        h.equal("chunk alias maps dog alias", aliases["阿墨"], "黑子")

    h.section("quick: is_process_running 不被陈旧 PID 崩溃(Windows os.kill 兼容)")
    with isolated_workspace() as tmp:
        core, api, gates, state = _import_pipeline_modules()
        # 自身进程必为运行中
        h.check("自身 PID 视为运行中", core.is_process_running(os.getpid()) is True, os.getpid())
        # 非法/不存在的 PID 必须安全返回 False,绝不抛异常(否则 acquire_lock 崩在启动)
        h.equal("PID 0 返回 False", core.is_process_running(0), False)
        h.equal("负 PID 返回 False", core.is_process_running(-1), False)
        # 一个几乎不可能存在的高位 PID:核心是「不抛异常」,陈旧锁能被当作可清理
        crashed = None
        try:
            core.is_process_running(999983)
            crashed = False
        except BaseException:  # noqa: BLE001
            crashed = True
        h.equal("不存在的高位 PID 不抛异常", crashed, False)
