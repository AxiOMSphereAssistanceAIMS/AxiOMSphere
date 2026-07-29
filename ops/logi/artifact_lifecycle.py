#!/usr/bin/env python3
"""Canonical lifecycle for audit and learning artifacts.

The registry is append-only by event, while the materialized status file is
idempotent. Raw content may be deleted only after BENEFIT_VERIFIED and APPLIED
are recorded and the artifact has spent the configured quarantine period.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STATES = ("CREATED", "USED", "BENEFIT_VERIFIED", "APPLIED", "QUARANTINED", "DELETED", "BLOCKED")
TERMINAL = {"DELETED", "BLOCKED"}
BENEFIT_PROBE_PROFILES = (
    frozenset({"ledger_replay", "traini_gate_trace", "knomi_retrieval", "raw_transcript_excluded_from_knomi"}),
    frozenset({"terminal_rejection", "operational_lesson_published", "knomi_retrieval", "raw_transcript_excluded_from_knomi", "traini_rejection_enforced"}),
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TRANSITIONS = {
    "CREATED": {"USED", "BLOCKED"},
    "USED": {"BENEFIT_VERIFIED", "BLOCKED"},
    "BENEFIT_VERIFIED": {"APPLIED", "BLOCKED"},
    "APPLIED": {"QUARANTINED", "BLOCKED"},
    "QUARANTINED": {"DELETED", "BLOCKED"},
    "DELETED": set(),
    "BLOCKED": set(),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def artifact_id(source_id: str, source_path: str = "") -> str:
    return "artifact_" + hashlib.sha256(f"{source_id}:{source_path}".encode()).hexdigest()[:20]


def status_path(root: Path, artifact: str) -> Path:
    return root / "aims_workspace/logi/artifact_lifecycle" / artifact / "status.json"


def events_path(root: Path) -> Path:
    return root / "aims_workspace/logi/artifact_lifecycle/events.jsonl"


def create(root: Path, *, source_id: str, source_path: str, artifact_type: str, owner: str, retention_hours: int = 168) -> dict[str, Any]:
    aid = artifact_id(source_id, source_path)
    path = status_path(root, aid)
    existing = _load(path)
    if existing:
        return existing
    record = {
        "schema_version": "1.0",
        "artifact_id": aid,
        "source_id": source_id,
        "source_path": source_path,
        "artifact_type": artifact_type,
        "owner": owner,
        "state": "CREATED",
        "created_at": iso(now()),
        "used_at": None,
        "benefit_verified_at": None,
        "applied_at": None,
        "quarantine_at": None,
        "deleted_at": None,
        "retention_hours": max(168, int(retention_hours)) if artifact_type == "codex_learning_material" else int(retention_hours),
        "benefit": None,
        "result": None,
        "evidence": [],
        "transition_reason": "created",
    }
    transition(root, record, "CREATED", reason="created")
    return record


def transition(
    root: Path,
    record: dict[str, Any],
    state: str,
    *,
    reason: str,
    evidence: list[str] | None = None,
    benefit: str | None = None,
    result: str | None = None,
    benefit_checks: dict[str, bool] | None = None,
    benefit_evidence: dict[str, dict[str, str]] | None = None,
    deletion_authorization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = str(record.get("state") or "CREATED")
    if state not in STATES:
        raise ValueError(f"unknown lifecycle state: {state}")
    if state != current and state not in TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid lifecycle transition {current} -> {state}")
    if state == "BENEFIT_VERIFIED":
        checks = benefit_checks or {}
        if frozenset(checks) not in BENEFIT_PROBE_PROFILES or not all(value is True for value in checks.values()):
            raise ValueError("BENEFIT_VERIFIED requires an exact passing downstream probe profile")
        probes = benefit_evidence or {}
        if set(probes) != set(checks):
            raise ValueError("BENEFIT_VERIFIED requires evidence for every downstream probe")
        root_resolved = root.resolve()
        typed_probe: dict[str, Any] | None = None
        for name, probe in probes.items():
            path = Path(str(probe.get("path") or ""))
            path = path if path.is_absolute() else root_resolved / path
            try:
                path = path.resolve()
                path.relative_to(root_resolved)
            except (OSError, ValueError):
                raise ValueError(f"benefit evidence escapes workspace: {name}") from None
            digest = str(probe.get("sha256") or "")
            if (
                probe.get("status") != "PASS"
                or SHA256_RE.fullmatch(digest) is None
                or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                raise ValueError(f"benefit evidence is not a current passing artifact: {name}")
            loaded = _load(path)
            if typed_probe is None:
                typed_probe = loaded
            if loaded != typed_probe:
                raise ValueError("benefit checks must reference one exact typed probe report")
        if (
            not typed_probe
            or typed_probe.get("schema") != "aims.closed_loop.benefit_probe.v1"
            or typed_probe.get("source_session_id") != record.get("source_id")
            or typed_probe.get("checks") != checks
        ):
            raise ValueError("benefit probe report schema, source, or checks mismatch")
        supporting = typed_probe.get("supporting_evidence")
        if not isinstance(supporting, dict) or set(supporting) != set(checks):
            raise ValueError("benefit probe supporting evidence is incomplete")
        for name, item in supporting.items():
            support_path = Path(str(item.get("path") or ""))
            support_path = support_path if support_path.is_absolute() else root_resolved / support_path
            try:
                support_path = support_path.resolve()
                support_path.relative_to(root_resolved)
            except (OSError, ValueError):
                raise ValueError(f"supporting evidence escapes workspace: {name}") from None
            support_hash = str(item.get("sha256") or "")
            if (
                item.get("status") != "PASS"
                or SHA256_RE.fullmatch(support_hash) is None
                or not support_path.is_file()
                or hashlib.sha256(support_path.read_bytes()).hexdigest() != support_hash
            ):
                raise ValueError(f"typed supporting evidence failed: {name}")
    if state == "DELETED":
        authorization = deletion_authorization or {}
        expected_target = str(authorization.get("resolved_source_target") or "")
        approved_targets = {str(Path(str(value)).resolve()) for value in authorization.get("exact_targets") or []}
        if not quarantine_ready(record):
            raise ValueError("DELETED requires at least 168 hours in quarantine")
        if (
            authorization.get("approved") is not True
            or authorization.get("action") != "DELETE_QUARANTINED_RAW"
            or authorization.get("lifecycle_source_path") != record.get("source_path")
            or expected_target not in approved_targets
        ):
            raise ValueError("DELETED requires exact operator confirmation for the source target")
    timestamp = iso(now())
    record["state"] = state
    record["transition_reason"] = reason
    if evidence:
        record["evidence"] = sorted(set(record.get("evidence") or []).union(evidence))
    if benefit is not None:
        record["benefit"] = benefit
    if result is not None:
        record["result"] = result
    key = {"USED": "used_at", "BENEFIT_VERIFIED": "benefit_verified_at", "APPLIED": "applied_at", "QUARANTINED": "quarantine_at", "DELETED": "deleted_at"}.get(state)
    if key:
        record[key] = timestamp
    _write(status_path(root, record["artifact_id"]), record)
    with events_path(root).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"artifact_id": record["artifact_id"], "from": current, "to": state, "at": timestamp, "reason": reason}, ensure_ascii=False) + "\n")
    return record


def lifecycle_for_session(
    root: Path,
    *,
    session_id: str,
    source_path: str,
    owner: str,
    evidence: list[str],
    benefit: str,
    result: str,
    benefit_checks: dict[str, bool] | None = None,
    benefit_evidence: dict[str, dict[str, str]] | None = None,
    quarantined: bool = False,
) -> dict[str, Any]:
    """Advance a session only as far as its evidence permits.

    Merely creating lesson/action artifacts proves use, not benefit.  A caller
    must supply named, passing downstream checks before the lifecycle may claim
    BENEFIT_VERIFIED or APPLIED.
    """
    record = create(root, source_id=session_id, source_path=source_path, artifact_type="codex_learning_material", owner=owner)
    if record["state"] == "CREATED":
        record = transition(root, record, "USED", reason="Logi lesson/action trace consumed", evidence=evidence)
    checks = benefit_checks or {}
    verified = bool(checks) and all(checks.values())
    if record["state"] == "USED" and verified:
        check_evidence = [f"benefit_check:{name}=PASS" for name in sorted(checks)]
        record = transition(
            root,
            record,
            "BENEFIT_VERIFIED",
            reason="all named downstream benefit checks passed",
            evidence=[*evidence, *check_evidence],
            benefit=benefit,
            result=result,
            benefit_checks=checks,
            benefit_evidence=benefit_evidence,
        )
    if record["state"] == "BENEFIT_VERIFIED":
        record = transition(root, record, "APPLIED", reason="verified compact lesson published for runtime reuse", evidence=evidence)
    if quarantined and record["state"] == "APPLIED":
        record = transition(root, record, "QUARANTINED", reason="raw staging retained for quarantine window")
    return record


def quarantine_ready(record: dict[str, Any], at: datetime | None = None) -> bool:
    if record.get("state") != "QUARANTINED":
        return False
    stamp = record.get("quarantine_at")
    if not stamp:
        return False
    try:
        started = datetime.fromisoformat(stamp)
    except ValueError:
        return False
    try:
        configured_hours = int(record.get("retention_hours") or 168)
    except (TypeError, ValueError):
        return False
    minimum_hours = 168 if record.get("artifact_type") == "codex_learning_material" else 0
    retention_hours = max(minimum_hours, configured_hours)
    effective_at = at or now()
    return effective_at >= started + timedelta(hours=retention_hours)


def audit(root: Path) -> dict[str, Any]:
    base = root / "aims_workspace/logi/artifact_lifecycle"
    records = [_load(p) for p in base.glob("*/status.json")] if base.exists() else []
    records = [r for r in records if r]
    counts = {state: sum(r.get("state") == state for r in records) for state in STATES}
    pending_quarantine = [r for r in records if r.get("state") == "QUARANTINED" and not quarantine_ready(r)]
    overdue_quarantine = [r for r in records if r.get("state") == "QUARANTINED" and quarantine_ready(r)]
    blockers = [
        r
        for r in records
        if r.get("state") in {"CREATED", "USED", "BENEFIT_VERIFIED", "APPLIED"}
    ] + overdue_quarantine
    return {
        "status": "PASS" if not blockers else "OPEN",
        "total": len(records),
        "counts": counts,
        "pending_quarantine_count": len(pending_quarantine),
        "overdue_quarantine_count": len(overdue_quarantine),
        "blockers": blockers,
    }


def backfill_ledger(root: Path, *, legacy_deleted: bool = False) -> dict[str, Any]:
    """Inventory legacy ledger rows without asserting downstream benefit."""
    if legacy_deleted:
        raise ValueError("legacy deletion bypass is disabled; use raw_material_clearance with exact confirmation")
    ledger = root / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl"
    created = 0
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            session_id = str(row.get("source_session_id") or "")
            if not session_id:
                continue
            evidence = [str(v) for k, v in row.items() if k.endswith("_path") and v]
            record = create(
                root,
                source_id=session_id,
                source_path=str(row.get("raw_package_path") or ""),
                artifact_type="codex_learning_material",
                owner="Logi",
            )
            if record["state"] == "CREATED":
                transition(root, record, "USED", reason="legacy ledger row inventoried; benefit probes pending", evidence=evidence)
            created += 1
    return {"status": "PASS", "records_seen": created, "audit": audit(root)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--backfill-ledger", action="store_true")
    parser.add_argument("--legacy-deleted", action="store_true")
    args = parser.parse_args()
    root = args.workspace.resolve()
    report = backfill_ledger(root, legacy_deleted=args.legacy_deleted) if args.backfill_ledger else audit(root)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
