"""Data retention validation with multi-dimensional tracking.

Hard thresholds: PASS ≤1.5%, ADVISORY 1.5-2.0%, FAIL >2.0%
Required element loss (sections, fields, references, tables, links) = instant FAIL
"""
import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RetentionVerdict(StrEnum):
    """Retention validation verdict."""

    PASS = "pass"
    ADVISORY = "advisory"
    FAIL = "fail"


@dataclass(frozen=True)
class DocumentSnapshot:
    """Immutable document state snapshot."""

    content: str
    sections: list[str] = field(default_factory=list)
    required_fields: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    semantic_claims: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DataRetentionReport:
    """Immutable retention validation report."""

    verdict: RetentionVerdict
    sha256_before: str
    sha256_after: str
    token_estimate_before: int
    token_estimate_after: int
    token_preservation_rate: float
    section_preservation_rate: float
    required_field_preservation_rate: float
    reference_preservation_rate: float
    table_preservation_rate: float
    link_preservation_rate: float
    semantic_claim_preservation_rate: float
    token_loss_percentage: float
    lost_sections: list[str] = field(default_factory=list)
    lost_required_fields: list[str] = field(default_factory=list)
    lost_references: list[str] = field(default_factory=list)
    lost_tables: list[str] = field(default_factory=list)
    lost_links: list[str] = field(default_factory=list)
    lost_semantic_claims: list[str] = field(default_factory=list)
    reasons: tuple[str, ...] = field(default_factory=tuple)


class DataRetentionValidator:
    """Validate data retention across repair cycle."""

    PASS_MAX_LOSS_PERCENTAGE = 1.5
    ADVISORY_MAX_LOSS_PERCENTAGE = 2.0

    @staticmethod
    def _sha256_text(text: str) -> str:
        """Calculate SHA256 hash of text."""
        return hashlib.sha256(text.encode()).hexdigest()

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize text for comparison."""
        return re.sub(r'\s+', ' ', text.strip())

    @staticmethod
    def _token_estimate(text: str) -> int:
        """Rough token count estimate (words * 1.3)."""
        words = len(text.split())
        return max(1, int(words * 1.3))

    @staticmethod
    def _preservation(before: list[str], after: list[str]) -> tuple[float, list[str]]:
        """Calculate preservation rate and find lost items."""
        if not before:
            return 100.0, []

        lost = [item for item in before if item not in after]
        rate = ((len(before) - len(lost)) / len(before)) * 100
        return rate, lost

    def validate(
        self, before: DocumentSnapshot, after: DocumentSnapshot
    ) -> DataRetentionReport:
        """Validate data retention from before to after snapshot."""
        reasons = []

        # Calculate hashes
        sha256_before = self._sha256_text(before.content)
        sha256_after = self._sha256_text(after.content)

        # Token estimates
        token_before = self._token_estimate(before.content)
        token_after = self._token_estimate(after.content)
        token_loss = max(0, token_before - token_after)
        token_loss_pct = (
            (token_loss / token_before * 100) if token_before > 0 else 0.0
        )

        # Preservation rates
        token_pres = ((token_after / token_before) * 100) if token_before > 0 else 0.0
        section_pres, lost_sections = self._preservation(
            before.sections, after.sections
        )
        field_pres, lost_fields = self._preservation(
            before.required_fields, after.required_fields
        )
        ref_pres, lost_refs = self._preservation(before.references, after.references)
        table_pres, lost_tables = self._preservation(before.tables, after.tables)
        link_pres, lost_links = self._preservation(before.links, after.links)
        claim_pres, lost_claims = self._preservation(
            before.semantic_claims, after.semantic_claims
        )

        # Hard failures: any required element lost
        verdict = RetentionVerdict.PASS
        if lost_sections:
            reasons = (
                *reasons,
                f"Lost required sections: {', '.join(lost_sections)}",
            )
            verdict = RetentionVerdict.FAIL

        if lost_fields:
            reasons = (*reasons, f"Lost required fields: {', '.join(lost_fields)}")
            verdict = RetentionVerdict.FAIL

        if lost_refs:
            reasons = (*reasons, f"Lost references: {', '.join(lost_refs)}")
            verdict = RetentionVerdict.FAIL

        if lost_tables:
            reasons = (*reasons, f"Lost tables: {', '.join(lost_tables)}")
            verdict = RetentionVerdict.FAIL

        if lost_links:
            reasons = (*reasons, f"Lost links: {', '.join(lost_links)}")
            verdict = RetentionVerdict.FAIL

        if lost_claims:
            reasons = (*reasons, f"Lost semantic claims: {', '.join(lost_claims)}")
            verdict = RetentionVerdict.FAIL

        # Token percentage threshold (only if no hard failures yet)
        if verdict != RetentionVerdict.FAIL:
            if token_loss_pct > self.ADVISORY_MAX_LOSS_PERCENTAGE:
                verdict = RetentionVerdict.FAIL
                reasons = (
                    *reasons,
                    f"Token loss {token_loss_pct:.2f}% exceeds limit {self.ADVISORY_MAX_LOSS_PERCENTAGE}%",
                )
            elif token_loss_pct > self.PASS_MAX_LOSS_PERCENTAGE:
                verdict = RetentionVerdict.ADVISORY
                reasons = (
                    *reasons,
                    f"Token loss {token_loss_pct:.2f}% in advisory range {self.PASS_MAX_LOSS_PERCENTAGE}%-{self.ADVISORY_MAX_LOSS_PERCENTAGE}%",
                )

        return DataRetentionReport(
            verdict=verdict,
            sha256_before=sha256_before,
            sha256_after=sha256_after,
            token_estimate_before=token_before,
            token_estimate_after=token_after,
            token_preservation_rate=token_pres,
            section_preservation_rate=section_pres,
            required_field_preservation_rate=field_pres,
            reference_preservation_rate=ref_pres,
            table_preservation_rate=table_pres,
            link_preservation_rate=link_pres,
            semantic_claim_preservation_rate=claim_pres,
            token_loss_percentage=token_loss_pct,
            lost_sections=lost_sections,
            lost_required_fields=lost_fields,
            lost_references=lost_refs,
            lost_tables=lost_tables,
            lost_links=lost_links,
            lost_semantic_claims=lost_claims,
            reasons=reasons,
        )
