from __future__ import annotations

from pathlib import Path
from typing import Any

from agents.self_learning.hermes_operational_status.claim_schema import HermesClaim
from agents.self_learning.hermes_operational_status.evidence_resolver import (
    find_active_skill_adoption_evidence,
    load_rejection_summary,
    path_exists,
    read_json,
)


def _supported(claim: HermesClaim, confidence: str = "ARTIFACT_VERIFIED") -> dict[str, Any]:
    claim.evidence_found = True
    claim.confidence = confidence
    claim.result = "SUPPORTED"
    return claim.to_dict()


def _unsupported(claim: HermesClaim, missing: list[str], confidence: str = "UNVERIFIED") -> dict[str, Any]:
    claim.evidence_found = False
    claim.missing_evidence = missing
    claim.confidence = confidence
    claim.result = "NOT_SUPPORTED"
    return claim.to_dict()


def verify_claim(claim: dict[str, Any], out_dir: Path, assist_dir: Path, rejection_dir: Path) -> dict[str, Any]:
    c = HermesClaim(**{k: v for k, v in claim.items() if k in HermesClaim.__dataclass_fields__})
    c.evidence_checked = list(c.required_evidence)

    if c.claim_type == "REPAIRMAN_COMPLETION":
        status_path = assist_dir / "latest_status_artifact.json"
        status = read_json(status_path, {})
        if not status_path.exists():
            return _unsupported(c, ["latest_status_artifact.json"])
        st = str(status.get("status", ""))
        if st.startswith("BLOCKED_") or st in {"COMPLETED", "FAILED", "TIMEOUT"}:
            c.evidence_paths = [str(status_path)]
            c.subject = str(status.get("audit_id") or c.subject)
            return _supported(c, "ARTIFACT_VERIFIED")
        return _unsupported(c, [f"terminal_status_missing:{st or 'empty'}"], "CONFLICTING")

    if c.claim_type == "HERMES_REVIEW":
        p1 = assist_dir / "hermes_assistance_results.json"
        p2 = assist_dir / "hermes_assistance_followup_report.json"
        has1 = path_exists(p1)
        has2 = path_exists(p2)
        if has1 or has2:
            c.evidence_paths = [str(p) for p in (p1, p2) if p.exists()]
            return _supported(c, "ARTIFACT_VERIFIED")
        return _unsupported(c, ["hermes_assistance_results.json", "hermes_assistance_followup_report.json"])

    if c.claim_type == "SKILL_ADOPTION":
        ok, paths = find_active_skill_adoption_evidence(assist_dir)
        if ok:
            c.evidence_paths = paths
            return _supported(c, "ARTIFACT_VERIFIED")
        return _unsupported(c, ["repairman_active_skill_registry.json", "repairman_owner_skill_bindings.json", "repairman_adoption_test_results.json"])

    if c.claim_type == "CONTAINER_HEALTH":
        # No live checker in this workflow branch: never claim live-verified.
        health_art = out_dir / "hermes_status_report.json"
        if health_art.exists():
            c.evidence_paths = [str(health_art)]
            c.result = "PARTIAL"
            c.confidence = "CACHED_ARTIFACT"
            c.evidence_found = True
            c.missing_evidence = ["live_health_check_required_for_live_verified"]
            return c.to_dict()
        return _unsupported(c, ["live_health_check_required_for_live_verified"])

    if c.claim_type == "HERMES_REJECTION":
        summary = load_rejection_summary(rejection_dir)
        real = int(summary.get("real_rejections", 0) or 0)
        ignored = int(summary.get("mock_rejections_ignored", 0) or 0)
        c.evidence_paths = [str(rejection_dir / "rejection_summary.json")] if (rejection_dir / "rejection_summary.json").exists() else []
        if real > 0:
            return _supported(c, "ARTIFACT_VERIFIED")
        c.result = "PARTIAL"
        c.confidence = "ARTIFACT_VERIFIED"
        c.evidence_found = True
        c.missing_evidence = [f"real_rejections=0", f"mock_rejections_ignored={ignored}"]
        return c.to_dict()

    if c.claim_type in {"MODEL_USED", "SLOT_POLICY", "TASK_STATUS", "LIVE_RUNTIME", "ARTIFACT_STATUS"}:
        # Generic artifact claim: require status json presence
        p = out_dir / "hermes_current_status.json"
        if p.exists():
            c.evidence_paths = [str(p)]
            return _supported(c, "CACHED_ARTIFACT")
        return _unsupported(c, ["hermes_current_status.json"])

    return _unsupported(c, ["unsupported_claim_type"], "UNVERIFIED")


def verify_claims(claims: list[dict[str, Any]], out_dir: Path, assist_dir: Path, rejection_dir: Path) -> list[dict[str, Any]]:
    return [verify_claim(c, out_dir=out_dir, assist_dir=assist_dir, rejection_dir=rejection_dir) for c in claims]

