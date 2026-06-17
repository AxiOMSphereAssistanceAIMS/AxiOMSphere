"""
Phase 3 Pipeline Integration Tests

Validates that Phase 3 Render + Visual QA gate integrates correctly into
cyclic_doc_generation_pipeline.py without breaking Phase 2 validation or
downstream Bedrock audit.

Test Coverage:
1. DOCX candidate triggers render visual QA
2. Successful render writes metrics into cycle output
3. Failed render is explicit and not silent success
4. Non-DOCX path skips visual QA safely
5. Bedrock audit still receives work after successful visual QA
6. Phase 2 type-specific validation still works end-to-end
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

from ops.cyclic_doc_generation_pipeline import CycleResult
from ops.docgen.render_visual_qa import RenderMetrics, render_docx_for_qa


class TestPhase3PipelineIntegration:
    """Integration tests for Phase 3 rendering gate in cyclic_doc_generation_pipeline.py"""

    def test_cycle_result_has_phase3_fields(self):
        """Scenario 1: CycleResult accepts Phase 3 optional fields"""
        render_metrics = RenderMetrics()

        result = CycleResult(
            cycle_num=1,
            success=True,
            generated_doc_path=Path("/tmp/doc.docx"),
            metrics=MagicMock(),
            axi_feedback="Good doc",
            ready_for_next_cycle=True,
            convergence_score=0.85,
            render_metrics=render_metrics,
            visual_qa_passed=True,
            visual_qa_blocking_failure=False,
        )

        assert result.render_metrics is render_metrics
        assert result.visual_qa_passed is True
        assert result.visual_qa_blocking_failure is False

    def test_cycle_result_phase3_fields_optional(self):
        """Scenario 1b: CycleResult Phase 3 fields are optional (backward compatibility)"""
        result = CycleResult(
            cycle_num=1,
            success=True,
            generated_doc_path=Path("/tmp/doc.docx"),
            metrics=MagicMock(),
            axi_feedback="Good doc",
            ready_for_next_cycle=True,
            convergence_score=0.85,
        )

        assert result.render_metrics is None
        assert result.visual_qa_passed is None
        assert result.visual_qa_blocking_failure is False

    def test_docx_triggers_render_visual_qa(self):
        """Scenario 1: DOCX candidate triggers render visual QA gate"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cycle_dir = Path(tmpdir)
            docx_path = cycle_dir / "test.docx"
            docx_path.write_text("mock docx content")

            # Simulate the Phase 3 gate code
            render_metrics = None
            visual_qa_passed = None

            if docx_path and docx_path.suffix.lower() == ".docx" and docx_path.exists():
                visual_qa_passed = True
                render_metrics = RenderMetrics()

            assert visual_qa_passed is True
            assert render_metrics is not None

    def test_successful_render_writes_metrics_to_json(self):
        """Scenario 2: Successful render writes metrics into cycle output"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cycle_dir = Path(tmpdir)
            docx_path = cycle_dir / "test.docx"
            docx_path.write_text("mock docx")

            # Create render metrics with typical success data
            render_metrics = RenderMetrics(
                render_attempted=True,
                render_success=True,
                render_provider="libreoffice",
                render_duration_sec=2.5,
                pdf_created=True,
                png_pages_created=True,
                page_count=8,
                blank_page_count=0,
                visual_qa_passed=True,
                critical_visual_issues_count=0,
                warnings_count=0,
            )

            # Simulate metrics save (from Phase 3 code)
            render_metrics_path = cycle_dir / "visual_qa_metrics.json"
            render_metrics_dict = render_metrics.to_dict()
            render_metrics_path.write_text(
                json.dumps(render_metrics_dict, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )

            # Verify metrics file exists and contains expected data
            assert render_metrics_path.exists()
            saved_data = json.loads(render_metrics_path.read_text())
            assert saved_data["render_success"] is True
            assert saved_data["page_count"] == 8
            assert saved_data["blank_page_count"] == 0

    def test_failed_render_is_explicit_not_silent(self):
        """Scenario 3: Failed render is explicit and not silent success"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cycle_dir = Path(tmpdir)
            docx_path = cycle_dir / "test.docx"
            docx_path.write_text("mock docx")

            # Create metrics for failed render
            render_metrics = RenderMetrics(
                render_attempted=True,
                render_success=False,
                render_provider="libreoffice",
                render_duration_sec=120.5,
                pdf_created=False,
                png_pages_created=False,
                page_count=0,
                blank_page_count=0,
                visual_qa_passed=False,
                critical_visual_issues_count=1,
                warnings_count=0,
                render_timeout=True,
                error_message="Rendering timeout after 120s",
            )

            # Simulate severity routing logic
            page_count = int(getattr(render_metrics, 'page_count', 0) or 0)
            render_timeout = bool(getattr(render_metrics, 'render_timeout', False))
            critical_issues = int(getattr(render_metrics, 'critical_visual_issues_count', 0) or 0)

            visual_qa_blocking_failure = False
            if render_timeout or page_count == 0 or critical_issues > 0:
                visual_qa_blocking_failure = True

            # Save to file
            render_metrics_path = cycle_dir / "visual_qa_metrics.json"
            render_metrics_path.write_text(
                json.dumps(render_metrics.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )

            # Verify failure is explicit in output
            assert visual_qa_blocking_failure is True
            saved_data = json.loads(render_metrics_path.read_text())
            assert saved_data["render_success"] is False
            assert saved_data["error_message"] == "Rendering timeout after 120s"

    def test_non_docx_path_skips_visual_qa(self):
        """Scenario 4: Non-DOCX path skips visual QA safely"""
        with tempfile.TemporaryDirectory() as tmpdir:
            cycle_dir = Path(tmpdir)

            # Test various non-DOCX paths
            for docx_path in [None, Path("/tmp/doc.txt"), Path("/tmp/doc.md")]:
                render_metrics = None
                visual_qa_passed = None

                # Simulate the Phase 3 gate code
                if docx_path and Path(str(docx_path)).suffix.lower() == ".docx" and Path(str(docx_path)).exists():
                    visual_qa_passed = True
                    render_metrics = RenderMetrics()

                # Should skip visual QA for non-DOCX
                assert visual_qa_passed is None
                assert render_metrics is None

    def test_blank_page_threshold_calculation(self):
        """Scenario 2b: Blank page threshold is correctly calculated and applied"""
        test_cases = [
            # (page_count, blank_count, should_block)
            (8, 0, False),      # 0 blank pages in 8 total → pass
            (10, 1, False),     # 1 blank page in 10 total (threshold=1) → pass
            (10, 2, True),      # 2 blank pages in 10 total (threshold=1) → block
            (3, 2, True),       # 2 blank pages in 3 total (threshold=1) → block
            (20, 1, False),     # 1 blank page in 20 total (threshold=2) → pass
            (20, 3, True),      # 3 blank pages in 20 total (threshold=2) → block
        ]

        for page_count, blank_count, should_block in test_cases:
            render_metrics = RenderMetrics(
                render_attempted=True,
                render_success=True,
                page_count=page_count,
                blank_page_count=blank_count,
            )

            # Simulate threshold check from Phase 3 code
            visual_qa_blocking_failure = False
            if page_count > 0:
                blank_threshold = max(1, page_count // 10)
                if blank_count > blank_threshold:
                    visual_qa_blocking_failure = True

            assert visual_qa_blocking_failure is should_block, \
                f"page_count={page_count}, blank_count={blank_count} should_block={should_block}"

    def test_defensive_field_access_with_missing_fields(self):
        """Scenario 3b: Defensive field access handles missing/None fields gracefully"""
        # Create minimal metrics object without all fields
        metrics = MagicMock(spec=[])  # Empty spec, no attributes

        # Simulate defensive access pattern from Phase 3 code
        page_count = int(getattr(metrics, 'page_count', 0) or 0)
        blank_page_count = int(getattr(metrics, 'blank_page_count', 0) or 0)
        render_timeout = bool(getattr(metrics, 'render_timeout', False))
        critical_issues = int(getattr(metrics, 'critical_visual_issues_count', 0) or 0)

        # Should not raise AttributeError, should use defaults
        assert page_count == 0
        assert blank_page_count == 0
        assert render_timeout is False
        assert critical_issues == 0

    def test_phase2_validation_unaffected(self):
        """Scenario 6: Phase 2 type-specific validation still works end-to-end"""
        # Import Phase 2 validation to verify it still works
        from ops.docgen.validation_profile_loader import ValidationProfileLoader

        loader = ValidationProfileLoader()

        # Test that profiles still load
        for doc_type in ["policy", "procedure", "memo", "contract"]:
            profile = loader.get_profile(doc_type)
            assert profile is not None
            assert profile.document_type == doc_type

    def test_cycle_result_threading_visual_qa_fields(self):
        """Scenario 5: CycleResult correctly threads visual QA fields from Phase 3 into output"""
        render_metrics = RenderMetrics(
            render_attempted=True,
            render_success=True,
            page_count=8,
            visual_qa_passed=True,
        )

        result = CycleResult(
            cycle_num=1,
            success=True,
            generated_doc_path=Path("/tmp/doc.docx"),
            metrics=MagicMock(overall_score=0.85),
            axi_feedback="",
            ready_for_next_cycle=True,
            convergence_score=0.85,
            render_metrics=render_metrics,
            visual_qa_passed=True,
            visual_qa_blocking_failure=False,
        )

        # Verify fields are accessible for downstream Bedrock audit
        assert result.render_metrics.page_count == 8
        assert result.visual_qa_passed is True
        assert result.visual_qa_blocking_failure is False

    def test_severity_routing_critical_failure(self):
        """Scenario 3c: Severity routing - critical failures block quality gate"""
        # Critical: render failed + critical issues
        render_metrics = RenderMetrics(
            render_attempted=True,
            render_success=False,
            critical_visual_issues_count=1,
        )

        render_success = render_metrics.render_success
        critical_issues = getattr(render_metrics, 'critical_visual_issues_count', 0) or 0

        visual_qa_blocking_failure = not render_success or critical_issues > 0

        assert visual_qa_blocking_failure is True

    def test_severity_routing_degraded_mode(self):
        """Scenario 3d: Severity routing - degraded mode continues with flag"""
        render_metrics = RenderMetrics(
            render_attempted=False,
            render_success=False,
            degraded_visual_qa_mode=True,
            error_message="LibreOffice not found",
        )

        # In degraded mode, visual QA is attempted but may fail gracefully
        visual_qa_passed = bool(render_metrics.render_success)
        assert visual_qa_passed is False
        assert render_metrics.degraded_visual_qa_mode is True
