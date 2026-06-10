"""
Tests for issue taxonomy classification and severity detection.

Validates classify_audit_finding(), batch classification, blocking/repairable
detection logic for quality cycle repair workflows.
"""

import pytest
from ops.docgen.issue_taxonomy import (
    IssueSeverity,
    IssueType,
    ClassifiedIssue,
    classify_audit_finding,
    classify_audit_report,
    has_blocking_issues,
    has_repairable_issues,
)


class TestIssueTaxonomy:
    """Test issue classification and severity detection."""

    def test_issue_severity_enum(self):
        """Test that IssueSeverity enum has expected values."""
        assert hasattr(IssueSeverity, "CRITICAL")
        assert hasattr(IssueSeverity, "MAJOR")
        assert hasattr(IssueSeverity, "WARNING")
        assert hasattr(IssueSeverity, "INFO")

    def test_issue_type_enum(self):
        """Test that IssueType enum has expected values."""
        expected_types = [
            "MISSING_REQUIRED_SECTION",
            "RENDER_FAILURE",
            "DUPLICATE_CONTENT",
            "PLACEHOLDER_CONTENT",
            "WEAK_RECOMMENDATIONS",
            "WEAK_EVIDENCE",
            "LOW_COHERENCE",
            "CITATION_GAP",
            "STRUCTURE_MISMATCH",
            "STYLE_MISMATCH",
            "INTERNAL_METADATA_LEAK",
            "UNKNOWN",
        ]

        for issue_type in expected_types:
            assert hasattr(IssueType, issue_type)

    def test_classified_issue_dataclass(self):
        """Test that ClassifiedIssue is frozen and has expected fields."""
        issue = ClassifiedIssue(
            issue_type=IssueType.MISSING_REQUIRED_SECTION,
            severity=IssueSeverity.MAJOR,
            block_id="block-1",
            message="Executive Summary section is missing",
        )

        assert issue.issue_type == IssueType.MISSING_REQUIRED_SECTION
        assert issue.severity == IssueSeverity.MAJOR
        assert issue.message == "Executive Summary section is missing"
        assert issue.block_id == "block-1"

        # Verify frozen (immutable)
        with pytest.raises(AttributeError):
            issue.severity = IssueSeverity.CRITICAL

    def test_classify_audit_finding_missing_section(self):
        """Test classification of missing section finding."""
        finding = {
            "message": "Executive Summary section is missing from document",
            "severity": "major",
        }

        result = classify_audit_finding(finding)

        assert result.issue_type == IssueType.MISSING_REQUIRED_SECTION
        assert result.severity == IssueSeverity.MAJOR
        assert "missing" in result.message.lower() or "Executive" in result.message

    def test_classify_audit_finding_render_failure(self):
        """Test classification of render failure finding."""
        finding = {
            "message": "Failed to render document to DOCX format",
            "severity": "critical",
        }

        result = classify_audit_finding(finding)

        assert result.issue_type == IssueType.RENDER_FAILURE
        assert result.severity in (IssueSeverity.CRITICAL, IssueSeverity.MAJOR)

    def test_classify_audit_finding_duplicate_content(self):
        """Test classification of duplicate content finding."""
        finding = {
            "message": "Recommendation text appears twice in document (duplicate content)",
            "severity": "major",
        }

        result = classify_audit_finding(finding)

        assert result.issue_type == IssueType.DUPLICATE_CONTENT
        assert result.severity in (IssueSeverity.MAJOR, IssueSeverity.WARNING)

    def test_classify_audit_finding_placeholder_content(self):
        """Test classification of placeholder content finding."""
        finding = {
            "message": "Document contains placeholder text: [TODO: add details]",
            "severity": "major",
        }

        result = classify_audit_finding(finding)

        assert result.issue_type == IssueType.PLACEHOLDER_CONTENT
        assert result.severity in (IssueSeverity.MAJOR, IssueSeverity.WARNING)

    def test_classify_audit_finding_weak_recommendations(self):
        """Test classification of weak recommendations finding."""
        finding = {
            "message": "Recommendations lack specific action items or timelines",
            "severity": "warning",
        }

        result = classify_audit_finding(finding)

        assert result.issue_type == IssueType.WEAK_RECOMMENDATIONS
        assert result.severity in (IssueSeverity.WARNING, IssueSeverity.INFO)

    def test_classify_audit_finding_citation_gap(self):
        """Test classification of citation gap finding."""
        finding = {
            "message": "Document has insufficient citations: only 2 references provided",
            "severity": "warning",
        }

        result = classify_audit_finding(finding)

        assert result.issue_type == IssueType.CITATION_GAP
        assert result.severity == IssueSeverity.WARNING

    def test_classify_audit_finding_unknown_type(self):
        """Test that unknown findings classify as UNKNOWN."""
        finding = {
            "message": "Some unusual issue not matching standard patterns",
        }

        result = classify_audit_finding(finding)

        assert result.issue_type == IssueType.UNKNOWN
        assert result.severity == IssueSeverity.INFO

    def test_classify_audit_report_batch(self):
        """Test batch classification of multiple findings."""
        audit_report = {
            "findings": [
                {
                    "description": "Executive Summary section is missing from document",
                    "location": "document_structure",
                },
                {
                    "description": "Failed to render document to DOCX format",
                    "location": "rendering",
                },
                {
                    "description": "Document has only 2 citations but 5 are required",
                    "citation_count": 2,
                    "citation_requirement": 5,
                },
            ]
        }

        results = classify_audit_report(audit_report)

        assert len(results) == 3
        assert isinstance(results, list)
        assert all(isinstance(r, ClassifiedIssue) for r in results)

    def test_classify_audit_report_empty(self):
        """Test batch classification with no findings."""
        audit_report = {"findings": []}

        results = classify_audit_report(audit_report)

        assert results == []

    def test_classify_audit_report_missing_findings_key(self):
        """Test batch classification when findings key is missing."""
        audit_report = {"audit_score": 0.75}

        results = classify_audit_report(audit_report)

        assert results == []

    def test_has_blocking_issues_with_critical(self):
        """Test that has_blocking_issues() detects CRITICAL severity."""
        issues = [
            ClassifiedIssue(
                issue_type=IssueType.RENDER_FAILURE,
                severity=IssueSeverity.CRITICAL,
                block_id="block-1",
                message="Cannot render document",
            ),
            ClassifiedIssue(
                issue_type=IssueType.MISSING_REQUIRED_SECTION,
                severity=IssueSeverity.WARNING,
                block_id="block-2",
                message="Missing optional section",
            ),
        ]

        assert has_blocking_issues(issues) is True

    def test_has_blocking_issues_without_critical(self):
        """Test that has_blocking_issues() returns False without CRITICAL."""
        issues = [
            ClassifiedIssue(
                issue_type=IssueType.CITATION_GAP,
                severity=IssueSeverity.WARNING,
                block_id="block-1",
                message="Low citation count",
            ),
            ClassifiedIssue(
                issue_type=IssueType.WEAK_EVIDENCE,
                severity=IssueSeverity.MAJOR,
                block_id="block-2",
                message="Evidence is weak",
            ),
        ]

        assert has_blocking_issues(issues) is False

    def test_has_repairable_issues_with_major(self):
        """Test that has_repairable_issues() detects MAJOR severity."""
        issues = [
            ClassifiedIssue(
                issue_type=IssueType.PLACEHOLDER_CONTENT,
                severity=IssueSeverity.MAJOR,
                block_id="block-1",
                message="Contains placeholder text",
            ),
        ]

        assert has_repairable_issues(issues) is True

    def test_has_repairable_issues_with_warning(self):
        """Test that has_repairable_issues() detects WARNING severity."""
        issues = [
            ClassifiedIssue(
                issue_type=IssueType.CITATION_GAP,
                severity=IssueSeverity.WARNING,
                block_id="block-1",
                message="Citation gap",
            ),
        ]

        assert has_repairable_issues(issues) is True

    def test_has_repairable_issues_without_major_or_warning(self):
        """Test that has_repairable_issues() returns False with only INFO."""
        issues = [
            ClassifiedIssue(
                issue_type=IssueType.UNKNOWN,
                severity=IssueSeverity.INFO,
                block_id="block-1",
                message="Informational note",
            ),
        ]

        assert has_repairable_issues(issues) is False

    def test_has_blocking_issues_empty_list(self):
        """Test has_blocking_issues with empty list."""
        assert has_blocking_issues([]) is False

    def test_has_repairable_issues_empty_list(self):
        """Test has_repairable_issues with empty list."""
        assert has_repairable_issues([]) is False
