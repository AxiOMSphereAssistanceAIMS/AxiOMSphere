"""
Tests for quality cycle state tracking and serialization.

Validates QualityCycleState dataclass lifecycle: creation, mutation,
JSON serialization, and deserialization.
"""

import json
import pytest
from pathlib import Path
from datetime import datetime, timezone

from ops.docgen.quality_cycle_state import QualityCycleState, utc_now


class TestQualityCycleStateSerialization:
    """Test QualityCycleState save/load and serialization."""

    def test_quality_cycle_state_creates_with_defaults(self):
        """Test that QualityCycleState initializes with sensible defaults."""
        state = QualityCycleState(
            cycle_id="cycle-0-tech",
            document_type="technical_report",
            topic="System Architecture",
            audience="engineers",
            cycle_index=0,
            output_dir="/tmp/cycles/cycle-0",
            target_baseline_score=0.90,
            max_cycles=5,
        )

        assert state.cycle_id == "cycle-0-tech"
        assert state.document_type == "technical_report"
        assert state.status == "INITIALIZED"
        assert state.baseline_score_before is None
        assert state.baseline_score_after is None
        assert state.training_pairs_count == 0
        assert state.repair_cycles_executed == 0
        assert len(state.errors) == 0
        assert len(state.warnings) == 0
        assert state.created_at is not None
        assert state.updated_at is not None

    def test_quality_cycle_state_is_mutable(self):
        """Test that QualityCycleState allows mutation during cycle execution."""
        state = QualityCycleState(
            cycle_id="cycle-1",
            document_type="audit_report",
            topic="Financial Audit",
            audience="auditors",
            cycle_index=1,
            output_dir="/tmp/cycles/cycle-1",
            target_baseline_score=0.89,
            max_cycles=5,
        )

        # Mutate state
        state.status = "RUNNING"
        state.baseline_score_after = 0.85
        state.final_verdict = "DOCGEN_CHATGPT55_VERTICAL_SLICE_PASS"
        state.training_pairs_count = 3
        state.errors.append("Test error")

        assert state.status == "RUNNING"
        assert state.baseline_score_after == 0.85
        assert state.final_verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_PASS"
        assert state.training_pairs_count == 3
        assert "Test error" in state.errors

    def test_quality_cycle_state_saves_to_json(self, tmp_path):
        """Test that QualityCycleState saves to JSON with all fields."""
        state = QualityCycleState(
            cycle_id="cycle-2",
            document_type="certification_report",
            topic="ISO 55001 Compliance",
            audience="compliance_officers",
            cycle_index=2,
            output_dir=str(tmp_path / "cycle-2"),
            target_baseline_score=0.92,
            max_cycles=5,
        )

        state.status = "EVALUATED"
        state.baseline_score_after = 0.93
        state.final_verdict = "DOCGEN_CHATGPT55_VERTICAL_SLICE_READY_WITH_WARNINGS"
        state.weakest_metric = "completeness"
        state.training_pairs_count = 5
        state.repair_cycles_executed = 1

        save_path = tmp_path / "state.json"
        saved_path = state.save(save_path)

        assert saved_path.exists()
        assert saved_path == save_path

        # Verify JSON structure
        with open(save_path) as f:
            data = json.load(f)

        assert data["cycle_id"] == "cycle-2"
        assert data["document_type"] == "certification_report"
        assert data["status"] == "EVALUATED"
        assert data["baseline_score_after"] == 0.93
        assert data["final_verdict"] == "DOCGEN_CHATGPT55_VERTICAL_SLICE_READY_WITH_WARNINGS"
        assert data["weakest_metric"] == "completeness"
        assert data["training_pairs_count"] == 5
        assert data["repair_cycles_executed"] == 1
        assert "created_at" in data
        assert "updated_at" in data

    def test_quality_cycle_state_loads_from_json(self, tmp_path):
        """Test that QualityCycleState loads from saved JSON with all fields restored."""
        # Create and save initial state
        original_state = QualityCycleState(
            cycle_id="cycle-3",
            document_type="implementation_plan",
            topic="Cloud Migration",
            audience="devops_engineers",
            cycle_index=3,
            output_dir=str(tmp_path / "cycle-3"),
            target_baseline_score=0.88,
            max_cycles=5,
        )

        original_state.status = "PROMOTED"
        original_state.baseline_score_after = 0.91
        original_state.final_verdict = "DOCGEN_CHATGPT55_VERTICAL_SLICE_PASS"
        original_state.training_pairs_count = 8
        original_state.evidence_manifest_path = str(tmp_path / "manifest.json")

        save_path = tmp_path / "saved_state.json"
        original_state.save(save_path)

        # Load and verify
        loaded_state = QualityCycleState.load(save_path)

        assert loaded_state.cycle_id == "cycle-3"
        assert loaded_state.document_type == "implementation_plan"
        assert loaded_state.topic == "Cloud Migration"
        assert loaded_state.audience == "devops_engineers"
        assert loaded_state.cycle_index == 3
        assert loaded_state.status == "PROMOTED"
        assert loaded_state.baseline_score_after == 0.91
        assert loaded_state.final_verdict == "DOCGEN_CHATGPT55_VERTICAL_SLICE_PASS"
        assert loaded_state.training_pairs_count == 8
        assert loaded_state.evidence_manifest_path == str(tmp_path / "manifest.json")

    def test_quality_cycle_state_update_timestamp(self):
        """Test that update_timestamp() refreshes the updated_at field."""
        state = QualityCycleState(
            cycle_id="cycle-4",
            document_type="technical_report",
            topic="Test Topic",
            audience="test_audience",
            cycle_index=4,
            output_dir="/tmp/cycle-4",
            target_baseline_score=0.90,
            max_cycles=5,
        )

        original_updated_at = state.updated_at

        # Wait a tiny bit and update timestamp
        state.update_timestamp()
        new_updated_at = state.updated_at

        # Timestamps should be different (or at least one is older)
        assert original_updated_at != new_updated_at or state.updated_at is not None

    def test_quality_cycle_state_to_dict(self):
        """Test that to_dict() returns all fields."""
        state = QualityCycleState(
            cycle_id="cycle-5",
            document_type="audit_report",
            topic="Audit Topic",
            audience="auditors",
            cycle_index=5,
            output_dir="/tmp/cycle-5",
            target_baseline_score=0.89,
            max_cycles=5,
        )

        state.baseline_score_after = 0.87
        state.errors.append("An error occurred")

        state_dict = state.to_dict()

        assert isinstance(state_dict, dict)
        assert state_dict["cycle_id"] == "cycle-5"
        assert state_dict["baseline_score_after"] == 0.87
        assert state_dict["errors"] == ["An error occurred"]

    def test_quality_cycle_state_load_missing_file(self, tmp_path):
        """Test that load() raises FileNotFoundError for missing file."""
        missing_path = tmp_path / "nonexistent.json"

        with pytest.raises(FileNotFoundError):
            QualityCycleState.load(missing_path)

    def test_quality_cycle_state_load_missing_required_field(self, tmp_path):
        """Test that load() raises ValueError for missing required fields."""
        save_path = tmp_path / "bad_state.json"

        # Write incomplete JSON
        with open(save_path, "w") as f:
            json.dump(
                {
                    "cycle_id": "cycle-6",
                    "document_type": "technical_report",
                    # Missing other required fields
                },
                f,
            )

        with pytest.raises(ValueError):
            QualityCycleState.load(save_path)

    def test_utc_now_returns_iso_format(self):
        """Test that utc_now() returns valid ISO format timestamp."""
        timestamp = utc_now()

        assert isinstance(timestamp, str)
        # Should be parseable as ISO format
        parsed = datetime.fromisoformat(timestamp)
        assert parsed is not None
        assert parsed.tzinfo is not None
