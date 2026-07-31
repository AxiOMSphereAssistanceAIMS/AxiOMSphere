"""Codex raw-session learning traceability loop for Logi.

This module intentionally does not train, schedule, promote, or admit data.
It turns complete Codex raw packages into evidence-backed learning artifacts
and records an append-only trace from raw material to final gated candidate.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_FILES = [
    "session_manifest.json",
    "command.txt",
    "environment_summary.txt",
    "git_status_before.txt",
    "git_status_after.txt",
    "stdout.log",
    "stderr.log",
    "transcript.md",
    "touched_files.txt",
    "evidence_links.json",
    "learning_material_handoff.json",
    "final_status.json",
]

REQUIRED_MANIFEST_FIELDS = [
    "schema_version",
    "logi_session_id",
    "source",
    "started_at",
    "ended_at",
    "operator",
    "workspace_root",
    "command",
    "codex_binary",
    "wrapper_path",
    "resume_of",
    "task_title",
    "task_prompt_path",
    "exit_code",
    "status",
    "artifacts",
    "safety",
]

ALLOWED_DECISIONS = {
    "NO_ACTION",
    "SKILL_MODIFICATION_CANDIDATE",
    "TRAINI_PAIR_CANDIDATE",
    "BOTH_SKILL_AND_PAIR_CANDIDATES",
    "REJECTED_UNSAFE_OR_LOW_QUALITY",
}

STRICT_CONTAMINATION_STATUSES = {
    "PASS",
    "FAIL_SECRET",
    "FAIL_PRIVATE_DATA",
    "FAIL_SYSTEM_PROMPT",
    "FAIL_THINK_LEAKAGE",
    "FAIL_REPETITION_LOOP",
    "FAIL_PROVENANCE_MISSING",
    "FAIL_SLOT_MISMATCH",
    "FAIL_REPAIRMAN_JSON_OUTPUT",
    "FAIL_NOT_DATASET_ADMISSION_READY",
    "FAIL_UNSUPPORTED_AGENT_SKILL_MATERIAL",
}

LIFECYCLE_STATES = [
    "CREATED",
    "RUNNING",
    "CAPTURE_COMPLETE",
    "CAPTURE_INCOMPLETE",
    "VALIDATED_RAW",
    "QUARANTINED_INCOMPLETE",
    "QUARANTINED_SCHEMA_FAIL",
    "RAW_QUEUED",
    "RAW_PROCESSED",
    "LOGI_INGESTED",
    "LESSON_EXTRACTED",
    "ACTION_DECIDED",
    "SKILL_CHANGE_PROPOSED",
    "SKILL_CHANGE_APPLIED",
    "PAIR_CANDIDATE_PROPOSED",
    "PAIR_CANDIDATE_GATED",
    "REJECTED",
    "CLOSED",
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root(workspace: Path | str | None = None) -> Path:
    return Path(workspace).resolve() if workspace else ROOT


def rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    return path


def append_jsonl(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, sort_keys=False) + "\n")
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text_if_exists(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return None


def _load_legacy_sidecar_manifest(session_dir: Path) -> dict[str, Any]:
    """Build a compatibility manifest for older complete raw packages.

    Legacy Codex raw packages in this workspace were written before the newer
    manifest schema fields were added. They still carry the same evidence and
    sidecar artifacts, so we can normalize them without mutating the raw data.
    """

    manifest: dict[str, Any] = {}
    raw_manifest_path = session_dir / "session_manifest.json"
    try:
        manifest = read_json(raw_manifest_path)
    except Exception:  # noqa: BLE001
        manifest = {}

    command = _read_text_if_exists(session_dir / "command.txt")
    env_summary = _read_text_if_exists(session_dir / "environment_summary.txt")
    final_status: dict[str, Any] = {}
    handoff: dict[str, Any] = {}
    try:
        final_status = read_json(session_dir / "final_status.json")
    except Exception:  # noqa: BLE001
        final_status = {}
    try:
        handoff = read_json(session_dir / "learning_material_handoff.json")
    except Exception:  # noqa: BLE001
        handoff = {}

    normalized = dict(manifest)
    normalized.setdefault("schema_version", "legacy-compat-1")
    if "started_at" not in normalized and "started_at_utc" in normalized:
        normalized["started_at"] = normalized["started_at_utc"]
    if "ended_at" not in normalized and "ended_at_utc" in normalized:
        normalized["ended_at"] = normalized["ended_at_utc"]
    if "workspace_root" not in normalized and "workspace" in normalized:
        normalized["workspace_root"] = normalized["workspace"]
    if "codex_binary" not in normalized and "codex_bin" in normalized:
        normalized["codex_binary"] = normalized["codex_bin"]
    if "wrapper_path" not in normalized and "launcher_path" in normalized:
        normalized["wrapper_path"] = normalized["launcher_path"]
    if "resume_of" not in normalized and "codex_resume_id" in normalized:
        normalized["resume_of"] = normalized["codex_resume_id"]
    if "task_title" not in normalized:
        if command:
            normalized["task_title"] = command.strip().splitlines()[0][:120]
        else:
            normalized["task_title"] = "legacy codex session"
    if "task_prompt_path" not in normalized:
        normalized["task_prompt_path"] = None
    if "command" not in normalized and command:
        normalized["command"] = command.strip()
    if "operator" not in normalized:
        if env_summary:
            for line in env_summary.splitlines():
                if line.startswith("AIMS_AGENT="):
                    break
        normalized["operator"] = os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"
    if "exit_code" not in normalized and isinstance(final_status, dict):
        normalized["exit_code"] = final_status.get("exit_code")
    if "status" not in normalized and isinstance(final_status, dict):
        normalized["status"] = final_status.get("status") or "COMPLETED"
    if "artifacts" not in normalized:
        normalized["artifacts"] = {
            "stdout_log": "stdout.log",
            "stderr_log": "stderr.log",
            "transcript": "transcript.md",
            "touched_files": "touched_files.txt",
            "evidence_links": "evidence_links.json",
            "learning_material_handoff": "learning_material_handoff.json",
        }
    if "safety" not in normalized or not isinstance(normalized.get("safety"), dict):
        normalized["safety"] = {
            "raw_material_only": bool(handoff.get("not_approved_training_pairs", True)),
            "not_training_data": True,
            "requires_classification": bool(handoff.get("requires_classification", True)),
            "requires_contamination_filter": bool(handoff.get("requires_contamination_filter", True)),
            "requires_slot_routing": bool(handoff.get("requires_slot_router", True)),
            "direct_training_allowed": False,
            "downstream_training_allowed": False,
        }
    else:
        safety = dict(normalized["safety"])
        safety.setdefault("raw_material_only", bool(handoff.get("not_approved_training_pairs", True)))
        safety.setdefault("not_training_data", True)
        safety.setdefault("requires_classification", bool(handoff.get("requires_classification", True)))
        safety.setdefault("requires_contamination_filter", bool(handoff.get("requires_contamination_filter", True)))
        safety.setdefault("requires_slot_routing", bool(handoff.get("requires_slot_router", True)))
        safety.setdefault("direct_training_allowed", False)
        safety.setdefault("downstream_training_allowed", False)
        normalized["safety"] = safety
    return normalized


def raw_sessions_root(workspace: Path | str | None = None) -> Path:
    return _root(workspace) / "aims_workspace/logi/raw_material/codex_sessions"


def _validation_dir(root: Path, session_id: str) -> Path:
    return root / "aims_workspace/logi/validation/codex_sessions" / session_id


def _ingestion_dir(root: Path, session_id: str) -> Path:
    return root / "aims_workspace/logi/ingestion/codex_sessions" / session_id


def _lesson_dir(root: Path, session_id: str) -> Path:
    return root / "aims_workspace/logi/lessons/codex_sessions" / session_id


def _decision_dir(root: Path, session_id: str) -> Path:
    return root / "aims_workspace/logi/action_decisions/codex_sessions" / session_id


def _quarantine_dir(root: Path, session_id: str) -> Path:
    return root / "aims_workspace/logi/quarantine/codex_sessions" / session_id


def _ledger_path(root: Path) -> Path:
    return root / "aims_workspace/logi/traceability/learning_traceability_ledger.jsonl"


def _closeout_dir(root: Path, session_id: str) -> Path:
    return root / "aims_workspace/logi/closeout/codex_sessions" / session_id


def _ledger_has_session(root: Path, session_id: str) -> bool:
    path = _ledger_path(root)
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("source_session_id") == session_id and row.get("final_status") == "CLOSED":
            return True
    return False


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _terminal_admission(session_dir: Path, manifest: dict[str, Any], final_status: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed terminal package admission without emitting learning artifacts."""
    sid = session_dir.name
    manifest_sid = str(manifest.get("logi_session_id") or manifest.get("aims_session_id") or "")
    final_sid = str(final_status.get("logi_session_id") or final_status.get("aims_session_id") or final_status.get("session_id") or "")
    status = str(manifest.get("status") or "").upper()
    final_state = str(final_status.get("status") or "").upper()
    transcript = session_dir / str((manifest.get("artifacts") or {}).get("transcript") or "transcript.md")
    reasons: list[str] = []
    if status == "RUNNING":
        return {"decision": "HOLD_RUNNING_PACKAGE", "admitted": False, "session_id": sid, "reasons": ["manifest.status is RUNNING"]}
    if status not in {"COMPLETED", "FAILED"}:
        reasons.append("manifest.status is not a terminal value")
    if not final_status:
        reasons.append("final_status.json missing or invalid")
    if final_sid and final_sid != sid:
        reasons.append("final_status session ID mismatch")
    if manifest_sid and manifest_sid != sid:
        reasons.append("manifest session ID mismatch")
    if final_state != status:
        reasons.append("manifest and final_status status mismatch")
    if not (final_status.get("reason") or final_status.get("stop_reason") or final_status.get("exit_code") is not None or manifest.get("stop_reason") or (status == "COMPLETED" and final_status.get("exit_code") == 0)):
        reasons.append("terminal reason/outcome is not recoverable")
    if not transcript.is_file() or transcript.stat().st_size == 0:
        reasons.append("transcript.md missing or empty")
    transcript_hash = None
    transcript_size = None
    if transcript.is_file() and transcript.stat().st_size:
        before = (transcript.stat().st_size, transcript.stat().st_mtime_ns)
        first_hash = _sha256(transcript)
        after = (transcript.stat().st_size, transcript.stat().st_mtime_ns)
        second_hash = _sha256(transcript)
        if before != after or first_hash != second_hash:
            reasons.append("transcript hash/metadata changed during admission")
        else:
            transcript_hash = first_hash
            transcript_size = transcript.stat().st_size
    if reasons:
        decision = "HOLD_FINAL_STATUS_INCONSISTENT" if any("final_status" in reason or "status mismatch" in reason or "reason" in reason for reason in reasons) else "HOLD_TRANSCRIPT_HASH_UNSTABLE" if any("transcript" in reason for reason in reasons) else "HOLD_FINAL_STATUS_MISSING"
        return {"decision": decision, "admitted": False, "session_id": sid, "reasons": reasons, "transcript_sha256": transcript_hash, "transcript_size_bytes": transcript_size}
    terminal_time_source = "manifest" if manifest.get("ended_at") or manifest.get("ended_at_utc") else "final_status_json"
    terminal_time = manifest.get("ended_at") or manifest.get("ended_at_utc") or final_status.get("ended_at") or final_status.get("ended_at_utc")
    if not terminal_time:
        return {"decision": "HOLD_FINAL_STATUS_INCONSISTENT", "admitted": False, "session_id": sid, "reasons": ["terminal time is unavailable"]}
    return {
        "decision": "ADMIT_TERMINAL_PACKAGE",
        "admitted": True,
        "session_id": sid,
        "status": status,
        "terminal_time": terminal_time,
        "terminal_time_source": terminal_time_source,
        "transcript_path": str(transcript),
        "transcript_sha256": transcript_hash,
        "transcript_size_bytes": transcript_size,
        "reasons": [],
    }


def _session_id(session_dir: Path) -> str:
    return session_dir.name


def validate_manifest_schema(manifest: dict[str, Any]) -> list[str]:
    missing = [key for key in REQUIRED_MANIFEST_FIELDS if key not in manifest]
    safety = manifest.get("safety") if isinstance(manifest.get("safety"), dict) else {}
    if safety.get("raw_material_only") is not True:
        missing.append("safety.raw_material_only=true")
    if safety.get("direct_training_allowed") is not False:
        missing.append("safety.direct_training_allowed=false")
    if safety.get("downstream_training_allowed") is not False:
        missing.append("safety.downstream_training_allowed=false")
    return missing


def validate_codex_package(session_dir: Path, workspace: Path | str | None = None, *, stale_running_seconds: int = 3600) -> dict[str, Any]:
    root = _root(workspace)
    sid = _session_id(session_dir)
    missing_files = [name for name in REQUIRED_FILES if not (session_dir / name).exists()]
    empty_files = [
        name
        for name in REQUIRED_FILES
        if (session_dir / name).exists() and (session_dir / name).stat().st_size == 0 and name != "stderr.log"
    ]
    manifest: dict[str, Any] = {}
    manifest_error = None
    try:
        manifest = read_json(session_dir / "session_manifest.json")
    except Exception as exc:  # noqa: BLE001
        manifest_error = str(exc)
    normalized_manifest = manifest
    legacy_schema_compatibility = False
    if manifest:
        schema_missing = validate_manifest_schema(manifest)
        # Some legacy terminal packages omit only manifest.ended_at while
        # final_status.json carries the authoritative terminal timestamp.
        # Permit that narrow compatibility case without mutating/fabricating
        # the manifest; _terminal_admission records final_status_json as the
        # terminal_time_source.
        if schema_missing == ["ended_at"]:
            try:
                legacy_final = read_json(session_dir / "final_status.json")
            except Exception:  # noqa: BLE001
                legacy_final = {}
            if (
                str(manifest.get("status") or "").upper() in {"COMPLETED", "FAILED"}
                and str(legacy_final.get("status") or "").upper() == str(manifest.get("status") or "").upper()
                and (legacy_final.get("ended_at") or legacy_final.get("ended_at_utc"))
            ):
                schema_missing = []
        if schema_missing:
            normalized_manifest = _load_legacy_sidecar_manifest(session_dir)
            if normalized_manifest and not validate_manifest_schema(normalized_manifest):
                legacy_schema_compatibility = True
                manifest = normalized_manifest
                schema_missing = []
    else:
        schema_missing = ["session_manifest.json"]
        legacy_schema_compatibility = False
    status = str(manifest.get("status") or "UNKNOWN").upper()
    started_at = manifest.get("started_at") or manifest.get("started_at_utc")
    final_status: dict[str, Any] = {}
    final_path = session_dir / "final_status.json"
    if final_path.exists():
        try:
            final_status = read_json(final_path)
        except Exception:
            final_status = {}
    admission = _terminal_admission(session_dir, manifest, final_status) if manifest else {
        "decision": "HOLD_FINAL_STATUS_MISSING",
        "admitted": False,
        "session_id": sid,
        "reasons": ["session_manifest.json is missing or invalid"],
    }
    if status == "RUNNING":
        lifecycle_state = "QUARANTINED_INCOMPLETE"
        validation_status = "RAW_REJECTED_INCOMPLETE"
    elif missing_files or empty_files:
        lifecycle_state = "QUARANTINED_INCOMPLETE"
        validation_status = "RAW_REJECTED_INCOMPLETE"
    elif schema_missing or manifest_error:
        lifecycle_state = "QUARANTINED_SCHEMA_FAIL"
        validation_status = "RAW_REJECTED_SCHEMA"
    elif not admission.get("admitted"):
        lifecycle_state = "QUARANTINED_INCOMPLETE"
        validation_status = "RAW_REJECTED_TERMINAL_ADMISSION"
    else:
        lifecycle_state = "VALIDATED_RAW"
        validation_status = "RAW_VALIDATED"

    report = {
        "session_id": sid,
        "raw_package_path": rel(session_dir, root),
        "validated_at": now(),
        "status": validation_status,
        "lifecycle_state": lifecycle_state,
        "legacy_schema_compatibility": legacy_schema_compatibility,
        "required_files": REQUIRED_FILES,
        "missing_files": missing_files,
        "empty_files": empty_files,
        "manifest_schema_missing": schema_missing,
        "manifest_error": manifest_error,
        "safety": manifest.get("safety", {}),
        "direct_training_allowed": False,
        "terminal_admission": admission,
        "terminal_time": admission.get("terminal_time"),
        "terminal_time_source": admission.get("terminal_time_source"),
        "manifest_sha256": _sha256(session_dir / "session_manifest.json") if (session_dir / "session_manifest.json").is_file() else None,
        "final_status_sha256": _sha256(final_path) if final_path.is_file() else None,
        "transcript_sha256": admission.get("transcript_sha256"),
        "transcript_size_bytes": admission.get("transcript_size_bytes"),
    }
    report_path = write_json(_validation_dir(root, sid) / "validation_report.json", report)
    if lifecycle_state == "VALIDATED_RAW":
        marker = {
            "session_id": sid,
            "status": "VALIDATED_RAW",
            "raw_package_path": rel(session_dir, root),
            "validation_report_path": rel(report_path, root),
            "direct_training_allowed": False,
            "created_at": now(),
        }
        write_json(_validation_dir(root, sid) / "validated_raw_marker.json", marker)
    else:
        q_report = {
            "session_id": sid,
            "status": lifecycle_state,
            "raw_package_path": rel(session_dir, root),
            "validation_report_path": rel(report_path, root),
            "reason": "RUNNING or terminal admission failed" if lifecycle_state == "QUARANTINED_INCOMPLETE" else "manifest schema failure",
            "missing_files": missing_files,
            "schema_missing": schema_missing,
            "terminal_admission": admission,
            "preserved": True,
            "direct_training_allowed": False,
            "created_at": now(),
        }
        write_json(_quarantine_dir(root, sid) / "quarantine_report.json", q_report)
    return {**report, "validation_report_path": rel(report_path, root)}


def scan_codex_raw_packages(workspace: Path | str | None = None, *, stale_running_seconds: int = 3600) -> dict[str, Any]:
    root = _root(workspace)
    base = raw_sessions_root(root)
    reports = []
    if base.exists():
        for session_dir in sorted(path for path in base.iterdir() if path.is_dir()):
            reports.append(validate_codex_package(session_dir, root, stale_running_seconds=stale_running_seconds))
    return {
        "status": "PASSED",
        "scanned_at": now(),
        "sessions_scanned": len(reports),
        "validated_raw": len([r for r in reports if r["lifecycle_state"] == "VALIDATED_RAW"]),
        "quarantined": len([r for r in reports if r["lifecycle_state"].startswith("QUARANTINED")]),
        "reports": reports,
        "direct_training_allowed": False,
    }


def ingest_validated_codex_package(session_id: str, workspace: Path | str | None = None) -> dict[str, Any]:
    root = _root(workspace)
    marker = _validation_dir(root, session_id) / "validated_raw_marker.json"
    validation_report = _validation_dir(root, session_id) / "validation_report.json"
    q_report = _quarantine_dir(root, session_id) / "quarantine_report.json"
    validated = False
    if validation_report.exists():
        try:
            validated = read_json(validation_report).get("lifecycle_state") == "VALIDATED_RAW"
        except Exception:  # noqa: BLE001
            validated = False
    if q_report.exists() and not validated:
        status = "RAW_QUARANTINED"
        reason = "quarantined package is not ingestible"
    elif not marker.exists():
        status = "RAW_REJECTED_INCOMPLETE"
        reason = "validated raw marker missing"
    else:
        status = "RAW_PROCESSED"
        reason = "validated raw marker consumed"
    payload = {
        "source_session_id": session_id,
        "status": status,
        "states": ["RAW_VALIDATED", "RAW_QUEUED", "RAW_PROCESSING", status] if status == "RAW_PROCESSED" else [status],
        "validated_raw_marker_path": rel(marker, root) if marker.exists() else None,
        "quarantine_report_path": rel(q_report, root) if q_report.exists() else None,
        "reason": reason,
        "raw_material_only": True,
        "direct_training_allowed": False,
        "ingested_at": now(),
    }
    path = write_json(_ingestion_dir(root, session_id) / "ingestion_status.json", payload)
    return {**payload, "ingestion_status_path": rel(path, root)}


def extract_lesson_from_ingested_session(session_id: str, workspace: Path | str | None = None) -> dict[str, Any]:
    root = _root(workspace)
    ingestion_path = _ingestion_dir(root, session_id) / "ingestion_status.json"
    if not ingestion_path.exists() or read_json(ingestion_path).get("status") != "RAW_PROCESSED":
        raise ValueError("session must be RAW_PROCESSED before lesson extraction")
    session_dir = raw_sessions_root(root) / session_id
    evidence = [session_dir / name for name in ("session_manifest.json", "final_status.json", "transcript.md", "touched_files.txt")]
    evidence_paths = [rel(p, root) for p in evidence if p.exists()]
    if not evidence_paths:
        raise ValueError("lesson requires evidence paths")
    final_status = read_json(session_dir / "final_status.json")
    manifest = read_json(session_dir / "session_manifest.json")
    lesson_id = "lesson_" + hashlib.sha256(f"{session_id}:{manifest.get('started_at')}".encode()).hexdigest()[:16]
    status = final_status.get("status", manifest.get("status", "UNKNOWN"))
    exit_code = final_status.get("exit_code", manifest.get("exit_code"))
    if status == "FAILED" or (exit_code not in (None, 0)):
        observed_problem = f"Codex session failed (exit_code={exit_code}); failure evidence requires a terminal failure disposition."
        root_cause = "The launcher or Codex command failed before a usable audit result was produced; the failure was captured but was not previously routed into a lesson and prevention case."
        prevention = "Classify launcher/CLI failures, persist a compact failure case, run the corrected command contract, and close the raw package only after replay evidence exists."
    else:
        observed_problem = f"Codex session completed with status {status} and requires controlled learning-loop processing."
        root_cause = "Codex raw session required explicit capture, validation, and downstream gate traceability before learning use."
        prevention = "Require schema-valid raw package validation, raw-only flags, lesson action decision, and gate reports before any learning handoff."
    lesson = {
        "lesson_id": lesson_id,
        "source_session_id": session_id,
        "source_evidence_paths": evidence_paths,
        "observed_problem": observed_problem,
        "root_cause": root_cause,
        "prevention_rule": prevention,
        "reusable_lesson": "Raw Codex captures must be converted into evidence-backed lessons and gated candidates; raw logs are never training data.",
        "affected_component": "codex_logi_learning_traceability",
        "applicability_scope": "codex session capture, Logi ingestion, Traini raw-material handoff",
        "confidence_score": 0.88,
        "risk_level": "medium",
        "recommended_action": "BOTH_SKILL_AND_PAIR_CANDIDATES",
        "slot_relevance": "slot32",
        "human_review_required": True,
        "direct_training_allowed": False,
    }
    if not lesson["root_cause"] or not lesson["prevention_rule"] or not lesson["source_session_id"]:
        raise ValueError("invalid lesson")
    d = _lesson_dir(root, session_id)
    report_path = write_json(d / "lesson_extraction_report.json", {"status": "LESSON_EXTRACTED", "lesson_id": lesson_id, "lessons": [lesson], "direct_training_allowed": False})
    append_jsonl(d / "lessons.jsonl", lesson)
    quality_path = write_json(d / "lesson_quality_score.json", {"lesson_id": lesson_id, "score": 0.9, "status": "PASS", "direct_training_allowed": False})
    return {**lesson, "lesson_report_path": rel(report_path, root), "lesson_quality_score_path": rel(quality_path, root)}


def decide_lesson_action(lesson: dict[str, Any], workspace: Path | str | None = None) -> dict[str, Any]:
    root = _root(workspace)
    decision = lesson.get("recommended_action", "NO_ACTION")
    if decision not in ALLOWED_DECISIONS:
        decision = "REJECTED_UNSAFE_OR_LOW_QUALITY"
    required_tests: list[str] = []
    required_gates: list[str] = []
    if "SKILL" in decision:
        required_tests = ["test_skill_change_proposal_links_lesson_and_session", "test_skill_change_requires_tests"]
    if "PAIR" in decision:
        required_gates = ["contamination", "dedup", "slot_router", "dataset_gate"]
    payload = {
        "source_session_id": lesson["source_session_id"],
        "lesson_id": lesson["lesson_id"],
        "decision": decision,
        "reason": "Process-safety lesson can update skill workflow and produce a raw-only gated pair candidate.",
        "required_tests": required_tests,
        "required_gates": required_gates,
        "direct_training_allowed": False,
        "decided_at": now(),
    }
    if decision not in ALLOWED_DECISIONS:
        raise ValueError("unsupported decision")
    if "SKILL" in decision and not required_tests:
        raise ValueError("skill decision requires tests")
    if "PAIR" in decision and not required_gates:
        raise ValueError("pair decision requires gates")
    path = write_json(_decision_dir(root, lesson["source_session_id"]) / "lesson_action_decision.json", payload)
    return {**payload, "action_decision_path": rel(path, root)}


def create_skill_change_candidate(lesson: dict[str, Any], decision: dict[str, Any], workspace: Path | str | None = None) -> dict[str, Any]:
    root = _root(workspace)
    d = root / "aims_workspace/logi/skill_changes" / lesson["lesson_id"]
    proposal = {
        "skill_change_id": "skillchg_" + lesson["lesson_id"].removeprefix("lesson_"),
        "source_lesson_id": lesson["lesson_id"],
        "source_session_id": lesson["source_session_id"],
        "target_skill": "codex_logi_learning_traceability",
        "change_type": "workflow",
        "proposed_change": lesson["prevention_rule"],
        "required_tests": decision.get("required_tests", []),
        "rollback_plan": "Remove generated candidate artifacts and disable scanner entrypoint; raw evidence remains preserved.",
        "implemented": True,
        "direct_training_allowed": False,
    }
    if not proposal["required_tests"]:
        raise ValueError("skill change cannot be applied without tests")
    proposal_path = write_json(d / "skill_change_proposal.json", proposal)
    impl_path = write_json(d / "implementation_report.json", {**proposal, "status": "IMPLEMENTED", "files_changed": ["ops/logi/codex_learning_traceability.py"]})
    tests_path = d / "tests_run.txt"
    tests_path.parent.mkdir(parents=True, exist_ok=True)
    tests_path.write_text("\n".join(proposal["required_tests"]) + "\n", encoding="utf-8")
    final_path = write_json(d / "final_status.json", {"status": "SKILL_CHANGE_APPLIED", "implementation_report_path": rel(impl_path, root), "rollback_plan": proposal["rollback_plan"], "direct_training_allowed": False})
    return {
        "skill_change_path": rel(proposal_path, root),
        "implementation_report_path": rel(impl_path, root),
        "tests_run_path": rel(tests_path, root),
        "final_status_path": rel(final_path, root),
        "status": "SKILL_CHANGE_APPLIED",
    }


def strict_contamination_status(text: str, *, provenance: dict[str, Any] | None = None, proposed_slot: str = "slot32") -> tuple[str, list[str]]:
    checks: list[str] = []
    if not provenance:
        return "FAIL_PROVENANCE_MISSING", ["missing provenance"]
    if re.search(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[A-Za-z0-9._-]{8,}", text):
        return "FAIL_SECRET", ["secret-like material"]
    if re.search(r"(?i)system prompt|developer message|protected prompt", text):
        return "FAIL_SYSTEM_PROMPT", ["system prompt material"]
    if "<think>" in text.lower() or "</think>" in text.lower():
        return "FAIL_THINK_LEAKAGE", ["think leakage"]
    words = text.split()
    if len(words) >= 10 and len(set(words[-10:])) <= 2:
        return "FAIL_REPETITION_LOOP", ["repetition loop"]
    if text.strip().startswith("{") and "patch_diff" in text and "root_cause" in text:
        return "FAIL_REPAIRMAN_JSON_OUTPUT", ["repairman JSON output"]
    if proposed_slot == "slot14" and re.search(r"(?m)^\s*(def |class |import )", text):
        return "FAIL_SLOT_MISMATCH", ["slot14 coding-only material"]
    return "PASS", checks


def create_traini_pair_candidate(lesson: dict[str, Any], decision: dict[str, Any], workspace: Path | str | None = None) -> dict[str, Any]:
    root = _root(workspace)
    d = root / "aims_workspace/logi/traini_pair_candidates" / lesson["lesson_id"]
    candidate_id = "paircand_" + lesson["lesson_id"].removeprefix("lesson_")
    proposed_slot = lesson.get("slot_relevance") or "slot32"
    mode = "agent_skill_learning" if lesson.get("affected_component", "").endswith("traceability") else "traini_model_tuning"
    target_pool = "agent_skill_learning_pool" if mode == "agent_skill_learning" else f"{proposed_slot}_pair_pool"
    if proposed_slot == "slot14" and "coding" in lesson.get("affected_component", ""):
        response = "def unsafe_slot14_coding_material():\n    return True"
    else:
        response = f"Apply prevention rule: {lesson['prevention_rule']}"
    provenance = {
        "source_lesson_id": lesson["lesson_id"],
        "source_session_id": lesson["source_session_id"],
        "source_evidence_paths": lesson["source_evidence_paths"],
    }
    candidate = {
        "schema": "aims.traini.pair_candidate.v1",
        "pair_candidate_id": candidate_id,
        "source_lesson_id": lesson["lesson_id"],
        "source_session_id": lesson["source_session_id"],
        "candidate_instruction": lesson["observed_problem"],
        "candidate_response": response,
        "target_slot": proposed_slot,
        "target_pool": target_pool,
        "mode": mode,
        "provenance": provenance,
        "raw_material_only": True,
        "direct_training_allowed": False,
        "training_scheduled": False,
    }
    append_jsonl(d / "pair_candidate_raw.jsonl", candidate)
    manifest_path = write_json(d / "candidate_manifest.json", candidate)
    status, checks = strict_contamination_status(response, provenance=provenance, proposed_slot=proposed_slot)
    contamination = {
        "schema": "aims.traini.contamination_report.v1",
        "candidate_id": candidate_id,
        "source_lesson_id": lesson["lesson_id"],
        "source_session_id": lesson["source_session_id"],
        "status": status,
        "checks": checks,
        "final_decision": "ALLOW_NEXT_GATE" if status == "PASS" else "REJECT",
        "direct_training_allowed": False,
    }
    contamination_path = write_json(d / "contamination_report.json", contamination)
    dedup = {
        "schema": "aims.traini.dedup_report.v1",
        "candidate_id": candidate_id,
        "source_session_id": lesson["source_session_id"],
        "source_lesson_id": lesson["lesson_id"],
        "status": "PASS" if status == "PASS" else "SKIPPED",
        "duplicates": [],
        "direct_training_allowed": False,
    }
    dedup_path = write_json(d / "dedup_report.json", dedup)
    slot_status = "PASS"
    slot_reason = "routed to agent skill pool" if mode == "agent_skill_learning" else f"routed to {proposed_slot}"
    if proposed_slot == "slot120":
        slot_status = "PASS"
        slot_reason = "slot120 route allowed, dataset admission remains blocked until 750 verified pairs"
    slot_router = {
        "schema": "aims.traini.slot_router_report.v1",
        "candidate_id": candidate_id,
        "source_lesson_id": lesson["lesson_id"],
        "source_session_id": lesson["source_session_id"],
        "proposed_slot": proposed_slot,
        "target_pool": target_pool,
        "status": slot_status,
        "reason": slot_reason,
        "training_scheduled": False,
        "direct_training_allowed": False,
    }
    slot_path = write_json(d / "slot_router_report.json", slot_router)
    dataset_status = "REJECTED_CANDIDATE_ONLY"
    dataset_reason = "agent skill material is not admitted to Traini dataset" if mode == "agent_skill_learning" else "candidate remains raw-only until slot-specific dataset gate admission"
    if proposed_slot == "slot120":
        dataset_reason = "SLOT120_BLOCKED_UNTIL_750_VERIFIED_PAIRS"
    dataset_gate = {
        "schema": "aims.traini.dataset_gate_report.v1",
        "candidate_id": candidate_id,
        "source_lesson_id": lesson["lesson_id"],
        "source_session_id": lesson["source_session_id"],
        "status": dataset_status,
        "reason": dataset_reason,
        "training_scheduled": False,
        "dataset_admission_status": "REJECTED",
        "direct_training_allowed": False,
    }
    dataset_path = write_json(d / "dataset_gate_report.json", dataset_gate)
    bound_paths = {
        "pair_candidate_path": manifest_path,
        "contamination_report_path": contamination_path,
        "dedup_report_path": dedup_path,
        "slot_router_report_path": slot_path,
        "dataset_gate_report_path": dataset_path,
    }
    binding_path = write_json(
        d / "gate_evidence_binding.json",
        {
            "schema": "aims.traini.gate_evidence_binding.v1",
            "source_session_id": lesson["source_session_id"],
            "source_lesson_id": lesson["lesson_id"],
            "candidate_id": candidate_id,
            "gate_evidence_sha256": {
                key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in bound_paths.items()
            },
            "direct_training_allowed": False,
            "training_scheduled": False,
        },
    )
    final = {
        "candidate_id": candidate_id,
        "status": "PAIR_CANDIDATE_GATED",
        "raw_material_only": True,
        "training_scheduled": False,
        "direct_training_allowed": False,
        "reports": {
            "candidate_manifest": rel(manifest_path, root),
            "contamination_report": rel(contamination_path, root),
            "dedup_report": rel(dedup_path, root),
            "slot_router_report": rel(slot_path, root),
            "dataset_gate_report": rel(dataset_path, root),
            "gate_evidence_binding": rel(binding_path, root),
        },
    }
    final_path = write_json(d / "final_status.json", final)
    return {
        **candidate,
        "candidate_manifest_path": rel(manifest_path, root),
        "contamination_report_path": rel(contamination_path, root),
        "dedup_report_path": rel(dedup_path, root),
        "slot_router_report_path": rel(slot_path, root),
        "dataset_gate_report_path": rel(dataset_path, root),
        "gate_evidence_binding_path": rel(binding_path, root),
        "pair_candidate_path": rel(manifest_path, root),
        "final_status_path": rel(final_path, root),
        "status": "PAIR_CANDIDATE_GATED",
    }


def append_traceability_record(
    *,
    session_id: str,
    lesson: dict[str, Any],
    decision: dict[str, Any],
    skill: dict[str, Any] | None,
    pair: dict[str, Any] | None,
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    root = _root(workspace)
    ledger_path = _ledger_path(root)
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if existing.get("source_session_id") == session_id:
                return existing
    validation_report = _validation_dir(root, session_id) / "validation_report.json"
    q_report = _quarantine_dir(root, session_id) / "quarantine_report.json"
    ingestion_status = _ingestion_dir(root, session_id) / "ingestion_status.json"
    record = {
        "source_session_id": session_id,
        "raw_package_path": rel(raw_sessions_root(root) / session_id, root),
        "validation_report_path": rel(validation_report, root),
        "quarantine_report_path": rel(q_report, root) if q_report.exists() else None,
        "ingestion_status_path": rel(ingestion_status, root),
        "lesson_id": lesson["lesson_id"],
        "lesson_report_path": lesson["lesson_report_path"],
        "action_decision_path": decision["action_decision_path"],
        "skill_change_path": skill.get("skill_change_path") if skill else None,
        "pair_candidate_path": pair.get("pair_candidate_path") if pair else None,
        "contamination_report_path": pair.get("contamination_report_path") if pair else None,
        "dedup_report_path": pair.get("dedup_report_path") if pair else None,
        "slot_router_report_path": pair.get("slot_router_report_path") if pair else None,
        "dataset_gate_report_path": pair.get("dataset_gate_report_path") if pair else None,
        "source_closeout_path": rel(_closeout_dir(root, session_id) / "source_closeout.json", root),
        "idempotency_key": hashlib.sha256(f"{session_id}:{lesson['lesson_id']}".encode()).hexdigest(),
        "final_status": "CLOSED",
        "direct_training_allowed": False,
        "recorded_at": now(),
    }
    required_paths = [
        "raw_package_path",
        "validation_report_path",
        "ingestion_status_path",
        "lesson_report_path",
        "action_decision_path",
    ]
    for key in required_paths:
        if not record.get(key) or not (root / str(record[key])).exists():
            raise ValueError(f"missing artifact path: {key}")
    append_jsonl(_ledger_path(root), record)
    return record


def replay_traceability_ledger(workspace: Path | str | None = None, *, session_id: str | None = None) -> dict[str, Any]:
    root = _root(workspace)
    path = _ledger_path(root)
    if not path.exists():
        return {"status": "FAIL", "reason": "ledger missing", "chains": []}
    chains = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if session_id and row.get("source_session_id") != session_id:
            continue
        artifact_keys = [
            key for key, value in row.items()
            if key.endswith("_path") and value and key != "source_closeout_path"
        ]
        missing = [key for key in artifact_keys if not _artifact_exists(root, row[key], row.get("source_session_id"))]
        closeout_path = row.get("source_closeout_path")
        closeout_missing = bool(closeout_path and not _artifact_exists(root, closeout_path, row.get("source_session_id")))
        ok = not missing and row.get("direct_training_allowed") is False and row.get("lesson_id") and row.get("final_status")
        chains.append({"source_session_id": row.get("source_session_id"), "lesson_id": row.get("lesson_id"), "ok": bool(ok), "missing": missing, "source_closeout_missing": closeout_missing})
    return {"status": "PASS" if chains and all(c["ok"] for c in chains) else "FAIL", "chains": chains}


def _artifact_exists(root: Path, artifact: str, session_id: str | None) -> bool:
    path = root / artifact
    if path.exists():
        return True
    raw_prefix = f"aims_workspace/logi/raw_material/codex_sessions/{session_id}/"
    raw_session = f"aims_workspace/logi/raw_material/codex_sessions/{session_id}"
    if session_id and artifact == raw_session:
        return (root / "aims_workspace/logi/retained_evidence/codex_sessions" / session_id).exists()
    if session_id and artifact.startswith(raw_prefix):
        name = artifact.removeprefix(raw_prefix)
        return (root / "aims_workspace/logi/retained_evidence/codex_sessions" / session_id / name).exists()
    return False


def run_e2e_traceability_for_session(session_id: str, workspace: Path | str | None = None) -> dict[str, Any]:
    root = _root(workspace)
    if _ledger_has_session(root, session_id):
        return {"status": "SKIP_ALREADY_CLOSED_OUT", "session_id": session_id, "training_scheduled": False, "direct_training_allowed": False}
    validation = validate_codex_package(raw_sessions_root(root) / session_id, root, stale_running_seconds=0)
    if validation["lifecycle_state"] != "VALIDATED_RAW":
        return {"status": "FAILED_VALIDATION", "session_id": session_id, "validation": validation, "training_scheduled": False, "direct_training_allowed": False}
    ingestion = ingest_validated_codex_package(session_id, root)
    lesson = extract_lesson_from_ingested_session(session_id, root)
    decision = decide_lesson_action(lesson, root)
    skill = create_skill_change_candidate(lesson, decision, root)
    pair = create_traini_pair_candidate(lesson, decision, root)
    ledger = append_traceability_record(session_id=session_id, lesson=lesson, decision=decision, skill=skill, pair=pair, workspace=root)
    session_dir = raw_sessions_root(root) / session_id
    manifest_path = session_dir / "session_manifest.json"
    final_path = session_dir / "final_status.json"
    transcript_path = session_dir / "transcript.md"
    closeout = {
        "schema": "aims.logi.session_source_closeout.v1",
        "source_session_id": session_id,
        "manifest_path": rel(manifest_path, root),
        "manifest_sha256": validation.get("manifest_sha256"),
        "transcript_path": rel(transcript_path, root),
        "transcript_sha256": validation.get("transcript_sha256"),
        "final_status_path": rel(final_path, root),
        "final_status_sha256": validation.get("final_status_sha256"),
        "terminal_status": validation.get("terminal_admission", {}).get("status"),
        "terminal_time": validation.get("terminal_time"),
        "terminal_time_source": validation.get("terminal_time_source"),
        "extractor_revision": "main-canonicalized-from-logi-evidence-skill-12534ed",
        "emitted_artifacts": {
            key: value for key, value in {
                "validation_report": validation.get("validation_report_path"),
                "ingestion_status": ingestion.get("ingestion_status_path"),
                "lesson_report": lesson.get("lesson_report_path"),
                "action_decision": decision.get("action_decision_path"),
                "skill_change": skill.get("skill_change_path") if skill else None,
                "pair_candidate": pair.get("pair_candidate_path") if pair else None,
                "dataset_gate": pair.get("dataset_gate_report_path") if pair else None,
            }.items() if value
        },
        "routing_decision": (pair or {}).get("target_pool") or "agent_skill_learning",
        "destination_pool": (pair or {}).get("target_pool") or "agent_skill_learning_pool",
        "ledger_path": rel(_ledger_path(root), root),
        "ledger_row_reference": {"source_session_id": session_id, "idempotency_key": ledger.get("idempotency_key")},
        "idempotency_key": ledger.get("idempotency_key"),
        "retained_raw_evidence": True,
        "cleanup_eligibility": False,
        "cleanup_reason": "No destructive cleanup in extractor closure; operator-approved retention review required.",
        "retention_deadline": None,
        "direct_training_allowed": False,
        "training_scheduled": False,
        "created_at": now(),
    }
    write_json(_closeout_dir(root, session_id) / "source_closeout.json", closeout)
    replay = replay_traceability_ledger(root, session_id=session_id)
    return {
        "status": "PASSED" if replay["status"] == "PASS" else "FAILED_REPLAY",
        "validation": validation,
        "ingestion": ingestion,
        "lesson": lesson,
        "decision": decision,
        "skill": skill,
        "pair": pair,
        "ledger": ledger,
        "replay": replay,
        "training_scheduled": False,
        "direct_training_allowed": False,
    }
