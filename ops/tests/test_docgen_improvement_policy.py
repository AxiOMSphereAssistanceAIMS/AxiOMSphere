import json

from ops.docgen.universal_overlay.improvement_policy import (
    evaluate_improvement_policy,
    write_improvement_policy,
)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _seed_cycle(cycle, quality, hard_gate=True, profile_status="PASS", repair_selected=1):
    cycle.mkdir(parents=True, exist_ok=True)
    _write_json(cycle / "metrics.json", {"overall_score": quality})
    _write_json(cycle / "skills_report.json", {"hard_gate_allowed": hard_gate})
    _write_json(cycle / "document_profile_conformance.json", {"status": profile_status})
    _write_json(cycle / "repair_plan.json", {"selected_count": repair_selected})


def test_first_cycle_triggers_immediate_analysis(tmp_path):
    run_dir = tmp_path / "run"
    _seed_cycle(run_dir / "cycle_01", 0.83)

    decision = evaluate_improvement_policy(
        run_dir=run_dir,
        document_type="policy_framework",
        audit_dir=tmp_path / "audit",
    )

    assert decision.action == "ANALYZE_AFTER_FIRST_CYCLE"
    assert decision.analysis_required is True
    assert decision.rollback_required is False
    assert decision.observed_attempts == 1


def test_degradation_triggers_rollback_before_retry_limit(tmp_path):
    run_dir = tmp_path / "run"
    _seed_cycle(run_dir / "cycle_01", 0.91)
    _seed_cycle(run_dir / "cycle_02", 0.87)

    decision = evaluate_improvement_policy(
        run_dir=run_dir,
        document_type="maintenance_procedure",
        audit_dir=tmp_path / "audit",
    )

    assert decision.action == "ROLLBACK_AND_REANALYZE"
    assert decision.rollback_required is True
    assert decision.attempts[-1].degraded_from_previous is True
    assert "rollback to the last stable cycle artifact" in decision.next_steps


def test_three_attempts_without_target_require_summative_analysis(tmp_path):
    run_dir = tmp_path / "run"
    _seed_cycle(run_dir / "cycle_01", 0.81)
    _seed_cycle(run_dir / "cycle_02", 0.84)
    _seed_cycle(run_dir / "cycle_03", 0.86)

    decision = evaluate_improvement_policy(
        run_dir=run_dir,
        document_type="technical_report",
        audit_dir=tmp_path / "audit",
    )

    assert decision.action == "ANALYZE_THREE_ATTEMPTS"
    assert decision.observed_attempts == 3
    assert decision.nightly_stability_required is False


def test_three_stable_passes_and_cross_branch_stability_promote(tmp_path):
    run_dir = tmp_path / "run"
    _seed_cycle(run_dir / "cycle_01", 0.99)
    _seed_cycle(run_dir / "cycle_02", 0.995)
    _seed_cycle(run_dir / "cycle_03", 0.997)
    _write_json(
        tmp_path / "audit" / "docgen_bulk_branch_run_20260616T223000Z.json",
        [
            {"document_type": "policy_framework", "result": True, "convergence_score": 0.99},
            {"document_type": "maintenance_procedure", "result": True, "convergence_score": 0.99},
        ],
    )

    decision = evaluate_improvement_policy(
        run_dir=run_dir,
        document_type="policy_framework",
        audit_dir=tmp_path / "audit",
    )

    assert decision.action == "APPROVED_AND_INTEGRATED"
    assert decision.promotion_ready is True
    assert decision.cross_branch_stability["verified"] is True


def test_policy_writer_persists_json(tmp_path):
    run_dir = tmp_path / "run"
    _seed_cycle(run_dir / "cycle_01", 0.82)
    _write_json(run_dir / "summary.json", {"status": "INCOMPLETE"})

    payload = write_improvement_policy(
        run_dir=run_dir,
        document_type="policy_framework",
        audit_dir=tmp_path / "audit",
    )

    out = run_dir / "universal_overlay" / "improvement_policy.json"
    assert out.exists()
    assert payload["status"] == "ANALYZE_AFTER_FIRST_CYCLE"
