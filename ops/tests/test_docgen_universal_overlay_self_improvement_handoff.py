import json

from unittest.mock import patch

from ops.docgen.universal_overlay.self_improvement_handoff import (
    create_self_improvement_handoff,
)


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_handoff_registers_problems_skills_and_slot32_candidates(tmp_path):
    run_dir = tmp_path / "run"
    cycle = run_dir / "cycle_01"
    cycle.mkdir(parents=True)
    (cycle / "draft.md").write_text("# Policy Framework", encoding="utf-8")
    _write(cycle / "metrics.json", {"changes_applied": []})
    _write(
        cycle / "section_failure_diagnostics.json",
        {
            "failures": [
                {
                    "stage": "generation",
                    "cause": "EMPTY_SECTION",
                    "section": "8.1",
                    "evidence": "missing body",
                    "next_action": "regenerate",
                }
            ]
        },
    )
    _write(cycle / "repair_plan.json", {"selected_count": 1})
    _write(
        cycle / "skill_recommendations.json",
        {"skill_recommendations": ["Generate all required policy sections"]},
    )
    _write(
        cycle / "training_quarantine.json",
        {"hard_gate_failures": ["structure=30% < 82%"]},
    )

    outputs = create_self_improvement_handoff(
        run_dir=run_dir,
        document_type="policy_framework",
    )

    ledger = json.loads(outputs["problem_ledger"].read_text())
    skills = json.loads(outputs["skill_candidate_requests"].read_text())
    slot32 = json.loads(outputs["slot32_task_candidates"].read_text())
    readiness = json.loads(outputs["self_improvement_readiness"].read_text())

    assert ledger["problem_count"] == 2
    assert skills["request_count"] == 1
    assert skills["requests"][0]["lifecycle_state"] == "OBSERVED_PATTERN"
    assert skills["canonical_registry_mutated"] is False
    assert slot32["task_count"] == 2
    assert all(not task["approved_for_training"] for task in slot32["tasks"])
    assert slot32["training_intake_mutated"] is False
    assert readiness["decision"] == "PARTIALLY_READY"


def test_handoff_marks_repeated_skill_as_candidate_and_verified_repair(tmp_path):
    run_dir = tmp_path / "run"
    for number in (1, 2):
        cycle = run_dir / f"cycle_{number:02d}"
        cycle.mkdir(parents=True)
        (cycle / "draft.md").write_text("# Procedure", encoding="utf-8")
        _write(
            cycle / "metrics.json",
            {"changes_applied": ["repair"] if number == 2 else []},
        )
        _write(cycle / "section_failure_diagnostics.json", {"failures": []})
        _write(cycle / "repair_plan.json", {"selected_count": 1})
        _write(
            cycle / "skill_recommendations.json",
            {"skill_recommendations": ["Improve grounded repair targeting"]},
        )
        _write(cycle / "training_quarantine.json", {"hard_gate_failures": []})

    outputs = create_self_improvement_handoff(
        run_dir=run_dir,
        document_type="maintenance_procedure",
    )

    skills = json.loads(outputs["skill_candidate_requests"].read_text())
    readiness = json.loads(outputs["self_improvement_readiness"].read_text())

    assert skills["requests"][0]["lifecycle_state"] == "CANDIDATE_SKILL"
    assert skills["requests"][0]["observed_count"] == 2
    assert readiness["capabilities"]["repair_application_verified"] is True
    assert readiness["autonomous_self_improvement_ready"] is True


def test_handoff_registers_empty_repair_plan_with_failed_gate(tmp_path):
    run_dir = tmp_path / "run"
    cycle = run_dir / "cycle_01"
    cycle.mkdir(parents=True)
    (cycle / "draft.md").write_text("# Procedure", encoding="utf-8")
    _write(cycle / "metrics.json", {"changes_applied": []})
    _write(cycle / "section_failure_diagnostics.json", {"failures": []})
    _write(cycle / "repair_plan.json", {"selected_count": 0})
    _write(cycle / "skill_recommendations.json", {"skill_recommendations": []})
    _write(
        cycle / "training_quarantine.json",
        {"audit_quality_failures": ["claude_axi_quality=83% < 85%"]},
    )

    outputs = create_self_improvement_handoff(
        run_dir=run_dir,
        document_type="maintenance_procedure",
    )
    ledger = json.loads(outputs["problem_ledger"].read_text())

    assert any(
        item["cause"] == "REPAIR_PLAN_EMPTY_WITH_FAILED_GATE"
        for item in ledger["problems"]
    )


def test_handoff_exports_training_intake_when_requested(tmp_path):
    run_dir = tmp_path / "run"
    cycle = run_dir / "cycle_01"
    cycle.mkdir(parents=True)
    (cycle / "draft.md").write_text("# Procedure", encoding="utf-8")
    _write(cycle / "metrics.json", {"changes_applied": ["repair"]})
    _write(
        cycle / "section_failure_diagnostics.json",
        {
            "failures": [
                {
                    "stage": "generation",
                    "cause": "EMPTY_SECTION",
                    "section": "3.1",
                    "evidence": "missing body",
                    "next_action": "regenerate",
                }
            ]
        },
    )
    _write(cycle / "repair_plan.json", {"selected_count": 1})
    _write(
        cycle / "skill_recommendations.json",
        {"skill_recommendations": ["Improve grounded repair targeting"]},
    )
    _write(cycle / "training_quarantine.json", {"hard_gate_failures": []})

    intake_dir = tmp_path / "training_intake"
    with patch(
        "ops.learning.training_intake.INTAKE_DIR",
        intake_dir,
    ):
        outputs = create_self_improvement_handoff(
            run_dir=run_dir,
            document_type="maintenance_procedure",
            export_training_intake=True,
        )

    slot32_intake = intake_dir / "slot32" / "intake.jsonl"
    slot14_intake = intake_dir / "slot14" / "intake.jsonl"
    assert slot32_intake.exists()
    assert slot14_intake.exists()
    lines = slot32_intake.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2
    payload = json.loads(lines[0])
    assert payload["slot"] == "slot32"
    assert payload["category"] in {"repair_diagnosis", "skill_assessment"}
    readiness = json.loads(outputs["self_improvement_readiness"].read_text())
    assert readiness["training_intake_export"]["requested"] is True
    assert readiness["training_intake_export"]["slot32_entries_written"] >= 2
    assert readiness["training_intake_export"]["slot14_entries_written"] >= 1


def test_handoff_writes_orchestration_state_for_nightly_follow_up(tmp_path):
    run_dir = tmp_path / "run"
    cycle = run_dir / "cycle_01"
    cycle.mkdir(parents=True)
    (cycle / "draft.md").write_text("# Policy Framework", encoding="utf-8")
    _write(cycle / "metrics.json", {"overall_score": 0.91, "changes_applied": []})
    _write(
        cycle / "document_profile_conformance.json",
        {"status": "REVIEW"},
    )
    _write(cycle / "skills_report.json", {"hard_gate_allowed": False})
    _write(cycle / "training_quarantine.json", {"hard_gate_failures": []})
    _write(cycle / "repair_plan.json", {"selected_count": 2})
    _write(cycle / "section_failure_diagnostics.json", {"failures": []})

    outputs = create_self_improvement_handoff(
        run_dir=run_dir,
        document_type="policy_framework",
    )

    orchestration = json.loads(outputs["orchestration_state"].read_text())
    policy = orchestration["policy"]

    assert orchestration["next_step"] == "analyze_then_schedule"
    assert orchestration["scheduling_required"] is True
    assert orchestration["approval_required"] is False
    assert orchestration["status"] == "ORCHESTRATION_STATE_READY"
    assert policy["observed_attempts"] == 1
    assert orchestration["policy_status"] == policy["status"]
    assert orchestration["monitoring_contract"]["launch_monitor"] == "watchdog"
    assert orchestration["monitoring_contract"]["completion_monitor"] == "argus"
    assert orchestration["orchestration_path"][0] == "analyze_failure_material"
    assert orchestration["followup_contract"]["owner_agent"] == "repairman"
    assert orchestration["followup_task_payload"]["agent"] == "repairman"
    assert orchestration["candidate_action"]["command_or_callable"] == (
        "python3 ops/scripts/docgen_branch_batch_nightly.py"
    )
    assert "slot32" in orchestration["candidate_action"]["resource_policy"][
        "forbidden_concurrent_slots"
    ]
    assert "slot120" in orchestration["candidate_action"]["resource_policy"][
        "forbidden_concurrent_slots"
    ]
