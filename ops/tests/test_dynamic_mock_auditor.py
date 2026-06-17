"""
Tests for dynamic content-signal mock auditor.

Verifies that _mock_audit() scores documents based on actual content signals
rather than a length formula, enabling repair-guided content to raise scores.
PHASE 4 validation suite.
"""

import asyncio
import json
import pytest
from ops.docgen.claude_code_auditor import ClaudeCodeAuditor
from ops.docgen.auditor_provider import AuditorProviderConfig


def _run(coro):
    """Run an async coroutine in a sync test."""
    return asyncio.run(coro)


class TestDynamicMockAuditor:
    """Test that _mock_audit() uses content signals, not length."""

    def setup_method(self):
        config = AuditorProviderConfig(provider="mock")
        self.auditor = ClaudeCodeAuditor(config)

    def test_minimal_content_gets_low_overall_score(self):
        """Short plain text with no repair markers gets a low overall score."""
        plain = "This is a short document. It has no owner, no metrics, no citations."
        result = _run(self.auditor.audit(plain, "technical_report"))
        # Minimal content should score well below 0.85
        assert result.overall_score < 0.75, (
            f"Minimal content should score < 0.75, got {result.overall_score}"
        )

    def test_repair_marker_content_scores_higher_than_plain(self):
        """Document with repair-guided markers scores higher than plain equivalent."""
        plain = " ".join(["content"] * 150)

        rich = plain + """

## Phase 1: Foundation
## Phase 2: Integration

Owner: Jane Smith
Responsible: Lead Engineer
Success criteria: 95% uptime achieved
Timeline: Q3 2026
Deadline: 2026-09-30
Action items: Configure monitoring

Data source: Production logs
Verification method: Automated audit trail
Source: Operations database
References: RFC 2119

Metric: 95% availability
Threshold: 500ms latency
Performance: 99.5%

Because this approach enables reliability, therefore we proceed.
As a result, the system achieves target SLA.

```bash
./monitor.sh --threshold 500
```
"""
        plain_result = _run(self.auditor.audit(plain, "technical_report"))
        rich_result = _run(self.auditor.audit(rich, "technical_report"))

        assert rich_result.overall_score > plain_result.overall_score, (
            f"Rich content ({rich_result.overall_score}) should score higher "
            f"than plain ({plain_result.overall_score})"
        )

    def test_dimension_scores_vary_by_content(self):
        """Each dimension score reflects that dimension's specific content signals."""
        # Document with strong actionability signals only
        action_doc = " ".join(["word"] * 100) + """
Owner: Alice
Responsible: Bob
Success criteria: Complete by Friday
Timeline: 3 weeks
Deadline: 2026-07-01
"""
        # Document with strong evidence signals only
        evidence_doc = " ".join(["word"] * 100) + """
Data source: Production monitoring logs
Verification method: Automated audit trail
Source: Operations database
Citation: IEEE Std 1012-2016
References: see appendix
"""
        action_result = _run(self.auditor.audit(action_doc, "technical_report"))
        evidence_result = _run(self.auditor.audit(evidence_doc, "technical_report"))

        action_dim = action_result.dimension_scores
        evidence_dim = evidence_result.dimension_scores

        # actionability document should score higher on actionability than evidence doc
        assert action_dim.get("actionability", 0) > evidence_dim.get("actionability", 0), (
            "Actionability doc should have higher actionability score"
        )
        # evidence document should score higher on evidence than action doc
        assert evidence_dim.get("evidence", 0) > action_dim.get("evidence", 0), (
            "Evidence doc should have higher evidence score"
        )

    def test_placeholder_text_penalizes_completeness(self):
        """[TODO] markers in content lower the completeness dimension score."""
        with_placeholder = " ".join(["word"] * 200) + "\n[TODO] Insert details here\n[TBD] Add later"
        without_placeholder = " ".join(["word"] * 200) + "\nAll sections are complete and finalized."

        result_with = _run(self.auditor.audit(with_placeholder, "technical_report"))
        result_without = _run(self.auditor.audit(without_placeholder, "technical_report"))

        comp_with = result_with.dimension_scores.get("completeness", 1.0)
        comp_without = result_without.dimension_scores.get("completeness", 0.0)

        assert comp_with < comp_without, (
            f"Placeholder text should lower completeness: "
            f"with={comp_with}, without={comp_without}"
        )

    def test_leakage_markers_lower_no_leakage_score(self):
        """Content with IP addresses or 'confidential' lowers no_leakage score."""
        clean_doc = " ".join(["word"] * 100) + "\nAll content is public-facing."
        leaked_doc = " ".join(["word"] * 100) + "\nServer: 192.168.1.1\nconfidential internal use only."

        clean_result = _run(self.auditor.audit(clean_doc, "technical_report"))
        leaked_result = _run(self.auditor.audit(leaked_doc, "technical_report"))

        assert clean_result.dimension_scores.get("no_leakage", 0) > \
               leaked_result.dimension_scores.get("no_leakage", 1.0), (
            "Leakage markers should lower no_leakage score"
        )

    def test_repair_recommendations_name_weakest_dimension(self):
        """repair_recommendations dimension has score <= all other dimension scores."""
        # Plain doc where multiple dimensions will be low
        doc = "Short document. No owner, no metrics, no citations. " * 5
        result = _run(self.auditor.audit(doc, "technical_report"))

        if result.repair_recommendations:
            rec_dim = result.repair_recommendations[0].get("dimension", "")
            dim_scores = result.dimension_scores
            rec_score = dim_scores.get(rec_dim, 1.0)
            # Recommendation dimension must be tied-weakest (score <= all others)
            assert all(score >= rec_score for score in dim_scores.values()), (
                f"Recommendation dimension {rec_dim!r} (score={rec_score}) "
                f"should be the weakest or tied-weakest dimension; "
                f"scores={dim_scores}"
            )
