from ops.docgen.universal_overlay.failure_analysis_registry import (
    build_failure_analysis_records,
    write_failure_analysis_registry,
)


def test_no_failure_cycle_writes_empty_registry(tmp_path):
    cycle_dir = tmp_path / "cycle_01"
    manifest = write_failure_analysis_registry(
        output_dir=tmp_path,
        cycle_dir=cycle_dir,
        cycle=1,
        document_type="technical_report",
        diagnostics={"status": "PASS", "failures": []},
        profile_conformance={
            "status": "PASS",
            "missing_sections": [],
            "forbidden_references": [],
            "numbering_issue_count": 0,
            "reference_register_present": True,
        },
        hard_gate_failures=[],
        export_failures=["learning_pair_export_not_requested"],
        scores={"overall": 0.91},
    )

    assert manifest["status"] == "NO_FAILURES"
    assert manifest["record_count"] == 0
    assert manifest["cycle_improvement_status"] == "NO_ACTION"
    assert manifest["model_training_status"] == "NOT_MODEL_TRAINING_DATA"
    assert not (
        tmp_path / "cycle_improvement_candidates" / "failure_analysis.jsonl"
    ).exists()
    assert (cycle_dir / "failure_analysis_registry.json").exists()


def test_diagnostic_failure_is_cycle_improvement_candidate():
    records = build_failure_analysis_records(
        cycle=2,
        document_type="maintenance_procedure",
        diagnostics={
            "status": "DIAGNOSED",
            "failures": [
                {
                    "stage": "generation",
                    "cause": "EMPTY_SECTION",
                    "section": "4",
                    "evidence": "4 Maintenance steps",
                    "next_action": "regenerate_from_assigned_requirements",
                }
            ],
        },
        profile_conformance={
            "status": "PASS",
            "missing_sections": [],
            "forbidden_references": [],
            "numbering_issue_count": 0,
            "reference_register_present": True,
        },
        hard_gate_failures=["structure=FAIL"],
        export_failures=["structure=FAIL"],
        artifact_paths={"cycle_dir": "/tmp/cycle_02"},
        scores={"structure": 0.5},
    )

    assert len(records) == 1
    record = records[0]
    assert record["normalized_failure"] == "missing_required_section"
    assert record["universal_failure_class"] == "STRUCTURE"
    assert record["cycle_improvement_status"] == "CANDIDATE_FOR_NEXT_REPAIR_CYCLE"
    assert record["model_training_status"] == "NOT_MODEL_TRAINING_DATA"
    assert record["repair_routing_target"] == "docgen_next_cycle_repair_plan"
    assert record["allowed_for_model_training"] is False
    assert record["allowed_for_promotion"] is False


def test_profile_failures_are_registered_for_cycle_repair(tmp_path):
    manifest = write_failure_analysis_registry(
        output_dir=tmp_path,
        cycle_dir=tmp_path / "cycle_03",
        cycle=3,
        document_type="policy_framework",
        diagnostics={"status": "PASS", "failures": []},
        profile_conformance={
            "status": "REVIEW",
            "missing_sections": ["1.0 Purpose and scope"],
            "forbidden_references": ["ISO 45001"],
            "numbering_issue_count": 1,
            "reference_register_present": False,
        },
        hard_gate_failures=["document_profile_conformance=REVIEW"],
        export_failures=["document_profile_conformance=REVIEW"],
        scores={"overall": 0.82},
    )

    failures = {item["normalized_failure"] for item in manifest["records"]}
    assert manifest["status"] == "RECORDED"
    assert manifest["cycle_improvement_status"] == (
        "CANDIDATE_FOR_NEXT_REPAIR_CYCLE"
    )
    assert manifest["model_training_status"] == "NOT_MODEL_TRAINING_DATA"
    assert manifest["allowed_for_model_training"] is False
    assert failures == {
        "missing_required_section",
        "forbidden_reference",
        "wrong_section_order",
        "missing_compliance_matrix",
    }
    jsonl = tmp_path / "cycle_improvement_candidates" / "failure_analysis.jsonl"
    assert len(jsonl.read_text(encoding="utf-8").splitlines()) == 4
