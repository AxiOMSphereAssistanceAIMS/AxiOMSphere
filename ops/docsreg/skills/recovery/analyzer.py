"""PHASE 8 Recovery Analyzer — diagnoses retention failures and proposes recovery strategies.

Given blocked skills from Phase 7, the analyzer:
1. Identifies which test cases caused the BLOCKED verdict
2. Classifies the type of data loss (sections, fields, references, mixed)
3. Determines root cause and severity
4. Proposes the most appropriate recovery strategy
"""
from typing import Dict, List

from ops.docsreg.skills.testing.models import (
    SkillName,
    SkillSuiteResult,
    SkillVerdict,
    DataRetentionStatus,
    SkillTestCase,
)
from ops.docsreg.skills.recovery.models import (
    LossCategory,
    RecoveryStrategy,
    RetentionDiagnosis,
    RecoveryProposal,
)


# Strategy selection rules: map loss category to best recovery strategy
_STRATEGY_MAP: Dict[LossCategory, RecoveryStrategy] = {
    LossCategory.SECTION_LOSS: RecoveryStrategy.SECTION_LEVEL_DIFF,
    LossCategory.FIELD_LOSS: RecoveryStrategy.FIELD_MERGE_BACK,
    LossCategory.REFERENCE_LOSS: RecoveryStrategy.REFERENCE_REBIND,
    LossCategory.MIXED_LOSS: RecoveryStrategy.PRESERVE_BEFORE_REPAIR,
}

# Severity thresholds
_SEVERITY_CRITICAL = 3.0
_SEVERITY_MODERATE = 2.0


class RecoveryAnalyzer:
    """Analyzes blocked skills to diagnose retention failures and propose recovery."""

    def __init__(self, skill_results: Dict[SkillName, SkillSuiteResult]):
        self.skill_results = skill_results

    def get_blocked_skills(self) -> List[SkillName]:
        """Return list of skills with BLOCKED verdict."""
        return [
            skill for skill, result in self.skill_results.items()
            if result.overall_verdict == SkillVerdict.BLOCKED
        ]

    def get_blocked_cases(self, skill: SkillName) -> List[SkillTestCase]:
        """Return blocked test cases for a specific skill."""
        result = self.skill_results.get(skill)
        if not result:
            return []
        return [
            case for case in result.cases
            if case.retention_report.status == DataRetentionStatus.FAIL
        ]

    def diagnose_case(self, case: SkillTestCase) -> RetentionDiagnosis:
        """Diagnose a single blocked test case.

        Examines what was lost and classifies the failure.
        """
        report = case.retention_report
        sections = report.sections_lost
        fields = report.fields_lost
        references = report.references_lost

        loss_category = self._classify_loss(sections, fields, references)
        severity = self._assess_severity(report.token_loss_percentage)
        root_cause = self._determine_root_cause(case, loss_category)

        return RetentionDiagnosis(
            skill_name=case.skill_name,
            test_case_id=case.test_case_id,
            original_loss_pct=report.token_loss_percentage,
            loss_category=loss_category,
            sections_lost=list(sections),
            fields_lost=list(fields),
            references_lost=list(references),
            root_cause=root_cause,
            severity=severity,
        )

    def diagnose_skill(self, skill: SkillName) -> List[RetentionDiagnosis]:
        """Diagnose all blocked cases for a skill."""
        blocked_cases = self.get_blocked_cases(skill)
        return [self.diagnose_case(case) for case in blocked_cases]

    def propose_recovery(self, diagnosis: RetentionDiagnosis) -> RecoveryProposal:
        """Propose a recovery strategy based on diagnosis."""
        strategy = _STRATEGY_MAP.get(
            diagnosis.loss_category,
            RecoveryStrategy.CONSERVATIVE_REPAIR,
        )

        # For high-loss scenarios, prefer chunked repair
        if diagnosis.original_loss_pct > _SEVERITY_CRITICAL:
            strategy = RecoveryStrategy.CHUNKED_REPAIR

        rationale = self._build_rationale(diagnosis, strategy)
        expected_reduction = self._estimate_reduction(diagnosis, strategy)
        estimated_new_loss = max(0.0, diagnosis.original_loss_pct - expected_reduction)
        confidence = self._estimate_confidence(diagnosis, strategy)

        return RecoveryProposal(
            skill_name=diagnosis.skill_name,
            test_case_id=diagnosis.test_case_id,
            diagnosis=diagnosis,
            strategy=strategy,
            rationale=rationale,
            expected_loss_reduction_pct=expected_reduction,
            estimated_new_loss_pct=round(estimated_new_loss, 2),
            confidence=confidence,
        )

    def analyze_all_blocked(self) -> List[RecoveryProposal]:
        """Analyze all blocked skills and produce proposals."""
        proposals = []
        for skill in self.get_blocked_skills():
            diagnoses = self.diagnose_skill(skill)
            for diag in diagnoses:
                proposals.append(self.propose_recovery(diag))
        return proposals

    def _classify_loss(
        self,
        sections: List[str],
        fields: List[str],
        references: List[str],
    ) -> LossCategory:
        """Classify the type of data loss."""
        has_sections = len(sections) > 0
        has_fields = len(fields) > 0
        has_references = len(references) > 0

        categories_present = sum([has_sections, has_fields, has_references])

        if categories_present >= 2:
            return LossCategory.MIXED_LOSS
        if has_sections:
            return LossCategory.SECTION_LOSS
        if has_fields:
            return LossCategory.FIELD_LOSS
        if has_references:
            return LossCategory.REFERENCE_LOSS

        # Default: if nothing specific detected, treat as section loss
        return LossCategory.SECTION_LOSS

    def _assess_severity(self, loss_pct: float) -> str:
        """Assess severity of retention failure."""
        if loss_pct > _SEVERITY_CRITICAL:
            return "critical"
        if loss_pct > _SEVERITY_MODERATE:
            return "moderate"
        return "marginal"

    def _determine_root_cause(
        self,
        case: SkillTestCase,
        loss_category: LossCategory,
    ) -> str:
        """Determine likely root cause based on case data and loss category."""
        skill = case.skill_name
        loss_pct = case.retention_report.token_loss_percentage

        causes = {
            SkillName.FIX_TIMEOUT: (
                f"Timeout retry for {case.test_case_id} dropped {loss_pct:.1f}% "
                f"of tokens during content reconstruction after failed API call"
            ),
            SkillName.FIX_STRUCTURE: (
                f"Structural repair for {case.test_case_id} removed {loss_pct:.1f}% "
                f"of tokens while normalizing document hierarchy"
            ),
            SkillName.FIX_POLICY_VIOLATION: (
                f"Policy compliance fix for {case.test_case_id} stripped {loss_pct:.1f}% "
                f"of tokens when removing non-compliant content"
            ),
            SkillName.FIX_QUALITY_GATE: (
                f"Quality gate remediation for {case.test_case_id} lost {loss_pct:.1f}% "
                f"of tokens during quality-driven content rewrite"
            ),
            SkillName.FIX_DATA_LOSS: (
                f"Data loss recovery for {case.test_case_id} could not restore {loss_pct:.1f}% "
                f"of tokens from partial corruption"
            ),
            SkillName.FIX_RESOURCE_EXHAUSTION: (
                f"Resource exhaustion handler for {case.test_case_id} truncated {loss_pct:.1f}% "
                f"of tokens when reducing document size under memory pressure"
            ),
        }
        return causes.get(skill, f"Unknown root cause for {skill.value}")

    def _build_rationale(
        self,
        diagnosis: RetentionDiagnosis,
        strategy: RecoveryStrategy,
    ) -> str:
        """Build explanation for why this strategy was selected."""
        rationales = {
            RecoveryStrategy.SECTION_LEVEL_DIFF: (
                f"Section-level diff repair will preserve original sections and only "
                f"apply targeted fixes to damaged areas, preventing the {diagnosis.original_loss_pct:.1f}% "
                f"wholesale section loss"
            ),
            RecoveryStrategy.FIELD_MERGE_BACK: (
                f"Field merge-back will reinsert the {len(diagnosis.fields_lost)} lost fields "
                f"from the original document into the repaired output"
            ),
            RecoveryStrategy.REFERENCE_REBIND: (
                f"Reference rebinding will restore the {len(diagnosis.references_lost)} lost references "
                f"by cross-matching with the original document's reference table"
            ),
            RecoveryStrategy.PRESERVE_BEFORE_REPAIR: (
                f"Pre-repair snapshot preservation will checkpoint the document before repair, "
                f"then merge back any content lost during the {diagnosis.loss_category.value} "
                f"failure mode"
            ),
            RecoveryStrategy.CHUNKED_REPAIR: (
                f"Chunked repair splits the document into independent sections and repairs "
                f"each chunk separately, preventing cascading loss from the critical "
                f"{diagnosis.original_loss_pct:.1f}% failure"
            ),
            RecoveryStrategy.CONSERVATIVE_REPAIR: (
                f"Conservative repair applies minimal changes, preserving maximum content "
                f"while addressing only the specific defect"
            ),
        }
        return rationales.get(strategy, "Strategy selected based on failure analysis")

    def _estimate_reduction(
        self,
        diagnosis: RetentionDiagnosis,
        strategy: RecoveryStrategy,
    ) -> float:
        """Estimate how much the strategy will reduce token loss."""
        base = diagnosis.original_loss_pct

        # Strategy effectiveness factors
        effectiveness = {
            RecoveryStrategy.SECTION_LEVEL_DIFF: 0.85,
            RecoveryStrategy.FIELD_MERGE_BACK: 0.90,
            RecoveryStrategy.REFERENCE_REBIND: 0.80,
            RecoveryStrategy.PRESERVE_BEFORE_REPAIR: 0.75,
            RecoveryStrategy.CHUNKED_REPAIR: 0.70,
            RecoveryStrategy.CONSERVATIVE_REPAIR: 0.60,
        }
        factor = effectiveness.get(strategy, 0.50)

        return round(base * factor, 2)

    def _estimate_confidence(
        self,
        diagnosis: RetentionDiagnosis,
        strategy: RecoveryStrategy,
    ) -> float:
        """Estimate confidence that the strategy will resolve the issue."""
        # Higher confidence for targeted strategies on specific loss types
        if diagnosis.loss_category == LossCategory.SECTION_LOSS and strategy == RecoveryStrategy.SECTION_LEVEL_DIFF:
            return 0.92
        if diagnosis.loss_category == LossCategory.FIELD_LOSS and strategy == RecoveryStrategy.FIELD_MERGE_BACK:
            return 0.95
        if diagnosis.loss_category == LossCategory.REFERENCE_LOSS and strategy == RecoveryStrategy.REFERENCE_REBIND:
            return 0.88
        if strategy == RecoveryStrategy.CHUNKED_REPAIR:
            return 0.78
        if strategy == RecoveryStrategy.PRESERVE_BEFORE_REPAIR:
            return 0.85
        return 0.70
