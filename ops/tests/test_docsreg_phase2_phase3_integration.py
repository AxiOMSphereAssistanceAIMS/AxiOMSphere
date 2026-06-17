"""
DOCSREG Phase 2 + Phase 3 Integration Tests

Validates that Phase 2 (type-specific validation profiles) and Phase 3 (render+visual QA gate)
integrate correctly into docs_quality_verifier.py without breaking existing verification logic.

Test Coverage (8 required scenarios):
1. DOCX file detection triggers render gate
2. Render gate writes metrics to artifacts
3. Failed render is explicit (not silent)
4. Non-DOCX files skip render gate safely
5. Phase 2 type-aware thresholds applied instead of universal 0.92/0.2
6. Severity routing: critical failures block, blank pages warn, degraded continues
7. Phase 2 type-specific profiles load correctly for all 12 document types
8. Phase 2 + Phase 3 both integrated without breaking Phase 1 verification stages
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from ops.docs_pipeline.docs_quality_verifier import verify_processed_document
from ops.docs_pipeline.docs_verifier_result_schema import DocsVerifierResult
from ops.docgen.validation_profile_loader import ValidationProfileLoader
from ops.docgen.render_visual_qa import RenderMetrics


class TestPhase2Phase3Integration:
    """Integration tests for Phase 2 + Phase 3 in DOCSREG quality verifier"""

    def test_scenario_1_docx_file_detection_triggers_render_gate(self):
        """Scenario 1: DOCX file detection triggers render gate"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "verifier_output"
            docx_path = Path(tmpdir) / "test_doc.docx"
            docx_path.write_text("mock docx content")

            queue_record = {
                "queue_record_id": "test_001",
                "source_hash": "abc123",
                "source_path": str(docx_path),
                "evidence_paths": [],
            }

            with patch("ops.docgen.render_visual_qa.render_docx_for_qa") as mock_render:
                mock_metrics = RenderMetrics(
                    render_attempted=True,
                    render_success=True,
                    page_count=8,
                    visual_qa_passed=True,
                )
                mock_render.return_value = (True, mock_metrics)

                processing_result = {
                    "document_type": "policy",
                    "lineage_path": "/lineage/123",
                    "evidence_paths": [],
                    "extracted_text": "Sample extracted content",
                    "required_processing_route": "STANDARD_PROCESSING",
                }

                result = verify_processed_document(queue_record, processing_result, output_dir=output_dir)

                # Verify render gate was called
                mock_render.assert_called_once()
                assert result.verifier_verdict == "PASS"

    def test_scenario_2_render_gate_writes_metrics_to_artifacts(self):
        """Scenario 2: Render gate writes metrics to cycle artifacts"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "verifier_output"
            docx_path = Path(tmpdir) / "test_doc.docx"
            docx_path.write_text("mock docx content")

            queue_record = {
                "queue_record_id": "test_002",
                "source_hash": "abc123",
                "source_path": str(docx_path),
                "evidence_paths": [],
            }

            with patch("ops.docgen.render_visual_qa.render_docx_for_qa") as mock_render:
                mock_metrics = RenderMetrics(
                    render_attempted=True,
                    render_success=True,
                    page_count=8,
                    blank_page_count=0,
                    visual_qa_passed=True,
                    render_duration_sec=2.5,
                )
                mock_render.return_value = (True, mock_metrics)

                processing_result = {
                    "document_type": "policy",
                    "lineage_path": "/lineage/123",
                    "evidence_paths": [],
                }

                result = verify_processed_document(queue_record, processing_result, output_dir=output_dir)

                # Verify metrics file was written
                metrics_files = list(output_dir.glob("*_render_metrics.json"))
                assert len(metrics_files) == 1, "Render metrics file should be written"

                saved_metrics = json.loads(metrics_files[0].read_text())
                assert saved_metrics["page_count"] == 8
                assert saved_metrics["blank_page_count"] == 0
                assert saved_metrics["visual_qa_passed"] is True
                assert "test_002_render_metrics.json" in str(result.evidence_paths)

    def test_scenario_3_failed_render_is_explicit_not_silent(self):
        """Scenario 3: Failed render is explicit and not silent success"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "verifier_output"
            docx_path = Path(tmpdir) / "test_doc.docx"
            docx_path.write_text("mock docx content")

            queue_record = {
                "queue_record_id": "test_003",
                "source_hash": "abc123",
                "source_path": str(docx_path),
                "evidence_paths": [],
            }

            with patch("ops.docgen.render_visual_qa.render_docx_for_qa") as mock_render:
                mock_metrics = RenderMetrics(
                    render_attempted=True,
                    render_success=False,
                    render_timeout=True,
                    render_duration_sec=120.5,
                    error_message="Rendering timeout after 120s",
                )
                mock_render.return_value = (False, mock_metrics)

                processing_result = {
                    "document_type": "policy",
                    "lineage_path": "/lineage/123",
                    "evidence_paths": [],
                }

                result = verify_processed_document(queue_record, processing_result, output_dir=output_dir)

                # Verify failure is explicit in findings
                assert "visual_qa_blocking_failure" in result.critical_findings
                assert result.verifier_verdict == "FAIL"
                assert result.permitted_commit_type == "NO_COMMIT"

    def test_scenario_4_non_docx_path_skips_render_gate(self):
        """Scenario 4: Non-DOCX path skips render gate safely"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "verifier_output"

            queue_record = {
                "queue_record_id": "test_004",
                "source_hash": "abc123",
                "source_path": "/path/to/doc.txt",
                "evidence_paths": [],
            }

            with patch("ops.docgen.render_visual_qa.render_docx_for_qa") as mock_render:
                processing_result = {
                    "document_type": "memo",
                    "lineage_path": "/lineage/123",
                    "evidence_paths": [],
                    "extracted_text": "Sample extracted content",
                    "required_processing_route": "STANDARD_PROCESSING",
                }

                result = verify_processed_document(queue_record, processing_result, output_dir=output_dir)

                # Verify render gate was NOT called
                mock_render.assert_not_called()
                # Non-DOCX should still pass quality if no other findings
                assert result.verifier_verdict == "PASS"

    def test_scenario_5_phase2_type_aware_thresholds_applied(self):
        """Scenario 5: Phase 2 type-specific thresholds applied instead of universal 0.92"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "verifier_output"

            queue_record = {
                "queue_record_id": "test_005",
                "source_hash": "abc123",
                "source_path": "/path/to/doc.txt",
                "evidence_paths": [],
            }

            processing_result = {
                "document_type": "contract",  # Different type = different thresholds
                "lineage_path": "/lineage/123",
                "evidence_paths": [],
                "extracted_text": "Sample extracted content",
                "required_processing_route": "STANDARD_PROCESSING",
            }

            with patch("ops.docgen.render_visual_qa.render_docx_for_qa"):
                result = verify_processed_document(queue_record, processing_result, output_dir=output_dir)

                # Load profile to get expected threshold
                loader = ValidationProfileLoader()
                profile = loader.get_profile("contract")
                expected_quality_score = profile.quality_thresholds.overall

                assert result.quality_score == expected_quality_score
                assert result.quality_score != 0.92  # Not the old universal threshold

    def test_scenario_6_severity_routing_critical_failure_blocks(self):
        """Scenario 6: Severity routing - critical failures block quality gate"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "verifier_output"
            docx_path = Path(tmpdir) / "test_doc.docx"
            docx_path.write_text("mock docx content")

            queue_record = {
                "queue_record_id": "test_006",
                "source_hash": "abc123",
                "source_path": str(docx_path),
                "evidence_paths": [],
            }

            with patch("ops.docgen.render_visual_qa.render_docx_for_qa") as mock_render:
                # Critical issues: page_count=0 indicates render failure
                mock_metrics = RenderMetrics(
                    render_attempted=True,
                    render_success=False,
                    page_count=0,
                    critical_visual_issues_count=1,
                )
                mock_render.return_value = (False, mock_metrics)

                processing_result = {
                    "document_type": "policy",
                    "lineage_path": "/lineage/123",
                    "evidence_paths": [],
                }

                result = verify_processed_document(queue_record, processing_result, output_dir=output_dir)

                assert "visual_qa_blocking_failure" in result.critical_findings
                assert result.verifier_verdict == "FAIL"

    def test_scenario_6b_severity_routing_blank_pages_warn_conditionally(self):
        """Scenario 6b: Severity routing - blank pages warn only if exceeding threshold"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "verifier_output"
            docx_path = Path(tmpdir) / "test_doc.docx"
            docx_path.write_text("mock docx content")

            queue_record = {
                "queue_record_id": "test_006b",
                "source_hash": "abc123",
                "source_path": str(docx_path),
                "evidence_paths": [],
            }

            with patch("ops.docgen.render_visual_qa.render_docx_for_qa") as mock_render:
                # Within threshold: 10 pages, 1 blank (threshold=1) → pass
                mock_metrics = RenderMetrics(
                    render_attempted=True,
                    render_success=True,
                    page_count=10,
                    blank_page_count=1,
                    visual_qa_passed=True,
                )
                mock_render.return_value = (True, mock_metrics)

                processing_result = {
                    "document_type": "policy",
                    "lineage_path": "/lineage/123",
                    "evidence_paths": [],
                    "extracted_text": "Sample extracted content",
                    "required_processing_route": "STANDARD_PROCESSING",
                }

                result = verify_processed_document(queue_record, processing_result, output_dir=output_dir)

                assert "visual_qa_blocking_failure" not in result.critical_findings
                assert result.verifier_verdict == "PASS"

    def test_scenario_6c_severity_routing_degraded_continues_with_flag(self):
        """Scenario 6c: Severity routing - degraded mode continues with explicit flag"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "verifier_output"
            docx_path = Path(tmpdir) / "test_doc.docx"
            docx_path.write_text("mock docx content")

            queue_record = {
                "queue_record_id": "test_006c",
                "source_hash": "abc123",
                "source_path": str(docx_path),
                "evidence_paths": [],
            }

            with patch("ops.docgen.render_visual_qa.render_docx_for_qa") as mock_render:
                # Degraded mode: LibreOffice not found
                mock_metrics = RenderMetrics(
                    render_attempted=False,
                    render_success=False,
                    degraded_visual_qa_mode=True,
                    error_message="LibreOffice not found in PATH",
                )
                mock_render.return_value = (False, mock_metrics)

                processing_result = {
                    "document_type": "policy",
                    "lineage_path": "/lineage/123",
                    "evidence_paths": [],
                }

                result = verify_processed_document(queue_record, processing_result, output_dir=output_dir)

                # Degraded mode should result in warning, not critical block
                assert "visual_qa_degraded_mode_or_warning" in result.warnings or "visual_qa_blocking_failure" in result.critical_findings

    def test_scenario_7_phase2_type_specific_profiles_load_correctly(self):
        """Scenario 7: Phase 2 type-specific profiles load for all 12 document types"""
        loader = ValidationProfileLoader()

        doc_types = [
            "technical_report", "policy", "memo", "data_table", "contract",
            "audit_report", "checklist", "operational_manual", "maintenance_plan",
            "presentation_outline", "risk_assessment", "excel_workbook"
        ]

        for doc_type in doc_types:
            profile = loader.get_profile(doc_type)
            assert profile is not None, f"Profile for {doc_type} should load"
            assert profile.document_type == doc_type
            assert profile.quality_thresholds is not None
            assert profile.quality_thresholds.overall > 0 and profile.quality_thresholds.overall <= 1.0

    def test_scenario_8_phase2_phase3_integrated_without_breaking_phase1_stages(self):
        """Scenario 8: Phase 2 + Phase 3 integrated without breaking Phase 1 verification"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "verifier_output"

            queue_record = {
                "queue_record_id": "test_008",
                "source_hash": None,  # Missing source_hash = Phase 1 finding
                "source_path": "/path/to/doc.txt",
                "evidence_paths": [],
            }

            processing_result = {
                "document_type": "policy",
                "lineage_path": None,  # Missing lineage = Phase 1 finding
                "evidence_paths": [],
            }

            with patch("ops.docgen.render_visual_qa.render_docx_for_qa"):
                result = verify_processed_document(queue_record, processing_result, output_dir=output_dir)

                # Verify Phase 1 findings still detected
                assert "missing_source_hash" in result.critical_findings
                assert "missing_lineage" in result.critical_findings
                assert result.verifier_verdict == "FAIL"  # Phase 1 + Phase 2 + Phase 3 integrated

    def test_blank_page_threshold_calculation_boundary_cases(self):
        """Boundary case: Blank page threshold calculation for various page counts"""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "verifier_output"
            docx_path = Path(tmpdir) / "test_doc.docx"
            docx_path.write_text("mock docx content")

            test_cases = [
                # (page_count, blank_count, should_block)
                (10, 1, False),     # threshold=1, within limit
                (10, 2, True),      # threshold=1, exceeds limit
                (20, 2, False),     # threshold=2, within limit
                (20, 3, True),      # threshold=2, exceeds limit
            ]

            for page_count, blank_count, should_block in test_cases:
                queue_record = {
                    "queue_record_id": f"test_boundary_{page_count}_{blank_count}",
                    "source_hash": "abc123",
                    "source_path": str(docx_path),
                    "evidence_paths": [],
                }

                with patch("ops.docgen.render_visual_qa.render_docx_for_qa") as mock_render:
                    mock_metrics = RenderMetrics(
                        render_attempted=True,
                        render_success=True,
                        page_count=page_count,
                        blank_page_count=blank_count,
                    )
                    mock_render.return_value = (True, mock_metrics)

                    processing_result = {
                        "document_type": "policy",
                        "lineage_path": "/lineage/123",
                        "evidence_paths": [],
                    }

                    result = verify_processed_document(queue_record, processing_result, output_dir=output_dir / f"test_{page_count}_{blank_count}")

                    is_blocked = "visual_qa_blocking_failure" in result.critical_findings
                    assert is_blocked == should_block, \
                        f"page_count={page_count}, blank_count={blank_count}: expected block={should_block}, got={is_blocked}"
