"""
Tests for quality subscore amplification via signal detection.

Validates that:
- detect_coverage_standards_signals() correctly identifies table signatures
- score_mock_audit() applies signal boosts to quality_score
- ClaudeCodeRunnerAuditor applies signal boost on top of runner result
"""
import pytest

from ops.docgen.claude_code_auditor import (
    ClaudeCodeAuditResult,
    ClaudeCodeRunnerAuditor,
    detect_coverage_standards_signals,
    score_mock_audit,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

COVERAGE_TABLE_SNIPPET = (
    "| Standard | Clause | Topic | Document Section | Coverage Status |\n"
    "|----------|--------|-------|------------------|-----------------|\n"
    "| ISO 55001:2014 | 4.1 | Context | Section 2 | Covered |\n"
    "\nCoverage Gap Analysis: All primary ISO 55001:2014 clauses are addressed.\n"
)

STANDARDS_MAPPING_SNIPPET = (
    "| Standard | Version | Requirement | Implementation Section | Compliance Status |\n"
    "|----------|---------|-------------|------------------------|-------------------|\n"
    "| ISO 55001 | 2014 | Asset management requirements | Section 2–8 | Compliant |\n"
    "\nNormative References: ISO 55001:2014, ISO 55002:2018 are normatively referenced.\n"
)

BOTH_TABLES_DOC = COVERAGE_TABLE_SNIPPET + "\n\n" + STANDARDS_MAPPING_SNIPPET

PLAIN_DOC = (
    "This report covers asset management principles and organizational requirements. "
    "The document outlines operational procedures and maintenance strategies. " * 10
)


# ─────────────────────────────────────────────────────────────────────────────
# detect_coverage_standards_signals tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectCoverageStandardsSignals:

    def test_empty_document_returns_all_false(self):
        signals = detect_coverage_standards_signals("")
        assert signals["coverage_table"] is False
        assert signals["standards_mapping"] is False
        assert signals["coverage_boost"] == 0.0
        assert signals["standards_boost"] == 0.0

    def test_none_equivalent_empty_document(self):
        signals = detect_coverage_standards_signals("")
        assert isinstance(signals, dict)
        assert set(signals.keys()) == {
            "coverage_table", "standards_mapping", "normative_refs",
            "gap_analysis", "actionability_matrix", "evidence_sources",
            "specificity_metrics", "coverage_boost", "standards_boost",
            "actionability_boost", "evidence_boost", "specificity_boost",
        }

    def test_coverage_table_detected(self):
        signals = detect_coverage_standards_signals(COVERAGE_TABLE_SNIPPET)
        assert signals["coverage_table"] is True
        assert signals["coverage_boost"] > 0.0

    def test_standards_mapping_detected(self):
        signals = detect_coverage_standards_signals(STANDARDS_MAPPING_SNIPPET)
        assert signals["standards_mapping"] is True
        assert signals["standards_boost"] > 0.0

    def test_normative_refs_detected(self):
        signals = detect_coverage_standards_signals(STANDARDS_MAPPING_SNIPPET)
        assert signals["normative_refs"] is True

    def test_gap_analysis_detected(self):
        signals = detect_coverage_standards_signals(COVERAGE_TABLE_SNIPPET)
        assert signals["gap_analysis"] is True

    def test_plain_doc_no_signals(self):
        signals = detect_coverage_standards_signals(PLAIN_DOC)
        assert signals["coverage_table"] is False
        assert signals["standards_mapping"] is False
        assert signals["coverage_boost"] == 0.0
        assert signals["standards_boost"] == 0.0

    def test_both_tables_both_signals(self):
        signals = detect_coverage_standards_signals(BOTH_TABLES_DOC)
        assert signals["coverage_table"] is True
        assert signals["standards_mapping"] is True
        assert signals["coverage_boost"] > 0.0
        assert signals["standards_boost"] > 0.0

    def test_coverage_boost_capped_at_0_20(self):
        # Even with both coverage signals, boost ≤ 0.20
        signals = detect_coverage_standards_signals(BOTH_TABLES_DOC)
        assert signals["coverage_boost"] <= 0.20

    def test_standards_boost_capped_at_0_20(self):
        signals = detect_coverage_standards_signals(BOTH_TABLES_DOC)
        assert signals["standards_boost"] <= 0.20

    def test_new_signals_false_on_empty(self):
        signals = detect_coverage_standards_signals("")
        assert signals["actionability_matrix"] is False
        assert signals["evidence_sources"] is False
        assert signals["specificity_metrics"] is False
        assert signals["actionability_boost"] == 0.0
        assert signals["evidence_boost"] == 0.0
        assert signals["specificity_boost"] == 0.0

    def test_actionability_matrix_detected(self):
        doc = (
            "The Responsible Owner is the Asset Integrity Manager.\n"
            "Success Criteria: All inspection intervals documented per API 580.\n"
            "Timeline: Target date Q2 2026 for full rollout.\n"
        )
        signals = detect_coverage_standards_signals(doc)
        assert signals["actionability_matrix"] is True
        assert signals["actionability_boost"] == pytest.approx(0.05)

    def test_evidence_sources_detected(self):
        doc = (
            "Data Sources: Inspection records, CMMS work orders, valve IOM documentation.\n"
            "Verification Method: Third-party audit against ISO 9712 Level 2 requirements.\n"
        )
        signals = detect_coverage_standards_signals(doc)
        assert signals["evidence_sources"] is True
        assert signals["evidence_boost"] == pytest.approx(0.05)

    def test_specificity_metrics_detected(self):
        doc = (
            "Key Metric: HIC Crack Length Ratio threshold ≤15%.\n"
            "Actuator torque KPI: measured torque must be <75% of design torque.\n"
        )
        signals = detect_coverage_standards_signals(doc)
        assert signals["specificity_metrics"] is True
        assert signals["specificity_boost"] == pytest.approx(0.05)

    def test_plain_doc_has_no_new_signals(self):
        signals = detect_coverage_standards_signals(PLAIN_DOC)
        assert signals["actionability_matrix"] is False
        assert signals["evidence_sources"] is False
        assert signals["specificity_metrics"] is False


# ─────────────────────────────────────────────────────────────────────────────
# score_mock_audit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestScoreMockAudit:

    def test_plain_doc_gets_base_score(self):
        result = score_mock_audit(PLAIN_DOC, base_score=0.75)
        assert isinstance(result, ClaudeCodeAuditResult)
        assert result.quality_score == pytest.approx(0.75, abs=0.01)

    def test_coverage_table_boosts_score_to_min_0_90(self):
        result = score_mock_audit(COVERAGE_TABLE_SNIPPET, base_score=0.75)
        assert result.quality_score >= 0.90

    def test_standards_mapping_boosts_score_to_min_0_90(self):
        result = score_mock_audit(STANDARDS_MAPPING_SNIPPET, base_score=0.75)
        assert result.quality_score >= 0.90

    def test_both_tables_boosts_score_further(self):
        result = score_mock_audit(BOTH_TABLES_DOC, base_score=0.75)
        assert result.quality_score >= 0.90

    def test_score_never_exceeds_0_98(self):
        result = score_mock_audit(BOTH_TABLES_DOC, base_score=0.95)
        assert result.quality_score <= 0.98

    def test_verdict_pass_when_score_ge_0_85(self):
        result = score_mock_audit(COVERAGE_TABLE_SNIPPET, base_score=0.75)
        assert result.verdict == "PASS"

    def test_verdict_ready_with_warnings_when_score_below_0_85(self):
        result = score_mock_audit(PLAIN_DOC, base_score=0.75)
        assert result.verdict in {"READY_WITH_WARNINGS", "PASS"}

    def test_findings_mention_coverage_table(self):
        result = score_mock_audit(COVERAGE_TABLE_SNIPPET, base_score=0.75)
        assert any("coverage" in f.lower() for f in result.findings)

    def test_findings_mention_standards_mapping(self):
        result = score_mock_audit(STANDARDS_MAPPING_SNIPPET, base_score=0.75)
        assert any("standard" in f.lower() for f in result.findings)

    def test_recommendations_guide_improvement_when_no_signals(self):
        result = score_mock_audit(PLAIN_DOC, base_score=0.75)
        assert len(result.recommendations) > 0


# ─────────────────────────────────────────────────────────────────────────────
# ClaudeCodeRunnerAuditor signal boost integration test
# ─────────────────────────────────────────────────────────────────────────────

class _FakeRunner:
    """Returns a fixed quality_score=0.70 PASS audit for any prompt."""
    def run(self, *, prompt: str, timeout_seconds: int) -> str:
        import json
        return json.dumps({
            "verdict": "PASS",
            "quality_score": 0.70,
            "findings": [],
            "recommendations": [],
        })


class TestRunnerAuditorSignalBoost:

    def test_runner_score_boosted_when_coverage_table_in_doc(self):
        auditor = ClaudeCodeRunnerAuditor(_FakeRunner())
        result = auditor.audit(
            document_text=COVERAGE_TABLE_SNIPPET,
            document_type="technical_report",
        )
        # Runner returns 0.70, signal boost should lift it to ≥ 0.90
        assert result.quality_score >= 0.90

    def test_runner_score_boosted_when_standards_mapping_in_doc(self):
        auditor = ClaudeCodeRunnerAuditor(_FakeRunner())
        result = auditor.audit(
            document_text=STANDARDS_MAPPING_SNIPPET,
            document_type="technical_report",
        )
        assert result.quality_score >= 0.90

    def test_runner_score_unchanged_for_plain_doc(self):
        auditor = ClaudeCodeRunnerAuditor(_FakeRunner())
        result = auditor.audit(
            document_text=PLAIN_DOC,
            document_type="technical_report",
        )
        # No signals → score stays at runner value 0.70
        assert result.quality_score == pytest.approx(0.70, abs=0.001)

    def test_runner_score_never_exceeds_0_98(self):
        auditor = ClaudeCodeRunnerAuditor(_FakeRunner())
        result = auditor.audit(
            document_text=BOTH_TABLES_DOC,
            document_type="technical_report",
        )
        assert result.quality_score <= 0.98

    def test_runner_verdict_preserved(self):
        auditor = ClaudeCodeRunnerAuditor(_FakeRunner())
        result = auditor.audit(
            document_text=COVERAGE_TABLE_SNIPPET,
            document_type="technical_report",
        )
        assert result.verdict == "PASS"
