"""Tests for PHASE 9 Deduplicator."""
import pytest

from ops.docsreg.dataset_qa.deduplicator import (
    Deduplicator,
    _normalize_text,
    _jaccard_similarity,
    NEAR_DUPLICATE_THRESHOLD,
)
from ops.docsreg.dataset_qa.models import TrainingExample


def _make_example(
    example_id: str = "ex1",
    source_text: str = "source",
    repaired_text: str = "repaired",
    quality_delta: float = 0.25,
    data_retention_rate: float = 0.99,
    data_loss_percentage: float = 1.0,
    skill_version: str = "v1",
    **overrides,
) -> TrainingExample:
    import hashlib
    in_sha = hashlib.sha256(source_text.encode()).hexdigest()
    out_sha = hashlib.sha256(repaired_text.encode()).hexdigest()
    defaults = dict(
        example_id=example_id,
        document_id="doc1",
        archetype="technical_report",
        failure_class="missing_header",
        skill_id="fix_structure",
        skill_version=skill_version,
        source_text=source_text,
        failure_context="ctx",
        repair_instruction="fix",
        repaired_text=repaired_text,
        quality_before=0.70,
        quality_after=0.70 + quality_delta,
        quality_delta=quality_delta,
        data_retention_rate=data_retention_rate,
        data_loss_percentage=data_loss_percentage,
        required_field_preservation_rate=1.0,
        section_preservation_rate=0.99,
        retention_verdict="PASS",
        repair_verdict="PROMOTED",
        input_sha256=in_sha,
        output_sha256=out_sha,
        created_at="2026-06-18T12:00:00+00:00",
    )
    defaults.update(overrides)
    return TrainingExample(**defaults)


class TestNormalizeText:
    def test_lowercase(self):
        assert _normalize_text("HELLO World") == "hello world"

    def test_collapse_whitespace(self):
        assert _normalize_text("hello   world\n\tfoo") == "hello world foo"

    def test_unicode_normalization(self):
        # NFKC converts ﬁ to fi
        assert "fi" in _normalize_text("ﬁnd")


class TestJaccardSimilarity:
    def test_identical(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        assert _jaccard_similarity("hello world", "foo bar") == 0.0

    def test_partial_overlap(self):
        sim = _jaccard_similarity("hello world foo", "hello world bar")
        assert 0.0 < sim < 1.0

    def test_both_empty(self):
        assert _jaccard_similarity("", "") == 1.0

    def test_one_empty(self):
        assert _jaccard_similarity("hello", "") == 0.0


class TestDeduplicator:
    def setup_method(self):
        self.dedup = Deduplicator()

    def test_no_duplicates(self):
        examples = [
            _make_example("e1", "src1", "rep1"),
            _make_example("e2", "src2", "rep2"),
        ]
        kept, result = self.dedup.deduplicate(examples)
        assert len(kept) == 2
        assert result.duplicates_removed == 0

    def test_exact_duplicate(self):
        examples = [
            _make_example("e1", "src", "repaired_exact"),
            _make_example("e2", "src", "repaired_exact"),
        ]
        kept, result = self.dedup.deduplicate(examples)
        assert len(kept) == 1
        assert result.exact_duplicates >= 1

    def test_normalized_duplicate(self):
        examples = [
            _make_example("e1", "src1", "Hello World   Foo"),
            _make_example("e2", "src2", "hello world foo"),
        ]
        kept, result = self.dedup.deduplicate(examples)
        assert len(kept) == 1
        assert result.normalized_duplicates >= 1 or result.near_duplicates >= 1

    def test_near_duplicate(self):
        # 100 unique words, variant changes 1 → Jaccard ~0.98 > 0.95
        words = [f"word_{i}" for i in range(100)]
        base = " ".join(words)
        variant = " ".join(words[:-1] + ["replaced_word"])
        examples = [
            _make_example("e1", "s1", base),
            _make_example("e2", "s2", variant),
        ]
        kept, result = self.dedup.deduplicate(examples)
        assert len(kept) == 1

    def test_keeps_better_quality_delta(self):
        examples = [
            _make_example("e1", "s1", "same output text here", quality_delta=0.10),
            _make_example("e2", "s2", "same output text here", quality_delta=0.30),
        ]
        kept, result = self.dedup.deduplicate(examples)
        assert len(kept) == 1
        assert kept[0].quality_delta == 0.30

    def test_keeps_better_retention(self):
        examples = [
            _make_example("e1", "s1", "same output text here", quality_delta=0.20, data_retention_rate=0.98),
            _make_example("e2", "s2", "same output text here", quality_delta=0.20, data_retention_rate=0.995),
        ]
        kept, result = self.dedup.deduplicate(examples)
        assert len(kept) == 1
        assert kept[0].data_retention_rate == 0.995

    def test_keeps_newer_version_on_tie(self):
        examples = [
            _make_example("e1", "s1", "same text", quality_delta=0.20, data_retention_rate=0.99,
                          data_loss_percentage=1.0, skill_version="v1"),
            _make_example("e2", "s2", "same text", quality_delta=0.20, data_retention_rate=0.99,
                          data_loss_percentage=1.0, skill_version="v2"),
        ]
        kept, result = self.dedup.deduplicate(examples)
        assert len(kept) == 1
        assert kept[0].skill_version == "v2"

    def test_empty_input(self):
        kept, result = self.dedup.deduplicate([])
        assert kept == []
        assert result.total_before == 0
        assert result.duplicates_removed == 0

    def test_same_doc_class_output_duplicate(self):
        examples = [
            _make_example("e1", "src_a", "same_output", document_id="docX", failure_class="fc1"),
            _make_example("e2", "src_b", "same_output", document_id="docX", failure_class="fc1"),
        ]
        kept, result = self.dedup.deduplicate(examples)
        assert len(kept) == 1

    def test_result_ids_tracked(self):
        examples = [
            _make_example("e1", "s1", "same output"),
            _make_example("e2", "s2", "same output"),
        ]
        kept, result = self.dedup.deduplicate(examples)
        assert len(result.kept_example_ids) == 1
        assert len(result.removed_example_ids) >= 1
        assert result.kept_example_ids[0] in {"e1", "e2"}

    def test_threshold_configurable(self):
        dedup = Deduplicator(threshold=0.99)
        assert dedup.threshold == 0.99
