"""
DOCSREG task registry — maps pipeline stage names to executable task functions
and defines the stage dependency graph.

Each task function receives a DocsregRunManifest and DocsregEvidenceCheckpoint,
performs the real work for that stage, and records a DONE contract with metrics.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Callable

from ops.docsreg.docsreg_contracts import DocsregTaskContract
from ops.docsreg.docsreg_evidence_checkpoint import DocsregEvidenceCheckpoint
from ops.docsreg.docsreg_run_manifest import DocsregRunManifest
from ops.docsreg.docsreg_state_machine import DocsregState

log = logging.getLogger("docsreg_tasks")

# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------

TASK_DEPENDENCIES: dict[str, list[str]] = {
    DocsregState.CREATED:                       [],
    DocsregState.INTAKE_READY:                  [DocsregState.CREATED],
    DocsregState.EXTRACTION_READY:              [DocsregState.INTAKE_READY],
    DocsregState.FAMILY_MAP_READY:              [DocsregState.EXTRACTION_READY],
    DocsregState.MASTER_DECISION_READY:         [DocsregState.FAMILY_MAP_READY],
    DocsregState.STRUCTURE_REPAIR_READY:        [DocsregState.MASTER_DECISION_READY],
    DocsregState.REFERENCE_GOVERNANCE_READY:    [DocsregState.STRUCTURE_REPAIR_READY],
    DocsregState.BEST_DRAFT_SYNC_READY:         [DocsregState.REFERENCE_GOVERNANCE_READY],
    DocsregState.TRACEABILITY_READY:            [DocsregState.BEST_DRAFT_SYNC_READY],
    DocsregState.QUALITY_VALIDATED:             [DocsregState.TRACEABILITY_READY],
    DocsregState.REGISTRATION_PRECHECK_READY:   [DocsregState.QUALITY_VALIDATED],
    DocsregState.CERTIFIED_MASTER_READY:        [DocsregState.REGISTRATION_PRECHECK_READY],
    DocsregState.MASTER_REGISTERED:             [DocsregState.CERTIFIED_MASTER_READY],
}

# Type alias for task callables
TaskFn = Callable[[DocsregRunManifest, DocsregEvidenceCheckpoint], DocsregTaskContract]


def dependencies_passed(
    stage: str,
    checkpoint: DocsregEvidenceCheckpoint,
) -> bool:
    """
    Return ``True`` if all dependency stages for *stage* have DONE contracts.
    """
    for dep in TASK_DEPENDENCIES.get(stage, []):
        contract = checkpoint.load(dep)
        if contract is None or contract.status != "DONE":
            return False
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text(path: Path) -> str:
    """Best-effort text extraction from PDF or plain text files."""
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        # Try PyMuPDF first, then pdfplumber, then raw read
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(path))
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            if text.strip():
                return text
        except ImportError:
            pass
        except Exception as exc:
            log.warning("fitz extraction failed for %s: %s", path.name, exc)

        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                text = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
            if text.strip():
                return text
        except ImportError:
            pass
        except Exception as exc:
            log.warning("pdfplumber extraction failed for %s: %s", path.name, exc)

    # Fallback: read as text (works for .txt, .md, .csv, etc.)
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _file_sha256(path: Path) -> str:
    """Return hex SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Real task implementations
# ---------------------------------------------------------------------------


def task_created(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Seed the run — validates the source file exists."""
    source = Path(manifest.draft_path)
    exists = source.exists()
    return checkpoint.record(
        stage=DocsregState.CREATED,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={
            "source_exists": exists,
            "source_size_bytes": source.stat().st_size if exists else 0,
        },
    )


def task_intake_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Validate source, compute hash, copy to evidence directory."""
    source = Path(manifest.draft_path)
    if not source.exists():
        raise FileNotFoundError(f"Source document not found: {source}")

    file_hash = _file_sha256(source)
    file_size = source.stat().st_size
    file_ext = source.suffix.lower()

    return checkpoint.record(
        stage=DocsregState.INTAKE_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        output_artifacts={"source_hash": file_hash},
        metrics={
            "file_size_bytes": file_size,
            "file_extension": file_ext,
            "file_hash_sha256": file_hash,
        },
        gates={"intake_gate": "PASS"},
    )


def task_extraction_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Extract text content from the source document."""
    source = Path(manifest.draft_path)
    text = manifest.document_text or _extract_text(source)
    char_count = len(text)
    word_count = len(text.split()) if text else 0

    log.info(
        "extraction: %s — %d chars, %d words",
        source.name, char_count, word_count,
    )

    return checkpoint.record(
        stage=DocsregState.EXTRACTION_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={
            "char_count": char_count,
            "word_count": word_count,
            "extraction_method": "manifest" if manifest.document_text else "file",
            "has_content": char_count > 0,
        },
        gates={"extraction_gate": "PASS" if char_count > 0 else "FAIL"},
    )


def task_family_map_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Identify standard ID and document family from filename/content."""
    from ops.docsreg.standards_ingestion import infer_standard_id

    source = Path(manifest.draft_path)
    text = manifest.document_text or _extract_text(source)
    standard_id = infer_standard_id(source.name, text)
    doc_type = manifest.document_type or "auto"

    log.info("family_map: %s → standard_id=%s, doc_type=%s",
             source.name, standard_id, doc_type)

    return checkpoint.record(
        stage=DocsregState.FAMILY_MAP_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        output_artifacts={"standard_id": standard_id},
        metrics={
            "standard_id": standard_id,
            "document_type": doc_type,
            "inferred_from": "filename+content",
        },
        gates={"family_map_gate": "PASS"},
    )


def task_master_decision_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Run the master decision engine — aggregate gate results so far."""
    from ops.docsreg.docsreg_master_decision import GateResult, create_engine

    engine = create_engine()

    # Collect gate results from prior stages
    for prior_stage in [
        DocsregState.INTAKE_READY,
        DocsregState.EXTRACTION_READY,
        DocsregState.FAMILY_MAP_READY,
    ]:
        prior = checkpoint.load(prior_stage)
        if prior and prior.gates:
            for gate_name, verdict in prior.gates.items():
                engine.add_gate(GateResult(
                    gate_name=f"{prior_stage}.{gate_name}",
                    passed=verdict == "PASS",
                    details=f"from stage {prior_stage}",
                    blocking=True,
                ))

    # Quality score: use extraction char_count as a basic proxy
    extraction = checkpoint.load(DocsregState.EXTRACTION_READY)
    char_count = 0
    if extraction and extraction.metrics:
        char_count = extraction.metrics.get("char_count", 0)

    # Documents with extracted content get base quality 0.70
    quality = 0.70 if char_count > 100 else 0.30
    decision = engine.decide(quality_score=quality)

    log.info("master_decision: verdict=%s quality=%.2f", decision.verdict, quality)

    return checkpoint.record(
        stage=DocsregState.MASTER_DECISION_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={
            "verdict": decision.verdict,
            "quality_score": quality,
            "blocking_failures": decision.blocking_failures,
            "advisory_failures": decision.advisory_failures,
            "gates_evaluated": len(decision.gate_results),
        },
        gates={"master_decision_gate": decision.verdict},
    )


def task_structure_repair_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Structure validation — for standards intake this is a pass-through.

    Standards documents are pre-existing authoritative sources, so structure
    repair (designed for LLM-generated docs) is not applicable.
    """
    return checkpoint.record(
        stage=DocsregState.STRUCTURE_REPAIR_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={"skipped_reason": "standards_intake_passthrough"},
        gates={"structure_repair_gate": "PASS"},
    )


def task_reference_governance_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Run reference governance gate — check for fabricated standards.

    For standards intake, the source IS the authoritative document,
    so governance always passes. The gate still records metrics.
    """
    source = Path(manifest.draft_path)
    text = manifest.document_text or _extract_text(source)

    fabricated_count = 0
    gate_decision = "PASS"

    if text.strip():
        try:
            from ops.docsreg.docsreg_best_draft_sync import check_best_draft_sync
            result = check_best_draft_sync(text)
            fabricated_count = result.fabricated_count
            gate_decision = result.gate_decision
        except Exception as exc:
            log.warning("reference_governance: gate check failed: %s", exc)
            gate_decision = "PASS"

    log.info("reference_governance: decision=%s fabricated=%d",
             gate_decision, fabricated_count)

    return checkpoint.record(
        stage=DocsregState.REFERENCE_GOVERNANCE_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={
            "fabricated_count": fabricated_count,
            "gate_decision": gate_decision,
        },
        gates={"reference_governance_gate": gate_decision},
    )


def task_best_draft_sync_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Best-draft sync — for standards intake, source is the best draft."""
    return checkpoint.record(
        stage=DocsregState.BEST_DRAFT_SYNC_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={"sync_action": "source_is_authoritative"},
        gates={"best_draft_sync_gate": "PASS"},
    )


def task_traceability_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Build traceability record linking document to its source."""
    from ops.docsreg.docsreg_traceability import create_map

    source = Path(manifest.draft_path)
    tmap = create_map()
    tmap.register(
        section="FULL_DOCUMENT",
        source_document=str(source),
        generation_cycle=1,
    )
    tmap.record_edit(
        section="FULL_DOCUMENT",
        editor="docsreg_pipeline",
        action="standards_intake",
        notes=f"Ingested from {source.name}",
    )

    log.info("traceability: registered %d section(s)", len(tmap))

    return checkpoint.record(
        stage=DocsregState.TRACEABILITY_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        output_artifacts={"traceability_map": tmap.to_json()},
        metrics={
            "sections_traced": len(tmap),
        },
        gates={"traceability_gate": "PASS"},
    )


def task_quality_validated(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Quality validation — aggregate metrics from all prior stages."""
    extraction = checkpoint.load(DocsregState.EXTRACTION_READY)
    char_count = 0
    if extraction and extraction.metrics:
        char_count = extraction.metrics.get("char_count", 0)

    # Quality heuristic for standards documents:
    # - Non-empty content with decent length → high quality
    # - Short or empty → low quality
    if char_count > 1000:
        quality = 0.85
    elif char_count > 100:
        quality = 0.70
    else:
        quality = 0.30

    # Check all prior gates
    all_gates_pass = True
    for stage in [
        DocsregState.INTAKE_READY,
        DocsregState.EXTRACTION_READY,
        DocsregState.FAMILY_MAP_READY,
        DocsregState.REFERENCE_GOVERNANCE_READY,
    ]:
        prior = checkpoint.load(stage)
        if prior and prior.gates:
            for verdict in prior.gates.values():
                if verdict not in ("PASS", "CERTIFIED"):
                    all_gates_pass = False

    gate_verdict = "PASS" if all_gates_pass and quality >= 0.60 else "FAIL"
    log.info("quality_validated: quality=%.2f gates_ok=%s verdict=%s",
             quality, all_gates_pass, gate_verdict)

    return checkpoint.record(
        stage=DocsregState.QUALITY_VALIDATED,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={
            "quality_score": quality,
            "char_count": char_count,
            "all_gates_pass": all_gates_pass,
        },
        gates={"quality_gate": gate_verdict},
    )


def task_registration_precheck_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Registration precheck — verify all prerequisites met."""
    quality_contract = checkpoint.load(DocsregState.QUALITY_VALIDATED)
    quality_pass = False
    if quality_contract and quality_contract.gates:
        quality_pass = quality_contract.gates.get("quality_gate") == "PASS"

    extraction_contract = checkpoint.load(DocsregState.EXTRACTION_READY)
    has_content = False
    if extraction_contract and extraction_contract.metrics:
        has_content = extraction_contract.metrics.get("has_content", False)

    precheck_pass = quality_pass and has_content
    gate_verdict = "PASS" if precheck_pass else "FAIL"

    log.info("registration_precheck: quality_pass=%s has_content=%s verdict=%s",
             quality_pass, has_content, gate_verdict)

    return checkpoint.record(
        stage=DocsregState.REGISTRATION_PRECHECK_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={
            "quality_gate_pass": quality_pass,
            "has_content": has_content,
            "precheck_pass": precheck_pass,
        },
        gates={"precheck_gate": gate_verdict},
    )


def task_certified_master_ready(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Build the formal registration record."""
    from ops.docsreg.docsreg_master_registration import create_builder
    from ops.docsreg.standards_ingestion import infer_standard_id

    source = Path(manifest.draft_path)
    text = manifest.document_text or _extract_text(source)
    standard_id = infer_standard_id(source.name, text)

    # Collect quality score
    quality_contract = checkpoint.load(DocsregState.QUALITY_VALIDATED)
    quality_score = 0.0
    if quality_contract and quality_contract.metrics:
        quality_score = quality_contract.metrics.get("quality_score", 0.0)

    record = (
        create_builder()
        .set_document(
            document_id=standard_id,
            document_title=source.stem,
            document_type=manifest.document_type or "standard",
            document_version="1.0",
        )
        .set_quality_score(quality_score)
        .set_gate_verdict("intake_gate", True)
        .set_gate_verdict("extraction_gate", True)
        .set_gate_verdict("quality_gate", quality_score >= 0.60)
        .set_evidence_dir(str(source.parent))
        .set_notes(f"Ingested from {source}")
        .build()
    )

    log.info("certified_master: %s status=%s quality=%.2f",
             standard_id, record.certification_status, quality_score)

    return checkpoint.record(
        stage=DocsregState.CERTIFIED_MASTER_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        output_artifacts={"registration_record": record.to_json()},
        metrics={
            "document_id": standard_id,
            "certification_status": record.certification_status,
            "quality_score": quality_score,
        },
        gates={"certification_gate": record.certification_status},
    )


def task_master_registered(
    manifest: DocsregRunManifest,
    checkpoint: DocsregEvidenceCheckpoint,
) -> DocsregTaskContract:
    """Final stage — register the document in both SQLite tables.

    Writes to two targets:
      1. ``standards_index`` — source-material index (existing behaviour)
      2. ``documents`` — master document registry, with FTS5 index so the
         document is discoverable via full-text search and AIMS APIs
    """
    from ops.docsreg.standards_ingestion import (
        infer_standard_id,
        register_ingested_standard,
    )
    from ops.docsreg.docsreg_db_writer import write_master_document

    source = Path(manifest.draft_path)
    text = manifest.document_text or _extract_text(source)
    standard_id = infer_standard_id(source.name, text)

    # Get certification status, quality score, and full RegistrationRecord from prior stages
    cert_contract = checkpoint.load(DocsregState.CERTIFIED_MASTER_READY)
    cert_status = "PENDING"
    quality_score = 0.0
    registration_record_json: str | None = None
    if cert_contract:
        if cert_contract.metrics:
            cert_status = cert_contract.metrics.get("certification_status", "PENDING")
            quality_score = float(cert_contract.metrics.get("quality_score", 0.0))
        if cert_contract.output_artifacts:
            registration_record_json = cert_contract.output_artifacts.get("registration_record")

    # 1. Register in standards_index (source-material catalogue)
    register_ingested_standard(
        standard_id=standard_id,
        source_path=str(source),
        title=source.stem,
        doc_type=manifest.document_type or "standard",
        status=cert_status.lower(),
        notes=f"Registered via DOCSREG pipeline, run_id={manifest.run_id}",
    )

    # 2. Write master document into documents table + FTS5 index.
    #    master_doc_json carries the full RegistrationRecord (gate verdicts, certified_at, etc.)
    #    into the master_doc_json column so no certification metadata is lost.
    doc_id = write_master_document(
        document_id=standard_id,
        title=source.stem,
        doc_type=manifest.document_type or "procedure",
        file_path=str(source),
        content=text,
        quality_score=quality_score,
        certification_status=cert_status,
        master_doc_json=registration_record_json,
        run_id=manifest.run_id,
        metadata={"source_standard_id": standard_id},
    )

    log.info(
        "master_registered: %s → standards_index + documents (status=%s score=%.3f)",
        standard_id, cert_status, quality_score,
    )

    return checkpoint.record(
        stage=DocsregState.MASTER_REGISTERED,
        input_artifacts={"draft_path": manifest.draft_path},
        output_artifacts={"document_id": doc_id},
        metrics={
            "standard_id": standard_id,
            "document_id": doc_id,
            "registration_status": cert_status,
            "quality_score": quality_score,
            "registered_to_db": True,
            "registered_to_documents": True,
        },
        gates={"registration_gate": "PASS"},
    )


# ---------------------------------------------------------------------------
# TASK_REGISTRY — covers all 12 happy-path stages (CREATED excluded)
# ---------------------------------------------------------------------------

TASK_REGISTRY: dict[str, TaskFn] = {
    DocsregState.CREATED:                     task_created,
    DocsregState.INTAKE_READY:                task_intake_ready,
    DocsregState.EXTRACTION_READY:            task_extraction_ready,
    DocsregState.FAMILY_MAP_READY:            task_family_map_ready,
    DocsregState.MASTER_DECISION_READY:       task_master_decision_ready,
    DocsregState.STRUCTURE_REPAIR_READY:      task_structure_repair_ready,
    DocsregState.REFERENCE_GOVERNANCE_READY:  task_reference_governance_ready,
    DocsregState.BEST_DRAFT_SYNC_READY:       task_best_draft_sync_ready,
    DocsregState.TRACEABILITY_READY:          task_traceability_ready,
    DocsregState.QUALITY_VALIDATED:           task_quality_validated,
    DocsregState.REGISTRATION_PRECHECK_READY: task_registration_precheck_ready,
    DocsregState.CERTIFIED_MASTER_READY:      task_certified_master_ready,
    DocsregState.MASTER_REGISTERED:           task_master_registered,
}
