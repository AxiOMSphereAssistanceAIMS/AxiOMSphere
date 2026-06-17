import json

from ops.docgen.universal_overlay.phase14_cross_type_compare import (
    compare_phase13_phase14,
)
from ops.docgen.universal_overlay.phase14_guard_report import (
    create_phase14_guard_report,
)
from ops.docgen.universal_overlay.phase14_reference_binding_detector import (
    detect_reference_binding,
)
from ops.docgen.universal_overlay.phase14_type_drift_detector import (
    detect_type_drift,
)


def test_phase14_type_drift_detector_detects_policy_framework(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "draft.md").write_text(
        "Policy Framework\nPolicy statement\nGovernance\n"
        "Compliance requirements\nReview cycle",
        encoding="utf-8",
    )
    out = detect_type_drift(
        run_dir,
        "policy_framework",
        tmp_path / "type.json",
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["expected_type"] == "policy_framework"
    assert data["drift"] is False


def test_phase14_type_drift_detector_prefers_declared_type(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "teacher_audit.json").write_text(
        json.dumps({"document_type": "technical_report"}),
        encoding="utf-8",
    )
    (run_dir / "draft.md").write_text(
        "Policy Framework Policy statement Governance Compliance",
        encoding="utf-8",
    )
    out = detect_type_drift(
        run_dir,
        "policy_framework",
        tmp_path / "type.json",
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["drift"] is True
    assert data["detected_type"] == "technical_report"


def test_phase14_reference_binding_detector(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "reference_pdf": "/references/policy.pdf",
                "standard": "ISO 55001",
            }
        ),
        encoding="utf-8",
    )
    out = detect_reference_binding(run_dir, tmp_path / "ref.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["reference_binding_present"] is True
    assert data["reference_count"] >= 1


def test_phase14_citations_alone_are_not_binding(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "draft.md").write_text(
        "The policy cites ISO 55001.",
        encoding="utf-8",
    )
    out = detect_reference_binding(run_dir, tmp_path / "ref.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["reference_count"] == 1
    assert data["reference_binding_present"] is False


def test_phase14_guard_report_review_on_type_drift(tmp_path):
    run_dir = tmp_path / "run"
    overlay = run_dir / "universal_overlay"
    overlay.mkdir(parents=True)
    (overlay / "overlay_report.json").write_text(
        json.dumps({"status": "OVERLAY_READ_ONLY_REPORT_CREATED"}),
        encoding="utf-8",
    )
    (overlay / "type_drift_report.json").write_text(
        json.dumps(
            {
                "status": "TYPE_DRIFT_DETECTED",
                "drift": True,
                "expected_type": "policy_framework",
                "detected_type": "technical_report",
            }
        ),
        encoding="utf-8",
    )
    (overlay / "reference_binding_report.json").write_text(
        json.dumps(
            {
                "status": "REFERENCE_BINDING_PRESENT",
                "reference_binding_present": True,
                "forbidden_reference_hits": [],
            }
        ),
        encoding="utf-8",
    )
    (overlay / "decision_summary.json").write_text(
        json.dumps({"weakest_dimension": "coverage"}),
        encoding="utf-8",
    )
    out = create_phase14_guard_report(run_dir, tmp_path / "guard.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "REVIEW"
    assert "type_drift_detected" in data["reviews"]


def test_phase14_cross_type_compare_repeated_systemic_signals(tmp_path):
    phase13 = tmp_path / "p13.json"
    phase14 = tmp_path / "p14.json"
    guard14 = tmp_path / "g14.json"
    architecture = {
        "generated_document_type": "technical_report",
        "reference_binding_present": False,
        "auditor_degraded": True,
        "auditor_provider": "mock",
    }
    phase13.write_text(
        json.dumps(
            {
                "architecture_observation": {
                    **architecture,
                    "requested_document_type": "maintenance_procedure",
                },
                "overlay_observation": {},
            }
        ),
        encoding="utf-8",
    )
    phase14.write_text(
        json.dumps(
            {
                "architecture_observation": {
                    **architecture,
                    "requested_document_type": "policy_framework",
                },
                "overlay_observation": {},
            }
        ),
        encoding="utf-8",
    )
    guard14.write_text(
        json.dumps(
            {
                "reviews": [
                    "type_drift_detected",
                    "reference_binding_absent_or_weak",
                ],
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    out_json, out_md = compare_phase13_phase14(
        phase13,
        phase14,
        guard14,
        tmp_path / "cross.json",
        tmp_path / "cross.md",
    )
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["status"] == "CROSS_TYPE_COMPARISON_CREATED"
    assert data["training_decision"] == "DO_NOT_TRAIN_YET"
    assert "judge_degraded_or_mock" in data["repeated_reviews"]
    assert out_md.exists()
