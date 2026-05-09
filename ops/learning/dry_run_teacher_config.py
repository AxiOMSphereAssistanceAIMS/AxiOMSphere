#!/usr/bin/env python3
"""Dry-run config check for teacher combo integration.

Prints current env values for all teacher combo variables and shows
which model is bound to which role. Makes NO LLM calls, starts NO tuning.

Usage:
    python ops/learning/dry_run_teacher_config.py
"""
from __future__ import annotations

import os


_DEFAULTS = {
    "OMNIROUTE_BASE_URL":        "http://127.0.0.1:20128/v1",
    "OMNIROUTE_MODEL":           "gemini-free-fallback",
    "OMNIROUTE_EXTRACT_MODEL":   "doc-extract-combo",
    "OMNIROUTE_EXPERT_MODEL":    "doc-standard-expert-combo",
    "OMNIROUTE_TEACHER_MODEL":   "doc-training-standards-best",
    "OMNIROUTE_AUDIT_MODEL":     "doc-training-pair-audit-combo",
    "AIMS_AUDIT_PAIRS_SHADOW":   "0",
}

_ROLES = {
    "OMNIROUTE_EXTRACT_MODEL":  "on_ingest() — document clause Q&A generation",
    "OMNIROUTE_EXPERT_MODEL":   "on_rag_query() — RAG answer scoring",
    "OMNIROUTE_TEACHER_MODEL":  "on_generation() / from_eval() / nim_synth / auto_pair — training pair generation",
    "OMNIROUTE_AUDIT_MODEL":    "save_quality_pair() shadow audit (only when AIMS_AUDIT_PAIRS_SHADOW=1)",
}


def _val(key: str) -> tuple[str, bool]:
    """Returns (resolved_value, is_from_env)."""
    v = os.environ.get(key)
    if v:
        return v, True
    return _DEFAULTS.get(key, "<unset>"), False


def main() -> None:
    print("\n=== AIMS Teacher Combo Dry-Run Config ===\n")

    print("Base / fallback:")
    for key in ("OMNIROUTE_BASE_URL", "OMNIROUTE_MODEL"):
        v, from_env = _val(key)
        src = "env" if from_env else "default"
        print(f"  {key:<32} = {v}  [{src}]")

    print("\nShadow audit:")
    v, from_env = _val("AIMS_AUDIT_PAIRS_SHADOW")
    src = "env" if from_env else "default"
    active = "ACTIVE" if v == "1" else "inactive"
    print(f"  AIMS_AUDIT_PAIRS_SHADOW          = {v}  [{src}]  → shadow audit is {active}")

    print("\nTeacher combo model bindings:")
    for key, role in _ROLES.items():
        v, from_env = _val(key)
        src = "env" if from_env else "default"
        print(f"\n  {key}")
        print(f"    model  : {v}  [{src}]")
        print(f"    role   : {role}")

    print("\nSummary — effective model routing:")
    extract,  _ = _val("OMNIROUTE_EXTRACT_MODEL")
    expert,   _ = _val("OMNIROUTE_EXPERT_MODEL")
    teacher,  _ = _val("OMNIROUTE_TEACHER_MODEL")
    audit,    _ = _val("OMNIROUTE_AUDIT_MODEL")
    shadow,   _ = _val("AIMS_AUDIT_PAIRS_SHADOW")
    base_url, _ = _val("OMNIROUTE_BASE_URL")

    print(f"  on_ingest()         → {extract}  @ {base_url}")
    print(f"  on_rag_query()      → {expert}  @ {base_url}")
    print(f"  on_generation()     → {teacher}  @ {base_url}")
    print(f"  from_eval()         → {teacher}  @ {base_url}")
    print(f"  nim_synth DEFAULT   → {teacher}  @ {base_url}")
    print(f"  nim_client TEACHER  → {teacher}  @ {base_url}")
    print(f"  auto_pair teacher   → {teacher}  @ {base_url}")
    print(f"  shadow audit        → {audit}  @ {base_url}  (enabled={shadow == '1'})")

    print()
    if shadow == "1":
        print("WARNING: Shadow audit is ACTIVE — extra API call per saved pair.")
    else:
        print("Shadow audit is inactive (AIMS_AUDIT_PAIRS_SHADOW=0). No extra calls.")
    print()


if __name__ == "__main__":
    main()
