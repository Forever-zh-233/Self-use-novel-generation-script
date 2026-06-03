#!/usr/bin/env python3
"""One-shot script to split run_pipeline.py into pipeline/ package modules.

Run from E:\\Novel 1:
  python scripts/_split_pipeline.py

This script:
1. Reads scripts/run_pipeline.py
2. Extracts functions into module files under scripts/pipeline/
3. Rewrites run_pipeline.py to import from the new modules
"""

import re
from pathlib import Path

SRC = Path(__file__).parent / "run_pipeline.py"
PKG = Path(__file__).parent / "pipeline"

# Read source
with open(SRC, encoding="utf-8") as f:
    lines = f.readlines()

# --- Step 1: Parse all top-level definitions and their line ranges ---

def find_functions(lines):
    """Return list of (start_line_idx, end_line_idx, name, body_lines)."""
    funcs = []
    starts = []
    for i, line in enumerate(lines):
        if re.match(r"^(def |class )", line):
            name = re.match(r"^(?:def |class )(\w+)", line).group(1)
            starts.append((i, name))
    for idx, (start, name) in enumerate(starts):
        end = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        # Include preceding comments/decorators
        actual_start = start
        while actual_start > 0 and lines[actual_start - 1].strip().startswith(("#", "@", '"""', "'''")):
            actual_start -= 1
        funcs.append((actual_start, end, name, lines[actual_start:end]))
    return funcs

all_funcs = find_functions(lines)
func_map = {name: (s, e, body) for s, e, name, body in all_funcs}

# --- Step 2: Define module assignments ---

CORE_FUNCS = [
    "load_env_local", "manuscript_path", "role_output_dir", "role_artifact",
    "chapter_artifact_prefix", "read_text", "write_text", "append_text",
    "load_json", "dump_json", "estimate_tokens", "now_text", "cli_print",
    "write_progress", "progress_bar", "poll_keyboard_control", "wait_if_paused",
    "stage_start", "stage_done", "acquire_lock", "release_lock", "is_process_running",
    "load_models", "load_run_config", "artifact_retention_mode",
    "cleanup_empty_output_dirs", "cleanup_chapter_artifacts",
    # Moved here to break cycles:
    "_sanitize_model_json",  # was archivist, used by gates
    # write_score_report stays in run_pipeline.py (depends on gates.needs_revision)
]

API_FUNCS = [
    "role_config", "get_api_key", "join_url", "configured_base_url",
    "configured_headers", "configured_extra_body", "RequestTimeout",
    "http_post", "extract_responses_text", "extract_chat_text",
    "extract_anthropic_text", "call_model", "role_max_output_tokens",
    "call_role", "role_context_window", "role_compress_threshold",
]

STATE_FUNCS = [
    "default_state", "default_active_threads", "default_ledger",
    "load_ledger", "load_state", "load_active_threads",
    "render_state_markdown", "render_active_threads_markdown", "write_state_mirrors",
    "_trim_state_for_context", "structured_state_text",
    "load_active_arcs", "save_active_arcs",
    "load_story_director", "save_story_director",
    "load_index", "chunk_aliases", "resolve_chunk_key", "load_chunk",
    "load_strand_config",
    # Moved here to break cycles:
    "normalize_strand", "update_strand_tracker",  # was context, used by archivist
    "render_story_director_markdown",  # was planning, used by state.save_story_director
    "volume_summary",  # was planning, used by state.write_state_mirrors
]

CONTEXT_FUNCS = [
    "make_section", "render_sections", "select_sections_for_budget",
    "compress_sections_if_needed",
    "writer_state_digest", "ledger_context_for_writer",
    "character_arcs_for_writer", "recent_ledger_tail",
    "safe_story_core_for_writer", "current_mc_realm",
    "safe_cultivation_for_writer", "safe_world_bible_for_writer",
    "safe_outline_for_writer", "long_foreshadowing_text",
    "sanitize_beat_for_writer", "select_chunks",
    "strand_pacing_warnings", "strand_digest_for_director",
    "pacing_variety_warnings", "emotional_distribution_warnings",
    "chapter_satisfaction_check", "power_scaling_for_chapter",
    "recent_signature_warnings", "writer_focus_modules",
    "build_writer_sections", "build_writer_input",
]

GATES_FUNCS = [
    "check_vision_consistency", "fact_check_against_ledger",
    "hard_gate", "style_gate", "continuity_check", "type_guard_check",
    "combine_checks",
    "project_character_names", "extract_character_mentions",
    "cast_checklist_for_reviewer", "make_review_input",
    "_parse_review_keywords", "parse_review_verdict",
    "parse_score_needs_revision", "needs_revision",
]

PLANNING_FUNCS = [
    "extract_volume_stage_for_chapter", "default_story_director_state",
    "story_director_prompt",
    "obligations_due_digest", "threads_digest_for_director",
    "_outline_digest_for_director", "build_story_director_input",
    "run_story_director", "story_director_context",
    "emotional_anchors_for_planner",
    "generate_master_outline", "current_volume_info", "needs_volume_planning",
    "long_foreshadowing_progress", "_generate_volume_digest",
    "run_volume_planner",
    "in_climax_window", "needs_arc_planning",
    "recent_beats_summary", "previous_arcs_summary",
    "build_arc_input", "run_arc_planner", "active_arcs_for_beat",
    "build_beat_input", "previous_final_excerpt", "recent_text_blob",
]

ARCHIVIST_FUNCS = [
    "extract_markdown_section", "_prune_empty",
    "_parse_structured_payload", "extract_structured_update",
    "merge_state_update", "merge_ledger_update",
    "write_ledger_markdown", "apply_character_arc_note",
    "validate_archivist_report", "apply_archivist_update",
]

# Everything else stays in run_pipeline.py

# --- Step 3: Verify all functions are assigned ---

assigned = set(CORE_FUNCS + API_FUNCS + STATE_FUNCS + CONTEXT_FUNCS + GATES_FUNCS + PLANNING_FUNCS + ARCHIVIST_FUNCS)
all_names = set(func_map.keys())
remaining = all_names - assigned
print(f"Total functions: {len(all_names)}")
print(f"Assigned to modules: {len(assigned)}")
print(f"Remaining in run_pipeline.py: {len(remaining)}")
print(f"Remaining: {sorted(remaining)}")

# Verify no assigned function is missing from source
missing = assigned - all_names
if missing:
    print(f"WARNING: These assigned functions don't exist in source: {missing}")
    raise SystemExit(1)

# --- Step 3: Extract and write module files ---

def extract_body(func_names):
    """Extract function bodies in source order, preserving blank lines between."""
    ordered = sorted([(func_map[n][0], func_map[n][1], n) for n in func_names if n in func_map])
    result = []
    for start, end, name in ordered:
        result.extend(lines[start:end])
    return "".join(result)


MODULES = {
    "core": CORE_FUNCS,
    "api": API_FUNCS,
    "state": STATE_FUNCS,
    "context": CONTEXT_FUNCS,
    "gates": GATES_FUNCS,
    "planning": PLANNING_FUNCS,
    "archivist": ARCHIVIST_FUNCS,
}

for mod_name, func_list in MODULES.items():
    body = extract_body(func_list)
    out_path = PKG / f"{mod_name}.py"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# -*- coding: utf-8 -*-\n")
        f.write(f'"""pipeline.{mod_name} — auto-extracted."""\n\n')
        f.write("# === IMPORTS TO BE ADDED ===\n")
        f.write("import json, os, re, sys, time, threading\n")
        f.write("import urllib.error, urllib.request\n")
        f.write("from pathlib import Path\n")
        f.write("from typing import Any, Dict, List, Optional\n\n")
        f.write(body)
    line_count = body.count("\n")
    print(f"  Wrote {out_path.name} ({line_count} lines)")

print("\nModule files written. Next: fix imports in each module.")
