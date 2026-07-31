#!/usr/bin/env python3
"""Run one bounded Codex -> Logi learning processing pulse.

This entrypoint is deliberately no-training. It consumes only scanner-created
VALIDATED_RAW markers and writes evidence for each bounded run.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.logi.codex_learning_traceability import (
    create_skill_change_candidate,
    create_traini_pair_candidate,
    decide_lesson_action,
    extract_lesson_from_ingested_session,
    ingest_validated_codex_package,
    rel,
    replay_traceability_ledger,
    run_e2e_traceability_for_session,
    scan_codex_raw_packages,
    write_json,
)
from ops.logi.artifact_lifecycle import lifecycle_for_session


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _ledger_count(ledger: Path) -> int:
    return len(_read_jsonl(ledger))


def _ledger_session_ids(ledger: Path) -> set[str]:
    return {str(row.get("source_session_id")) for row in _read_jsonl(ledger) if row.get("source_session_id")}


def run_once(args: argparse.Namespace) -> dict:
    root = Path(args.workspace).resolve()
    evidence_dir = (root / args.evidence_dir).resolve() if not Path(args.evidence_dir).is_absolute() else Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ledger = (root / args.ledger).resolve() if not Path(args.ledger).is_absolute() else Path(args.ledger)
    if not args.no_training:
        raise SystemExit("--no-training is required")

    before_count = _ledger_count(ledger)
    scan = scan_codex_raw_packages(root, stale_running_seconds=args.stale_running_seconds)
    validation_root = root / args.validation_root
    markers = sorted(validation_root.glob("*/validated_raw_marker.json"))
    processed = []
    skipped = []
    processed_ids = _ledger_session_ids(ledger)
    marker_batch = markers if args.max_items <= 0 else markers[: args.max_items]
    for marker in marker_batch:
        session_id = marker.parent.name
        if session_id in processed_ids:
            skipped.append({"session_id": session_id, "reason": "already_terminal_in_ledger"})
            continue
        validation_report = marker.parent / "validation_report.json"
        q_report = root / "aims_workspace/logi/quarantine/codex_sessions" / session_id / "quarantine_report.json"
        validation_state = None
        if validation_report.exists():
            try:
                validation_state = json.loads(validation_report.read_text(encoding="utf-8")).get("lifecycle_state")
            except Exception:
                validation_state = None
        if validation_state and validation_state.startswith("QUARANTINED"):
            skipped.append({"session_id": session_id, "reason": "quarantined"})
            continue
        if not marker.exists() and q_report.exists():
            skipped.append({"session_id": session_id, "reason": "quarantined"})
            continue
        result = run_e2e_traceability_for_session(session_id, root)
        if result.get("status") == "PASSED":
            lifecycle = lifecycle_for_session(
                root,
                session_id=session_id,
                source_path=f"aims_workspace/logi/raw_material/codex_sessions/{session_id}",
                owner="Logi",
                evidence=[str(value) for key, value in (result.get("ledger") or {}).items() if key.endswith("_path") and value],
                benefit="lesson and gated skill/pair artifacts were produced",
                result="Logi consumption recorded; downstream benefit verification pending",
                benefit_checks=None,
                quarantined=False,
            )
            result["artifact_lifecycle"] = lifecycle
        processed.append(result)

    after_count = _ledger_count(ledger)
    replay = replay_traceability_ledger(root)
    lessons_created = sum(1 for item in processed if item.get("lesson"))
    decisions_created = sum(1 for item in processed if item.get("decision"))
    skill_candidates = sum(1 for item in processed if item.get("skill"))
    pair_candidates = sum(1 for item in processed if item.get("pair"))
    full_gate_trace = 0
    for item in processed:
        pair = item.get("pair") or {}
        if all(pair.get(key) for key in ("contamination_report_path", "dedup_report_path", "slot_router_report_path", "dataset_gate_report_path")):
            full_gate_trace += 1
    unsafe = [
        item
        for item in processed
        if item.get("training_scheduled") or item.get("direct_training_allowed") is not False
    ]
    report = {
        "status": "PASSED" if not unsafe and replay["status"] == "PASS" else "FAILED",
        "mode": "CONTROLLED_LOGI_CODEX_ONE_SHOT",
        "no_training": True,
        "no_traini_schedule": True,
        "no_model_promotion": True,
        "only_validated_raw_processed": True,
        "max_items": args.max_items,
        "scan": scan,
        "processed_count": len(processed),
        "processed_sessions": [item.get("ledger", {}).get("source_session_id") for item in processed],
        "skipped": skipped,
        "lessons_created": lessons_created,
        "action_decisions_created": decisions_created,
        "skill_candidates_created": skill_candidates,
        "pair_candidates_created": pair_candidates,
        "pair_candidates_with_full_gate_trace": full_gate_trace,
        "ledger_records_added": after_count - before_count,
        "ledger_replay": replay,
        "training_scheduled_count": 0,
        "raw_direct_training_admission_count": 0,
        "unsafe_candidate_count": len(unsafe),
        "processed": processed,
    }
    write_json(evidence_dir / "logi_processing_pulse_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded no-training Codex learning pulse.")
    parser.add_argument("--workspace", default="/home/axi_omi_sphere/aims-workspace")
    parser.add_argument("--raw-root", default="aims_workspace/logi/raw_material/codex_sessions")
    parser.add_argument("--validation-root", default="aims_workspace/logi/validation/codex_sessions")
    parser.add_argument("--ingestion-root", default="aims_workspace/logi/ingestion/codex_sessions")
    parser.add_argument("--lessons-root", default="aims_workspace/logi/lessons/codex_sessions")
    parser.add_argument("--actions-root", default="aims_workspace/logi/action_decisions/codex_sessions")
    parser.add_argument("--pair-root", default="aims_workspace/logi/traini_pair_candidates")
    parser.add_argument("--ledger", default="aims_workspace/logi/traceability/learning_traceability_ledger.jsonl")
    parser.add_argument("--max-items", type=int, default=0, help="0 means drain every validated package")
    parser.add_argument("--stale-running-seconds", type=int, default=3600)
    parser.add_argument("--no-training", action="store_true")
    parser.add_argument("--evidence-dir", required=True)
    args = parser.parse_args()
    report = run_once(args)
    print(json.dumps({"status": report["status"], "processed_count": report["processed_count"]}, indent=2))
    return 0 if report["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
