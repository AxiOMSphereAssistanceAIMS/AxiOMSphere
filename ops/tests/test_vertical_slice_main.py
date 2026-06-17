"""
Unit tests for vertical_slice_main orchestrator.

Validates end-to-end pipeline wiring and final-verdict routing with the
surrounding stages mocked. The evaluator mock returns a REAL gate-bearing
eval dict (canonical/legacy gate names) so determine_final_verdict routes the
same way it does in production — never a pre-canonical {current_quality, delta}
stub, which silently routed every run to BLOCKED.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ops.docgen.vertical_slice_main import run_vertical_slice


def _gates(**overrides) -> dict:
    """Producer-shaped gate dict (legacy names) with all gates passing by default."""
    base = {
        "required_blocks_present": True,
        "no_critical_issues": True,
        "render_success": True,
        "no_duplicate_blocks": True,
        "no_placeholder_content": True,
        "training_pairs_available": True,
        "evidence_complete": True,
        "audit_pass": True,
    }
    base.update(overrides)
    return base


def _eval(score: float, overall: str, *, training_readiness: float = 0.9, **gate_overrides) -> dict:
    """Build a BaselineEvalMinimal-shaped result the way the real evaluator emits it."""
    return {
        "baseline_score": score,
        "overall_verdict": overall,
        "metrics": {"training_readiness": training_readiness},
        "gates": _gates(**gate_overrides),
    }


def _run_with_mocks(
    tmp_path,
    *,
    eval_return: dict,
    render_result=(True, {}),
    audit_return: dict | None = None,
) -> dict:
    """
    Run run_vertical_slice with every surrounding stage mocked.

    The mocks are configured for the rewritten 10-step orchestrator:
    - plan.to_dict() returns a JSON-serializable dict (evidence staging serializes it),
    - graph.get_execution_order() returns an iterable,
    - the evaluator returns a real gate-bearing eval dict.
    """
    audit_return = audit_return or {"overall_status": "PASS", "approval": True, "findings": []}

    with ExitStack() as stack:
        mock_plan = stack.enter_context(patch("ops.docgen.vertical_slice_main.PlanCoordinator"))
        plan_instance = MagicMock()
        plan_instance.plan = MagicMock()
        plan_instance.plan.to_dict.return_value = {"topic": "Test Topic"}
        mock_plan.return_value = plan_instance

        mock_builder = stack.enter_context(
            patch("ops.docgen.vertical_slice_main.TechnicalReportGraphBuilder")
        )
        mock_graph = MagicMock()
        mock_graph.blocks = {}
        mock_graph.to_dict.return_value = {"blocks": {}}
        mock_graph.get_execution_order.return_value = []
        mock_graph.get_block.return_value = None
        builder_instance = MagicMock()
        builder_instance.build.return_value = mock_graph
        mock_builder.return_value = builder_instance

        stack.enter_context(patch("ops.docgen.vertical_slice_main.BlockGeneratorMinimal"))

        mock_asm = stack.enter_context(
            patch("ops.docgen.vertical_slice_main.DocumentAssemblerMinimal")
        )
        asm_instance = MagicMock()
        asm_instance.assemble.return_value = tmp_path / "test.docx"
        asm_instance.audit_trail = []
        mock_asm.return_value = asm_instance

        mock_render = stack.enter_context(patch("ops.docgen.vertical_slice_main.RenderQAWrapper"))
        render_instance = MagicMock()
        render_instance.render_and_inspect.return_value = render_result
        mock_render.return_value = render_instance

        mock_teacher = stack.enter_context(patch("ops.docgen.vertical_slice_main.TeacherAuditMinimal"))
        teacher_instance = MagicMock()
        teacher_instance.audit.return_value = audit_return
        mock_teacher.return_value = teacher_instance

        stack.enter_context(patch("ops.docgen.vertical_slice_main.TrainingPairCaptureMinimal"))

        mock_eval = stack.enter_context(patch("ops.docgen.vertical_slice_main.BaselineEvalMinimal"))
        eval_instance = MagicMock()
        eval_instance.evaluate.return_value = eval_return
        mock_eval.return_value = eval_instance

        return run_vertical_slice("Test Topic", tmp_path)


class TestVerticalSliceOrchestrator:
    """Test suite for run_vertical_slice orchestrator."""

    def test_vertical_slice_result_structure(self, tmp_path):
        """run_vertical_slice returns a dict with the required contract fields."""
        result = _run_with_mocks(
            tmp_path, eval_return=_eval(0.80, "MARGINAL")
        )

        assert isinstance(result, dict)
        for key in (
            "success",
            "output_dir",
            "verdict",
            "run_id",
            "evidence_dir",
            "baseline_score",
            "final_decision_path",
            "baseline_eval_path",
            "evidence_manifest_path",
            "chatgpt55_quality_claimed",
            "process_alignment_claimed",
        ):
            assert key in result, f"Missing return key: {key}"
        assert result["chatgpt55_quality_claimed"] is False

    def test_vertical_slice_success_path(self, tmp_path):
        """All gates pass + score >= 0.90 + PASS_QUALITY_GATE → PASS."""
        result = _run_with_mocks(
            tmp_path, eval_return=_eval(0.93, "PASS_QUALITY_GATE")
        )

        assert result["verdict"] == "DOCGEN_CHATGPT55_VERTICAL_SLICE_PASS"
        assert result["success"] is True

    def test_vertical_slice_ready_with_warnings(self, tmp_path):
        """Renders and audits OK but below the PASS score threshold → READY_WITH_WARNINGS."""
        result = _run_with_mocks(
            tmp_path, eval_return=_eval(0.78, "MARGINAL")
        )

        assert result["verdict"] == "DOCGEN_CHATGPT55_VERTICAL_SLICE_READY_WITH_WARNINGS"

    def test_vertical_slice_needs_repair(self, tmp_path):
        """Audit FAIL (unresolved issues) is repairable → NEEDS_MORE_REPAIR, not BLOCKED."""
        result = _run_with_mocks(
            tmp_path,
            eval_return=_eval(0.55, "NEEDS_REPAIR", training_readiness=0.0,
                              training_pairs_available=False),
            audit_return={"overall_status": "FAIL", "approval": False, "findings": []},
        )

        assert result["verdict"] == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"
        assert "BLOCKED" not in result["verdict"]

    def test_vertical_slice_evidence_manifest_path_exists(self, tmp_path):
        """Blocker-3 regression guard: the advertised evidence_manifest_path must exist on disk."""
        result = _run_with_mocks(
            tmp_path, eval_return=_eval(0.93, "PASS_QUALITY_GATE")
        )

        manifest_path = Path(result["evidence_manifest_path"])
        assert manifest_path.name == "evidence_manifest.json"
        assert manifest_path.exists(), (
            f"Return contract advertises {manifest_path} but it was not written"
        )

    def test_vertical_slice_exception_handling(self, tmp_path):
        """A failure during the run is caught and reported as BLOCKED with an error."""
        with patch("ops.docgen.vertical_slice_main.PlanCoordinator") as mock_plan:
            mock_plan.side_effect = Exception("Plan creation failed")

            result = run_vertical_slice("Test Topic", tmp_path)

            assert result["success"] is False
            assert result["verdict"] == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"
            assert "error" in result

    def test_vertical_slice_saves_artifacts(self, tmp_path):
        """The run creates its output directory with the expected naming."""
        result = _run_with_mocks(
            tmp_path, eval_return=_eval(0.80, "MARGINAL")
        )

        output_dir = Path(result["output_dir"])
        assert "docgen_chatgpt55_vertical_slice" in output_dir.name
        assert output_dir.exists()
