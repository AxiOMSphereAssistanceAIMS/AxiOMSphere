import json

from ops.docgen.universal_overlay.stage_contract_audit import (
    audit_stage_contracts,
    write_stage_contract_audit,
)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _minimal_run(tmp_path, *, policy_failures: bool, include_brief: bool = True):
    run = tmp_path / "run"
    cycle = run / "cycle_01"
    _write_json(run / "runtime_preflight.json", {"status": "PASS"})
    _write_json(
        run / "document_generation_profile_contract.json",
        {
            "document_type": "policy_framework",
            "required_sections": ["Purpose"],
            "formation_standards": ["ISO 10013:2021"],
            "read_full_standards_during_generation": False,
        },
    )
    _write_json(
        cycle / "phase16_generated_type_gate.json",
        {
            "status": "PASS",
            "evidence": {
                "requested_document_type": "policy_framework",
                "detected_document_type": "policy_framework",
            },
        },
    )
    _write_json(
        cycle / "skills_report.json",
        {
            "structure": {
                "passed": True,
                "completeness_ratio": 1.0,
                "empty_sections": [],
                "stub_sections": [],
            },
            "hard_gate_allowed": not policy_failures,
            "hard_gate_failures": (
                ["standard_reference_register=FAIL"] if policy_failures else []
            ),
            "audit_quality_passed": not policy_failures,
            "audit_quality_failures": (
                ["claude_reference_gap=20.7% > 10%"] if policy_failures else []
            ),
        },
    )
    _write_json(
        cycle / "document_profile_conformance.json",
        {
            "status": "REVIEW" if policy_failures else "PASS",
            "missing_sections": [],
            "forbidden_references": ["API 510"] if policy_failures else [],
            "reference_register_present": True,
        },
    )
    _write_json(
        cycle / "standard_reference_register.json",
        {
            "status": "FAIL" if policy_failures else "PASS",
            "body_citations": ["API 510"] if policy_failures else ["ISO 10013"],
            "unverified_citations": ["API 510"] if policy_failures else [],
            "excluded_discovered_standards": [],
        },
    )
    _write_json(cycle / "docx_quality.json", {"passed": True, "score": 10.0})
    _write_json(
        cycle / "visual_qa_metrics.json",
        {
            "render_success": True,
            "critical_visual_issues_count": 0,
            "page_count": 3,
        },
    )
    _write_json(cycle / "repair_plan.json", {"selected_count": 2})
    _write_json(cycle / "failure_analysis_registry.json", {"record_count": 1})
    if include_brief:
        _write_json(
            cycle / "failure_analysis_brief.json",
            {"slot32": {"model": "axi_omi_sphere:latest"}},
        )
    (cycle / "draft.md").write_text("# Draft\n", encoding="utf-8")
    return run


def test_stage_contract_audit_passes_clean_policy_run(tmp_path):
    run = _minimal_run(tmp_path, policy_failures=False)
    manifest = audit_stage_contracts(run, cycle=1)

    assert manifest["status"] == "PASS"
    assert manifest["failed_count"] == 0


def test_stage_contract_audit_fails_policy_branch_handoffs(tmp_path):
    run = _minimal_run(tmp_path, policy_failures=True)
    manifest = audit_stage_contracts(run, cycle=1)

    failed_ids = {
        item["contract_id"]
        for item in manifest["contracts"]
        if item["status"] == "FAIL"
    }
    assert manifest["status"] == "FAIL"
    assert "branch.policy_framework.reference_pack_to_audit" in failed_ids
    assert "branch.policy_framework.profile_conformance_to_hard_gate" in failed_ids
    assert "branch.policy_framework.audit_quality_to_repair_plan" in failed_ids


def test_write_stage_contract_audit_writes_manifest(tmp_path):
    run = _minimal_run(tmp_path, policy_failures=True)
    manifest = write_stage_contract_audit(run, cycle=1)

    assert manifest["failed_count"] == 3
    assert (run / "cycle_01" / "stage_contract_audit.json").exists()


def test_stage_contract_audit_requires_failure_brief_for_failed_cycle(tmp_path):
    run = _minimal_run(tmp_path, policy_failures=True, include_brief=False)
    manifest = audit_stage_contracts(run, cycle=1)

    failed_ids = {
        item["contract_id"]
        for item in manifest["contracts"]
        if item["status"] == "FAIL"
    }
    assert manifest["status"] == "FAIL"
    assert "common.failed_cycle_to_next_repair_input" in failed_ids
