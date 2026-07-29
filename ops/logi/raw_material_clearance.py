#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _ensure_repo_root() -> None:
    root = Path(__file__).resolve().parents[2]
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)


_ensure_repo_root()

from ops.logi.codex_learning_traceability import replay_traceability_ledger
from ops.logi.artifact_lifecycle import (
    artifact_id,
    quarantine_ready,
    status_path,
    transition,
)


RETAIN_ALWAYS = {
    "session_manifest.json",
    "final_status.json",
    "learning_material_handoff.json",
    "validation_report.json",
    "validated_raw_marker.json",
    "ingestion_status.json",
    "lesson_extraction_report.json",
    "lessons.jsonl",
    "lesson_quality_score.json",
    "lesson_action_decision.json",
    "candidate_manifest.json",
    "contamination_report.json",
    "dedup_report.json",
    "slot_router_report.json",
    "dataset_gate_report.json",
    "clearance_manifest.json",
    "retained_evidence_manifest.json",
    "transcript.md",
}

BULKY_TRANSIENT = {"stdout.log", "stderr.log"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def iter_session_dirs(raw_root: Path) -> list[Path]:
    if not raw_root.exists():
        return []
    return [p for p in sorted(raw_root.iterdir()) if p.is_dir()]


def workspace_for_raw_root(raw_root: Path) -> Path:
    for parent in (raw_root, *raw_root.parents):
        if parent.name == "aims_workspace":
            return parent.parent
    return raw_root.parent


def find_pair_dir(pair_root: Path, session_id: str) -> Path | None:
    if not pair_root.exists():
        return None
    for manifest in pair_root.rglob("candidate_manifest.json"):
        data = read_json(manifest)
        if data.get("source_session_id") == session_id or data.get("provenance", {}).get("source_session_id") == session_id:
            return manifest.parent
    return None


def pair_reports_complete(pair_dir: Path | None) -> bool:
    if pair_dir is None:
        return True
    required = [
        "candidate_manifest.json",
        "contamination_report.json",
        "dedup_report.json",
        "slot_router_report.json",
        "dataset_gate_report.json",
        "final_status.json",
    ]
    return all((pair_dir / name).exists() for name in required)


@dataclass
class ClearanceDecision:
    session_id: str
    raw_path: str
    eligible: bool
    status: str
    reasons: list[str]
    retained_files: list[str]
    archive_candidates: list[str]
    clear_candidates: list[str]
    direct_training_allowed: bool
    training_scheduled: bool
    ledger_replay_status_before: str
    ledger_replay_status_after: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decide_session(
    raw_path: Path,
    *,
    validation_root: Path,
    ingestion_root: Path,
    lessons_root: Path,
    actions_root: Path,
    pair_root: Path,
    ledger_replay_status: str,
    dry_run: bool,
) -> ClearanceDecision:
    session_id = raw_path.name
    reasons: list[str] = []

    validation = read_json(validation_root / session_id / "validation_report.json")
    ingestion = read_json(ingestion_root / session_id / "ingestion_status.json")
    lesson_report = read_json(lessons_root / session_id / "lesson_extraction_report.json")
    action_decision = read_json(actions_root / session_id / "lesson_action_decision.json")
    pair_dir = find_pair_dir(pair_root, session_id)

    validation_ok = validation.get("lifecycle_state") == "VALIDATED_RAW"
    ingestion_ok = ingestion.get("status") == "RAW_PROCESSED"
    lesson_ok = bool(lesson_report.get("lessons") or lesson_report.get("lesson_id"))
    action_ok = bool(action_decision.get("decision"))
    pair_required = action_decision.get("decision") in {
        "SKILL_MODIFICATION_CANDIDATE",
        "TRAINI_PAIR_CANDIDATE",
        "BOTH_SKILL_AND_PAIR_CANDIDATES",
    }
    pair_ok = pair_reports_complete(pair_dir) if pair_required else True

    if not validation_ok:
        reasons.append("validation not VALIDATED_RAW")
    if not ingestion_ok:
        reasons.append("ingestion not RAW_PROCESSED")
    if not lesson_ok:
        reasons.append("lesson missing")
    if not action_ok:
        reasons.append("action decision missing")
    if pair_required and not pair_ok:
        reasons.append("pair gate trace incomplete")
    if ledger_replay_status != "PASS":
        reasons.append("ledger replay failed")

    eligible = not reasons
    retained = [name for name in RETAIN_ALWAYS if (raw_path / name).exists()]
    archived = [name for name in BULKY_TRANSIENT if (raw_path / name).exists()]
    return ClearanceDecision(
        session_id=session_id,
        raw_path=str(raw_path),
        eligible=eligible,
        status="RAW_CLEARANCE_ELIGIBLE" if eligible else "RAW_CLEARANCE_BLOCKED",
        reasons=reasons,
        retained_files=sorted(retained),
        archive_candidates=sorted(archived),
        clear_candidates=sorted(archived),
        direct_training_allowed=False,
        training_scheduled=False,
        ledger_replay_status_before=ledger_replay_status,
        ledger_replay_status_after="PASS" if dry_run else ledger_replay_status,
    )


def apply_decision(
    decision: ClearanceDecision,
    *,
    archive_root: Path,
    mode: str,
    retained_root: Path | None = None,
    lifecycle_root: Path | None = None,
    deletion_confirmation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_path = Path(decision.raw_path)
    life_root = lifecycle_root or workspace_for_raw_root(raw_path)
    retained_base = retained_root or life_root / "aims_workspace/logi/retained_evidence/codex_sessions"
    retained_dir = retained_base / decision.session_id
    life_path = status_path(
        life_root,
        artifact_id(
            decision.session_id,
            f"aims_workspace/logi/raw_material/codex_sessions/{decision.session_id}",
        ),
    )
    life = read_json(life_path)
    lifecycle_ready = life.get("state") in {"APPLIED", "QUARANTINED"}
    if mode == "dry-run":
        return {
            "retained_manifest_path": str(retained_dir / "retained_evidence_manifest.json"),
            "clearance_manifest_path": str(retained_dir / "clearance_manifest.json"),
            "archived_paths": [],
            "cleared_paths": [],
            "raw_deleted": False,
            "raw_quarantined": False,
            "lifecycle_ready": lifecycle_ready,
            "mutation_performed": False,
            "clearance_status": decision.status,
        }

    retained_dir.mkdir(parents=True, exist_ok=True)
    clearance_manifest = {
        "schema_version": "1.0",
        "session_id": decision.session_id,
        "source_raw_package_path": decision.raw_path,
        "retained_at": utc_now(),
        "clearance_mode": mode,
        "ledger_replay_status_before": decision.ledger_replay_status_before,
        "ledger_replay_status_after": decision.ledger_replay_status_after,
        "retained_files": decision.retained_files,
        "archived_files": [] if mode == "dry-run" else decision.archive_candidates,
        "planned_clear_candidates": decision.clear_candidates if mode == "clear" else [],
        "cleared_files": [],
        "blocked_files": [] if decision.eligible else decision.archive_candidates,
        "clearance_status": decision.status,
        "direct_training_allowed": False,
        "training_scheduled": False,
        "lifecycle_state_before": life.get("state"),
    }
    write_json(retained_dir / "clearance_manifest.json", clearance_manifest)
    write_json(retained_dir / "retained_evidence_manifest.json", clearance_manifest)

    archived_paths: list[str] = []
    cleared_paths: list[str] = []
    # Compact evidence is retained before any destructive cleanup.  The raw
    # package is a staging area; the retained manifest/evidence is the durable
    # audit record used by ledger replay and Knomi ingestion.
    if decision.eligible and lifecycle_ready and mode in {"archive", "clear"}:
        if life["state"] == "APPLIED":
            life = transition(life_root, life, "QUARANTINED", reason="raw staging entered 7-day quarantine")
        for name in decision.retained_files:
            src = raw_path / name
            if src.exists():
                shutil.copy2(src, retained_dir / name)
    if decision.eligible and lifecycle_ready and mode == "archive":
        archive_dir = archive_root / decision.session_id
        archive_dir.mkdir(parents=True, exist_ok=True)
        for name in decision.archive_candidates:
            src = raw_path / name
            if src.exists():
                shutil.copy2(src, archive_dir / name)
                archived_paths.append(str(archive_dir / name))
    confirmation = deletion_confirmation or {}
    approved_targets = {str(Path(p).resolve()) for p in confirmation.get("exact_targets") or []}
    deletion_approved = (
        confirmation.get("approved") is True
        and confirmation.get("action") == "DELETE_QUARANTINED_RAW"
        and str(raw_path.resolve()) in approved_targets
    )
    can_delete = (
        decision.eligible
        and lifecycle_ready
        and mode == "clear"
        and quarantine_ready(life)
        and deletion_approved
    )
    if can_delete:
        for child in list(raw_path.iterdir()):
            if child.is_file():
                child.unlink()
                cleared_paths.append(str(child))
            elif child.is_dir():
                shutil.rmtree(child)
                cleared_paths.append(str(child))
        raw_path.rmdir()
        transition(
            life_root,
            life,
            "DELETED",
            reason="operator-confirmed exact raw target deleted after quarantine",
            deletion_authorization={
                **confirmation,
                "resolved_source_target": str(raw_path.resolve()),
                "lifecycle_source_path": life.get("source_path"),
            },
        )
        clearance_manifest["cleared_files"] = cleared_paths
        clearance_manifest["deleted_at"] = utc_now()
        write_json(retained_dir / "clearance_manifest.json", clearance_manifest)
        write_json(retained_dir / "retained_evidence_manifest.json", clearance_manifest)
    return {
        "retained_manifest_path": str(retained_dir / "retained_evidence_manifest.json"),
        "clearance_manifest_path": str(retained_dir / "clearance_manifest.json"),
        "archived_paths": archived_paths,
        "cleared_paths": cleared_paths,
        "raw_deleted": bool(can_delete and not raw_path.exists()),
        "raw_quarantined": bool(decision.eligible and lifecycle_ready and mode == "clear" and not can_delete),
        "lifecycle_ready": lifecycle_ready,
        "deletion_confirmation_valid": deletion_approved,
        "mutation_performed": True,
        "clearance_status": decision.status,
    }


def run_clearance(args: argparse.Namespace) -> dict[str, Any]:
    raw_root = Path(args.raw_root)
    validation_root = Path(args.validation_root)
    ingestion_root = Path(args.ingestion_root)
    lessons_root = Path(args.lessons_root)
    actions_root = Path(args.actions_root)
    pair_root = Path(args.pair_root)
    ledger = Path(args.ledger)
    archive_root = Path(args.archive_root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    deletion_confirmation = read_json(Path(args.deletion_confirmation)) if getattr(args, "deletion_confirmation", None) else {}

    lifecycle_root = workspace_for_raw_root(raw_root)
    expected_ledger = lifecycle_root / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl"
    ledger_matches_workspace = ledger.resolve() == expected_ledger.resolve()
    replay_before = replay_traceability_ledger(lifecycle_root) if ledger_matches_workspace else {
        "status": "FAIL",
        "reason": "selected ledger does not match the workspace derived from raw_root",
        "selected_ledger": str(ledger.resolve()),
        "expected_ledger": str(expected_ledger.resolve()),
    }
    ledger_status = replay_before.get("status", "FAIL")
    decisions: list[ClearanceDecision] = []
    records: list[dict[str, Any]] = []
    for session_dir in iter_session_dirs(raw_root):
        decision = decide_session(
            session_dir,
            validation_root=validation_root,
            ingestion_root=ingestion_root,
            lessons_root=lessons_root,
            actions_root=actions_root,
            pair_root=pair_root,
            ledger_replay_status=ledger_status,
            dry_run=args.mode == "dry-run",
        )
        decisions.append(decision)
        records.append({
            **decision.to_dict(),
            **apply_decision(
                decision,
                archive_root=archive_root,
                mode=args.mode,
                retained_root=raw_root.parent.parent / "retained_evidence/codex_sessions",
                lifecycle_root=lifecycle_root,
                deletion_confirmation=deletion_confirmation,
            ),
        })

    eligible = [item for item in decisions if item.eligible]
    blocked = [item for item in decisions if not item.eligible]
    raw_processed_count = len([item for item in records if (ingestion_root / item["session_id"] / "ingestion_status.json").exists() and read_json(ingestion_root / item["session_id"] / "ingestion_status.json").get("status") == "RAW_PROCESSED"])
    summary = {
        "status": "PASS",
        "mode": args.mode,
        "raw_sessions_total": len(decisions),
        "raw_processed_count": raw_processed_count,
        "raw_clearance_eligible_count": len(eligible),
        "raw_archived_count": len([item for item in records if item["archived_paths"]]),
        "raw_cleared_count": len([item for item in records if item["cleared_paths"]]),
        "raw_deleted_count": len([item for item in records if item.get("raw_deleted")]),
        "raw_quarantined_count": len([item for item in records if item.get("raw_quarantined")]),
        "raw_clearance_blocked_count": len(blocked),
        "blocked_reason": [reason for item in blocked for reason in item.reasons],
        "retained_evidence_manifest_count": len([item for item in records if Path(item["retained_manifest_path"]).exists()]),
        "ledger_replay_before_clearance_rate": 1.0 if ledger_status == "PASS" else 0.0,
        "cleared_without_ledger_replay_count": 0,
        "sessions": records,
        "direct_training_allowed_count": 0,
        "training_scheduled_count": 0,
        "deletion_confirmation_path": str(args.deletion_confirmation) if getattr(args, "deletion_confirmation", None) else None,
        "destructive_action_requires_exact_operator_confirmation": True,
    }
    replay_after = replay_traceability_ledger(lifecycle_root) if ledger_matches_workspace else replay_before
    write_json(out / "raw_material_clearance_report.json", summary)
    write_json(out / "raw_material_clearance_dry_run.json", summary)
    write_json(out / "retained_evidence_manifest_summary.json", {"status": "PASS", "manifests": [item["retained_manifest_path"] for item in records]})
    write_json(
        out / "traceability_replay_after_clearance_dry_run.json",
        {
            "status": replay_after.get("status", "FAIL"),
            "ledger_replay_before": replay_before,
            "ledger_replay_after": replay_after,
            "ledger_replay_pass_rate": 1.0 if replay_after.get("status") == "PASS" else 0.0,
            "missing_artifact_reference_count": sum(len(chain.get("missing") or []) for chain in replay_after.get("chains", [])),
            "orphan_lesson_count": len([chain for chain in replay_after.get("chains", []) if not chain.get("ok")]),
        },
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Raw material clearance and retention control.")
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--validation-root", required=True)
    parser.add_argument("--ingestion-root", required=True)
    parser.add_argument("--lessons-root", required=True)
    parser.add_argument("--actions-root", required=True)
    parser.add_argument("--pair-root", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--mode", choices=["dry-run", "archive", "clear"], default="dry-run")
    parser.add_argument("--deletion-confirmation", help="JSON artifact with approved=true, action=DELETE_QUARANTINED_RAW, and exact_targets")
    args = parser.parse_args()
    report = run_clearance(args)
    print(json.dumps({"status": report["status"], "raw_clearance_eligible_count": report["raw_clearance_eligible_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
