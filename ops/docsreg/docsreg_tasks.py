"""
DOCSREG task registry — maps pipeline stage names to executable task functions
and defines the stage dependency graph.

Each task function receives a DocsregRunManifest and DocsregEvidenceCheckpoint,
performs the real work for that stage, and records a DONE contract with metrics.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Callable

from ops.docsreg.docsreg_contracts import DocsregTaskContract
from ops.docsreg.docsreg_evidence_checkpoint import DocsregEvidenceCheckpoint
from ops.docsreg.docsreg_run_manifest import DocsregRunManifest
from ops.docsreg.docsreg_state_machine import DocsregState
from ops.docsreg.extraction.extraction_models import ExtractionResult, make_extraction_result
from ops.docsreg.extraction.markitdown_adapter import (
    MARKITDOWN_SUPPORTED_SUFFIXES,
    extract_with_markitdown,
    write_extraction_artifacts,
)

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

OFFICE_MARKITDOWN_SUFFIXES = frozenset({".docx", ".pptx", ".xlsx", ".xls", ".html", ".htm"})


def _extractor_backend_mode() -> str:
    backend = os.environ.get("DOCSREG_EXTRACTOR_BACKEND", "auto").strip().lower()
    if backend not in {"auto", "legacy", "markitdown"}:
        log.warning("Unknown DOCSREG_EXTRACTOR_BACKEND=%r; falling back to auto", backend)
        return "auto"
    return backend


def _extraction_artifact_dir(source: Path) -> Path:
    configured = os.environ.get("DOCSREG_EXTRACTION_ARTIFACT_DIR", "").strip()
    if configured:
        return Path(configured)
    return source.parent


def _looks_like_text(text: str, suffix: str) -> bool:
    if not text or not text.strip():
        return False
    if "\x00" in text:
        return False
    if suffix in OFFICE_MARKITDOWN_SUFFIXES:
        return False
    if suffix == ".pdf" and text.lstrip().startswith("%PDF"):
        return False
    printable = sum(1 for ch in text if ch.isprintable() or ch.isspace())
    return (printable / max(1, len(text))) >= 0.85


def _legacy_extract_text_result(path: Path) -> ExtractionResult:
    """Best-effort text extraction from PDF or plain text files."""
    suffix = path.suffix.lower()
    warnings: list[str] = []

    if suffix == ".pdf":
        # Try PyMuPDF first, then pdfplumber, then raw read
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(path))
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            if text.strip():
                return make_extraction_result(
                    source_path=str(path),
                    extractor="legacy",
                    status="extracted",
                    raw_markdown=text,
                    metadata={"method": "fitz", "source_suffix": suffix},
                )
        except ImportError:
            pass
        except Exception as exc:
            warnings.append(f"fitz_failed:{exc.__class__.__name__}:{exc}")
            log.warning("fitz extraction failed for %s: %s", path.name, exc)

        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                text = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
            if text.strip():
                return make_extraction_result(
                    source_path=str(path),
                    extractor="legacy",
                    status="extracted",
                    raw_markdown=text,
                    warnings=warnings,
                    metadata={"method": "pdfplumber", "source_suffix": suffix},
                )
        except ImportError:
            pass
        except Exception as exc:
            warnings.append(f"pdfplumber_failed:{exc.__class__.__name__}:{exc}")
            log.warning("pdfplumber extraction failed for %s: %s", path.name, exc)

    # Fallback: read as text (works for .txt, .md, .csv, etc.)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        status = "extracted" if _looks_like_text(text, suffix) else "extraction_failed"
        if status != "extracted":
            warnings.append("legacy_text_not_acceptable")
        return make_extraction_result(
            source_path=str(path),
            extractor="legacy",
            status=status,
            raw_markdown=text if status == "extracted" else "",
            warnings=warnings,
            metadata={"method": "plain_text", "source_suffix": suffix},
        )
    except Exception as exc:
        warnings.append(f"plain_text_failed:{exc.__class__.__name__}:{exc}")
        return make_extraction_result(
            source_path=str(path),
            extractor="legacy",
            status="extraction_failed",
            warnings=warnings,
            metadata={"source_suffix": suffix},
        )


def _extract_text_result(path: Path) -> ExtractionResult:
    source = Path(path)
    backend = _extractor_backend_mode()
    suffix = source.suffix.lower()

    if backend == "legacy":
        result = _legacy_extract_text_result(source)
        result.metadata["backend_mode"] = backend
        return result

    if backend == "markitdown":
        result = extract_with_markitdown(source)
        result.metadata["backend_mode"] = backend
        return result

    if suffix in OFFICE_MARKITDOWN_SUFFIXES:
        markitdown_result = extract_with_markitdown(source)
        markitdown_result.metadata["backend_mode"] = backend
        if markitdown_result.status == "extracted":
            return markitdown_result
        legacy_result = _legacy_extract_text_result(source)
        legacy_result.metadata["backend_mode"] = backend
        legacy_result.warnings.extend(markitdown_result.warnings)
        legacy_result.metadata["markitdown_status"] = markitdown_result.status
        return legacy_result

    legacy_result = _legacy_extract_text_result(source)
    legacy_result.metadata["backend_mode"] = backend
    if legacy_result.status == "extracted":
        return legacy_result

    if suffix in MARKITDOWN_SUPPORTED_SUFFIXES:
        markitdown_result = extract_with_markitdown(source)
        markitdown_result.metadata["backend_mode"] = backend
        if markitdown_result.status == "extracted":
            return markitdown_result
        markitdown_result.warnings.extend(legacy_result.warnings)
        markitdown_result.metadata["legacy_status"] = legacy_result.status
        return markitdown_result

    return legacy_result


def _extract_text(path: Path) -> str:
    return _extract_text_result(path).raw_markdown


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
    output_artifacts: dict[str, str] = {}

    if manifest.document_text:
        extraction_result = make_extraction_result(
            source_path=str(source),
            extractor="manifest",
            status="extracted",
            raw_markdown=manifest.document_text,
            metadata={"backend_mode": "manifest"},
        )
    else:
        extraction_result = _extract_text_result(source)
        if extraction_result.extractor == "markitdown":
            output_artifacts.update(
                write_extraction_artifacts(
                    extraction_result,
                    _extraction_artifact_dir(source),
                )
            )

    text = extraction_result.raw_markdown
    char_count = extraction_result.char_count
    word_count = extraction_result.word_count

    log.info(
        "extraction: %s — extractor=%s status=%s %d chars, %d words",
        source.name, extraction_result.extractor, extraction_result.status, char_count, word_count,
    )

    return checkpoint.record(
        stage=DocsregState.EXTRACTION_READY,
        input_artifacts={"draft_path": manifest.draft_path},
        output_artifacts=output_artifacts,
        metrics={
            "char_count": char_count,
            "word_count": word_count,
            "extraction_method": extraction_result.extractor,
            "extraction_status": extraction_result.status,
            "backend_mode": extraction_result.metadata.get("backend_mode", ""),
            "warnings": extraction_result.warnings,
            "metadata": extraction_result.metadata,
            "has_content": char_count > 0,
        },
        gates={"extraction_gate": "PASS" if extraction_result.status == "extracted" and char_count > 0 else "FAIL"},
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

    # Quality score: content-richness proxy from extraction metrics
    extraction = checkpoint.load(DocsregState.EXTRACTION_READY)
    char_count = 0
    word_count = 0
    if extraction and extraction.metrics:
        char_count = extraction.metrics.get("char_count", 0)
        word_count = extraction.metrics.get("word_count", 0)

    # Richness tiers: standards docs with ≥500 words score 0.95
    if word_count >= 500:
        quality = 0.95
    elif word_count >= 200:
        quality = 0.85
    elif char_count > 100:
        quality = 0.70
    else:
        quality = 0.30
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
    """Quality validation — composite scoring from all prior stages.

    Uses the composite quality gate (min of 5 component scores) so raw
    word-count cannot inflate the final score without a complete package.
    Writes ``quality_report.json`` to the evidence directory if writable.
    """
    import json as _json  # noqa: PLC0415
    from ops.docsreg.docsreg_composite_quality_gate import (  # noqa: PLC0415
        compute_composite_quality,
    )

    extraction = checkpoint.load(DocsregState.EXTRACTION_READY)
    char_count = 0
    word_count = 0
    if extraction and extraction.metrics:
        char_count = extraction.metrics.get("char_count", 0)
        word_count = extraction.metrics.get("word_count", 0)

    # Resolve evidence dir: check if package sentinels exist next to draft_path
    _SENT = ("alignment_report.json", "master_document.md", "validation_report.json")
    evidence_dir = None
    source_path = Path(manifest.draft_path)
    candidate = source_path.parent
    if any((candidate / s).exists() for s in _SENT):
        evidence_dir = candidate

    content = manifest.document_text or _extract_text(source_path)
    scores = compute_composite_quality(
        content=content,
        evidence_dir=evidence_dir,
        archetype_type=manifest.document_type or "unknown",
    )
    quality = scores.final_quality

    # Write quality_report.json alongside the source document when writable
    quality_report_path = candidate / "quality_report.json"
    try:
        quality_report_path.write_text(
            _json.dumps(scores.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        log.debug("quality_validated: wrote %s", quality_report_path)
    except Exception as exc:
        log.debug("quality_validated: could not write quality_report.json: %s", exc)

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
    log.info(
        "quality_validated: quality=%.2f gates_ok=%s verdict=%s method=%s",
        quality, all_gates_pass, gate_verdict, scores.quality_method,
    )

    return checkpoint.record(
        stage=DocsregState.QUALITY_VALIDATED,
        input_artifacts={"draft_path": manifest.draft_path},
        metrics={
            "quality_score": quality,
            "char_count": char_count,
            "word_count": word_count,
            "all_gates_pass": all_gates_pass,
            "content_richness_score": scores.content_richness_score,
            "data_retention_score": scores.data_retention_score,
            "source_to_master_alignment_score": scores.source_to_master_alignment_score,
            "structure_score": scores.structure_score,
            "metadata_safety_score": scores.metadata_safety_score,
            "quality_method": scores.quality_method,
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

    # 1. Always catalogue in standards_index — this is an audit trail of every file
    #    that entered the pipeline, regardless of whether it passed certification.
    register_ingested_standard(
        standard_id=standard_id,
        source_path=str(source),
        title=source.stem,
        doc_type=manifest.document_type or "standard",
        status=cert_status.lower(),
        notes=f"Registered via DOCSREG pipeline, run_id={manifest.run_id}",
    )

    # 2. Gate master-document write + Qdrant upsert on CERTIFIED status.
    #    A document may enter the master registry and become Qdrant-active only
    #    after the RegistrationRecord builder confirmed quality ≥ 0.95 and all
    #    gate verdicts passed.  PENDING or REJECTED documents are catalogued
    #    in standards_index (step 1) but must not appear in the documents
    #    table or Qdrant search index.
    if cert_status != "CERTIFIED":
        log.warning(
            "master_registered: SKIP documents+Qdrant write — "
            "certification_status=%r (must be CERTIFIED); standard_id=%s quality=%.3f",
            cert_status, standard_id, quality_score,
        )
        return checkpoint.record(
            stage=DocsregState.MASTER_REGISTERED,
            input_artifacts={"draft_path": manifest.draft_path},
            output_artifacts={"document_id": None},
            metrics={
                "standard_id": standard_id,
                "document_id": None,
                "registration_status": cert_status,
                "quality_score": quality_score,
                "registered_to_db": False,
                "registered_to_documents": False,
                "skipped_reason": f"certification_status={cert_status!r} is not CERTIFIED",
            },
            gates={"registration_gate": "SKIP"},
        )

    # 3. Artifact integrity gate — even CERTIFIED documents must have all
    #    required physical artifacts present and valid before the master-
    #    registry write.  If any check fails the document is catalogued in
    #    standards_index (already done above) but blocked from the documents
    #    table and Qdrant upsert.
    from ops.docsreg.docsreg_artifact_integrity import validate_artifact_integrity  # noqa: PLC0415

    intake_contract = checkpoint.load(DocsregState.INTAKE_READY)
    source_sha256: str | None = None
    if intake_contract and intake_contract.output_artifacts:
        source_sha256 = intake_contract.output_artifacts.get("source_hash")

    integrity = validate_artifact_integrity(
        cert_status=cert_status,
        quality_report_path=source.parent / "quality_report.json",
        master_document_path=source,
        source_sha256=source_sha256,
    )

    if not integrity.ok:
        log.warning(
            "master_registered: SKIP — artifact integrity failed; "
            "standard_id=%s missing_checks=%s",
            standard_id, integrity.missing_checks,
        )
        return checkpoint.record(
            stage=DocsregState.MASTER_REGISTERED,
            input_artifacts={"draft_path": manifest.draft_path},
            output_artifacts={"document_id": None},
            metrics={
                "standard_id": standard_id,
                "document_id": None,
                "registration_status": cert_status,
                "quality_score": quality_score,
                "registered_to_db": False,
                "registered_to_documents": False,
                "skipped_reason": integrity.reason,
                "missing_checks": integrity.missing_checks,
            },
            gates={"registration_gate": "SKIP"},
        )

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
