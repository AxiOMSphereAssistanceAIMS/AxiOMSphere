"""
Unit tests for PlanCoordinator and TechnicalReportGraphBuilder.

Validates plan creation, graph construction, dependency resolution, and
execution order generation.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from ops.docgen.document_generation_plan import (
    DocumentGenerationPlan,
    GenerationStatus,
)
from ops.docgen.document_block_graph import (
    DocumentBlock,
    DocumentBlockGraph,
    BlockType,
)
from ops.docgen.graph_builder_technical_report import TechnicalReportGraphBuilder
from ops.docgen.plan_coordinator import PlanCoordinator


class TestPlanCoordinator:
    """Test suite for PlanCoordinator."""

    def test_plan_creation_basic(self, tmp_path):
        """Test basic plan creation for technical report."""
        topic = "AI in Manufacturing"
        coordinator = PlanCoordinator(topic, tmp_path)
        plan = coordinator.plan

        assert plan is not None
        assert plan.user_topic == topic
        assert plan.document_type == "technical_report"
        assert plan.generation_status == GenerationStatus.INITIALIZED

    def test_plan_has_required_blocks(self, tmp_path):
        """Test that plan includes all required blocks."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        # required_blocks is a list of block ID strings
        required_block_ids = plan.required_blocks
        assert "SEC-001" in required_block_ids
        assert "SEC-002" in required_block_ids
        assert "SEC-003" in required_block_ids
        assert "SEC-004" in required_block_ids
        assert "SEC-005" in required_block_ids

    def test_plan_has_optional_blocks(self, tmp_path):
        """Test that plan includes optional blocks."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        # optional_blocks is a list of block ID strings
        optional_block_ids = plan.optional_blocks
        assert "APP-A" in optional_block_ids
        assert "TBL-001" in optional_block_ids
        assert "FIG-001" in optional_block_ids

    def test_plan_snapshot_creation(self, tmp_path):
        """Test that plan snapshot is created and valid JSON."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        coordinator.save_plan_snapshot()

        snapshot_path = tmp_path / "plan_snapshot.json"
        assert snapshot_path.exists()

        snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert "plan_id" in snapshot_data
        assert "user_topic" in snapshot_data
        assert "document_type" in snapshot_data
        assert snapshot_data["document_type"] == "technical_report"

    def test_plan_contains_purpose_and_audience(self, tmp_path):
        """Test that plan includes purpose and audience."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        assert plan.purpose is not None
        assert len(plan.purpose) > 0
        assert plan.audience is not None
        assert len(plan.audience) > 0


class TestTechnicalReportGraphBuilder:
    """Test suite for TechnicalReportGraphBuilder."""

    def test_graph_creation_from_plan(self, tmp_path):
        """Test graph creation from technical report plan."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        assert graph is not None
        assert isinstance(graph, DocumentBlockGraph)
        assert len(graph.blocks) > 0

    def test_graph_includes_all_required_blocks(self, tmp_path):
        """Test that graph includes all required blocks."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        required_ids = {"SEC-001", "SEC-002", "SEC-003", "SEC-004", "SEC-005"}
        graph_block_ids = set(graph.blocks.keys())

        assert required_ids.issubset(graph_block_ids)

    def test_graph_includes_optional_blocks_when_requested(self, tmp_path):
        """Test that graph includes optional blocks when include_optional=True."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        optional_ids = {"APP-A", "TBL-001", "FIG-001"}
        graph_block_ids = set(graph.blocks.keys())

        assert optional_ids.issubset(graph_block_ids)

    def test_graph_excludes_optional_blocks_when_not_requested(self, tmp_path):
        """Test that graph excludes optional blocks when include_optional=False."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=False)

        optional_ids = {"APP-A", "TBL-001", "FIG-001"}
        graph_block_ids = set(graph.blocks.keys())

        for optional_id in optional_ids:
            assert optional_id not in graph_block_ids

    def test_graph_has_valid_dependencies(self, tmp_path):
        """Test that graph dependency structure is valid."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        # Validate dependencies: all depends_on references should exist
        for block in graph.blocks.values():
            for dep_id in block.depends_on:
                assert dep_id in graph.blocks, f"Dependency {dep_id} not found in graph"

    def test_graph_execution_order(self, tmp_path):
        """Test that graph generates valid topological execution order."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        execution_order = graph.get_execution_order()
        assert len(execution_order) > 0
        assert len(execution_order) == len(graph.blocks)

        # Verify topological sort: dependencies come before dependents
        block_index = {block_id: idx for idx, block_id in enumerate(execution_order)}
        for block_id in execution_order:
            block = graph.blocks[block_id]
            for dep_id in block.depends_on:
                assert block_index[dep_id] < block_index[block_id], (
                    f"Dependency {dep_id} should come before {block_id}"
                )

    def test_graph_no_cycles(self, tmp_path):
        """Test that graph contains no cycles."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        issues = graph.validate_dependencies()
        # Filter for cycle-type issues (if any cycle detection logic exists)
        cycle_issues = [
            issue for issue in issues
            if "cycle" in issue.description.lower() or issue.issue_type == "cycle"
        ]
        assert len(cycle_issues) == 0

    def test_graph_to_dict_serialization(self, tmp_path):
        """Test that graph can be serialized to dict."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        graph_dict = graph.to_dict()
        assert isinstance(graph_dict, dict)
        assert "blocks" in graph_dict
        assert len(graph_dict["blocks"]) > 0

    def test_graph_json_serializable(self, tmp_path):
        """Test that graph dict is JSON serializable."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        graph_dict = graph.to_dict()
        json_str = json.dumps(graph_dict, indent=2, ensure_ascii=False)

        assert json_str is not None
        assert len(json_str) > 0

        # Verify it can be parsed back
        parsed = json.loads(json_str)
        assert "blocks" in parsed

    def test_block_types_in_graph(self, tmp_path):
        """Test that blocks in graph have valid types."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        valid_types = {
            BlockType.SECTION,
            BlockType.APPENDIX,
            BlockType.TABLE,
            BlockType.FIGURE,
        }

        for block in graph.blocks.values():
            assert block.block_type in valid_types

    def test_required_blocks_marked_required(self, tmp_path):
        """Test that required blocks are marked as such."""
        coordinator = PlanCoordinator("Test Topic", tmp_path)
        plan = coordinator.plan

        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        required_ids = {"SEC-001", "SEC-002", "SEC-003", "SEC-004", "SEC-005"}
        for block_id in required_ids:
            assert graph.blocks[block_id].required is True
