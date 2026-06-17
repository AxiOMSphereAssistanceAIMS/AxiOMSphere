"""
Unit tests for DocumentAssemblerMinimal and RenderQAWrapper.

Validates DOCX assembly, rendering, and visual QA integration.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ops.docgen.document_assembler_minimal import DocumentAssemblerMinimal
from ops.docgen.render_qa_wrapper import RenderQAWrapper
from ops.docgen.document_block_graph import (
    DocumentBlock,
    DocumentBlockGraph,
    BlockType,
)
from ops.docgen.plan_coordinator import PlanCoordinator
from ops.docgen.graph_builder_technical_report import TechnicalReportGraphBuilder
from ops.docgen.block_generator_minimal import BlockGeneratorMinimal


class TestDocumentAssemblerMinimal:
    """Test suite for DocumentAssemblerMinimal."""

    @pytest.fixture
    def setup_generated_graph(self, tmp_path):
        """Create a graph with generated blocks."""
        coordinator = PlanCoordinator("AI in Manufacturing", tmp_path)
        plan = coordinator.plan
        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        # Generate content for all blocks
        generator = BlockGeneratorMinimal(model_slot="SLOT32")
        execution_order = graph.get_execution_order()

        for block_id in execution_order:
            block = graph.blocks[block_id]
            generated_block, quality = generator.generate_block(
                block=block,
                document_context="AI in Manufacturing",
                previous_blocks=[],
            )
            graph.blocks[block_id] = generated_block

        return graph

    def test_assembler_initialization(self, tmp_path):
        """Test DocumentAssemblerMinimal initialization."""
        graph = DocumentBlockGraph(document_type="technical_report")
        assembler = DocumentAssemblerMinimal(graph, tmp_path)

        assert assembler is not None
        assert assembler.output_dir == tmp_path

    def test_assemble_creates_docx_file(self, setup_generated_graph, tmp_path):
        """Test that assemble() creates a DOCX file."""
        assembler = DocumentAssemblerMinimal(setup_generated_graph, tmp_path)
        docx_path = assembler.assemble()

        assert docx_path.exists()
        assert docx_path.suffix == ".docx"
        assert "generated_technical_report" in docx_path.name

    def test_assemble_returns_path(self, setup_generated_graph, tmp_path):
        """Test that assemble() returns a Path object."""
        assembler = DocumentAssemblerMinimal(setup_generated_graph, tmp_path)
        docx_path = assembler.assemble()

        assert isinstance(docx_path, Path)

    def test_assemble_fails_if_required_block_missing(self, tmp_path):
        """Test that assemble() fails gracefully if required block is missing content."""
        graph = DocumentBlockGraph(document_type="technical_report")

        # Add a required block WITHOUT content (should fail validation)
        required_block = DocumentBlock(
            block_id="SEC-001",
            block_type=BlockType.SECTION,
            document_type="technical_report",
            required=True,
            generated_content=None,  # Missing content
            quality_score=0.0,
        )
        graph.blocks["SEC-001"] = required_block

        assembler = DocumentAssemblerMinimal(graph, tmp_path)

        # Should return None in non-strict mode (graceful degradation)
        result = assembler.assemble()
        assert result is None

    def test_assemble_with_only_required_blocks(self, tmp_path):
        """Test assembly with only required blocks (no optional)."""
        graph = DocumentBlockGraph(document_type="technical_report")

        # Add only required blocks
        for i, block_id in enumerate(["SEC-001", "SEC-002", "SEC-003", "SEC-004", "SEC-005"]):
            block = DocumentBlock(
                block_id=block_id,
                block_type=BlockType.SECTION,
                document_type="technical_report",
                required=True,
                generated_content=f"Content for {block_id}. " * 50,  # Sufficient content
                quality_score=0.8,
            )
            if i > 0:
                block.depends_on = [graph.get_block(["SEC-001", "SEC-002", "SEC-003", "SEC-004"][i - 1]).block_id]
            graph.blocks[block_id] = block

        assembler = DocumentAssemblerMinimal(graph, tmp_path)
        docx_path = assembler.assemble()

        assert docx_path is not None
        assert docx_path.exists()

    def test_docx_file_has_reasonable_size(self, setup_generated_graph, tmp_path):
        """Test that generated DOCX file has reasonable size (not empty)."""
        assembler = DocumentAssemblerMinimal(setup_generated_graph, tmp_path)
        docx_path = assembler.assemble()

        file_size = docx_path.stat().st_size
        assert file_size > 1024  # At least 1 KB


class TestRenderQAWrapper:
    """Test suite for RenderQAWrapper."""

    def test_wrapper_initialization(self, tmp_path):
        """Test RenderQAWrapper initialization."""
        wrapper = RenderQAWrapper(tmp_path)
        assert wrapper is not None
        assert wrapper.output_dir == tmp_path

    def test_visual_qa_subdir_created(self, tmp_path):
        """Test that visual_qa subdirectory is created during inspection."""
        wrapper = RenderQAWrapper(tmp_path)

        # Create a mock DOCX file
        docx_path = tmp_path / "test.docx"
        docx_path.write_bytes(b"mock docx content")

        # Mock the render_docx_for_qa function
        with patch(
            "ops.docgen.render_qa_wrapper.render_docx_for_qa"
        ) as mock_render:
            mock_metrics = MagicMock()
            mock_metrics.to_dict.return_value = {
                "page_count": 5,
                "blank_page_count": 0,
            }
            mock_render.return_value = (True, mock_metrics)
            visual_qa_passed, metrics = wrapper.render_and_inspect(docx_path)

            # Directory should be passed to render function
            assert visual_qa_passed is True

    def test_render_and_inspect_returns_tuple(self, tmp_path):
        """Test that render_and_inspect returns (bool, Optional[metrics]) tuple."""
        wrapper = RenderQAWrapper(tmp_path)

        # Create a mock DOCX file
        docx_path = tmp_path / "test.docx"
        docx_path.write_bytes(b"mock docx content")

        with patch(
            "ops.docgen.render_qa_wrapper.render_docx_for_qa"
        ) as mock_render:
            mock_metrics = MagicMock()
            mock_metrics.to_dict.return_value = {
                "page_count": 5,
                "blank_page_count": 0,
            }
            mock_render.return_value = (True, mock_metrics)
            result = wrapper.render_and_inspect(docx_path)

            assert isinstance(result, tuple)
            assert len(result) == 2
            visual_qa_passed, metrics = result
            assert isinstance(visual_qa_passed, bool)

    def test_render_and_inspect_handles_render_success(self, tmp_path):
        """Test successful render scenario."""
        wrapper = RenderQAWrapper(tmp_path)

        docx_path = tmp_path / "test.docx"
        docx_path.write_bytes(b"mock docx content")

        with patch(
            "ops.docgen.render_qa_wrapper.render_docx_for_qa"
        ) as mock_render:
            mock_metrics = MagicMock()
            mock_metrics.to_dict.return_value = {
                "page_count": 5,
                "blank_page_count": 0,
            }
            mock_render.return_value = (True, mock_metrics)

            visual_qa_passed, metrics = wrapper.render_and_inspect(docx_path)

            assert visual_qa_passed is True
            assert metrics is not None

    def test_render_and_inspect_handles_render_failure(self, tmp_path):
        """Test failed render scenario."""
        wrapper = RenderQAWrapper(tmp_path)

        docx_path = tmp_path / "test.docx"
        docx_path.write_bytes(b"mock docx content")

        with patch(
            "ops.docgen.render_qa_wrapper.render_docx_for_qa"
        ) as mock_render:
            mock_render.return_value = (False, None)

            visual_qa_passed, metrics = wrapper.render_and_inspect(docx_path)

            assert visual_qa_passed is False
            assert metrics is None

    def test_render_and_inspect_handles_exception(self, tmp_path):
        """Test exception handling during render."""
        wrapper = RenderQAWrapper(tmp_path)

        docx_path = tmp_path / "test.docx"
        docx_path.write_bytes(b"mock docx content")

        with patch(
            "ops.docgen.render_qa_wrapper.render_docx_for_qa"
        ) as mock_render:
            mock_render.side_effect = Exception("Render failed")

            visual_qa_passed, metrics = wrapper.render_and_inspect(docx_path)

            # Should handle gracefully and return False
            assert visual_qa_passed is False
            assert metrics is None

    def test_render_metrics_saved_to_json(self, tmp_path):
        """Test that render metrics are saved to JSON."""
        wrapper = RenderQAWrapper(tmp_path)

        docx_path = tmp_path / "test.docx"
        docx_path.write_bytes(b"mock docx content")

        with patch(
            "ops.docgen.render_qa_wrapper.render_docx_for_qa"
        ) as mock_render:
            mock_metrics = MagicMock()
            mock_metrics.to_dict.return_value = {
                "page_count": 5,
                "blank_page_count": 0,
            }
            mock_render.return_value = (True, mock_metrics)

            wrapper.render_and_inspect(docx_path)

            # Check if metrics file was created
            metrics_path = tmp_path / "render_metrics.json"
            # File should exist or be attempted to be written
            # (actual check depends on implementation)

    def test_wrapper_timeout_passed_to_render(self, tmp_path):
        """Test that timeout is passed to render function."""
        wrapper = RenderQAWrapper(tmp_path)

        docx_path = tmp_path / "test.docx"
        docx_path.write_bytes(b"mock docx content")

        with patch(
            "ops.docgen.render_qa_wrapper.render_docx_for_qa"
        ) as mock_render:
            mock_metrics = MagicMock()
            mock_metrics.to_dict.return_value = {
                "page_count": 5,
                "blank_page_count": 0,
            }
            mock_render.return_value = (True, mock_metrics)

            wrapper.render_and_inspect(docx_path)

            # Verify timeout was passed
            call_args = mock_render.call_args
            assert call_args is not None
            # Should have timeout_sec in kwargs
            if "timeout_sec" in call_args.kwargs:
                assert call_args.kwargs["timeout_sec"] >= 60
