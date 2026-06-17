"""
Tests for training dataset builder validation and storage.

Validates quality improvement checks, deduplication, JSONL append, and
acceptance criteria for training pair capture.
"""

import json
import pytest
from pathlib import Path

from ops.docgen.training_dataset_builder import (
    TrainingPairCandidate,
    TrainingDatasetBuilder,
    stable_hash,
)


class TestStableHash:
    """Test deterministic hashing for deduplication."""

    def test_stable_hash_dict_is_deterministic(self):
        """Test that stable_hash returns same hash for same dict content."""
        payload1 = {"before": "old text", "after": "new text", "run_id": "run-1"}
        payload2 = {"before": "old text", "after": "new text", "run_id": "run-1"}

        hash1 = stable_hash(payload1)
        hash2 = stable_hash(payload2)

        assert hash1 == hash2

    def test_stable_hash_dict_order_independent(self):
        """Test that stable_hash is independent of dict key order."""
        payload1 = {"after": "new text", "before": "old text", "run_id": "run-1"}
        payload2 = {"before": "old text", "after": "new text", "run_id": "run-1"}

        hash1 = stable_hash(payload1)
        hash2 = stable_hash(payload2)

        assert hash1 == hash2

    def test_stable_hash_string(self):
        """Test that stable_hash works with strings."""
        text = "repair instruction for document"

        hash1 = stable_hash(text)
        hash2 = stable_hash(text)

        assert hash1 == hash2
        assert isinstance(hash1, str)
        assert len(hash1) == 64  # SHA256 hex digest length

    def test_stable_hash_different_content_different_hash(self):
        """Test that different content produces different hashes."""
        payload1 = {"before": "text A", "after": "text B"}
        payload2 = {"before": "text A", "after": "text C"}

        hash1 = stable_hash(payload1)
        hash2 = stable_hash(payload2)

        assert hash1 != hash2


class TestTrainingPairCandidate:
    """Test training pair candidate dataclass."""

    def test_training_pair_candidate_creates(self):
        """Test that TrainingPairCandidate initializes with all fields."""
        candidate = TrainingPairCandidate(
            run_id="run-1",
            document_type="technical_report",
            block_id="block-42",
            issue_type="MISSING_REQUIRED_SECTION",
            severity="major",
            before="Old text without executive summary",
            after="New text with executive summary included",
            repair_instruction="Add executive summary at start of document",
            quality_score_before=0.72,
            quality_score_after=0.85,
        )

        assert candidate.run_id == "run-1"
        assert candidate.document_type == "technical_report"
        assert candidate.severity == "major"
        assert candidate.quality_score_before == 0.72
        assert candidate.quality_score_after == 0.85
        assert candidate.accepted is False
        assert candidate.rejection_reason is None

    def test_training_pair_candidate_is_frozen(self):
        """Test that TrainingPairCandidate is immutable."""
        candidate = TrainingPairCandidate(
            run_id="run-2",
            document_type="audit_report",
            block_id="block-1",
            issue_type="WEAK_EVIDENCE",
            severity="major",
            before="Weak evidence",
            after="Strong evidence",
            repair_instruction="Strengthen evidence",
            quality_score_before=0.60,
            quality_score_after=0.80,
        )

        with pytest.raises(AttributeError):
            candidate.run_id = "run-3"


class TestTrainingDatasetBuilder:
    """Test training dataset builder validation and storage."""

    def test_training_dataset_builder_creates_output_dir(self, tmp_path):
        """Test that builder creates parent directories for output file."""
        output_path = tmp_path / "training_data" / "dataset.jsonl"

        builder = TrainingDatasetBuilder(output_path)

        assert output_path.parent.exists()

    def test_should_accept_pair_accepts_improved_pair(self):
        """Test that valid improvement is accepted."""
        builder = TrainingDatasetBuilder(Path("/tmp/dataset.jsonl"))

        candidate = TrainingPairCandidate(
            run_id="run-1",
            document_type="technical_report",
            block_id="block-1",
            issue_type="MISSING_REQUIRED_SECTION",
            severity="major",
            before="Old text",
            after="Better text with new section",
            repair_instruction="Add missing section",
            quality_score_before=0.70,
            quality_score_after=0.85,
        )

        accepted, reason = builder.should_accept_pair(candidate)

        assert accepted is True
        assert reason is None

    def test_should_accept_pair_rejects_empty_content(self):
        """Test that empty content is rejected."""
        builder = TrainingDatasetBuilder(Path("/tmp/dataset.jsonl"))

        candidate = TrainingPairCandidate(
            run_id="run-1",
            document_type="technical_report",
            block_id="block-1",
            issue_type="TEST",
            severity="warning",
            before="",
            after="Some text",
            repair_instruction="Test",
            quality_score_before=0.5,
            quality_score_after=0.6,
        )

        accepted, reason = builder.should_accept_pair(candidate)

        assert accepted is False
        assert "empty" in reason.lower()

    def test_should_accept_pair_rejects_identical_content(self):
        """Test that identical before/after is rejected."""
        builder = TrainingDatasetBuilder(Path("/tmp/dataset.jsonl"))

        candidate = TrainingPairCandidate(
            run_id="run-1",
            document_type="technical_report",
            block_id="block-1",
            issue_type="TEST",
            severity="warning",
            before="Same text",
            after="Same text",
            repair_instruction="No change",
            quality_score_before=0.5,
            quality_score_after=0.5,
        )

        accepted, reason = builder.should_accept_pair(candidate)

        assert accepted is False
        assert "identical" in reason.lower()

    def test_should_accept_pair_rejects_no_improvement(self):
        """Test that no quality improvement is rejected."""
        builder = TrainingDatasetBuilder(Path("/tmp/dataset.jsonl"))

        candidate = TrainingPairCandidate(
            run_id="run-1",
            document_type="technical_report",
            block_id="block-1",
            issue_type="TEST",
            severity="warning",
            before="Old text",
            after="Different text",
            repair_instruction="Change",
            quality_score_before=0.75,
            quality_score_after=0.75,
        )

        accepted, reason = builder.should_accept_pair(candidate)

        assert accepted is False
        assert "improvement" in reason.lower()

    def test_should_accept_pair_rejects_poor_severity(self):
        """Test that INFO and CRITICAL severities are rejected."""
        builder = TrainingDatasetBuilder(Path("/tmp/dataset.jsonl"))

        # Test INFO
        candidate_info = TrainingPairCandidate(
            run_id="run-1",
            document_type="technical_report",
            block_id="block-1",
            issue_type="TEST",
            severity="info",
            before="Old",
            after="New improved text",
            repair_instruction="Test",
            quality_score_before=0.5,
            quality_score_after=0.7,
        )

        accepted, reason = builder.should_accept_pair(candidate_info)
        assert accepted is False
        assert "severity" in reason.lower()

        # Test CRITICAL
        candidate_critical = TrainingPairCandidate(
            run_id="run-1",
            document_type="technical_report",
            block_id="block-1",
            issue_type="TEST",
            severity="critical",
            before="Old",
            after="New improved text",
            repair_instruction="Test",
            quality_score_before=0.5,
            quality_score_after=0.7,
        )

        accepted, reason = builder.should_accept_pair(candidate_critical)
        assert accepted is False
        assert "severity" in reason.lower()

    def test_should_accept_pair_rejects_small_improvement_delta(self):
        """Test that small improvement (< 0.01) is rejected."""
        builder = TrainingDatasetBuilder(Path("/tmp/dataset.jsonl"))

        candidate = TrainingPairCandidate(
            run_id="run-1",
            document_type="technical_report",
            block_id="block-1",
            issue_type="TEST",
            severity="major",
            before="Old text",
            after="Slightly modified text",
            repair_instruction="Minor change",
            quality_score_before=0.50,
            quality_score_after=0.505,  # Only 0.005 delta
        )

        accepted, reason = builder.should_accept_pair(candidate)

        assert accepted is False
        assert "delta" in reason.lower()

    def test_append_candidate_writes_accepted_pair_to_jsonl(self, tmp_path):
        """Test that accepted pair is appended to JSONL file."""
        output_path = tmp_path / "dataset.jsonl"
        builder = TrainingDatasetBuilder(output_path)

        candidate = TrainingPairCandidate(
            run_id="run-1",
            document_type="technical_report",
            block_id="block-1",
            issue_type="MISSING_REQUIRED_SECTION",
            severity="major",
            before="Without summary",
            after="With executive summary",
            repair_instruction="Add summary",
            quality_score_before=0.70,
            quality_score_after=0.88,
        )

        result = builder.append_candidate(candidate)

        assert result["accepted"] is True
        assert result["rejection_reason"] is None
        assert "hash" in result
        assert output_path.exists()

        # Verify content was written
        with open(output_path) as f:
            lines = f.readlines()

        assert len(lines) == 1
        pair_data = json.loads(lines[0])
        assert pair_data["accepted"] is True
        assert pair_data["before"] == "Without summary"
        assert pair_data["after"] == "With executive summary"

    def test_append_candidate_rejects_rejected_pair(self, tmp_path):
        """Test that rejected pair is NOT appended to JSONL file."""
        output_path = tmp_path / "dataset.jsonl"
        builder = TrainingDatasetBuilder(output_path)

        candidate = TrainingPairCandidate(
            run_id="run-1",
            document_type="technical_report",
            block_id="block-1",
            issue_type="TEST",
            severity="warning",
            before="Old",
            after="New",
            repair_instruction="Test",
            quality_score_before=0.7,
            quality_score_after=0.7,  # No improvement
        )

        result = builder.append_candidate(candidate)

        assert result["accepted"] is False
        assert "improvement" in result["rejection_reason"].lower()

        # Verify file was NOT created (or is empty)
        if output_path.exists():
            with open(output_path) as f:
                lines = f.readlines()
            assert len(lines) == 0

    def test_count_accepted_returns_zero_for_missing_file(self, tmp_path):
        """Test that count_accepted() returns 0 for missing file."""
        output_path = tmp_path / "nonexistent.jsonl"
        builder = TrainingDatasetBuilder(output_path)

        count = builder.count_accepted()

        assert count == 0

    def test_count_accepted_counts_accepted_pairs(self, tmp_path):
        """Test that count_accepted() counts only accepted=True pairs."""
        output_path = tmp_path / "dataset.jsonl"
        builder = TrainingDatasetBuilder(output_path)

        # Add multiple pairs
        for i in range(3):
            candidate = TrainingPairCandidate(
                run_id=f"run-{i}",
                document_type="technical_report",
                block_id=f"block-{i}",
                issue_type="TEST",
                severity="major",
                before=f"Old text {i}",
                after=f"New improved text {i}",
                repair_instruction=f"Repair {i}",
                quality_score_before=0.60 + (i * 0.05),
                quality_score_after=0.80 + (i * 0.05),
            )
            builder.append_candidate(candidate)

        count = builder.count_accepted()

        assert count == 3

    def test_count_accepted_skips_malformed_json(self, tmp_path):
        """Test that count_accepted() gracefully handles malformed JSON."""
        output_path = tmp_path / "dataset.jsonl"
        builder = TrainingDatasetBuilder(output_path)

        # Write a mix of valid and invalid JSON
        with open(output_path, "w") as f:
            f.write('{"accepted": true, "before": "text"}\n')
            f.write("this is not valid json\n")
            f.write('{"accepted": true, "before": "text2"}\n')

        count = builder.count_accepted()

        # Should count only valid JSON with accepted=true
        assert count == 2
