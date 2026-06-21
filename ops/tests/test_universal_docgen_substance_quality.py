from __future__ import annotations

from pathlib import Path

from ops.docgen.universal_pipeline.boilerplate_detector import detect_boilerplate
from ops.docgen.universal_pipeline.compliance_matrix_builder import build_compliance_matrix
from ops.docgen.universal_pipeline.compliance_matrix_validator import validate_compliance_matrix
from ops.docgen.universal_pipeline.etalon_substance_gate import evaluate_etalon_substance
from ops.docgen.universal_pipeline.orchestrator import run_universal_pipeline
from ops.docgen.universal_pipeline.standard_substance_gate import evaluate_standard_substance
from ops.tests.docgen_substance_helpers import build_policy_models, fake_render


def test_current_cycle2_policy_output_fails_substance_gates(tmp_path: Path) -> None:
    models = build_policy_models(tmp_path)
    fixture = Path("ops/tests/fixtures/docgen_bad_outputs/aims_policy_boilerplate_cycle2.docx")
    empty_matrix_validation = validate_compliance_matrix(
        compliance_matrix={"required": True, "rows": []},
        section_content_plan=models["section_plan"],
    )

    boilerplate = detect_boilerplate(document_path=fixture, section_content_plan=models["section_plan"])
    standard = evaluate_standard_substance(
        generated_docx=fixture,
        compiled_requirements=models["compiled"],
        section_content_plan=models["section_plan"],
        compliance_matrix_validation=empty_matrix_validation,
    )
    etalon = evaluate_etalon_substance(
        generated_docx=fixture,
        section_content_plan=models["section_plan"],
        document_type="policy_framework",
    )

    assert boilerplate["boilerplate_gate"] == "FAIL"
    assert standard["gate"] == "FAIL"
    assert etalon["gate"] == "FAIL"
    assert empty_matrix_validation["gate"] == "FAIL"


def test_new_generation_uses_section_content_plan(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ops.docgen.universal_pipeline.orchestrator.render_document",
        fake_render,
    )

    result = run_universal_pipeline(
        "Create maintenance procedure with CMMS, backlog, permit, isolation, records, and acceptance criteria.",
        project="AIMS",
        document_type="maintenance_procedure",
        title="Maintenance Work Preparation Scheduling and Execution Procedure",
        output_dir=tmp_path / "pipeline",
        target_quality=0.80,
        improvement_level=1,
    )
    text = "\n".join(
        paragraph.text
        for paragraph in __import__("docx").Document(str(result.final_docx)).paragraphs
        if paragraph.text.strip()
    ).lower()

    assert (result.evidence_dir / "compiled_requirements.json").exists()
    assert (result.evidence_dir / "section_content_plan.json").exists()
    assert "cmms" in text
    assert "planning and scheduling" in text
    assert "technical closeout" in text
    assert "schedule compliance" in text


def test_quality_loop_cannot_reach_target_with_failed_hard_gate(tmp_path: Path) -> None:
    models = build_policy_models(tmp_path)
    fixture = Path("ops/tests/fixtures/docgen_bad_outputs/aims_policy_boilerplate_cycle2.docx")
    matrix = build_compliance_matrix(
        compiled_requirements=models["compiled"],
        section_content_plan=models["section_plan"],
        standards=models["standards"],
    )
    matrix_validation = validate_compliance_matrix(
        compliance_matrix=matrix,
        section_content_plan=models["section_plan"],
    )
    boilerplate = detect_boilerplate(document_path=fixture, section_content_plan=models["section_plan"])
    standard = evaluate_standard_substance(
        generated_docx=fixture,
        compiled_requirements=models["compiled"],
        section_content_plan=models["section_plan"],
        compliance_matrix_validation=matrix_validation,
    )
    etalon = evaluate_etalon_substance(
        generated_docx=fixture,
        section_content_plan=models["section_plan"],
        document_type="policy_framework",
    )

    assert boilerplate["boilerplate_gate"] == "FAIL"
    assert standard["gate"] == "FAIL" or etalon["gate"] == "FAIL"
