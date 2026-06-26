from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .boilerplate_detector import detect_boilerplate
from .authored_section_loader import load_authored_sections
from .source_only_compliance_matrix_builder import (
    build_source_only_compliance_matrix,
)
from .compliance_matrix_validator import validate_compliance_matrix
from .document_architecture_builder import build_document_architecture
from .document_type_resolver import resolve_document_type
from .source_only_draft_generator import generate_source_only_draft
from .etalon_selector import select_etalon
from .etalon_substance_gate import evaluate_etalon_substance
from .evidence_writer import write_json, write_text
from .gap_map_builder import build_gap_map
from .generation_trace_writer import write_provenance_bundle
from .implementation_model_builder import build_implementation_model
from .quality_scorer import score_quality
from .renderer import render_document
from .reference_register_builder import build_reference_register
from .repairer import repair_document
from .request_interpreter import interpret_request
from .source_only_requirement_compiler import (
    compile_source_only_requirements,
)
from .reviewer import review_document
from .section_model_builder import build_section_model
from .source_only_section_content_planner import (
    build_source_only_section_content_plan,
)
from .skeleton_builder import build_skeleton
from .source_discovery import discover_sources
from .standard_markitdown_normalizer import attach_standard_normalization_summary
from .standard_substance_gate import evaluate_standard_substance
from .standards_binder import bind_standards
from ops.docgen.skills import build_skill_application_manifest
from ops.docgen.archetypes import (
    bind_structural_archetype,
    validate_archetype_binding,
)
from .validator import validate_document
from ops.docgen.quality_gates.generation_leakage_gate import (
    evaluate_generation_leakage,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN_ROOT = REPO_ROOT / "aims_workspace" / "agent_architecture_status" / "universal_docgen_runs"


@dataclass(frozen=True)
class UniversalPipelineResult:
    verdict: str
    document_type: str
    quality_score: float
    evidence_dir: Path
    final_docx: Path | None
    final_pdf: Path | None
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "document_type": self.document_type,
            "quality_score": self.quality_score,
            "evidence_dir": str(self.evidence_dir),
            "final_docx": str(self.final_docx) if self.final_docx else "",
            "final_pdf": str(self.final_pdf) if self.final_pdf else "",
            "blockers": list(self.blockers),
        }


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_universal_pipeline(
    request_payload: str | Mapping[str, Any],
    *,
    project: str = "AIMS",
    document_type: str | None = None,
    title: str = "Generated Document",
    output_dir: str | Path | None = None,
    reference_path: str | None = None,
    target_quality: float = 0.98,
    improvement_level: int = 1,
    applied_corrections: list[dict[str, Any]] | None = None,
    adaptive_config: dict[str, Any] | None = None,
    authoring_candidates_path: str | Path | None = None,
) -> UniversalPipelineResult:
    generation_started_at = datetime.now(timezone.utc).isoformat()
    request = interpret_request(
        request_payload,
        project=project,
        title=title,
        document_type=document_type,
        reference_path=reference_path,
    )
    resolved = resolve_document_type(request)
    doc_type = resolved["document_type"]
    run_id = f"{doc_type}_{project.lower()}_{_timestamp()}"
    evidence_dir = Path(output_dir) if output_dir else DEFAULT_RUN_ROOT / run_id
    evidence_dir.mkdir(parents=True, exist_ok=True)

    write_json(evidence_dir / "request.json", request)
    write_json(evidence_dir / "document_type_resolution.json", resolved)
    write_json(evidence_dir / "adaptive_generation_config.json", adaptive_config or {})
    structural_archetype = bind_structural_archetype(doc_type)
    write_json(evidence_dir / "structural_archetype_binding.json", structural_archetype)
    write_json(
        evidence_dir / "structural_archetype_validation.json",
        validate_archetype_binding(structural_archetype),
    )

    sources = discover_sources(request, resolved)
    generation_sources = {
        key: value for key, value in sources.items()
        if key != "etalon_candidates"
    }
    generation_sources["evaluation_candidates_hidden_until_post_generation"] = True
    write_json(evidence_dir / "source_discovery.json", generation_sources)
    skill_manifest = build_skill_application_manifest(
        document_type=doc_type,
        project=project,
        applied_corrections=applied_corrections,
        adaptive_config=adaptive_config,
    )
    write_json(evidence_dir / "skill_application_manifest.json", skill_manifest)

    standards = bind_standards(request, generation_sources)
    standards = attach_standard_normalization_summary(standards, evidence_dir)
    write_json(
        evidence_dir / "standard_markitdown_normalization.json",
        standards.get("markitdown_standard_normalization", {}),
    )
    write_json(evidence_dir / "standards_binding.json", standards)
    reference_register = build_reference_register(standards)
    write_json(evidence_dir / "reference_register.json", reference_register)
    requirement_graph = compile_source_only_requirements(
        request=request,
        resolved=resolved,
        source_selection={},
        standards=standards,
        source_documents=generation_sources,
    )
    write_json(evidence_dir / "compiled_requirements.json", requirement_graph)
    write_json(
        evidence_dir / "compiled_requirements_audit.json",
        requirement_graph.get("compiled_requirements_audit", {}),
    )
    write_json(evidence_dir / "requirement_graph.json", requirement_graph)
    architecture = build_document_architecture(
        request,
        requirement_graph,
        structural_archetype=structural_archetype,
    )
    write_json(evidence_dir / "document_architecture.json", architecture)
    section_model = build_section_model(architecture, requirement_graph)
    write_json(evidence_dir / "section_model.json", section_model)
    implementation_model = build_implementation_model(
        request,
        section_model,
        improvement_level=improvement_level,
    )
    write_json(evidence_dir / "implementation_model.json", implementation_model)
    section_content_plan = build_source_only_section_content_plan(
        compiled_requirements=requirement_graph,
        section_model=section_model,
        implementation_model=implementation_model,
        adaptive_config=adaptive_config,
    )
    authored_sections, authoring_binding = load_authored_sections(
        authoring_candidates_path
    )
    if authoring_binding.get("status") == "FAIL":
        write_json(
            evidence_dir / "authoring_candidate_binding.json",
            authoring_binding,
        )
        raise RuntimeError("SOURCE_ONLY_AUTHORING_CANDIDATES_REJECTED")
    section_content_plan["authoring_candidate_binding"] = authoring_binding
    write_json(evidence_dir / "section_content_plan.json", section_content_plan)
    write_json(
        evidence_dir / "authoring_candidate_binding.json",
        authoring_binding,
    )
    write_json(evidence_dir / "section_content_plan_audit.json", section_content_plan.get("audit", {}))
    leakage_gate = evaluate_generation_leakage(
        requirement_graph,
        section_content_plan,
    )
    write_json(
        evidence_dir / "generation_leakage_gate.json",
        leakage_gate,
    )
    if leakage_gate.get("gate") != "PASS":
        raise RuntimeError("GENERATION_ETALON_LEAKAGE_DETECTED")
    compliance_matrix = build_source_only_compliance_matrix(
        compiled_requirements=requirement_graph,
        section_content_plan=section_content_plan,
        standards=standards,
    )
    write_json(evidence_dir / "compliance_matrix.json", compliance_matrix)
    compliance_matrix_validation = validate_compliance_matrix(
        compliance_matrix=compliance_matrix,
        section_content_plan=section_content_plan,
    )
    write_json(evidence_dir / "compliance_matrix_validation.json", compliance_matrix_validation)
    skeleton = build_skeleton(request, section_model)
    write_json(evidence_dir / "skeleton.json", {k: v for k, v in skeleton.items() if k != "markdown"})
    write_text(evidence_dir / "skeleton.md", skeleton["markdown"])

    first_draft = generate_source_only_draft(
        request=request,
        section_model=section_model,
        implementation_model=implementation_model,
        section_content_plan=section_content_plan,
        compliance_matrix=compliance_matrix,
        reference_register=reference_register,
        adaptive_config=adaptive_config,
        authored_sections=authored_sections,
        output_path=evidence_dir / "first_draft.docx",
    )
    review = review_document(
        document_path=first_draft,
        section_model=section_model,
        implementation_model=implementation_model,
        standards=standards,
        compiled_requirements=requirement_graph,
        section_content_plan=section_content_plan,
    )
    write_json(evidence_dir / "review_comments.json", review)
    gap_map = build_gap_map(review)
    write_json(evidence_dir / "gap_map.json", gap_map)
    repair_plan = {
        "status": "READY",
        "target_document": str(first_draft),
        "repair_same_document_lineage": True,
        "actions": gap_map.get("gaps") or gap_map.get("items") or [],
    }
    write_json(evidence_dir / "repair_plan.json", repair_plan)
    repair = repair_document(
        first_draft=first_draft,
        repaired_document=evidence_dir / "repaired_document.docx",
        gap_map=gap_map,
        compiled_requirements=requirement_graph,
        section_content_plan=section_content_plan,
    )
    write_json(evidence_dir / "repair_evidence.json", repair)
    final_docx = evidence_dir / "final_document.docx"
    shutil.copy2(Path(repair["repaired_document"]), final_docx)

    boilerplate_report = detect_boilerplate(
        document_path=final_docx,
        section_content_plan=section_content_plan,
    )
    write_json(evidence_dir / "boilerplate_report.json", boilerplate_report)
    standard_substance_coverage = evaluate_standard_substance(
        generated_docx=final_docx,
        compiled_requirements=requirement_graph,
        section_content_plan=section_content_plan,
        compliance_matrix_validation=compliance_matrix_validation,
    )
    write_json(evidence_dir / "standard_substance_coverage.json", standard_substance_coverage)
    etalon_substance_coverage = evaluate_etalon_substance(
        generated_docx=final_docx,
        section_content_plan=section_content_plan,
        document_type=doc_type,
    )
    write_json(evidence_dir / "etalon_substance_coverage.json", etalon_substance_coverage)
    final_review = review_document(
        document_path=final_docx,
        section_model=section_model,
        implementation_model=implementation_model,
        standards=standards,
        compiled_requirements=requirement_graph,
        section_content_plan=section_content_plan,
        boilerplate_report=boilerplate_report,
        standard_substance_coverage=standard_substance_coverage,
        etalon_substance_coverage=etalon_substance_coverage,
        compliance_matrix_validation=compliance_matrix_validation,
    )
    write_json(evidence_dir / "review_comments.json", final_review)
    validation = validate_document(
        final_docx=final_docx,
        section_model=section_model,
        review=final_review,
        boilerplate_report=boilerplate_report,
        standard_substance_coverage=standard_substance_coverage,
        etalon_substance_coverage=etalon_substance_coverage,
        compliance_matrix_validation=compliance_matrix_validation,
    )
    write_json(evidence_dir / "validation.json", validation)
    render_metrics = render_document(final_docx, evidence_dir / "render")
    write_json(evidence_dir / "render_metrics.json", render_metrics)
    final_pdf = evidence_dir / "final_document.pdf"
    rendered_pdf = Path(str(render_metrics.get("pdf_path") or ""))
    if rendered_pdf.exists():
        shutil.copy2(rendered_pdf, final_pdf)
    command = (
        "python -m ops.docgen.self_improvement.run_quality_loop "
        f"--document-type {doc_type} --title {title!r} --project {project}"
    )
    if authoring_candidates_path:
        command += (
            " --authoring-candidates "
            + str(authoring_candidates_path)
        )
    write_provenance_bundle(
        evidence_dir=evidence_dir,
        repo_root=REPO_ROOT,
        generation_started_at=generation_started_at,
        command=command,
        section_content_plan=section_content_plan,
        repair_plan=repair_plan,
    )
    # Blind evaluation starts only after the final artifact exists.
    source_selection = select_etalon(request, sources)
    write_json(
        evidence_dir / "evaluation_candidate_inventory.json",
        {
            "request_domain": sources.get("request_domain"),
            "candidates": sources.get("etalon_candidates", []),
            "made_available_after_generation": True,
        },
    )
    write_json(evidence_dir / "source_selection.json", source_selection)
    selected = source_selection.get("selected") or {}
    etalon_docx: Path | None = None
    if selected.get("path"):
        candidate = Path(str(selected["path"]))
        etalon_docx = candidate if candidate.exists() else None
    quality = score_quality(
        final_docx=final_docx,
        final_pdf=final_pdf if final_pdf.exists() else None,
        etalon_docx=etalon_docx,
        source_selection=source_selection,
        requirement_graph=requirement_graph,
        section_model=section_model,
        implementation_model=implementation_model,
        review=final_review,
        validation=validation,
        render_metrics=render_metrics,
        boilerplate_report=boilerplate_report,
        standard_substance_coverage=standard_substance_coverage,
        etalon_substance_coverage=etalon_substance_coverage,
        compliance_matrix_validation=compliance_matrix_validation,
        section_content_plan=section_content_plan,
        evidence_dir=evidence_dir,
        request=request,
    )
    write_json(
        evidence_dir / "requirement_transformation_gate.json",
        quality.get("gates", {}).get("requirement_transformation", {}),
    )
    write_json(
        evidence_dir / "context_accuracy_gate.json",
        quality.get("gates", {}).get("context_accuracy", {}),
    )
    write_json(
        evidence_dir / "generation_leakage_gate.json",
        quality.get("gates", {}).get("generation_leakage", {}),
    )
    quality["target_quality"] = target_quality
    quality["target_reached"] = (
        quality["quality_score"] >= target_quality
        and validation["status"] == "PASS"
        and quality.get("hard_gates_passed") is True
    )
    write_json(evidence_dir / "quality_score.json", quality)

    blockers = list(validation.get("blockers") or [])
    blockers.extend(
        str(item)
        for item in quality.get("hard_gate_failures") or []
        if str(item) not in blockers
    )
    if not quality["target_reached"]:
        blockers.append("QUALITY_BELOW_TARGET")
    verdict = "PASS" if not blockers else "NOT_PASSED"
    final = {
        "final_verdict": verdict,
        "run_id": run_id,
        "document_type": doc_type,
        "quality_score": quality["quality_score"],
        "quality_percent": quality["quality_percent"],
        "target_quality": target_quality,
        "blockers": blockers,
        "etalon_source": source_selection.get("selected"),
        "final_docx": str(final_docx),
        "final_pdf": str(final_pdf) if final_pdf.exists() else "",
        "evidence_dir": str(evidence_dir),
    }
    write_json(evidence_dir / "final_verdict.json", final)
    write_provenance_bundle(
        evidence_dir=evidence_dir,
        repo_root=REPO_ROOT,
        generation_started_at=generation_started_at,
        command=command,
        section_content_plan=section_content_plan,
        repair_plan=repair_plan,
    )
    return UniversalPipelineResult(
        verdict=verdict,
        document_type=doc_type,
        quality_score=float(quality["quality_score"]),
        evidence_dir=evidence_dir,
        final_docx=final_docx,
        final_pdf=final_pdf if final_pdf.exists() else None,
        blockers=tuple(blockers),
    )
