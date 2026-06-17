import json

from ops.docgen.universal_overlay.nightly_improvement_orchestrator import (
    build_docgen_nightly_batch_action,
    write_nightly_feedback,
)


def test_build_docgen_nightly_batch_action_is_scheduler_ready():
    action = build_docgen_nightly_batch_action(
        document_types=["policy_framework", "technical_report"],
        run_tag="20260616T223000Z",
    )

    assert action.action_id.startswith("PA-DOCGEN-NIGHTLY-")
    assert action.command_or_callable == "python3 ops/scripts/docgen_branch_batch_nightly.py"
    assert action.command_args[:2] == ["--run-tag", "20260616T223000Z"]
    assert action.resource_policy["max_vram_gb"] == 0
    assert action.resource_policy["cpu_only_ok"] is True
    assert action.safety_policy["no_model_promotion"] is True


def test_write_nightly_feedback_consumes_batch_report(tmp_path):
    report = tmp_path / "docgen_bulk_branch_run_20260616T223000Z.json"
    report.write_text(
        json.dumps(
            [
                {"document_type": "policy_framework", "convergence_score": 0.93},
                {"document_type": "technical_report", "error": "RuntimeError: blocked"},
            ]
        ),
        encoding="utf-8",
    )

    feedback = write_nightly_feedback(report_path=report, feedback_path=tmp_path / "feedback.json")

    assert feedback["branch_count"] == 2
    assert feedback["error_count"] == 1
    assert feedback["status"] == "REVIEW"
    assert (tmp_path / "feedback.json").exists()
