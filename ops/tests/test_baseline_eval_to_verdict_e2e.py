"""
Real producer-consumer integration test for DOCGEN verdict routing.

Exercises the FULL contract path with the REAL evaluator:
    BaselineEvalMinimal.evaluate(graph=...)   (producer, real gate vocabulary)
        -> result["gates"]                     (legacy producer gate names)
        -> determine_final_verdict(...)        (consumer, normalizes internally)

This is the test that would have caught the original gate-name drift blocker:
the producer emitted ``required_blocks_present`` while the consumer read
``all_required_blocks_generated``. It must run the REAL evaluator on a REAL
DocumentBlockGraph — never hand-fabricated gate dicts and never a local mock.

This is CERTIFICATION EVIDENCE, not unit-level mocking.
"""

from __future__ import annotations

import pytest

from ops.docgen.baseline_eval_minimal import BaselineEvalMinimal
from ops.docgen.document_block_graph import (
    BlockType,
    DocumentBlock,
    DocumentBlockGraph,
)
from ops.docgen.vertical_slice_main import determine_final_verdict


def _make_graph(
    *,
    block_count: int = 4,
    content_per_block: str | None = None,
    quality: float = 0.9,
    duplicate: bool = False,
    empty_required_block: bool = False,
) -> DocumentBlockGraph:
    """
    Build a real DocumentBlockGraph of required SECTION blocks.

    Args:
        block_count: number of required section blocks.
        content_per_block: explicit content; defaults to distinct per-section text.
        quality: quality_score assigned to each block.
        duplicate: if True, every block shares identical content (triggers the
            evaluator's duplicate detector).
        empty_required_block: if True, the last required block has no content
            (triggers required_blocks_present == False).
    """
    graph = DocumentBlockGraph(document_type="technical_report")
    for i in range(1, block_count + 1):
        if duplicate:
            content = "Identical duplicated section content. " * 40
        else:
            content = content_per_block or (
                f"Section {i} discusses a distinct technical topic in depth "
                f"with specific engineering detail number {i}. " * 25
            )
        if empty_required_block and i == block_count:
            content = ""
        block = DocumentBlock(
            block_id=f"SEC-{i:03d}",
            block_type=BlockType.SECTION,
            document_type="technical_report",
            required=True,
            generated_content=content,
            quality_score=quality,
        )
        graph.blocks[f"SEC-{i:03d}"] = block
    return graph


def _full_evidence_manifest() -> dict[str, str]:
    """Manifest with all artifacts the evaluator counts as complete evidence."""
    return {
        "plan_snapshot": "/tmp/plan_snapshot.json",
        "block_graph_final": "/tmp/block_graph_final.json",
        "implementation_log": "/tmp/implementation_log.json",
        "final_decision": "/tmp/final_decision.json",
        "baseline_eval": "/tmp/baseline_eval.json",
    }


class TestRealProducerConsumerContract:
    """Integration tests driving the REAL BaselineEvalMinimal output through the verdict router."""

    def test_real_baseline_eval_good_document_does_not_block(self):
        """High-quality document with all gates passing must NOT route to BLOCKED."""
        graph = _make_graph(block_count=4, quality=0.95)
        result = BaselineEvalMinimal().evaluate(
            graph=graph,
            audit_report={"overall_status": "PASS", "approval": True, "findings": []},
            render_metrics={"page_count": 4, "blank_page_count": 0},
            visual_qa_passed=True,
            training_pairs_count=3,
            evidence_manifest=_full_evidence_manifest(),
            docx_size_bytes=20_000,
        )

        # Feed the REAL producer output (legacy gate names) straight to the consumer.
        verdict = determine_final_verdict(
            baseline_eval=result,
            blocked_error=False,
            repair_attempted=False,
            unresolved_issues=False,
        )

        assert "BLOCKED" not in verdict, (
            f"Good document blocked — producer/consumer gate drift? "
            f"verdict={verdict} gates={result.get('gates')}"
        )
        assert verdict in {
            "DOCGEN_CHATGPT55_VERTICAL_SLICE_PASS",
            "DOCGEN_CHATGPT55_VERTICAL_SLICE_READY_WITH_WARNINGS",
        }

    def test_real_baseline_eval_missing_required_blocks_blocks(self):
        """A required block with no content must route to BLOCKED (Phase 1)."""
        graph = _make_graph(block_count=4, empty_required_block=True)
        result = BaselineEvalMinimal().evaluate(
            graph=graph,
            audit_report={"overall_status": "PASS", "approval": True, "findings": []},
            render_metrics={"page_count": 3, "blank_page_count": 0},
            visual_qa_passed=True,
            training_pairs_count=3,
            evidence_manifest=_full_evidence_manifest(),
            docx_size_bytes=20_000,
        )

        # Sanity: the real producer must report the missing block.
        assert result["gates"]["required_blocks_present"] is False

        verdict = determine_final_verdict(baseline_eval=result)
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"

    def test_real_baseline_eval_duplicate_content_routes_to_repair(self):
        """Duplicate content is a Phase-2 repairable issue → NEEDS_MORE_REPAIR, not BLOCKED."""
        graph = _make_graph(block_count=4, duplicate=True)
        result = BaselineEvalMinimal().evaluate(
            graph=graph,
            audit_report={"overall_status": "PASS", "approval": True, "findings": []},
            render_metrics={"page_count": 3, "blank_page_count": 0},
            visual_qa_passed=True,
            training_pairs_count=3,
            evidence_manifest=_full_evidence_manifest(),
            docx_size_bytes=20_000,
        )

        # Sanity: the real producer must detect the duplicates.
        assert result["gates"]["no_duplicate_blocks"] is False
        # Phase-1 gates must still pass so we genuinely reach Phase 2.
        assert result["gates"]["required_blocks_present"] is True

        verdict = determine_final_verdict(baseline_eval=result)
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_NEEDS_MORE_REPAIR"
        assert "BLOCKED" not in verdict

    def test_real_baseline_eval_render_failure_blocks(self):
        """visual_qa_passed=False → render_success gate False → BLOCKED (Phase 1, gate-driven)."""
        graph = _make_graph(block_count=4, quality=0.95)
        result = BaselineEvalMinimal().evaluate(
            graph=graph,
            audit_report={"overall_status": "PASS", "approval": True, "findings": []},
            render_metrics={"page_count": 0, "blank_page_count": 0},
            visual_qa_passed=False,  # render QA failed
            training_pairs_count=3,
            evidence_manifest=_full_evidence_manifest(),
            docx_size_bytes=20_000,
        )

        assert result["gates"]["render_success"] is False

        # No blocked_error flag — the gate itself must drive the block.
        verdict = determine_final_verdict(baseline_eval=result, blocked_error=False)
        assert verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_BLOCKED"
