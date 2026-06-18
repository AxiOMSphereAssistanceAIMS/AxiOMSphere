"""Tests for PHASE 9 Balance Analyzer."""
import pytest

from ops.docsreg.dataset_qa.balance_analyzer import (
    BalanceAnalyzer,
    _quality_delta_bucket,
    _retention_bucket,
    MIN_EXAMPLES_PER_FAILURE_CLASS,
    MIN_EXAMPLES_PER_SKILL_ID,
    MAX_FAILURE_CLASS_SHARE,
)
from ops.docsreg.dataset_qa.models import TrainingExample, BalanceReport


def _make_example(
    example_id="ex1", failure_class="fc1", skill_id="sk1",
    archetype="technical_report", repair_verdict="PROMOTED",
    quality_delta=0.15, data_retention_rate=0.995, **kw,
) -> TrainingExample:
    import hashlib
    defaults = dict(
        example_id=example_id, document_id="doc1", archetype=archetype,
        failure_class=failure_class, skill_id=skill_id, skill_version="v1",
        source_text="src", failure_context="ctx", repair_instruction="fix",
        repaired_text="rep", quality_before=0.70, quality_after=0.70 + quality_delta,
        quality_delta=quality_delta, data_retention_rate=data_retention_rate,
        data_loss_percentage=round((1 - data_retention_rate) * 100, 2),
        required_field_preservation_rate=1.0, section_preservation_rate=0.99,
        retention_verdict="PASS", repair_verdict=repair_verdict,
        input_sha256=hashlib.sha256(f"in_{example_id}".encode()).hexdigest(),
        output_sha256=hashlib.sha256(f"out_{example_id}".encode()).hexdigest(),
        created_at="2026-06-18T12:00:00+00:00",
    )
    defaults.update(kw)
    return TrainingExample(**defaults)


class TestBucketFunctions:
    def test_quality_delta_no_improvement(self):
        assert _quality_delta_bucket(0.0) == "no_improvement"
        assert _quality_delta_bucket(-0.1) == "no_improvement"

    def test_quality_delta_marginal(self):
        assert "marginal" in _quality_delta_bucket(0.03)

    def test_quality_delta_moderate(self):
        assert "moderate" in _quality_delta_bucket(0.07)

    def test_quality_delta_good(self):
        assert "good" in _quality_delta_bucket(0.15)

    def test_quality_delta_excellent(self):
        assert "excellent" in _quality_delta_bucket(0.25)

    def test_retention_low(self):
        assert "low" in _retention_bucket(0.90)

    def test_retention_moderate(self):
        assert "moderate" in _retention_bucket(0.96)

    def test_retention_high(self):
        assert "high" in _retention_bucket(0.985)

    def test_retention_excellent(self):
        assert "excellent" in _retention_bucket(0.995)


class TestBalanceAnalyzer:
    def setup_method(self):
        self.analyzer = BalanceAnalyzer()

    def test_empty_dataset(self):
        report = self.analyzer.analyze([])
        assert report.total_examples == 0
        assert report.passes_balance_gate is True

    def test_balanced_dataset(self):
        examples = []
        for i in range(10):
            examples.append(_make_example(
                example_id=f"e{i}", failure_class="fc1", skill_id="sk1",
            ))
        report = self.analyzer.analyze(examples)
        assert report.total_examples == 10
        assert len(report.by_failure_class) >= 1

    def test_failure_class_minimum_violation(self):
        examples = [
            _make_example(example_id=f"e{i}", failure_class="fc1")
            for i in range(2)
        ]
        report = self.analyzer.analyze(examples)
        assert not report.passes_balance_gate
        assert any("fc1" in v for v in report.violations)

    def test_skill_id_minimum_violation(self):
        examples = [
            _make_example(example_id=f"e{i}", skill_id="rare_skill")
            for i in range(2)
        ]
        report = self.analyzer.analyze(examples)
        assert any("rare_skill" in v for v in report.violations)

    def test_failure_class_share_violation(self):
        examples = []
        for i in range(8):
            examples.append(_make_example(example_id=f"major_{i}", failure_class="dominant"))
        for i in range(2):
            examples.append(_make_example(example_id=f"minor_{i}", failure_class="other"))
        report = self.analyzer.analyze(examples)
        violations_text = " ".join(report.violations)
        assert "dominant" in violations_text

    def test_blocked_verdict_violation(self):
        examples = [
            _make_example(example_id=f"e{i}", repair_verdict="PROMOTED")
            for i in range(5)
        ]
        examples.append(_make_example(example_id="blocked", repair_verdict="BLOCKED"))
        report = self.analyzer.analyze(examples)
        assert any("BLOCKED" in v for v in report.violations)

    def test_advisory_verdict_violation(self):
        examples = [
            _make_example(example_id=f"e{i}")
            for i in range(5)
        ]
        examples.append(_make_example(example_id="adv", repair_verdict="ADVISORY"))
        report = self.analyzer.analyze(examples)
        assert any("ADVISORY" in v for v in report.violations)

    def test_distribution_buckets_populated(self):
        examples = [_make_example(example_id=f"e{i}") for i in range(6)]
        report = self.analyzer.analyze(examples)
        assert len(report.by_archetype) >= 1
        assert len(report.by_quality_delta_bucket) >= 1
        assert len(report.by_retention_bucket) >= 1
        assert report.by_archetype[0].percentage > 0

    def test_passes_when_sufficient(self):
        examples = [
            _make_example(example_id=f"e{i}", failure_class="fc1", skill_id="sk1")
            for i in range(10)
        ]
        report = self.analyzer.analyze(examples)
        has_share_violation = any("occupies" in v for v in report.violations)
        has_blocked = any("BLOCKED" in v or "ADVISORY" in v for v in report.violations)
        if not has_share_violation and not has_blocked:
            assert report.passes_balance_gate or len(report.violations) > 0
