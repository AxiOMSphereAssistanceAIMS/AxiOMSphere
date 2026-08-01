#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = ROOT / "configs/traini/dataset_admission_policy.json"
PRECEDENCE_PATH = ROOT / "configs/traini/slot_route_precedence.json"


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def load_policy() -> dict[str, Any]:
    policy = read_json(CONFIG_PATH)
    policy.setdefault("schema_version", "1.0")
    policy.setdefault("allowed_slots", ["slot14", "slot32", "slot120"])
    policy.setdefault("blocked_pools_for_dataset_admission", ["agent_skill_learning_pool"])
    policy.setdefault("slot120_min_verified_reasoning_pairs", 750)
    policy.setdefault("strict_binary_decisions", True)
    policy.setdefault("human_approval_required", False)
    return policy


def load_precedence() -> dict[str, Any]:
    precedence = read_json(PRECEDENCE_PATH)
    precedence.setdefault("precedence", ["slot32", "slot14", "slot120"])
    return precedence


def report_status(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    data = read_json(path)
    return str(
        data.get("status")
        or data.get("dataset_gate_status")
        or data.get("dataset_admission_status")
        or "MISSING"
    )


def decide_candidate(candidate_dir: Path, policy: dict[str, Any], precedence: dict[str, Any]) -> dict[str, Any]:
    manifest_path = candidate_dir / "candidate_manifest.json"
    if not manifest_path.exists():
        return {
            "candidate_dir": str(candidate_dir),
            "decision": "REJECTED_PROVENANCE_MISSING",
            "reason": "missing candidate_manifest.json",
            "training_allowed": False,
        }

    manifest = read_json(manifest_path)
    source_lesson_id = manifest.get("source_lesson_id") or manifest.get("provenance", {}).get("source_lesson_id")
    source_session_id = manifest.get("source_session_id") or manifest.get("provenance", {}).get("source_session_id")
    target_slot = str(manifest.get("target_slot") or manifest.get("proposed_slot") or "").strip() or None
    target_pool = str(manifest.get("target_pool") or "").strip() or None
    mode = str(manifest.get("mode") or "").strip()

    if not source_lesson_id or not source_session_id:
        decision, reason = "REJECTED_PROVENANCE_MISSING", "missing source_lesson_id or source_session_id"
    else:
        contamination = report_status(candidate_dir / "contamination_report.json")
        dedup = report_status(candidate_dir / "dedup_report.json")
        codex_cli_audit = report_status(candidate_dir / "codex_cli_audit_report.json")
        slot_router = report_status(candidate_dir / "slot_router_report.json")
        dataset_gate = report_status(candidate_dir / "dataset_gate_report.json")
        independent_clearance = manifest.get("independent_clearance") if isinstance(manifest.get("independent_clearance"), dict) else {}
        clearance_required = bool(manifest.get("clearance_required"))
        verified_reasoning_pairs = int(manifest.get("verified_reasoning_pairs") or manifest.get("provenance", {}).get("verified_reasoning_pairs") or 0)
        allowed_slots = set(str(item) for item in policy.get("allowed_slots", []))

        # Resolve the intentional skill-learning terminal before model-only
        # audit checks. It is consumed knowledge, not a failed model pair.
        if target_pool in set(policy.get("blocked_pools_for_dataset_admission", [])) or mode == "agent_skill_learning":
            decision, reason = "CONSUMED_BY_AGENT_SKILL_LEARNING", "consumed by skill-learning route; intentionally excluded from Traini model datasets"
        elif contamination != "PASS":
            decision, reason = "REJECTED_CONTAMINATION", "contamination status is not PASS"
        elif dedup != "PASS":
            decision, reason = "REJECTED_DUPLICATE", "dedup status is not PASS"
        elif codex_cli_audit != "PASS":
            decision, reason = "REJECTED_CODEX_CLI_AUDIT", "Codex CLI pair audit is not PASS"
        elif slot_router != "PASS":
            decision, reason = "REJECTED_SLOT_MISMATCH", "slot router status is not PASS"
        elif clearance_required and independent_clearance.get("decision") != "ADMIT":
            decision, reason = "REJECTED_INDEPENDENT_CLEARANCE", "independent clearance did not return ADMIT"
        elif target_slot == "slot120" and verified_reasoning_pairs < int(policy.get("slot120_min_verified_reasoning_pairs", 750)):
            decision, reason = "BLOCKED_SLOT_THRESHOLD", "slot120 remains blocked until 750 verified reasoning pairs"
        elif target_slot and target_slot not in allowed_slots:
            decision, reason = "REJECTED_UNSUPPORTED_TYPE", f"unsupported target slot: {target_slot}"
        elif dataset_gate not in {"PASS_DATASET_READY", "DATASET_READY", "PASS"}:
            decision, reason = "REJECTED_NOT_DATASET_READY", f"dataset gate status is {dataset_gate}"
        else:
            admission = read_json(candidate_dir / "dataset_gate_report.json").get("dataset_admission_status")
            if admission not in {"APPROVED", "ADMITTED", "PASS"}:
                decision, reason = "REJECTED_NOT_DATASET_READY", "dataset gate not approved"
            else:
                decision, reason = "DATASET_ELIGIBLE", "all deterministic gates passed"

    return {
        "candidate_dir": str(candidate_dir),
        "source_lesson_id": source_lesson_id,
        "source_session_id": source_session_id,
        "target_slot": target_slot,
        "target_pool": target_pool,
        "decision": decision,
        "reason": reason,
        "human_approval_required": False,
        "training_allowed": decision == "DATASET_ELIGIBLE",
        "codex_cli_audit_status": report_status(candidate_dir / "codex_cli_audit_report.json"),
        "route_precedence": precedence.get("precedence", []),
    }


def run_dataset_admission(pair_root: Path) -> dict[str, Any]:
    policy = load_policy()
    precedence = load_precedence()
    decisions: list[dict[str, Any]] = []
    if pair_root.exists():
        for candidate_dir in sorted(p for p in pair_root.iterdir() if p.is_dir()):
            decisions.append(decide_candidate(candidate_dir, policy, precedence))
    report = {
        "status": "PASS",
        "strict_binary_decisions": True,
        "human_approval_required": False,
        "policy": policy,
        "precedence": precedence,
        "total_candidates": len(decisions),
        "dataset_eligible_count": sum(1 for item in decisions if item["decision"] == "DATASET_ELIGIBLE"),
        "skill_learning_consumed_count": sum(1 for item in decisions if item["decision"] == "CONSUMED_BY_AGENT_SKILL_LEARNING"),
        "agent_skill_rejected_count": 0,
        "rejected_count": sum(1 for item in decisions if str(item["decision"]).startswith("REJECTED")),
        "blocked_count": sum(1 for item in decisions if str(item["decision"]).startswith("BLOCKED")),
        "decisions": decisions,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministic Traini dataset admission policy.")
    parser.add_argument("--pair-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run_dataset_admission(args.pair_root)
    write_json(args.out, report)
    print(json.dumps({"status": report["status"], "dataset_eligible_count": report["dataset_eligible_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
