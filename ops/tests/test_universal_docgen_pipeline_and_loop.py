from __future__ import annotations

from pathlib import Path

from ops.docgen.self_improvement.quality_loop_orchestrator import run_quality_loop
from ops.docgen.universal_pipeline.orchestrator import run_universal_pipeline


def _fake_render(final_docx: str | Path, output_dir: str | Path) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / "fake-render.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% fake test render\n")
    return {
        "status": "PASS",
        "render_ok": True,
        "visual_qa_passed": True,
        "pdf_path": str(pdf_path),
    }


def test_universal_pipeline_generates_non_policy_artifacts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ops.docgen.universal_pipeline.orchestrator.render_document",
        _fake_render,
    )

    result = run_universal_pipeline(
        "Create maintenance procedure with CMMS, backlog, permit, isolation, records, and acceptance criteria.",
        project="AIMS",
        document_type="maintenance_procedure",
        title="Maintenance Work Preparation Scheduling and Execution Procedure",
        output_dir=tmp_path / "pipeline",
        target_quality=0.98,
        improvement_level=1,
    )

    assert result.quality_score > 0
    assert (result.evidence_dir / "requirement_graph.json").exists()
    assert (result.evidence_dir / "document_architecture.json").exists()
    assert (result.evidence_dir / "section_model.json").exists()
    assert (result.evidence_dir / "implementation_model.json").exists()
    assert result.final_docx and result.final_docx.exists()
    assert result.final_pdf and result.final_pdf.exists()


def test_quality_loop_improves_non_policy_document(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "ops.docgen.universal_pipeline.orchestrator.render_document",
        _fake_render,
    )

    result = run_quality_loop(
        document_type="maintenance_procedure",
        title="Maintenance Work Preparation Scheduling and Execution Procedure",
        project="AIMS",
        request="Create maintenance procedure with work preparation scheduling CMMS backlog permit isolation HSE controls records and acceptance criteria.",
        output_root=tmp_path / "loop",
        target_quality=0.98,
        plateau_window=3,
        max_cycles=4,
    )

    assert result["cycles_executed"] >= 1
    assert result["best_quality"] > 0
    assert (tmp_path / "loop" / "cycle_1" / "improvement" / "corrective_actions.json").exists()
    assert (tmp_path / "loop" / "cycle_1" / "regression" / "degradation_guard.json").exists()
    assert (tmp_path / "loop" / "quality_loop_summary.json").exists()
