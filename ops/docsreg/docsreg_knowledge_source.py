"""
DOCSREG Knowledge Source Layer.

After every completed DOCSREG cycle, converts quality_report.json into a
canonical knowledge_entry.json and appends to append-only JSONL learning
artifacts.  Does NOT start model training — all candidates are written with
``approved_for_training=false`` and require a manual approval step.

Typical call sequence:
    from ops.docsreg.docsreg_knowledge_source import record_knowledge_source
    record_knowledge_source(evidence_dir=..., workspace_dir=..., ...)
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional


COMPONENT_KEYS: tuple[str, ...] = (
    "content_richness_score",
    "data_retention_score",
    "source_to_master_alignment_score",
    "structure_score",
    "metadata_safety_score",
)

# Audit statuses that are valid production outcomes from the real auditor.
# COMPONENT_BLOCKED is the legacy noop-auditor status and must not be treated
# as a normal production status.
RECOGNISED_AUDIT_STATUSES: frozenset[str] = frozenset({
    "COMPONENT_PASS",
    "COMPONENT_FAIL_REPAIRABLE",
    "READY_TO_FREEZE",
})

BOTTLENECK_LABELS: dict[str, dict[str, str]] = {
    "content_richness_score": {
        "label": "Content richness",
        "description": (
            "The master document retains insufficient useful source content. "
            "Typical causes: weak OCR, poor PDF extraction, missing body sections, "
            "over-aggressive cleaning, or chunking before complete extraction."
        ),
        "skill_target": "content_extraction",
    },
    "data_retention_score": {
        "label": "Data retention",
        "description": (
            "Important source data is missing or degraded. Typical causes: lost tables, "
            "dropped lists, failed spreadsheet parsing, or conversion that removes numeric data."
        ),
        "skill_target": "data_retention",
    },
    "source_to_master_alignment_score": {
        "label": "Source-to-master alignment",
        "description": (
            "The generated master document does not align closely enough with the source. "
            "Typical causes: hallucinated restructuring, missing source anchors, wrong template, "
            "or excessive normalisation."
        ),
        "skill_target": "source_alignment",
    },
    "structure_score": {
        "label": "Structure",
        "description": (
            "The master document structure is weak. Typical causes: missing headings, flat chunks, "
            "no section hierarchy, broken tables, or invalid schema."
        ),
        "skill_target": "master_structure",
    },
    "metadata_safety_score": {
        "label": "Metadata safety",
        "description": (
            "Metadata is incomplete, unsafe, inconsistent, or insufficiently traceable. "
            "Typical causes: missing source path, missing checksum, unsafe filename handling, "
            "or untracked archive provenance."
        ),
        "skill_target": "metadata_safety",
    },
}


# ── Filesystem helpers ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KnowledgePaths:
    evidence_dir: Path
    workspace_dir: Path

    @property
    def quality_report_path(self) -> Path:
        return self.evidence_dir / "quality_report.json"

    @property
    def knowledge_entry_path(self) -> Path:
        return self.evidence_dir / "knowledge_entry.json"

    @property
    def learning_jsonl_path(self) -> Path:
        return self.workspace_dir / "axi_ft_log" / "docsreg_learning.jsonl"

    @property
    def training_candidates_path(self) -> Path:
        return self.workspace_dir / "axi_ft_log" / "training_candidates.jsonl"

    @property
    def sft_gold_pairs_path(self) -> Path:
        return self.workspace_dir / "axi_ft_log" / "gold_pairs.jsonl"

    @property
    def dpo_pairs_path(self) -> Path:
        return self.workspace_dir / "axi_ft_log" / "dpo_pairs.jsonl"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_json_object(path: Path) -> dict[str, Any]:
    """Read and return a JSON object from *path*.  Raises on any error."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return data


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write *payload* as JSON to *path* atomically via a tmp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp_path, path)


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        f.write("\n")


def sha256_file(path: Optional[Path]) -> Optional[str]:
    if path is None or not path.exists() or not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def compute_file_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of *path*.

    Unlike :func:`sha256_file`, this raises rather than returning ``None``
    when the file is missing or unreadable.  Use at call sites where a
    missing file is an error, not a graceful skip.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _try_read_text(path_str: Optional[str]) -> Optional[str]:
    """Read text from *path_str* if it exists and is non-empty, else return None."""
    if not path_str:
        return None
    try:
        text = Path(path_str).read_text(encoding="utf-8").strip()
        return text if text else None
    except Exception:
        return None


def _find_prior_failed_entry(
    learning_path: Path,
    source_file: str,
    source_sha256: Optional[str],
) -> Optional[dict[str, Any]]:
    """Scan *learning_path* for the most recent failed entry matching source identity.

    Matches by sha256 first (handles renamed files), then by source_file string.
    Skips entries where ``outcome.passed`` is True.
    """
    if not learning_path.exists():
        return None
    last_failed: Optional[dict[str, Any]] = None
    try:
        with learning_path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    e = json.loads(raw)
                except Exception:
                    continue
                if e.get("outcome", {}).get("passed", True):
                    continue  # skip passing entries
                e_sha = e.get("source_sha256")
                e_file = e.get("source_file", "")
                if source_sha256 and e_sha:
                    # Both carry sha256: only match if equal.
                    # Different sha256 → not the same source; do NOT fall back.
                    if source_sha256 == e_sha:
                        last_failed = e
                elif not source_sha256 and not e_sha:
                    # Neither has a sha256: filename is the only identity signal.
                    if e_file and e_file == source_file:
                        last_failed = e
                # else: one has sha256 and the other does not → no match (strict).
    except Exception:
        pass
    return last_failed


# ── Score normalisation ────────────────────────────────────────────────────────


def normalise_component_scores(raw: Mapping[str, Any]) -> dict[str, float]:
    """Extract the five component scores from *raw*, handling both nested and flat layouts.

    Flat layout (older): scores at the root of quality_report.json.
    Nested layout (current): scores under ``component_scores`` sub-dict.
    Missing or non-numeric values default to 0.0.
    """
    if isinstance(raw.get("component_scores"), Mapping):
        source: Mapping[str, Any] = raw["component_scores"]
    else:
        source = raw

    out: dict[str, float] = {}
    for key in COMPONENT_KEYS:
        value = source.get(key, 0.0)
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            out[key] = 0.0
    return out


def determine_bottleneck(component_scores: Mapping[str, float]) -> dict[str, Any]:
    """Return the weakest component as a bottleneck descriptor."""
    key = min(COMPONENT_KEYS, key=lambda k: float(component_scores.get(k, 0.0)))
    score = float(component_scores.get(key, 0.0))
    meta = BOTTLENECK_LABELS[key]
    return {
        "key": key,
        "score": score,
        "label": meta["label"],
        "description": meta["description"],
        "skill_target": meta["skill_target"],
    }


# ── Recommendation builder ─────────────────────────────────────────────────────


def make_recommendations(
    *,
    bottleneck: Mapping[str, Any],
    quality: float,
    target_quality: float,
    file_type: Optional[str],
) -> list[dict[str, Any]]:
    key = str(bottleneck.get("key", "unknown"))
    skill_target = str(bottleneck.get("skill_target", "unknown"))
    gap = max(0.0, target_quality - quality)

    if gap >= 0.20:
        priority = "critical"
    elif gap >= 0.10:
        priority = "high"
    elif gap >= 0.03:
        priority = "medium"
    else:
        priority = "low"

    recs: list[dict[str, Any]] = [
        {
            "type": "skill",
            "target": skill_target,
            "priority": priority,
            "reason": f"{key} is the weakest component; quality gap is {gap:.3f}.",
        }
    ]

    if file_type:
        recs.append({
            "type": "parser",
            "target": f"{file_type.lower()}_parser",
            "priority": priority,
            "reason": f"Improve parser behaviour for file_type={file_type}.",
        })

    if key == "content_richness_score":
        recs.append({
            "type": "diagnostic",
            "target": "extracted_text_vs_source_size_ratio",
            "priority": "high",
            "reason": "Measure whether extraction loses source content before master generation.",
        })
    elif key == "data_retention_score":
        recs.append({
            "type": "diagnostic",
            "target": "table_and_numeric_retention",
            "priority": "high",
            "reason": "Measure table, numeric, and spreadsheet retention explicitly.",
        })

    return recs


# ── Quality report value extraction ───────────────────────────────────────────


def _extract_quality_report_values(quality_report: Mapping[str, Any]) -> dict[str, Any]:
    quality_raw = quality_report.get("quality", quality_report.get("composite_quality", 0.0))
    target_raw = quality_report.get("target_quality", quality_report.get("threshold", 0.80))
    audit_status = str(quality_report.get("audit_status", quality_report.get("status", "UNKNOWN")))
    passed_raw = quality_report.get("passed", None)

    try:
        quality_f = float(quality_raw)
    except (TypeError, ValueError):
        quality_f = 0.0

    try:
        target_f = float(target_raw)
    except (TypeError, ValueError):
        target_f = 0.80

    if passed_raw is None:
        passed = audit_status in {"COMPONENT_PASS", "READY_TO_FREEZE"} and quality_f >= target_f
    else:
        passed = bool(passed_raw)

    return {
        "quality": quality_f,
        "target_quality": target_f,
        "audit_status": audit_status,
        "passed": passed,
    }


# ── Training state ─────────────────────────────────────────────────────────────


def build_training_state(
    *,
    passed: bool,
    quality: float,
    target_quality: float,
    audit_status: str,
    has_prior_failure: bool,
) -> dict[str, Any]:
    """Compute SFT/DPO eligibility flags.

    ``approved_for_training`` is always False — manual approval is required.
    """
    eligible_for_sft = bool(
        passed
        and quality >= target_quality
        and audit_status in RECOGNISED_AUDIT_STATUSES
    )
    eligible_for_dpo = bool(eligible_for_sft and has_prior_failure)

    if eligible_for_dpo:
        reason = "current cycle passed and a prior failed attempt exists"
    elif eligible_for_sft:
        reason = "current cycle passed quality gate"
    elif audit_status not in RECOGNISED_AUDIT_STATUSES:
        reason = f"unrecognised audit status: {audit_status}"
    elif quality < target_quality:
        reason = f"quality below target: {quality:.3f} < {target_quality:.3f}"
    else:
        reason = "not eligible under current training policy"

    return {
        "candidate_created": True,
        "approved_for_training": False,
        "eligible_for_sft": eligible_for_sft,
        "eligible_for_dpo": eligible_for_dpo,
        "reason": reason,
    }


# ── Core entry builder ─────────────────────────────────────────────────────────


def build_knowledge_entry(
    *,
    quality_report: Mapping[str, Any],
    evidence_dir: Path,
    workspace_dir: Path,
    job_id: Optional[str] = None,
    doc_id: Optional[str] = None,
    cycle_id: Optional[str] = None,
    source_file: Optional[str] = None,
    file_type: Optional[str] = None,
    final_state: Optional[str] = None,
    model_slots: Optional[Mapping[str, str]] = None,
    pipeline_version: Optional[str] = None,
    has_prior_failure: bool = False,
) -> dict[str, Any]:
    """Build a canonical ``docsreg.knowledge.v1`` entry dict without writing to disk."""
    values = _extract_quality_report_values(quality_report)
    component_scores = normalise_component_scores(quality_report)
    bottleneck = determine_bottleneck(component_scores)

    source_path = Path(source_file) if source_file else None
    # Prefer an explicitly injected sha256 (e.g. archive member provenance) over
    # the value computed from the file on disk.  Falls back to sha256_file() when
    # the quality_report does not carry a pre-computed value.
    _report_sha = str(quality_report.get("source_sha256") or "").strip() or None
    source_sha = _report_sha or sha256_file(source_path)

    recommendations = make_recommendations(
        bottleneck=bottleneck,
        quality=values["quality"],
        target_quality=values["target_quality"],
        file_type=file_type,
    )

    training = build_training_state(
        passed=values["passed"],
        quality=values["quality"],
        target_quality=values["target_quality"],
        audit_status=values["audit_status"],
        has_prior_failure=has_prior_failure,
    )

    paths = KnowledgePaths(evidence_dir=evidence_dir, workspace_dir=workspace_dir)

    return {
        "schema_version": "docsreg.knowledge.v1",
        "created_at": utc_now_iso(),
        "job_id": job_id or str(quality_report.get("job_id") or ""),
        "doc_id": doc_id or str(quality_report.get("doc_id") or ""),
        "cycle_id": cycle_id or str(quality_report.get("cycle_id") or ""),
        "source_file": source_file or str(quality_report.get("source_file") or ""),
        "source_sha256": source_sha,
        "file_type": file_type or str(quality_report.get("file_type") or ""),
        "pipeline_version": pipeline_version or str(quality_report.get("pipeline_version") or "unknown"),
        "model_slots": dict(model_slots or {}),
        "real_auditor_used": values["audit_status"] in RECOGNISED_AUDIT_STATUSES,
        "outcome": {
            "passed": values["passed"],
            "quality": values["quality"],
            "target_quality": values["target_quality"],
            "audit_status": values["audit_status"],
            "final_state": final_state or str(quality_report.get("final_state") or ""),
        },
        "component_scores": component_scores,
        "bottleneck": bottleneck,
        "evidence": {
            "quality_report_path": str(paths.quality_report_path),
            "knowledge_entry_path": str(paths.knowledge_entry_path),
            "master_document_path": str(quality_report.get("master_document_path") or ""),
            "source_text_path": str(quality_report.get("source_text_path") or ""),
            "repair_log_path": str(quality_report.get("repair_log_path") or ""),
        },
        "recommendations": recommendations,
        "training": training,
        "approved_for_training": training["approved_for_training"],
    }


# ── Public API ─────────────────────────────────────────────────────────────────


def record_knowledge_source(
    *,
    evidence_dir: Path,
    workspace_dir: Path,
    quality_report: Optional[Mapping[str, Any]] = None,
    job_id: Optional[str] = None,
    doc_id: Optional[str] = None,
    cycle_id: Optional[str] = None,
    source_file: Optional[str] = None,
    file_type: Optional[str] = None,
    final_state: Optional[str] = None,
    model_slots: Optional[Mapping[str, str]] = None,
    pipeline_version: Optional[str] = None,
    has_prior_failure: bool = False,
    source_text: Optional[str] = None,
    response_text: Optional[str] = None,
) -> dict[str, Any]:
    """Write a knowledge entry and append to all learning JSONL files.

    If *quality_report* is None, reads ``evidence_dir/quality_report.json``.
    Raises if the quality report is missing or malformed — callers must handle
    this exception; it must not be silently swallowed.

    Always writes:
    - ``evidence_dir/knowledge_entry.json``
    - ``workspace_dir/axi_ft_log/docsreg_learning.jsonl``
    - ``workspace_dir/axi_ft_log/training_candidates.jsonl``

    Conditionally writes (real auditor + guards pass):
    - ``workspace_dir/axi_ft_log/gold_pairs.jsonl``   (SFT-eligible cycles)
    - ``workspace_dir/axi_ft_log/dpo_pairs.jsonl``    (DPO-eligible cycles)

    Returns the knowledge entry dict.
    """
    paths = KnowledgePaths(evidence_dir=evidence_dir, workspace_dir=workspace_dir)

    if quality_report is None:
        quality_report = read_json_object(paths.quality_report_path)

    entry = build_knowledge_entry(
        quality_report=quality_report,
        evidence_dir=evidence_dir,
        workspace_dir=workspace_dir,
        job_id=job_id,
        doc_id=doc_id,
        cycle_id=cycle_id,
        source_file=source_file,
        file_type=file_type,
        final_state=final_state,
        model_slots=model_slots,
        pipeline_version=pipeline_version,
        has_prior_failure=has_prior_failure,
    )

    write_json_atomic(paths.knowledge_entry_path, entry)
    append_jsonl(paths.learning_jsonl_path, entry)

    training_candidate = {
        "schema_version": "docsreg.training_candidate.v1",
        "created_at": entry["created_at"],
        "job_id": entry["job_id"],
        "doc_id": entry["doc_id"],
        "cycle_id": entry["cycle_id"],
        "source_file": entry["source_file"],
        "quality": entry["outcome"]["quality"],
        "target_quality": entry["outcome"]["target_quality"],
        "audit_status": entry["outcome"]["audit_status"],
        "bottleneck": entry["bottleneck"],
        "approved_for_training": False,
        "eligible_for_sft": entry["training"]["eligible_for_sft"],
        "eligible_for_dpo": entry["training"]["eligible_for_dpo"],
        "reason": entry["training"]["reason"],
        "knowledge_entry_path": str(paths.knowledge_entry_path),
    }
    append_jsonl(paths.training_candidates_path, training_candidate)

    # ── SFT gold pair ──────────────────────────────────────────────────────────
    # Write only when: real auditor used + SFT-eligible + source text not empty
    # + metadata_safety_score > 0.0 (score of exactly 0 is a hard block).
    if entry["training"]["eligible_for_sft"] and entry["real_auditor_used"]:
        _src_text = source_text or _try_read_text(
            quality_report.get("source_text_path")  # type: ignore[union-attr]
        )
        _resp_text = response_text or _try_read_text(
            quality_report.get("master_document_path")  # type: ignore[union-attr]
        )
        _meta_safety = entry["component_scores"].get("metadata_safety_score", 0.0)
        if _src_text and _resp_text and _meta_safety > 0.0:
            gold_pair = build_sft_pair_from_entry(
                entry=entry,
                source_text=_src_text,
                response_text=_resp_text,
            )
            append_jsonl(paths.sft_gold_pairs_path, gold_pair)

    # ── DPO pair ───────────────────────────────────────────────────────────────
    # Write only when: real auditor used + DPO-eligible + can find the prior
    # failed entry with a readable rejected response.
    if entry["training"]["eligible_for_dpo"] and entry["real_auditor_used"]:
        prior = _find_prior_failed_entry(
            paths.learning_jsonl_path,
            entry["source_file"],
            entry.get("source_sha256"),
        )
        if prior is not None:
            _chosen_resp = response_text or _try_read_text(
                quality_report.get("master_document_path")  # type: ignore[union-attr]
            )
            _rejected_resp = _try_read_text(
                prior.get("evidence", {}).get("master_document_path")
            )
            _src_text_dpo = source_text or _try_read_text(
                quality_report.get("source_text_path")  # type: ignore[union-attr]
            )
            if _chosen_resp and _rejected_resp and _src_text_dpo:
                try:
                    dpo_pair = build_dpo_pair_from_entries(
                        chosen_entry=entry,
                        rejected_entry=prior,
                        chosen_response=_chosen_resp,
                        rejected_response=_rejected_resp,
                        source_text=_src_text_dpo,
                    )
                    append_jsonl(paths.dpo_pairs_path, dpo_pair)
                except ValueError:
                    pass  # quality or identity constraint not met — skip silently

    return entry


# ── SFT / DPO pair builders ────────────────────────────────────────────────────


def build_sft_pair_from_entry(
    *,
    entry: Mapping[str, Any],
    source_text: str,
    response_text: str,
) -> dict[str, Any]:
    """Build an SFT training pair from an eligible knowledge entry.

    Raises ``ValueError`` if the entry is not eligible for SFT.
    The returned pair always has ``approved_for_training=False``.
    """
    if not entry.get("training", {}).get("eligible_for_sft"):
        raise ValueError(
            f"Knowledge entry doc_id={entry.get('doc_id')!r} is not eligible for SFT; "
            f"reason: {entry.get('training', {}).get('reason')!r}"
        )

    if not source_text or not source_text.strip():
        raise ValueError(
            f"source_text must not be empty for SFT pair (doc_id={entry.get('doc_id')!r})"
        )

    return {
        "schema_version": "docsreg.sft_pair.v1",
        "created_at": utc_now_iso(),
        "doc_id": entry.get("doc_id"),
        "cycle_id": entry.get("cycle_id"),
        "quality": entry.get("outcome", {}).get("quality"),
        "prompt": (
            "Convert the following source document into DOCSREG master document format "
            "while preserving content, structure, tables, traceability, and metadata safety.\n\n"
            f"{source_text}"
        ),
        "response": response_text,
        "approved_for_training": False,
        "knowledge_entry_path": entry.get("evidence", {}).get("knowledge_entry_path"),
    }


def build_dpo_pair_from_entries(
    *,
    chosen_entry: Mapping[str, Any],
    rejected_entry: Mapping[str, Any],
    chosen_response: str,
    rejected_response: str,
    source_text: str,
) -> dict[str, Any]:
    """Build a DPO preference pair from a chosen (passed) and rejected (failed) entry.

    Raises ``ValueError`` if the chosen entry is not DPO-eligible or if
    chosen quality is not strictly greater than rejected quality.
    The returned pair always has ``approved_for_training=False``.
    """
    if not chosen_entry.get("training", {}).get("eligible_for_dpo"):
        raise ValueError(
            f"Chosen entry doc_id={chosen_entry.get('doc_id')!r} is not eligible for DPO; "
            f"reason: {chosen_entry.get('training', {}).get('reason')!r}"
        )

    # Same-source identity check: sha256 first (handles renames), then filename.
    chosen_sha = chosen_entry.get("source_sha256")
    rejected_sha = rejected_entry.get("source_sha256")
    chosen_file = chosen_entry.get("source_file", "")
    rejected_file = rejected_entry.get("source_file", "")

    if chosen_sha and rejected_sha:
        same_source = chosen_sha == rejected_sha
    else:
        same_source = bool(chosen_file and chosen_file == rejected_file)

    if not same_source:
        raise ValueError(
            f"DPO chosen and rejected entries must share the same source identity; "
            f"chosen={chosen_file!r} (sha={chosen_sha!r}), "
            f"rejected={rejected_file!r} (sha={rejected_sha!r})"
        )

    chosen_quality = float(chosen_entry.get("outcome", {}).get("quality", 0.0))
    rejected_quality = float(rejected_entry.get("outcome", {}).get("quality", 0.0))

    if chosen_quality <= rejected_quality:
        raise ValueError(
            f"DPO chosen quality ({chosen_quality:.3f}) must be strictly greater "
            f"than rejected quality ({rejected_quality:.3f})"
        )

    chosen_bn = chosen_entry.get("bottleneck") or {}
    rejected_bn = rejected_entry.get("bottleneck") or {}

    return {
        "schema_version": "docsreg.dpo_pair.v1",
        "created_at": utc_now_iso(),
        "doc_id": chosen_entry.get("doc_id"),
        "chosen_cycle_id": chosen_entry.get("cycle_id"),
        "rejected_cycle_id": rejected_entry.get("cycle_id"),
        "source_file": chosen_file,
        "source_sha256": chosen_sha,
        "prompt": (
            "Convert the following source document into DOCSREG master document format "
            "with maximum preservation of content and structure.\n\n"
            f"{source_text}"
        ),
        "chosen": chosen_response,
        "rejected": rejected_response,
        "chosen_quality": chosen_quality,
        "rejected_quality": rejected_quality,
        "quality_delta": round(chosen_quality - rejected_quality, 6),
        "chosen_bottleneck": chosen_bn,
        "rejected_bottleneck": rejected_bn,
        "bottleneck_delta": {
            "chosen_key": chosen_bn.get("key"),
            "rejected_key": rejected_bn.get("key"),
            "chosen_score": chosen_bn.get("score"),
            "rejected_score": rejected_bn.get("score"),
        },
        "approved_for_training": False,
    }
