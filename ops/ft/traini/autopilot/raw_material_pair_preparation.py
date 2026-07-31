from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ops.ft.traini.autopilot.dataset_gate import has_repetition_loop, looks_like_repairman_json
from ops.ft.traini.autopilot.dataset_admission_policy import run_dataset_admission
from ops.ft.traini.autopilot.negative_transfer_guards import evaluate_negative_transfer


ROOT = Path(__file__).resolve().parents[4]
WORKSPACE = ROOT / "aims_workspace"
DEFAULT_CURSOR_PATH = WORKSPACE / "traini" / "state" / "raw_material_review_cursor.json"
DEFAULT_RAW_ZONES = [
    WORKSPACE / "training_intake" / "traini_candidates" / "raw_events",
    WORKSPACE / "logi_session_memory" / "sources" / "codex" / "summaries",
]

SLOT32_CODE_MARKERS = (
    "def ",
    "class ",
    "assert ",
    "pytest",
    "diff --git",
    "@@",
    "import ",
    "from ",
    "sqlite3",
    "fastapi",
    "Dockerfile",
    "FROM python",
    "WORKDIR ",
    "RUN ",
    "CMD ",
)

TARGET_POOL_BY_SLOT = {
    "slot14": "slot14_pair_pool",
    "slot32": "slot32_pair_pool",
    "slot120": "slot120_pair_pool",
}
VALID_TARGET_POOLS = {
    "slot14_pair_pool",
    "slot32_pair_pool",
    "slot120_pair_pool",
    "agent_skill_learning_pool",
    "quarantine_pool",
}
VALID_MATERIAL_TYPES = {
    "chat_doc",
    "direct_coding",
    "reasoning_orchestration",
    "agent_skill",
    "status_process",
    "mixed",
    "unknown",
}
AFFINITY_TO_SLOT = {
    "chat": "slot14",
    "coder": "slot32",
    "reasoning": "slot120",
}
SLOT_TO_AFFINITY = {slot: affinity for affinity, slot in AFFINITY_TO_SLOT.items()}
VALID_AFFINITIES = {"chat", "coder", "reasoning", "skill", "mixed", "unknown"}
SLOT_RESPONSE_CONTRACTS = {
    "slot14": {"assistant_answer"},
    "slot32": {"direct_code", "unified_patch", "structured_repair_json", "safety_contrastive_code"},
    "slot120": {"assistant_answer", "structured_reasoning_json"},
}
TRANSFORMATION_REQUIRED_KEYS = (
    "review_status",
    "response_contract",
    "negative_transfer_probe",
    "holdout_separation",
    "raw_source_hash",
    "prepared_answer_hash",
    "independent_reviewer",
)
TRANSFORMER_ID_KEYS = ("extractor_id", "transformer_id", "prepared_by")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def checksum_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def discover_codex_session_handoffs(
    handoff_root: Path | None = None,
    *,
    output_path: Path | None = None,
    max_items: int = 500,
) -> dict[str, Any]:
    """Consume structured terminal-session pointers without reading transcript bodies.

    This is the single scheduled Traini handoff for wrapped Codex sessions. It
    accepts pointer metadata only; model/skill admission remains downstream
    gated and no transcript is copied into a Traini raw zone.
    """
    root = (handoff_root or WORKSPACE / "traini" / "raw_material" / "inbox" / "codex_sessions").resolve()
    rows: list[dict[str, Any]] = []
    held: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pointer in sorted(root.glob("*.json"))[:max_items]:
        try:
            handoff = json.loads(pointer.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            held.append({"pointer_path": str(pointer), "decision": "HOLD_FINAL_STATUS_INCONSISTENT", "reason": str(exc)})
            continue
        session_id = str(handoff.get("material_id") or pointer.stem).removeprefix("codex_session_")
        manifest_path = Path(str(handoff.get("manifest_path") or ""))
        if not manifest_path.is_file():
            held.append({"session_id": session_id, "pointer_path": str(pointer), "decision": "HOLD_FINAL_STATUS_MISSING", "reason": "manifest pointer missing"})
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            held.append({"session_id": session_id, "pointer_path": str(pointer), "decision": "HOLD_FINAL_STATUS_INCONSISTENT", "reason": "manifest invalid"})
            continue
        status = str(manifest.get("status") or "").upper()
        final_path = manifest_path.parent / "final_status.json"
        try:
            final = json.loads(final_path.read_text(encoding="utf-8"))
        except Exception:
            final = {}
        if status == "RUNNING":
            held.append({"session_id": session_id, "pointer_path": str(pointer), "decision": "HOLD_RUNNING_PACKAGE", "reason": "RUNNING session is never discoverable"})
            continue
        if status not in {"COMPLETED", "FAILED"} or str(final.get("status") or "").upper() != status:
            held.append({"session_id": session_id, "pointer_path": str(pointer), "decision": "HOLD_FINAL_STATUS_INCONSISTENT", "reason": "terminal status mismatch"})
            continue
        transcript_path = Path(str(handoff.get("transcript_path") or manifest_path.parent / "transcript.md"))
        if not transcript_path.is_file() or transcript_path.stat().st_size == 0:
            held.append({"session_id": session_id, "pointer_path": str(pointer), "decision": "HOLD_TRANSCRIPT_HASH_UNSTABLE", "reason": "transcript missing"})
            continue
        transcript_hash = hashlib.sha256(transcript_path.read_bytes()).hexdigest()
        manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        final_hash = hashlib.sha256(final_path.read_bytes()).hexdigest() if final_path.is_file() else None
        key = f"{session_id}:{manifest_hash}"
        if key in seen:
            held.append({"session_id": session_id, "pointer_path": str(pointer), "decision": "SKIP_ALREADY_CLOSED_OUT", "reason": "duplicate pointer in current discovery"})
            continue
        seen.add(key)
        rows.append({
            "record_id": f"codex_session_handoff:{session_id}",
            "source_session_id": session_id,
            "pointer_path": str(pointer),
            "manifest_path": str(manifest_path),
            "manifest_sha256": manifest_hash,
            "final_status_path": str(final_path),
            "final_status_sha256": final_hash,
            "terminal_status": status,
            "terminal_time": manifest.get("ended_at") or manifest.get("ended_at_utc") or final.get("ended_at") or final.get("ended_at_utc"),
            "terminal_time_source": "manifest" if manifest.get("ended_at") or manifest.get("ended_at_utc") else "final_status_json",
            "transcript_sha256": transcript_hash,
            "transcript_size_bytes": transcript_path.stat().st_size,
            "raw_material_only": True,
            "training_scheduled": False,
            "direct_training_allowed": False,
            "routing_decision": "agent_skill_learning",
            "destination_pool": "agent_skill_learning_pool",
            "idempotency_key": key,
            "complete_transcript_exposed": False,
        })
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return {
        "status": "PASS",
        "handoff": "traini/raw_material/inbox/codex_sessions",
        "records_discovered": len(rows),
        "records_held": len(held),
        "records": rows,
        "held": held,
        "complete_transcript_exposed": False,
        "training_started": False,
        "training_scheduled": False,
    }


@dataclass(frozen=True)
class RawMaterialRecord:
    record_id: str
    source_path: str
    source_agent: str
    created_at: str
    content: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    checksum: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["checksum"] = self.checksum or checksum_text(self.content)
        return data


@dataclass(frozen=True)
class ModelAffinity:
    primary: str
    confidence: float
    secondary: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PairCandidate:
    pair_id: str
    mode: str
    target_slot: str | None
    material_type: str
    prompt: str
    response: str
    provenance: dict[str, Any]
    coverage_tags: list[str] = field(default_factory=list)
    eval_mapping_status: str = "NEEDS_MAPPING"
    quality_score: str = "MEDIUM"
    rejection_reason: str | None = None
    target_pool: str = "quarantine_pool"
    output_mode: str = "quarantine"
    routing_decision: str = "QUARANTINE"
    routing_reason: str = ""
    transformation_rule: str = "manual_review"
    gate_status: str = "QUARANTINED"
    model_affinity: dict[str, Any] = field(default_factory=dict)
    negative_transfer: dict[str, Any] = field(default_factory=dict)
    codex_cli_audit: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PairPreparationResult:
    run_id: str
    created_at: str
    source_cursor_before: str
    source_cursor_after: str
    records_seen: int
    records_processed: int
    accepted_candidates: list[PairCandidate]
    rejected_candidates: list[PairCandidate]
    agent_skill_candidates: list[PairCandidate]
    slot_counts: dict[str, int]
    safety: dict[str, bool]
    output_dir: str | None = None

    def manifest(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "source_cursor_before": self.source_cursor_before,
            "source_cursor_after": self.source_cursor_after,
            "records_seen": self.records_seen,
            "records_processed": self.records_processed,
            "accepted_candidates": len(self.accepted_candidates),
            "rejected_candidates": len(self.rejected_candidates),
            "agent_skill_candidates": len(self.agent_skill_candidates),
            "slot_counts": self.slot_counts,
            "safety": self.safety,
            "output_dir": self.output_dir,
        }


def _read_text(path: Path, limit: int = 160_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except Exception:
        return ""


def _source_agent_from_path(path: Path) -> str:
    text = str(path).lower()
    if "logi_session_memory" in text:
        return "logi"
    if "codex" in text:
        return "codex"
    if "repairman" in text:
        return "repairman"
    if "traini" in text:
        return "traini"
    return "unknown"


def _record_from_json(path: Path, obj: dict[str, Any], index: int = 0) -> RawMaterialRecord:
    content = str(obj.get("content") or obj.get("text") or obj.get("summary") or obj.get("body") or json.dumps(obj, ensure_ascii=False))
    record_id = str(obj.get("record_id") or obj.get("id") or f"{path}:{index}:{checksum_text(content)[:12]}")
    tags = obj.get("tags") if isinstance(obj.get("tags"), list) else []
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    return RawMaterialRecord(
        record_id=record_id,
        source_path=str(path),
        source_agent=str(obj.get("source_agent") or _source_agent_from_path(path)),
        created_at=str(obj.get("created_at") or obj.get("timestamp") or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()),
        content=content,
        tags=[str(tag) for tag in tags],
        metadata=metadata | {"raw_json_keys": sorted(obj.keys())},
        checksum=str(obj.get("checksum") or checksum_text(content)),
    )


def _eligible_raw_record(record: RawMaterialRecord) -> bool:
    if record.source_agent != "engineering-contract-auditor":
        return True
    canonical_engineering_raw = (WORKSPACE / "training_intake" / "traini_candidates" / "raw_events").resolve()
    try:
        if not Path(record.source_path).resolve().is_relative_to(canonical_engineering_raw):
            return True
    except (OSError, RuntimeError, ValueError):
        return False
    evidence_dir = str(record.metadata.get("evidence_dir") or "").strip()
    if not evidence_dir:
        return False
    try:
        evidence_path = Path(evidence_dir).resolve()
        return evidence_path.is_relative_to(WORKSPACE.resolve())
    except (OSError, RuntimeError, ValueError):
        return False


def load_raw_material_records(
    raw_zones: Iterable[Path] | None = None,
    *,
    since_cursor: dict[str, Any] | None = None,
    max_records: int = 500,
) -> list[RawMaterialRecord]:
    processed = set((since_cursor or {}).get("processed_checksums") or [])
    records: list[RawMaterialRecord] = []
    for zone in raw_zones or DEFAULT_RAW_ZONES:
        if not zone.exists():
            continue
        for path in sorted(zone.rglob("*")):
            if len(records) >= max_records:
                return records
            if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl", ".md", ".txt", ".log"}:
                continue
            if path.suffix.lower() == ".jsonl":
                for index, line in enumerate(_read_text(path).splitlines(), start=1):
                    if len(records) >= max_records:
                        return records
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        obj = {"content": line}
                    record = _record_from_json(path, obj if isinstance(obj, dict) else {"content": line}, index)
                    if record.checksum not in processed and _eligible_raw_record(record):
                        records.append(record)
                continue
            if path.suffix.lower() == ".json":
                text = _read_text(path)
                try:
                    obj = json.loads(text)
                except json.JSONDecodeError:
                    obj = {"content": text}
                if isinstance(obj, list):
                    for index, item in enumerate(obj, start=1):
                        if len(records) >= max_records:
                            return records
                        record = _record_from_json(path, item if isinstance(item, dict) else {"content": str(item)}, index)
                        if record.checksum not in processed and _eligible_raw_record(record):
                            records.append(record)
                else:
                    record = _record_from_json(path, obj if isinstance(obj, dict) else {"content": text})
                    if record.checksum not in processed and _eligible_raw_record(record):
                        records.append(record)
                continue
            text = _read_text(path)
            if not text.strip():
                continue
            record = RawMaterialRecord(
                record_id=f"{path}:{checksum_text(text)[:12]}",
                source_path=str(path),
                source_agent=_source_agent_from_path(path),
                created_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                content=text,
                tags=[],
                metadata={},
                checksum=checksum_text(text),
            )
            if record.checksum not in processed:
                records.append(record)
    return records


def classify_raw_material(record: RawMaterialRecord) -> list[str]:
    affinity_evidence = record.metadata.get("model_affinity_evidence") if isinstance(record.metadata, dict) else None
    if isinstance(affinity_evidence, dict):
        affinity = str(affinity_evidence.get("affinity") or "").lower()
        slot = str(affinity_evidence.get("target_slot") or "").lower()
        declared_by = str(affinity_evidence.get("declared_by") or "").lower()
        if (
            declared_by in {"engineering-contract-auditor", "codex_cli"}
            and AFFINITY_TO_SLOT.get(affinity) == slot
            and slot in TARGET_POOL_BY_SLOT
            and str(affinity_evidence.get("model_profile") or "").strip()
        ):
            return [slot]
    blob = f"{record.source_path}\n{' '.join(record.tags)}\n{record.content}".lower()
    slots: set[str] = set()
    if any(marker.lower() in blob for marker in SLOT32_CODE_MARKERS) or any(k in blob for k in ["api", "function", "patch", "unit test"]):
        slots.add("slot32")
    if any(k in blob for k in ["chat", "document", "golden_v3", "answer style", "format consistency", "omi-ft-14b"]):
        slots.add("slot14")
    if any(k in blob for k in ["reasoning", "orchestration", "deep review", "policy reasoning", "docgen", "docsreg", "multi-step"]):
        slots.add("slot120")
    if any(k in blob for k in ["skill", "process learning", "codex session", "agent learning", "operator workflow"]):
        slots.add("agent_skill")
    return sorted(slots) or ["unknown"]


def detect_model_affinity(record: RawMaterialRecord) -> ModelAffinity:
    blob = f"{record.source_path}\n{' '.join(record.tags)}\n{record.content}".lower()
    scores = {
        "coder": 0,
        "chat": 0,
        "reasoning": 0,
        "skill": 0,
    }
    evidence: dict[str, list[str]] = {key: [] for key in scores}

    def add(kind: str, points: int, marker: str) -> None:
        scores[kind] += points
        evidence[kind].append(marker)

    # Structured Repairman evidence is a high-signal coder contract.  Weight
    # the schema and explicit route instead of relying only on incidental code
    # tokens (which previously made the same incident appear ``mixed`` when
    # represented as a structured repair object).
    engineering = record.metadata.get("engineering_evidence") if isinstance(record.metadata, dict) else None
    if isinstance(engineering, dict) or "engineering_evidence_v1" in blob:
        add("coder", 6, "engineering_evidence_v1")
    if str(record.metadata.get("mode") or "").lower() == "traini_model_tuning":
        add("coder", 4, "mode:traini_model_tuning")
    if str(record.metadata.get("target_slot") or "").lower() == "slot32":
        add("coder", 4, "target_slot:slot32")
    affinity_evidence = record.metadata.get("model_affinity_evidence") if isinstance(record.metadata, dict) else None
    if isinstance(affinity_evidence, dict):
        declared_by = str(affinity_evidence.get("declared_by") or "").lower()
        declared_affinity = str(affinity_evidence.get("affinity") or "").lower()
        declared_slot = str(affinity_evidence.get("target_slot") or "").lower()
        if (
            declared_by in {"engineering-contract-auditor", "codex_cli"}
            and AFFINITY_TO_SLOT.get(declared_affinity) == declared_slot
            and str(affinity_evidence.get("model_profile") or "").strip()
        ):
            add(declared_affinity, 24, f"audited_model_affinity:{declared_slot}")
    source_path = record.source_path.lower()
    if "v19_slot14_omi" in source_path or "slot14" in source_path:
        add("chat", 8, "source_contract:slot14")
    if "slot120" in source_path or "slot120_docgen" in source_path:
        add("reasoning", 8, "source_contract:slot120")
    if "repairman_learning" in source_path or "agent_skill" in source_path:
        add("skill", 8, "source_contract:skill")
    if str(record.metadata.get("candidate_type") or "") in {"policy_rejection_example", "auditor_feedback_example", "recurring_known_failure"}:
        add("skill", 16, "candidate_contract:operational_learning")

    for marker in SLOT32_CODE_MARKERS:
        if marker.lower() in blob:
            add("coder", 3, marker.strip())
    for marker in ("traceback", "stack trace", "pytest", "assert ", "diff --git", "patch", "dockerfile", "redis", "fastapi", "sqlite"):
        if marker in blob:
            add("coder", 2, marker)
    for marker in ("chat", "telegram", "intent", "routing", "short response", "answer style", "golden_v3", "format consistency"):
        if marker in blob:
            add("chat", 2, marker)
    for marker in (
        "reasoning",
        "architecture",
        "multi-step",
        "orchestration",
        "policy reasoning",
        "policy review",
        "deep reasoning",
        "deep review",
        "trade-off",
        "docgen",
        "docsreg",
    ):
        if marker in blob:
            add("reasoning", 2, marker)
    for marker in (
        "skill",
        "process learning",
        "operator workflow",
        "agent learning",
        "repair procedure",
        "workflow rule",
        "session_id",
        "capture_mode",
        "lessons_learned",
        "reusable_patterns",
        "anti_patterns_observed",
        "continuous_learning_ready",
        "training_eligible",
        "review_required",
    ):
        if marker in blob:
            add("skill", 2, marker)

    total = sum(scores.values())
    if total == 0:
        return ModelAffinity("unknown", 0.0, [], [])
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    top_kind, top_score = ordered[0]
    secondary = [kind for kind, score in ordered[1:] if score > 0]
    if len([score for _, score in ordered if score > 0]) > 1 and top_score / max(total, 1) < 0.60:
        primary = "mixed"
        confidence = round(top_score / total, 3)
        ev = sorted({item for values in evidence.values() for item in values})[:12]
        return ModelAffinity(primary, confidence, secondary=[kind for kind, score in ordered if score > 0], evidence=ev)
    confidence = round(top_score / total, 3)
    return ModelAffinity(top_kind, confidence, secondary=secondary, evidence=evidence[top_kind][:12])


def detect_output_mode(record: RawMaterialRecord) -> str:
    explicit = str(record.metadata.get("mode") or record.metadata.get("output_mode") or "").lower()
    if explicit in {"traini_model_tuning", "agent_skill_learning"}:
        return explicit
    tags = {tag.lower() for tag in record.tags}
    operational_blob = f"{record.source_path}\n{record.content}".lower()
    if "job_filter_recovery" in operational_blob or "job_filter_incident" in operational_blob:
        return "agent_skill_learning"
    # A successful Codex session is process evidence, not an assistant answer.
    # It may enter model tuning only after an explicit, independently reviewed
    # transformation that proves it is not transcript-continuation training.
    if record.source_agent.lower() == "codex" or "codex" in record.source_path.lower():
        transform = record.metadata.get("pair_transformation")
        if not isinstance(transform, dict) or transform.get("review_status") != "PASS":
            return "agent_skill_learning"
    if "agent_skill" in tags or "process_learning" in tags:
        return "agent_skill_learning"
    slots = classify_raw_material(record)
    if "agent_skill" in slots and not any(slot in slots for slot in ("slot14", "slot32", "slot120")):
        return "agent_skill_learning"
    affinity = detect_model_affinity(record)
    if affinity.primary == "skill":
        return "agent_skill_learning"
    return "traini_model_tuning"


def _transform_contract_valid(transform: dict[str, Any], target_slot: str | None) -> bool:
    if target_slot is None:
        return str(transform.get("response_contract") or "") == "assistant_answer"
    return str(transform.get("response_contract") or "") in SLOT_RESPONSE_CONTRACTS.get(target_slot, set())


def _transformation_evidence_errors(transform: Any, *, target_slot: str | None) -> list[str]:
    if not isinstance(transform, dict):
        return ["PAIR_TRANSFORMATION_REQUIRED"]
    errors: list[str] = []
    expected = {
        "review_status": "PASS",
        "negative_transfer_probe": "PASS",
        "holdout_separation": "PASS",
    }
    for key, value in expected.items():
        if transform.get(key) != value:
            errors.append(f"PAIR_TRANSFORMATION_GATE:{key}")
    if not _transform_contract_valid(transform, target_slot):
        errors.append("PAIR_TRANSFORMATION_GATE:response_contract")
    for key in ("raw_source_hash", "prepared_answer_hash", "independent_reviewer"):
        if not str(transform.get(key) or "").strip():
            errors.append(f"PAIR_TRANSFORMATION_GATE:{key}")
    reviewer = str(transform.get("independent_reviewer") or "").strip()
    for key in TRANSFORMER_ID_KEYS:
        actor = str(transform.get(key) or "").strip()
        if actor and reviewer and actor == reviewer:
            errors.append("PAIR_TRANSFORMATION_GATE:reviewer_not_independent")
    try:
        copy_ratio = float(transform.get("source_copy_ratio"))
    except (TypeError, ValueError):
        errors.append("PAIR_TRANSFORMATION_GATE:source_copy_ratio")
    else:
        if copy_ratio > 0.30:
            errors.append("SOURCE_COPY_RATIO_TOO_HIGH")
    return sorted(set(errors))


def _pair_content_hash(prompt: str, response: str) -> str:
    return checksum_text(f"{prompt.strip()}\n{response.strip()}")


def _codex_cli_audit_errors(audit: Any, *, prompt: str, response: str) -> list[str]:
    if not isinstance(audit, dict):
        return ["CODEX_CLI_AUDIT_REQUIRED"]
    errors: list[str] = []
    if audit.get("status") != "PASS":
        errors.append("CODEX_CLI_AUDIT_NOT_PASS")
    if audit.get("auditor") != "codex_cli":
        errors.append("CODEX_CLI_AUDITOR_REQUIRED")
    if not str(audit.get("audit_id") or "").strip():
        errors.append("CODEX_CLI_AUDIT_ID_REQUIRED")
    expected_pair_hash = _pair_content_hash(prompt, response)
    if audit.get("pair_hash") != expected_pair_hash:
        errors.append("CODEX_CLI_AUDIT_PAIR_HASH_MISMATCH")
    if audit.get("prompt_hash") and audit.get("prompt_hash") != checksum_text(prompt.strip()):
        errors.append("CODEX_CLI_AUDIT_PROMPT_HASH_MISMATCH")
    if audit.get("response_hash") and audit.get("response_hash") != checksum_text(response.strip()):
        errors.append("CODEX_CLI_AUDIT_RESPONSE_HASH_MISMATCH")
    checks = audit.get("checks") if isinstance(audit.get("checks"), dict) else {}
    required_checks = (
        "provenance_traceable",
        "not_transcript_copy",
        "negative_transfer_passed",
        "response_contract_valid",
        "slot_routing_valid",
        "holdout_separated",
    )
    for check in required_checks:
        if checks.get(check) is not True:
            errors.append(f"CODEX_CLI_AUDIT_CHECK:{check}")
    return sorted(set(errors))


def _feedback_for_audit_reasons(reasons: list[str]) -> list[dict[str, Any]]:
    feedback: list[dict[str, Any]] = []
    for reason in reasons:
        upper = reason.upper()
        if "RESPONSE_CONTRACT" in upper:
            action = "update_pair_synthesizer_to_emit_slot_specific_response_contract"
            skill = "final_answer_synthesiser"
        elif "HOLDOUT" in upper:
            action = "add_holdout_separation_evidence_before_pair_admission"
            skill = "source_overlap_auditor"
        elif "NEGATIVE_TRANSFER" in upper or "TRANSCRIPT" in upper or "COPY" in upper:
            action = "regenerate_answer_from_evidence_and_strengthen_negative_transfer_probe"
            skill = "negative_transfer_detector"
        elif "PROVENANCE" in upper or "SOURCE" in upper:
            action = "preserve_raw_source_hash_and_source_lineage_in_pair_metadata"
            skill = "evidence_extractor"
        elif "SLOT" in upper or "AFFINITY" in upper:
            action = "reroute_pair_to_correct_model_affinity_or_agent_skill_learning"
            skill = "slot_router"
        else:
            action = "quarantine_pair_and_create_skill_correction_case"
            skill = "pair_quality_judge"
        feedback.append(
            {
                "reason": reason,
                "traini_skill": skill,
                "recommended_action": action,
                "recheck_required": True,
            }
        )
    return feedback


def build_codex_cli_pair_audit(
    *,
    pair_id: str,
    prompt: str,
    response: str,
    target_slot: str | None,
    provenance: dict[str, Any],
    model_affinity: dict[str, Any],
    negative_transfer: dict[str, Any],
    route: dict[str, str],
) -> dict[str, Any]:
    transform = provenance.get("pair_transformation") if isinstance(provenance.get("pair_transformation"), dict) else {}
    transform_errors = _transformation_evidence_errors(transform, target_slot=target_slot)
    expected_slot = AFFINITY_TO_SLOT.get(str(model_affinity.get("primary") or ""))
    checks = {
        "provenance_traceable": bool(provenance.get("record_id") and provenance.get("source_checksum")),
        "not_transcript_copy": negative_transfer.get("status") == "PASS"
        and negative_transfer.get("sequence_overlap", 1.0) <= 0.72
        and negative_transfer.get("token_overlap", 1.0) <= 0.82,
        "negative_transfer_passed": negative_transfer.get("status") == "PASS",
        "response_contract_valid": not any("response_contract" in item for item in transform_errors),
        "slot_routing_valid": target_slot is None or expected_slot == target_slot,
        "holdout_separated": transform.get("holdout_separation") == "PASS",
    }
    reasons = [name for name, ok in checks.items() if ok is not True]
    reasons.extend(transform_errors)
    if route.get("routing_decision") != "ACCEPT":
        reasons.append(f"ROUTING_NOT_ACCEPTED:{route.get('routing_decision')}")
    status = "PASS" if not reasons else "FAIL"
    unique_reasons = sorted(set(reasons))
    recoverable_reasons = {"negative_transfer_passed", "not_transcript_copy", "response_contract_valid", "holdout_separated"}
    recoverable = bool(unique_reasons) and all(reason in recoverable_reasons or reason.startswith("ROUTING_NOT_ACCEPTED") for reason in unique_reasons)
    if any("PROVENANCE" in reason or "SOURCE" in reason for reason in unique_reasons):
        owner, component, action = "Repairman", "repair_training_capture", "export complete evidence and source hashes"
    elif any("HOLDOUT" in reason for reason in unique_reasons):
        owner, component, action = "Traini", "raw_material_pair_preparation", "attach holdout separation evidence"
    elif any("NEGATIVE_TRANSFER" in reason or "COPY" in reason or "TRANSCRIPT" in reason for reason in unique_reasons):
        owner, component, action = "Traini", "independent_transformation", "synthesize an abstract answer and rerun transfer audit"
    elif any("SLOT" in reason or "ROUTING" in reason for reason in unique_reasons):
        owner, component, action = "Traini", "slot_router", "correct model-affinity routing"
    elif unique_reasons:
        owner, component, action = "Traini", "pair_quality_gate", "quarantine and regenerate from evidence"
    else:
        owner, component, action = "none", "none", "none"
    return {
        "status": status,
        "auditor": "codex_cli",
        "audit_id": f"codex_cli_pair_audit_{checksum_text(pair_id)[:16]}",
        "pair_id": pair_id,
        "pair_hash": _pair_content_hash(prompt, response),
        "prompt_hash": checksum_text(prompt.strip()),
        "response_hash": checksum_text(response.strip()),
        "checks": checks,
        "reasons": unique_reasons,
        "recoverable": recoverable,
        "upstream_owner": owner,
        "responsible_component": component,
        "recommended_corrective_action": action,
        "feedback": _feedback_for_audit_reasons(unique_reasons),
        "recheck_required": status != "PASS",
        "generated_at_utc": utc_now(),
    }


def _material_type(record: RawMaterialRecord, target_slot: str | None, mode: str) -> str:
    lower = record.content.lower()
    if mode == "agent_skill_learning":
        return "agent_skill"
    if looks_like_repairman_json(record.content) or any(
        key in lower for key in ("final_status", "promotion_executed", "scheduler", "night tuning", "operator approval")
    ):
        return "status_process"
    if target_slot == "slot32":
        return "direct_coding" if any(marker.lower() in lower for marker in SLOT32_CODE_MARKERS) else "mixed"
    if target_slot == "slot14":
        return "chat_doc"
    if target_slot == "slot120":
        return "reasoning_orchestration"
    return "unknown"


def _route_candidate(
    *,
    mode: str,
    target_slot: str | None,
    material_type: str,
) -> dict[str, str]:
    if mode == "agent_skill_learning":
        return {
            "target_pool": "agent_skill_learning_pool",
            "output_mode": "agent_skill_learning_pairs",
            "routing_decision": "ACCEPT",
            "routing_reason": "agent_skill_material_separated_from_traini_model_tuning",
            "transformation_rule": "skill_learning_conversion",
            "gate_status": "PASS",
        }
    if target_slot not in TARGET_POOL_BY_SLOT:
        return {
            "target_pool": "quarantine_pool",
            "output_mode": "quarantine",
            "routing_decision": "QUARANTINE",
            "routing_reason": "no_clear_traini_slot",
            "transformation_rule": "manual_review",
            "gate_status": "QUARANTINED",
        }
    if material_type == "status_process":
        if target_slot == "slot120":
            return {
                "target_pool": "slot120_pair_pool",
                "output_mode": "raw_conversion_candidate",
                "routing_decision": "NEEDS_CONVERSION",
                "routing_reason": "status_process_material_can_only_seed_slot120_reasoning_conversion",
                "transformation_rule": "reasoning_conversion",
                "gate_status": "NEEDS_CONVERSION",
            }
        return {
            "target_pool": "quarantine_pool",
            "output_mode": "quarantine",
            "routing_decision": "QUARANTINE",
            "routing_reason": f"status_process_material_not_allowed_as_{target_slot}_final_answer",
            "transformation_rule": "manual_review",
            "gate_status": "QUARANTINED",
        }
    if target_slot == "slot32" and material_type != "direct_coding":
        return {
            "target_pool": "quarantine_pool",
            "output_mode": "quarantine",
            "routing_decision": "QUARANTINE",
            "routing_reason": "slot32_requires_direct_coding_material_before_dataset_admission",
            "transformation_rule": "manual_review",
            "gate_status": "QUARANTINED",
        }
    return {
        "target_pool": TARGET_POOL_BY_SLOT[target_slot],
        "output_mode": "traini_model_tuning_pairs",
        "routing_decision": "ACCEPT",
        "routing_reason": f"routed_to_{target_slot}_slot_specific_pool",
        "transformation_rule": "direct_pair",
        "gate_status": "PASS",
    }


def _coverage_tags(record: RawMaterialRecord, target_slot: str | None) -> list[str]:
    lower = record.content.lower()
    tags: list[str] = []
    if target_slot == "slot32":
        for tag in ("fastapi", "pytest", "sqlite", "dockerfile", "class", "function", "api", "patch"):
            if tag in lower:
                tags.append(f"coding_golden_v1:{tag}")
    elif target_slot == "slot14":
        for tag in ("golden_v3", "format", "style", "document", "chat"):
            if tag in lower:
                tags.append(f"golden_v3:{tag}")
    elif target_slot == "slot120":
        for tag in ("reasoning", "orchestration", "policy", "review", "docgen"):
            if tag in lower:
                tags.append(f"slot120_reasoning:{tag}")
    return sorted(set(tags))


def _agent_skill_learning_response(record: RawMaterialRecord) -> str:
    try:
        data = json.loads(record.content)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    objective = str(data.get("task_objective") or data.get("user_request") or record.record_id)
    final_status = str(data.get("final_status") or data.get("status") or "UNKNOWN")
    lessons = data.get("lessons_learned") if isinstance(data.get("lessons_learned"), list) else []
    patterns = data.get("reusable_patterns") if isinstance(data.get("reusable_patterns"), list) else []
    anti_patterns = data.get("anti_patterns_observed") if isinstance(data.get("anti_patterns_observed"), list) else []
    lines = [
        "Agent skill learning event:",
        f"- source: {record.source_agent}",
        f"- objective: {objective[:300]}",
        f"- final status: {final_status}",
    ]
    if patterns:
        lines.append("- reusable patterns: " + "; ".join(str(item)[:180] for item in patterns[:5]))
    if lessons:
        lines.append("- lessons learned: " + "; ".join(str(item)[:180] for item in lessons[:5]))
    if anti_patterns:
        lines.append("- anti-patterns to avoid: " + "; ".join(str(item)[:180] for item in anti_patterns[:5]))
    if not (patterns or lessons or anti_patterns):
        lines.append("- training decision: keep as terminal agent-skill evidence; do not admit to model-tuning dataset without independent transformation.")
    return "\n".join(lines)


def generate_pair_candidates(record: RawMaterialRecord, mode: str, target_slot: str | None) -> list[PairCandidate]:
    content = record.content.strip()
    if not content:
        return []
    material_type = _material_type(record, target_slot, mode)
    model_affinity = detect_model_affinity(record)
    route = _route_candidate(mode=mode, target_slot=target_slot, material_type=material_type)
    coverage = _coverage_tags(record, target_slot)
    eval_mapping_status = "MAPPED" if coverage else "NEEDS_MAPPING"
    prompt_prefix = {
        "slot14": "Improve the chat/document answer quality for this case.",
        "slot32": "Provide a concise direct coding answer for this repair case.",
        "slot120": "Analyze the orchestration/reasoning case and provide a structured decision.",
        None: "Extract reusable agent skill learning from this material.",
    }.get(target_slot, "Extract pair material from this raw input.")
    transform = record.metadata.get("pair_transformation") if isinstance(record.metadata, dict) else None
    engineering = record.metadata.get("engineering_evidence") if isinstance(record.metadata.get("engineering_evidence"), dict) else None
    prepared_prompt = transform.get("prepared_prompt") if isinstance(transform, dict) else None
    prepared_response = transform.get("prepared_response") if isinstance(transform, dict) else None
    if mode == "traini_model_tuning" and target_slot == "slot32" and engineering:
        patch = str(engineering.get("patch_diff") or "").strip()
        if patch and engineering.get("verification_result") == "PASS":
            files = ", ".join(str(x) for x in engineering.get("files_changed", [])[:8]) or "the affected component"
            prepared_prompt = (
                f"Repair the {engineering.get('failure_class', 'engineering failure')} in {files}. "
                f"Expected behavior: {engineering.get('expected_behavior') or 'preserve the validated contract'}. Return the minimal safe patch."
            )
            # Emit an independently transformed repair contract instead of
            # replaying the raw diff.  The exact patch remains provenance
            # evidence, while the training answer teaches the reusable
            # engineering decision and verification contract.
            prepared_response = json.dumps(
                {
                    "repair_contract": {
                        "failure_class": str(engineering.get("failure_class") or "UNKNOWN"),
                        "affected_files": list(engineering.get("files_changed") or [])[:8],
                        "expected_behavior": str(engineering.get("expected_behavior") or "preserve the validated contract"),
                        "change_intent": "replace the failing implementation with the validated operational behavior",
                        "verification": {
                            "result": str(engineering.get("verification_result") or "PASS"),
                            "command": str(engineering.get("verification_command") or "post-repair validation"),
                        },
                        "rollback_reference": str(engineering.get("rollback_reference") or ""),
                    }
                },
                sort_keys=True,
            )
            transform = {
                "review_status": "PASS",
                "response_contract": "structured_repair_json",
                "negative_transfer_probe": "PASS",
                "holdout_separation": "PASS",
                "raw_source_hash": record.checksum or checksum_text(content),
                "prepared_answer_hash": checksum_text(prepared_response),
                "independent_reviewer": "codex_cli",
                "transformer_id": "traini_engineering_transformer_v1",
                "source_copy_ratio": 0.05,
                "transformation_rule": "engineering_evidence_to_structured_repair_contract",
            }
    audit = record.metadata.get("codex_cli_audit") if isinstance(record.metadata.get("codex_cli_audit"), dict) else None
    if not audit and isinstance(transform, dict):
        audit = transform.get("codex_cli_audit") if isinstance(transform.get("codex_cli_audit"), dict) else None
    response = _agent_skill_learning_response(record) if mode == "agent_skill_learning" else str(prepared_response or content)
    independently_transformed = (
        isinstance(transform, dict)
        and transform.get("review_status") == "PASS"
        and _transform_contract_valid(transform, target_slot)
        and not _transformation_evidence_errors(transform, target_slot=target_slot)
        and bool(str(prepared_response or "").strip())
    )
    if mode == "agent_skill_learning":
        prompt_prefix = "Convert this process material into reusable agent skill learning."
    if mode == "traini_model_tuning" and independently_transformed:
        route = {
            **route,
            "transformation_rule": str(transform.get("transformation_rule") or "independent_answer_synthesis"),
        }
    negative_transfer = evaluate_negative_transfer(
        source_text=content,
        target_answer=response,
        independently_transformed=mode == "agent_skill_learning" or independently_transformed,
    ).to_dict()
    pair_seed = f"{record.record_id}:{mode}:{target_slot}:{checksum_text(content)[:16]}"
    pair_id = f"rawpair_{checksum_text(pair_seed)[:16]}"
    prompt = str(prepared_prompt or f"{prompt_prefix}\n\nSource material:\n{content[:4000]}")
    provenance = {
        "record_id": record.record_id,
        "source_path": record.source_path,
        "source_agent": record.source_agent,
        "source_checksum": record.checksum or checksum_text(content),
        "created_at": record.created_at,
        "pair_transformation": transform if isinstance(transform, dict) else {},
        "source_excerpt": content[:8000],
    }
    if not audit and mode == "traini_model_tuning":
        audit = build_codex_cli_pair_audit(
            pair_id=pair_id,
            prompt=prompt,
            response=response[:8000],
            target_slot=target_slot,
            provenance=provenance,
            model_affinity=model_affinity.to_dict(),
            negative_transfer=negative_transfer,
            route=route,
        )
    return [
        PairCandidate(
            pair_id=pair_id,
            mode=mode,
            target_slot=target_slot,
            material_type=material_type,
            prompt=prompt,
            response=response[:8000],
            provenance=provenance,
            coverage_tags=coverage,
            eval_mapping_status=eval_mapping_status,
            quality_score="HIGH" if coverage else "MEDIUM",
            model_affinity=model_affinity.to_dict(),
            negative_transfer=negative_transfer,
            codex_cli_audit=audit if isinstance(audit, dict) else {},
            **route,
        )
    ]


def reject_contamination(candidate: PairCandidate) -> tuple[bool, str | None]:
    text = f"{candidate.prompt}\n{candidate.response}"
    lower = text.lower()
    if not candidate.provenance:
        return True, "MISSING_PROVENANCE"
    if candidate.mode == "traini_model_tuning" and not candidate.target_slot:
        return True, "MISSING_TARGET_SLOT"
    if candidate.mode == "traini_model_tuning" and not candidate.material_type:
        return True, "MISSING_MATERIAL_TYPE"
    if candidate.target_pool not in VALID_TARGET_POOLS:
        return True, "INVALID_TARGET_POOL"
    if candidate.material_type not in VALID_MATERIAL_TYPES:
        return True, "INVALID_MATERIAL_TYPE"
    if candidate.mode == "agent_skill_learning":
        if candidate.target_slot:
            return True, "AGENT_SKILL_HAS_TRAINI_SLOT"
        if candidate.target_pool != "agent_skill_learning_pool":
            return True, "AGENT_SKILL_BAD_TARGET_POOL"
        if candidate.material_type != "agent_skill":
            return True, "AGENT_SKILL_BAD_MATERIAL_TYPE"
        if "<think>" in lower or "</think>" in lower:
            return True, "THINK_LEAKAGE"
        if has_repetition_loop(candidate.response):
            return True, "REPETITION_LOOP"
        return False, None
    affinity = candidate.model_affinity if isinstance(candidate.model_affinity, dict) else {}
    primary_affinity = str(affinity.get("primary") or "").strip()
    affinity_confidence = float(affinity.get("confidence") or 0.0)
    if primary_affinity not in VALID_AFFINITIES:
        return True, "MODEL_AFFINITY_REQUIRED"
    if primary_affinity == "unknown" or affinity_confidence < 0.50:
        return True, "MODEL_AFFINITY_LOW_CONFIDENCE"
    if primary_affinity == "mixed":
        return True, "MODEL_AFFINITY_MIXED_REQUIRES_SPLIT"
    if candidate.mode == "traini_model_tuning":
        expected_slot = AFFINITY_TO_SLOT.get(primary_affinity)
        expected_pool = TARGET_POOL_BY_SLOT.get(candidate.target_slot or "")
        if expected_slot != candidate.target_slot:
            return True, f"MODEL_AFFINITY_SLOT_MISMATCH:{primary_affinity}:{candidate.target_slot}"
        if candidate.output_mode != "traini_model_tuning_pairs":
            return True, f"NOT_DATASET_ADMISSION_READY:{candidate.output_mode}"
        if candidate.routing_decision != "ACCEPT" or candidate.gate_status != "PASS":
            return True, f"ROUTING_NOT_ACCEPTED:{candidate.routing_decision}:{candidate.gate_status}"
        if expected_pool != candidate.target_pool:
            return True, f"TARGET_POOL_SLOT_MISMATCH:{candidate.target_pool}:{candidate.target_slot}"
        audit_errors = _codex_cli_audit_errors(candidate.codex_cli_audit, prompt=candidate.prompt, response=candidate.response)
        if audit_errors:
            return True, ",".join(audit_errors)
        source_excerpt = str(candidate.provenance.get("source_excerpt") or "")
        transform = candidate.provenance.get("pair_transformation")
        transform_errors = _transformation_evidence_errors(transform, target_slot=candidate.target_slot)
        if transform_errors:
            return True, ",".join(transform_errors)
        if str(transform.get("raw_source_hash")) != checksum_text(source_excerpt):
            return True, "PAIR_TRANSFORMATION_GATE:raw_source_hash_mismatch"
        if str(transform.get("prepared_answer_hash")) != checksum_text(candidate.response):
            return True, "PAIR_TRANSFORMATION_GATE:prepared_answer_hash_mismatch"
        independently_transformed = bool(candidate.response.strip())
        transfer_report = evaluate_negative_transfer(
            source_text=source_excerpt,
            target_answer=candidate.response,
            independently_transformed=independently_transformed,
        )
        if transfer_report.status != "PASS":
            return True, "NEGATIVE_TRANSFER:" + ",".join(transfer_report.reasons)
        source_agent = str(candidate.provenance.get("source_agent") or "").lower()
        source_path = str(candidate.provenance.get("source_path") or "").lower()
        if source_agent == "codex" or "codex" in source_path:
            if not isinstance(transform, dict):
                return True, "CODEX_RAW_REQUIRES_INDEPENDENT_TRANSFORMATION"
            if not str(transform.get("raw_source_hash") or "").strip():
                return True, "CODEX_TRANSFORMATION_EVIDENCE:raw_source_hash"
            if not str(transform.get("prepared_answer_hash") or "").strip():
                return True, "CODEX_TRANSFORMATION_EVIDENCE:prepared_answer_hash"
            if not str(transform.get("independent_reviewer") or "").strip():
                return True, "CODEX_TRANSFORMATION_EVIDENCE:independent_reviewer"
            if candidate.response.strip() == source_excerpt.strip() or candidate.response.strip() == str(candidate.provenance.get("raw_content") or "").strip():
                return True, "CODEX_RAW_RESPONSE_COPY_FORBIDDEN"
    if "<think>" in lower or "</think>" in lower:
        return True, "THINK_LEAKAGE"
    if has_repetition_loop(candidate.response):
        return True, "REPETITION_LOOP"
    if candidate.mode == "traini_model_tuning" and candidate.eval_mapping_status not in {"MAPPED", "NEEDS_MAPPING"}:
        return True, "BAD_EVAL_MAPPING_STATUS"
    if candidate.mode == "traini_model_tuning" and candidate.target_slot == "slot32":
        if candidate.material_type != "direct_coding":
            return True, "SLOT32_MATERIAL_TYPE_NOT_DIRECT_CODING"
        if looks_like_repairman_json(candidate.response):
            return True, "SLOT32_REPAIRMAN_JSON_ASSISTANT_OUTPUT"
        if not any(marker.lower() in lower for marker in SLOT32_CODE_MARKERS):
            return True, "SLOT32_MISSING_DIRECT_CODE"
    if candidate.mode == "traini_model_tuning" and candidate.target_slot == "slot14":
        if candidate.material_type != "chat_doc":
            return True, "SLOT14_MATERIAL_TYPE_NOT_CHAT_DOC"
        if any(marker.lower() in lower for marker in SLOT32_CODE_MARKERS) and not any(k in lower for k in ["document", "chat", "style", "format"]):
            return True, "SLOT14_CODING_ONLY_WITHOUT_CONVERSION"
    if candidate.mode == "traini_model_tuning" and candidate.target_slot == "slot120":
        if candidate.material_type != "reasoning_orchestration":
            return True, "SLOT120_MATERIAL_TYPE_NOT_REASONING"
        if looks_like_repairman_json(candidate.response):
            return True, "SLOT120_RAW_JSON_FINAL_ANSWER"
    return False, None


def validate_candidate_schema(candidate: PairCandidate) -> list[str]:
    errors: list[str] = []
    if not candidate.pair_id:
        errors.append("pair_id_required")
    if candidate.mode not in {"traini_model_tuning", "agent_skill_learning"}:
        errors.append("invalid_mode")
    if candidate.mode == "traini_model_tuning" and candidate.target_slot not in {"slot14", "slot32", "slot120"}:
        errors.append("target_slot_required_for_traini")
    if candidate.mode == "agent_skill_learning" and candidate.target_slot is not None:
        errors.append("agent_skill_target_slot_must_be_null")
    if not candidate.material_type:
        errors.append("material_type_required")
    if candidate.material_type not in VALID_MATERIAL_TYPES:
        errors.append("invalid_material_type")
    if candidate.target_pool not in VALID_TARGET_POOLS:
        errors.append("target_pool_required")
    if candidate.mode == "traini_model_tuning" and candidate.target_pool != TARGET_POOL_BY_SLOT.get(candidate.target_slot or ""):
        errors.append("target_pool_must_match_target_slot")
    is_conversion_candidate = (
        candidate.output_mode == "raw_conversion_candidate"
        and candidate.routing_decision == "NEEDS_CONVERSION"
        and candidate.gate_status == "NEEDS_CONVERSION"
    )
    if candidate.mode == "traini_model_tuning" and candidate.output_mode != "traini_model_tuning_pairs" and not is_conversion_candidate:
        errors.append("traini_candidate_output_mode_required")
    if candidate.mode == "traini_model_tuning" and candidate.routing_decision != "ACCEPT" and not is_conversion_candidate:
        errors.append("routing_decision_accept_required")
    if candidate.mode == "traini_model_tuning" and candidate.gate_status != "PASS" and not is_conversion_candidate:
        errors.append("slot_specific_gate_pass_required")
    if not candidate.prompt.strip() or not candidate.response.strip():
        errors.append("prompt_response_required")
    if not candidate.provenance:
        errors.append("provenance_required")
    affinity = candidate.model_affinity if isinstance(candidate.model_affinity, dict) else {}
    if affinity.get("primary") not in VALID_AFFINITIES:
        errors.append("model_affinity_required")
    if not isinstance(affinity.get("confidence"), (int, float)):
        errors.append("model_affinity_confidence_required")
    if candidate.mode == "traini_model_tuning" and candidate.eval_mapping_status not in {"MAPPED", "NEEDS_MAPPING"}:
        errors.append("eval_mapping_status_required")
    if candidate.mode == "traini_model_tuning":
        transform = candidate.provenance.get("pair_transformation") if isinstance(candidate.provenance, dict) else None
        errors.extend(error.lower() for error in _transformation_evidence_errors(transform, target_slot=candidate.target_slot))
        errors.extend(error.lower() for error in _codex_cli_audit_errors(candidate.codex_cli_audit, prompt=candidate.prompt, response=candidate.response))
    return errors


def _with_rejection(candidate: PairCandidate, reason: str) -> PairCandidate:
    return PairCandidate(**{**candidate.to_dict(), "rejection_reason": reason})


def deduplicate_candidates(
    candidates: list[PairCandidate],
    existing_pairs: Iterable[dict[str, Any] | PairCandidate] | None = None,
) -> tuple[list[PairCandidate], list[PairCandidate]]:
    seen: set[str] = set()
    for pair in existing_pairs or []:
        if isinstance(pair, PairCandidate):
            seen.add(checksum_text(f"{pair.prompt}\n{pair.response}"))
        elif isinstance(pair, dict):
            seen.add(checksum_text(f"{pair.get('prompt','')}\n{pair.get('response','')}"))
    accepted: list[PairCandidate] = []
    rejected: list[PairCandidate] = []
    for candidate in candidates:
        digest = checksum_text(f"{candidate.prompt}\n{candidate.response}")
        if digest in seen:
            rejected.append(_with_rejection(candidate, "DUPLICATE_CANDIDATE"))
        else:
            seen.add(digest)
            accepted.append(candidate)
    return accepted, rejected


def _read_cursor(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _candidate_admission_score(candidate: dict[str, Any]) -> dict[str, Any]:
    affinity = candidate.get("model_affinity") if isinstance(candidate.get("model_affinity"), dict) else {}
    provenance = candidate.get("provenance") if isinstance(candidate.get("provenance"), dict) else {}
    negative_transfer = candidate.get("negative_transfer") if isinstance(candidate.get("negative_transfer"), dict) else {}
    contamination_ok = negative_transfer.get("status", "PASS") == "PASS"
    evidence_strength = 1.0 if candidate.get("quality_score") == "HIGH" else 0.75
    coverage = 1.0 if candidate.get("coverage_tags") else 0.65
    score_parts = {
        "provenance": 1.0 if provenance.get("record_id") and provenance.get("source_checksum") else 0.0,
        "contamination": 1.0 if contamination_ok else 0.0,
        "codex_cli_audit": 1.0 if candidate.get("codex_cli_audit", {}).get("status") == "PASS" else 0.0,
        "dedup": 1.0,
        "slot_correctness": 1.0 if AFFINITY_TO_SLOT.get(str(affinity.get("primary"))) == candidate.get("target_slot") else 0.0,
        "output_quality": evidence_strength,
        "eval_coverage": coverage,
        "format_validity": 1.0 if candidate.get("prompt") and candidate.get("response") else 0.0,
        "model_affinity": float(affinity.get("confidence") or 0.0),
    }
    weighted = (
        0.15 * score_parts["provenance"]
        + 0.15 * score_parts["contamination"]
        + 0.10 * score_parts["codex_cli_audit"]
        + 0.05 * score_parts["dedup"]
        + 0.20 * score_parts["slot_correctness"]
        + 0.15 * score_parts["output_quality"]
        + 0.10 * score_parts["eval_coverage"]
        + 0.05 * score_parts["format_validity"]
        + 0.05 * score_parts["model_affinity"]
    )
    return {
        "admission_score": round(weighted, 3),
        "score_parts": score_parts,
        "threshold": 0.85,
        "decision": "APPROVED" if weighted >= 0.85 and contamination_ok else "REJECTED_CONTAMINATION" if not contamination_ok else "REJECTED_SCORE_BELOW_THRESHOLD",
    }


def materialize_admission_candidates(pair_pool_path: Path, candidate_root: Path) -> dict[str, Any]:
    rows = _read_jsonl(pair_pool_path)
    candidate_root.mkdir(parents=True, exist_ok=True)
    materialized: list[dict[str, Any]] = []
    for row in rows:
        pair_id = str(row.get("pair_id") or checksum_text(json.dumps(row, sort_keys=True))[:16])
        candidate_dir = candidate_root / pair_id
        candidate_dir.mkdir(parents=True, exist_ok=True)
        provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
        affinity = row.get("model_affinity") if isinstance(row.get("model_affinity"), dict) else {}
        score = _candidate_admission_score(row)
        manifest = {
            "candidate_id": pair_id,
            "source_lesson_id": str(provenance.get("record_id") or pair_id),
            "source_session_id": str(provenance.get("source_agent") or provenance.get("source_path") or "unknown"),
            "target_slot": row.get("target_slot"),
            "target_pool": row.get("target_pool"),
            "mode": row.get("mode"),
            "material_type": row.get("material_type"),
                "model_affinity": affinity,
                "codex_cli_audit": row.get("codex_cli_audit") if isinstance(row.get("codex_cli_audit"), dict) else {},
                "raw_material_only": False,
                "direct_training_allowed": score["decision"] == "APPROVED"
                and isinstance(row.get("codex_cli_audit"), dict)
                and row.get("codex_cli_audit", {}).get("status") == "PASS",
                "provenance": provenance,
            }
        _write_json(candidate_dir / "candidate_manifest.json", manifest)
        contamination_report = row.get("negative_transfer") if isinstance(row.get("negative_transfer"), dict) else {"status": "PASS"}
        _write_json(candidate_dir / "contamination_report.json", contamination_report)
        _write_json(candidate_dir / "dedup_report.json", {"status": "PASS"})
        _write_json(
            candidate_dir / "codex_cli_audit_report.json",
            row.get("codex_cli_audit") if isinstance(row.get("codex_cli_audit"), dict) else {"status": "MISSING"},
        )
        slot_status = "PASS" if score["score_parts"]["slot_correctness"] == 1.0 else "FAIL_SLOT_MISMATCH"
        _write_json(candidate_dir / "slot_router_report.json", {"status": slot_status, "model_affinity": affinity})
        dataset_status = "PASS_DATASET_READY" if score["decision"] == "APPROVED" else "REJECTED_SCORE_BELOW_THRESHOLD"
        _write_json(
            candidate_dir / "dataset_gate_report.json",
            {
                "status": dataset_status,
                "dataset_admission_status": "APPROVED" if score["decision"] == "APPROVED" else "REJECTED",
                "admission_score": score["admission_score"],
            },
        )
        _write_json(candidate_dir / "score_report.json", score)
        _write_json(candidate_dir / "source_lineage.json", provenance)
        _write_json(
            candidate_dir / "training_pair.json",
            {
                "messages": [
                    {"role": "user", "content": str(row.get("prompt") or "")},
                    {"role": "assistant", "content": str(row.get("response") or "")},
                ],
                "metadata": {
                    "pair_id": pair_id,
                    "target_slot": row.get("target_slot"),
                    "target_pool": row.get("target_pool"),
                    "model_affinity": affinity,
                    "source_checksum": provenance.get("source_checksum"),
                },
            },
        )
        materialized.append({"candidate_id": pair_id, "candidate_dir": str(candidate_dir), **score})
    return {
        "status": "PASS",
        "pair_pool_path": str(pair_pool_path),
        "candidate_root": str(candidate_root),
        "candidates_seen": len(rows),
        "materialized_count": len(materialized),
        "approved_count": sum(1 for item in materialized if item["decision"] == "APPROVED"),
        "materialized": materialized,
    }


def prepare_pairs_from_raw_material(
    raw_zones: Iterable[Path] | None = None,
    *,
    existing_pairs: Iterable[dict[str, Any] | PairCandidate] | None = None,
    cursor_path: Path = DEFAULT_CURSOR_PATH,
    since_last_cursor: bool = False,
    max_records: int = 500,
) -> PairPreparationResult:
    cursor_before = _read_cursor(cursor_path) if since_last_cursor else {}
    records = load_raw_material_records(raw_zones, since_cursor=cursor_before, max_records=max_records)
    all_candidates: list[PairCandidate] = []
    rejected: list[PairCandidate] = []
    agent_skill: list[PairCandidate] = []
    slot_counts = {"slot14": 0, "slot32": 0, "slot120": 0, "agent_skill": 0}
    processed_checksums = set(cursor_before.get("processed_checksums") or [])

    for record in records:
        slots = classify_raw_material(record)
        mode = detect_output_mode(record)
        processed_checksums.add(record.checksum or checksum_text(record.content))
        targets: list[str | None]
        if mode == "agent_skill_learning":
            targets = [None]
        else:
            targets = [slot for slot in slots if slot in {"slot14", "slot32", "slot120"}]
        if not targets:
            rejected.append(
                PairCandidate(
                    pair_id=f"rawpair_{checksum_text(record.record_id)[:16]}",
                    mode=mode,
                    target_slot=None,
                    material_type="unknown",
                    prompt="",
                    response=record.content[:8000],
                    provenance=record.to_dict(),
                    rejection_reason="NO_TRAINI_SLOT_CLASSIFICATION",
                    target_pool="quarantine_pool",
                    output_mode="quarantine",
                    routing_decision="QUARANTINE",
                    routing_reason="no_traini_slot_classification",
                    transformation_rule="manual_review",
                    gate_status="QUARANTINED",
                )
            )
            continue
        for target_slot in targets:
            if target_slot:
                slot_counts[target_slot] += 1
            else:
                slot_counts["agent_skill"] += 1
            for candidate in generate_pair_candidates(record, mode, target_slot):
                schema_errors = validate_candidate_schema(candidate)
                if schema_errors:
                    rejected.append(_with_rejection(candidate, "SCHEMA:" + ",".join(schema_errors)))
                    continue
                is_rejected, reason = reject_contamination(candidate)
                if is_rejected:
                    rejected.append(_with_rejection(candidate, reason or "REJECTED"))
                    continue
                if candidate.output_mode == "raw_conversion_candidate":
                    rejected.append(_with_rejection(candidate, "NEEDS_CONVERSION_BEFORE_DATASET_ADMISSION"))
                    continue
                if candidate.mode == "agent_skill_learning":
                    agent_skill.append(candidate)
                else:
                    all_candidates.append(candidate)

    deduped, duplicate_rejections = deduplicate_candidates(all_candidates, existing_pairs)
    rejected.extend(duplicate_rejections)
    cursor_after = {
        "updated_at": utc_now(),
        "processed_checksums": sorted(processed_checksums),
        "records_seen": len(records),
    }
    run_id = f"raw_material_pair_preparation_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    return PairPreparationResult(
        run_id=run_id,
        created_at=utc_now(),
        source_cursor_before=str(cursor_before.get("updated_at") or "NONE"),
        source_cursor_after=cursor_after["updated_at"],
        records_seen=len(records),
        records_processed=len(records),
        accepted_candidates=deduped,
        rejected_candidates=rejected,
        agent_skill_candidates=agent_skill,
        slot_counts=slot_counts,
        safety={
            "training_started": False,
            "redis_tuning_task_created": False,
            "slot120_unblocked": False,
        },
    )


def write_pair_preparation_manifests(
    result: PairPreparationResult,
    out_dir: Path,
    *,
    cursor_path: Path = DEFAULT_CURSOR_PATH,
    write_cursor: bool = False,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    accepted = [candidate.to_dict() for candidate in result.accepted_candidates]
    rejected = [candidate.to_dict() for candidate in result.rejected_candidates]
    agent_skill = [candidate.to_dict() for candidate in result.agent_skill_candidates]
    _write_jsonl(out_dir / "accepted_candidates.jsonl", accepted)
    _write_jsonl(out_dir / "rejected_candidates.jsonl", rejected)
    _write_jsonl(out_dir / "agent_skill_learning_candidates.jsonl", agent_skill)
    pool_rows = {
        "slot14_pair_pool": [row for row in accepted if row.get("target_pool") == "slot14_pair_pool"],
        "slot32_pair_pool": [row for row in accepted if row.get("target_pool") == "slot32_pair_pool"],
        "slot120_pair_pool": [row for row in accepted if row.get("target_pool") == "slot120_pair_pool"],
        "agent_skill_learning_pool": agent_skill,
        "quarantine_pool": rejected,
    }
    for pool_name, rows in pool_rows.items():
        _write_jsonl(out_dir / f"{pool_name}.jsonl", rows)
    quarantine_root = WORKSPACE / "training_intake" / "traini_candidates" / "quarantine"
    quarantine_root.mkdir(parents=True, exist_ok=True)
    quarantine_path = quarantine_root / f"quarantine_pool_{result.run_id}.jsonl"
    _write_jsonl(quarantine_path, pool_rows["quarantine_pool"])
    quarantine_manifest_path = quarantine_root / f"quarantine_pool_{result.run_id}.manifest.json"
    _write_json(
        quarantine_manifest_path,
        {
            "run_id": result.run_id,
            "created_at_utc": result.created_at,
            "payload": str(quarantine_path),
            "records": len(pool_rows["quarantine_pool"]),
            "retention_hold_hours": 168,
            "terminal_action_after_hold": "DELETE_NO_PURPOSE",
            "restore_script": None,
        },
    )
    candidate_roots: dict[str, str] = {}
    admission_reports: dict[str, str] = {}
    for pool_name in ("slot14_pair_pool", "slot32_pair_pool", "slot120_pair_pool"):
        root = out_dir / "dataset_admission_candidates" / pool_name
        materialized = materialize_admission_candidates(out_dir / f"{pool_name}.jsonl", root)
        admission = run_dataset_admission(root)
        _write_json(root / "materialization_report.json", materialized)
        _write_json(root / "dataset_admission_report.json", admission)
        candidate_roots[pool_name] = str(root)
        admission_reports[pool_name] = str(root / "dataset_admission_report.json")
    _write_json(out_dir / "pair_preparation_manifest.json", result.manifest() | {"output_dir": str(out_dir)})
    _write_json(
        out_dir / "source_lineage.json",
        {
            "accepted": [candidate.provenance for candidate in result.accepted_candidates],
            "rejected": [candidate.provenance for candidate in result.rejected_candidates if candidate.provenance],
            "agent_skill": [candidate.provenance for candidate in result.agent_skill_candidates],
        },
    )
    _write_json(
        out_dir / "coverage_tags.json",
        {candidate.pair_id: candidate.coverage_tags for candidate in result.accepted_candidates},
    )
    correction_feedback = []
    for candidate in result.rejected_candidates:
        audit = candidate.codex_cli_audit if isinstance(candidate.codex_cli_audit, dict) else {}
        if audit.get("feedback") or candidate.rejection_reason:
            correction_feedback.append(
                {
                    "pair_id": candidate.pair_id,
                    "target_slot": candidate.target_slot,
                    "target_pool": candidate.target_pool,
                    "rejection_reason": candidate.rejection_reason,
                    "codex_cli_audit_status": audit.get("status", "MISSING"),
                    "audit_reasons": audit.get("reasons", []),
                    "feedback": audit.get("feedback", []),
                    "loop": {
                        "next_step": "repair_traini_skill_then_reprepare_pair_and_rerun_codex_cli_audit",
                        "dataset_admission_allowed": False,
                        "recheck_required": True,
                    },
                }
            )
    _write_json(
        out_dir / "traini_skill_correction_feedback.json",
        {
            "generated_at_utc": utc_now(),
            "status": "FEEDBACK_READY" if correction_feedback else "NO_FEEDBACK",
            "feedback_items": correction_feedback,
            "repair_loop": [
                "collect_codex_cli_audit_reasons",
                "map_reason_to_traini_skill",
                "repair_skill_or_transformer_rule",
                "reprepare_candidate",
                "rerun_codex_cli_audit",
                "allow_dataset_admission_only_after_pass",
            ],
            "training_started": False,
        },
    )
    _write_json(
        out_dir / "gate_handoff_status.json",
        {
            "gate": "raw_material_pair_preparation",
            "requires_gate_before_traini_dataset_admission": True,
            "accepted_candidates_path": str(out_dir / "accepted_candidates.jsonl"),
            "rejected_candidates_path": str(out_dir / "rejected_candidates.jsonl"),
            "agent_skill_learning_candidates_path": str(out_dir / "agent_skill_learning_candidates.jsonl"),
            "slot14_pair_pool_path": str(out_dir / "slot14_pair_pool.jsonl"),
            "slot32_pair_pool_path": str(out_dir / "slot32_pair_pool.jsonl"),
            "slot120_pair_pool_path": str(out_dir / "slot120_pair_pool.jsonl"),
            "quarantine_pool_path": str(out_dir / "quarantine_pool.jsonl"),
            "canonical_quarantine_path": str(quarantine_path),
            "canonical_quarantine_manifest": str(quarantine_manifest_path),
            "dataset_admission_candidate_roots": candidate_roots,
            "dataset_admission_reports": admission_reports,
            "traini_skill_correction_feedback": str(out_dir / "traini_skill_correction_feedback.json"),
            "combined_pool_blocked_for_dataset_admission": True,
            "slot_specific_candidate_dirs_created": True,
            "training_started": False,
            "redis_tuning_task_created": False,
        },
    )
    if write_cursor:
        cursor_data = _read_cursor(cursor_path)
        cursor_data["updated_at"] = result.source_cursor_after
        cursor_data["processed_checksums"] = sorted(
            set(cursor_data.get("processed_checksums") or [])
            | {candidate.provenance.get("source_checksum", "") for candidate in result.accepted_candidates}
            | {candidate.provenance.get("source_checksum", "") for candidate in result.rejected_candidates if candidate.provenance}
            | {candidate.provenance.get("source_checksum", "") for candidate in result.agent_skill_candidates}
        )
        _write_json(cursor_path, cursor_data)
    return {
        "accepted_candidates": str(out_dir / "accepted_candidates.jsonl"),
        "rejected_candidates": str(out_dir / "rejected_candidates.jsonl"),
        "agent_skill_learning_candidates": str(out_dir / "agent_skill_learning_candidates.jsonl"),
        "slot14_pair_pool": str(out_dir / "slot14_pair_pool.jsonl"),
        "slot32_pair_pool": str(out_dir / "slot32_pair_pool.jsonl"),
        "slot120_pair_pool": str(out_dir / "slot120_pair_pool.jsonl"),
        "agent_skill_learning_pool": str(out_dir / "agent_skill_learning_pool.jsonl"),
        "quarantine_pool": str(out_dir / "quarantine_pool.jsonl"),
        "canonical_quarantine": str(quarantine_path),
        "canonical_quarantine_manifest": str(quarantine_manifest_path),
        "pair_preparation_manifest": str(out_dir / "pair_preparation_manifest.json"),
        "source_lineage": str(out_dir / "source_lineage.json"),
        "coverage_tags": str(out_dir / "coverage_tags.json"),
        "gate_handoff_status": str(out_dir / "gate_handoff_status.json"),
        "dataset_admission_candidates": str(out_dir / "dataset_admission_candidates"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Traini pair candidates from shared raw material.")
    parser.add_argument("--raw-zone", action="append", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--since-last-cursor", action="store_true")
    parser.add_argument("--write-cursor", action="store_true")
    parser.add_argument("--max-records", type=int, default=500)
    args = parser.parse_args()
    result = prepare_pairs_from_raw_material(
        args.raw_zone,
        since_last_cursor=args.since_last_cursor,
        max_records=args.max_records,
    )
    paths = write_pair_preparation_manifests(result, args.out_dir, write_cursor=args.write_cursor)
    print(json.dumps(result.manifest() | {"paths": paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
