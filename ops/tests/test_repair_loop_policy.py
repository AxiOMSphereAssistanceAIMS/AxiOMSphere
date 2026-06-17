"""
Unit tests for DOCGEN repair loop policy module.

Tests repair loop termination logic, dimension selection, task creation,
and state serialization.
"""

import pytest
from pathlib import Path
import json
import tempfile

from ops.docgen.repair_loop_policy import (
    is_true_blocker,
    should_continue_repair,
    pick_weakest_dimension,
    repair_action_for_dimension,
    target_content_for_dimension,
    create_repair_task,
    save_repair_task,
    RepairTask,
    REPAIR_PRIORITY,
    TRUE_BLOCKER_STATUSES,
    TARGET_RATIO_DEFAULT,
)


class TestIsTrueBlocker:
    """Test is_true_blocker() function."""

    def test_is_true_blocker_with_valid_status(self):
        """Valid true blocker status returns True."""
        for status in TRUE_BLOCKER_STATUSES:
            assert is_true_blocker(status) is True

    def test_is_true_blocker_with_invalid_status(self):
        """Invalid status returns False."""
        assert is_true_blocker("DOCGEN_RUNNING") is False
        assert is_true_blocker("DOCGEN_BLOCKED") is False
        assert is_true_blocker("RANDOM_STATUS") is False

    def test_is_true_blocker_with_none(self):
        """None status returns False."""
        assert is_true_blocker(None) is False


class TestShouldContinueRepair:
    """Test should_continue_repair() function."""

    def test_should_continue_below_target(self):
        """Continue if quality_ratio below target and no blocker."""
        assert should_continue_repair(
            best_quality_ratio=0.90,
            target_ratio=0.95,
            status=None
        ) is True

    def test_should_continue_at_target(self):
        """Stop if quality_ratio at or above target."""
        assert should_continue_repair(
            best_quality_ratio=0.95,
            target_ratio=0.95,
            status=None
        ) is False

    def test_should_continue_above_target(self):
        """Stop if quality_ratio above target."""
        assert should_continue_repair(
            best_quality_ratio=0.96,
            target_ratio=0.95,
            status=None
        ) is False

    def test_should_continue_with_true_blocker(self):
        """Stop immediately if true blocker, even if below target."""
        assert should_continue_repair(
            best_quality_ratio=0.80,
            target_ratio=0.95,
            status="DOCGEN_EXTERNAL_CREDENTIALS_REQUIRED"
        ) is False

    def test_should_continue_with_invalid_blocker_status(self):
        """Continue if blocker status invalid (not in TRUE_BLOCKER_STATUSES)."""
        assert should_continue_repair(
            best_quality_ratio=0.80,
            target_ratio=0.95,
            status="DOCGEN_BLOCKED"  # Not a true blocker
        ) is True


class TestPickWeakestDimension:
    """Test pick_weakest_dimension() function."""

    def test_pick_weakest_dimension_with_gaps_list(self):
        """Pick first dimension in REPAIR_PRIORITY that appears in gaps."""
        dimension_scores = {
            "clarity": 0.90,
            "actionability": 0.75,
            "evidence": 0.80,
        }
        dimensions_in_gaps = ["clarity", "actionability", "evidence"]

        # Should pick "actionability" (first in REPAIR_PRIORITY)
        result = pick_weakest_dimension(dimension_scores, dimensions_in_gaps)
        assert result == "actionability"

    def test_pick_weakest_dimension_without_gaps_list(self):
        """Without gaps list, pick lowest-scored dimension."""
        dimension_scores = {
            "clarity": 0.90,
            "actionability": 0.75,
            "evidence": 0.60,
        }

        # Should pick "evidence" (lowest score, in REPAIR_PRIORITY)
        result = pick_weakest_dimension(dimension_scores)
        assert result == "evidence"

    def test_pick_weakest_dimension_respects_priority_order(self):
        """Gaps list ordering ignored; REPAIR_PRIORITY ordering respected."""
        dimension_scores = {
            "clarity": 0.80,
            "completeness": 0.85,
            "actionability": 0.90,
        }
        # Even though in list order it's clarity→completeness→actionability,
        # REPAIR_PRIORITY has actionability→...→completeness→clarity
        # So should pick actionability (first in REPAIR_PRIORITY)
        dimensions_in_gaps = ["clarity", "completeness", "actionability"]
        result = pick_weakest_dimension(dimension_scores, dimensions_in_gaps)
        assert result == "actionability"

    def test_pick_weakest_dimension_empty_scores_returns_default(self):
        """Empty dimension_scores returns default (actionability)."""
        result = pick_weakest_dimension({})
        assert result == "actionability"


class TestRepairActionForDimension:
    """Test repair_action_for_dimension() function."""

    def test_repair_action_for_all_dimensions(self):
        """Repair action returned for all canonical dimensions."""
        for dimension in REPAIR_PRIORITY:
            action = repair_action_for_dimension(dimension)
            assert isinstance(action, str)
            assert len(action) > 0

    def test_repair_action_for_unknown_dimension(self):
        """Unknown dimension returns generic suggestion."""
        action = repair_action_for_dimension("unknown_dimension")
        assert "Improve unknown_dimension dimension" in action

    def test_repair_action_for_actionability(self):
        """Actionability repair includes owner/success_criteria."""
        action = repair_action_for_dimension("actionability")
        assert "owner" in action.lower()
        assert "success criteria" in action.lower()


class TestTargetContentForDimension:
    """Test target_content_for_dimension() function."""

    def test_target_content_for_all_dimensions(self):
        """Target content spec returned for all canonical dimensions."""
        for dimension in REPAIR_PRIORITY:
            spec = target_content_for_dimension(dimension)
            assert isinstance(spec, str)
            assert len(spec) > 0
            assert "Include:" in spec or "Exclude:" in spec

    def test_target_content_for_unknown_dimension(self):
        """Unknown dimension returns generic suggestion."""
        spec = target_content_for_dimension("unknown_dimension")
        assert "Improve unknown_dimension to meet quality standards" in spec

    def test_target_content_for_actionability(self):
        """Actionability target includes owner, success criteria, timeline."""
        spec = target_content_for_dimension("actionability")
        assert "Owner" in spec
        assert "Success criteria" in spec
        assert "Timeline" in spec


class TestRepairTask:
    """Test RepairTask dataclass."""

    def test_repair_task_creation(self):
        """RepairTask created with correct fields."""
        task = RepairTask(
            task_id="test_task_001",
            document_type="technical_report",
            current_quality_ratio=0.85,
            target_quality_ratio=0.95,
            weakest_dimension="actionability",
            repair_action="Add owner information",
            target_content="Include owner name and role",
            evidence_paths=["/path/to/evidence"],
            status="CREATED",
        )
        assert task.task_id == "test_task_001"
        assert task.document_type == "technical_report"
        assert task.current_quality_ratio == 0.85
        assert task.weakest_dimension == "actionability"

    def test_repair_task_frozen_immutable(self):
        """RepairTask is frozen and immutable."""
        task = RepairTask(
            task_id="test_001",
            document_type="technical_report",
            current_quality_ratio=0.85,
            target_quality_ratio=0.95,
            weakest_dimension="actionability",
            repair_action="test",
            target_content="test",
        )
        with pytest.raises(AttributeError):
            task.task_id = "modified"

    def test_repair_task_to_dict(self):
        """RepairTask.to_dict() serializes correctly."""
        task = RepairTask(
            task_id="test_001",
            document_type="technical_report",
            current_quality_ratio=0.85,
            target_quality_ratio=0.95,
            weakest_dimension="actionability",
            repair_action="test",
            target_content="test",
            evidence_paths=["/path1", "/path2"],
        )
        task_dict = task.to_dict()
        assert task_dict["task_id"] == "test_001"
        assert task_dict["current_quality_ratio"] == 0.85
        assert len(task_dict["evidence_paths"]) == 2


class TestCreateRepairTask:
    """Test create_repair_task() function."""

    def test_create_repair_task_with_explicit_dimension(self):
        """Create task with explicit weakest_dimension."""
        task = create_repair_task(
            document_type="technical_report",
            current_quality_ratio=0.85,
            target_quality_ratio=0.95,
            weakest_dimension="evidence",
        )
        assert task.document_type == "technical_report"
        assert task.weakest_dimension == "evidence"
        assert task.status == "CREATED"

    def test_create_repair_task_auto_selects_weakest_dimension(self):
        """Create task auto-selects weakest dimension from scores."""
        dimension_scores = {
            "actionability": 0.90,
            "evidence": 0.60,
            "clarity": 0.85,
        }
        task = create_repair_task(
            document_type="technical_report",
            current_quality_ratio=0.80,
            dimension_scores=dimension_scores,
        )
        # Should pick "evidence" (lowest score)
        assert task.weakest_dimension == "evidence"

    def test_create_repair_task_with_evidence_paths(self):
        """Create task with evidence paths."""
        evidence_paths = ["/path/to/evidence1.json", "/path/to/evidence2.json"]
        task = create_repair_task(
            document_type="technical_report",
            current_quality_ratio=0.85,
            weakest_dimension="actionability",
            evidence_paths=evidence_paths,
        )
        assert task.evidence_paths == evidence_paths

    def test_create_repair_task_default_target_ratio(self):
        """Create task uses default target_ratio if not specified."""
        task = create_repair_task(
            document_type="technical_report",
            current_quality_ratio=0.85,
            weakest_dimension="actionability",
        )
        assert task.target_quality_ratio == TARGET_RATIO_DEFAULT


class TestSaveRepairTask:
    """Test save_repair_task() function."""

    def test_save_repair_task_creates_json_file(self):
        """save_repair_task() creates JSON file with task data."""
        task = create_repair_task(
            document_type="technical_report",
            current_quality_ratio=0.85,
            weakest_dimension="actionability",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            task_path = Path(tmpdir) / "repair_task.json"
            save_repair_task(task, task_path)

            assert task_path.exists()

            with open(task_path) as f:
                saved_data = json.load(f)

            assert saved_data["task_id"] == task.task_id
            assert saved_data["document_type"] == "technical_report"
            assert saved_data["current_quality_ratio"] == 0.85

    def test_save_repair_task_creates_parent_directories(self):
        """save_repair_task() creates parent directories if missing."""
        task = create_repair_task(
            document_type="technical_report",
            current_quality_ratio=0.85,
            weakest_dimension="actionability",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            task_path = Path(tmpdir) / "nested" / "deep" / "repair_task.json"
            save_repair_task(task, task_path)

            assert task_path.exists()
            assert task_path.parent == Path(tmpdir) / "nested" / "deep"
