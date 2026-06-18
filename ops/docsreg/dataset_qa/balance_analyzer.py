"""PHASE 9 Balance Analyzer — checks dataset distribution across key dimensions."""
from collections import Counter
from typing import Dict, List

from ops.docsreg.dataset_qa.models import (
    TrainingExample,
    BalanceBucket,
    BalanceReport,
)


# Minimum requirements
MIN_EXAMPLES_PER_FAILURE_CLASS = 5
MIN_EXAMPLES_PER_SKILL_ID = 3
MAX_FAILURE_CLASS_SHARE = 0.40  # No failure_class > 40% of dataset


def _quality_delta_bucket(delta: float) -> str:
    """Classify quality delta into buckets."""
    if delta <= 0:
        return "no_improvement"
    if delta < 0.05:
        return "marginal (0-5%)"
    if delta < 0.10:
        return "moderate (5-10%)"
    if delta < 0.20:
        return "good (10-20%)"
    return "excellent (>20%)"


def _retention_bucket(rate: float) -> str:
    """Classify retention rate into buckets."""
    if rate < 0.95:
        return "low (<95%)"
    if rate < 0.98:
        return "moderate (95-98%)"
    if rate < 0.99:
        return "high (98-99%)"
    return "excellent (>=99%)"


def _counter_to_buckets(counter: Counter, total: int) -> List[BalanceBucket]:
    """Convert a Counter to BalanceBucket list."""
    return [
        BalanceBucket(
            key=str(key),
            count=count,
            percentage=round(count / total * 100, 1) if total > 0 else 0.0,
        )
        for key, count in counter.most_common()
    ]


class BalanceAnalyzer:
    """Analyzes dataset balance across multiple dimensions.

    Checks:
    - At least 5 examples per failure_class
    - At least 3 examples per skill_id
    - No failure_class occupies > 40% of dataset
    - BLOCKED and ADVISORY cases excluded from training set
    """

    def analyze(self, examples: List[TrainingExample]) -> BalanceReport:
        """Analyze balance of a dataset."""
        if not examples:
            return BalanceReport(total_examples=0, passes_balance_gate=True)

        total = len(examples)
        violations: List[str] = []

        # Count by dimensions
        archetype_counts = Counter(ex.archetype for ex in examples)
        failure_class_counts = Counter(ex.failure_class for ex in examples)
        skill_id_counts = Counter(ex.skill_id for ex in examples)
        verdict_counts = Counter(ex.repair_verdict for ex in examples)
        quality_delta_counts = Counter(_quality_delta_bucket(ex.quality_delta) for ex in examples)
        retention_counts = Counter(_retention_bucket(ex.data_retention_rate) for ex in examples)

        # Check minimum examples per failure_class
        for fc, count in failure_class_counts.items():
            if count < MIN_EXAMPLES_PER_FAILURE_CLASS:
                violations.append(
                    f"failure_class '{fc}' has {count} examples (minimum: {MIN_EXAMPLES_PER_FAILURE_CLASS})"
                )

        # Check minimum examples per skill_id
        for sid, count in skill_id_counts.items():
            if count < MIN_EXAMPLES_PER_SKILL_ID:
                violations.append(
                    f"skill_id '{sid}' has {count} examples (minimum: {MIN_EXAMPLES_PER_SKILL_ID})"
                )

        # Check max share per failure_class
        for fc, count in failure_class_counts.items():
            share = count / total
            if share > MAX_FAILURE_CLASS_SHARE:
                violations.append(
                    f"failure_class '{fc}' occupies {share:.1%} of dataset (maximum: {MAX_FAILURE_CLASS_SHARE:.0%})"
                )

        # Check no BLOCKED/ADVISORY in training set
        for verdict in ["BLOCKED", "ADVISORY"]:
            if verdict_counts.get(verdict, 0) > 0:
                violations.append(
                    f"{verdict_counts[verdict]} examples with repair_verdict={verdict} in training set"
                )

        return BalanceReport(
            total_examples=total,
            by_archetype=_counter_to_buckets(archetype_counts, total),
            by_failure_class=_counter_to_buckets(failure_class_counts, total),
            by_skill_id=_counter_to_buckets(skill_id_counts, total),
            by_verdict=_counter_to_buckets(verdict_counts, total),
            by_quality_delta_bucket=_counter_to_buckets(quality_delta_counts, total),
            by_retention_bucket=_counter_to_buckets(retention_counts, total),
            violations=violations,
            passes_balance_gate=len(violations) == 0,
        )
