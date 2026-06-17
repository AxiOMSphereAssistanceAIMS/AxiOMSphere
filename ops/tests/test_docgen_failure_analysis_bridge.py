from ops.docgen.universal_overlay.failure_analysis_bridge import (
    build_failure_analysis_brief,
    write_failure_analysis_brief,
)
from ops.docgen.universal_overlay.cycle_improvement_loop import (
    build_canonical_cycle_improvement_loop,
)


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(__import__("json").dumps(data), encoding="utf-8")


def _seed_run(tmp_path):
    run = tmp_path / "run"
    cycle = run / "cycle_01"
    _write_json(
        cycle / "failure_analysis_registry.json",
        {
            "document_type": "policy_framework",
            "record_count": 2,
            "records": [
                {"cause": "PROFILE_FORBIDDEN_REFERENCE"},
                {"cause": "PROFILE_FORBIDDEN_REFERENCE"},
            ],
        },
    )
    _write_json(
        cycle / "stage_contract_audit.json",
        {
            "contracts": [
                {"contract_id": "branch.policy_framework.reference_pack_to_audit", "status": "FAIL"},
                {"contract_id": "common.runtime_preflight_to_profile_router", "status": "PASS"},
            ]
        },
    )
    _write_json(cycle / "repair_plan.json", {"selected_count": 4})
    _write_json(
        cycle / "recommendation_pool.json",
        {
            "item_count": 3,
            "conflict_pool": [
                {
                    "document_name": "policy_framework",
                    "page_refs": ["11"],
                }
            ],
        },
    )
    _write_json(cycle / "document_profile_conformance.json", {"status": "REVIEW"})
    _write_json(cycle / "standard_reference_register.json", {"status": "FAIL"})
    _write_json(cycle / "skills_report.json", {"hard_gate_failures": ["standard_reference_register=FAIL"]})
    _write_json(run / "summary.json", {"document_type": "policy_framework"})
    return run


def test_failure_analysis_brief_bridges_to_slot32_and_actions(tmp_path):
    run = _seed_run(tmp_path)
    brief = build_failure_analysis_brief(run_dir=run, cycle=1)

    assert brief["analysis_status"] == "READY_FOR_AGENT_CONSUMPTION"
    assert brief["slot32"]["ready"] is True
    assert brief["slot32"]["model"]
    assert brief["failure_summary"]["record_count"] == 2
    assert brief["failure_summary"]["top_causes"] == {"PROFILE_FORBIDDEN_REFERENCE": 2}
    assert "branch.policy_framework.reference_pack_to_audit" in brief["failure_summary"]["stage_contract_failures"]
    assert brief["failure_summary"]["recommendation_pool_count"] == 3
    assert brief["failure_summary"]["recommendation_pool_conflicts"] == 1
    assert brief["model_training_status"] == "NOT_MODEL_TRAINING_DATA"
    assert (run / "cycle_01" / "failure_analysis_brief.json").exists()


def test_write_failure_analysis_brief_writes_json(tmp_path):
    run = _seed_run(tmp_path)
    brief = write_failure_analysis_brief(run_dir=run, cycle=1)
    assert brief["slot32"]["role"] == "repair_reasoning_and_reconstruction"


def test_canonical_cycle_improvement_loop_has_seven_steps():
    loop = build_canonical_cycle_improvement_loop("policy_framework")

    assert loop.document_type == "policy_framework"
    assert loop.self_healing_status == "READY_PARTIALLY"
    assert loop.self_learning_status == "NOT_MODEL_TRAINING_DATA"
    assert loop.steps == [
        "register_failure",
        "analyze_failure",
        "repair_or_reconstruct",
        "verify_fix",
        "learn_from_failure",
        "run_branch_cycle",
        "extract_common_behavior_later",
    ]
    assert [contract.step_id for contract in loop.contracts] == loop.steps
