"""
Unit tests for BlockGeneratorMinimal.

Validates block content generation, quality scoring, and error handling.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from ops.docgen.block_generator_minimal import BlockGeneratorMinimal
from ops.docgen.document_block_graph import (
    DocumentBlock,
    BlockType,
)
from ops.docgen.plan_coordinator import PlanCoordinator
from ops.docgen.graph_builder_technical_report import TechnicalReportGraphBuilder


class TestBlockGeneratorMinimal:
    """Test suite for BlockGeneratorMinimal."""

    @pytest.fixture
    def setup_generator_and_graph(self, tmp_path):
        """Create a BlockGeneratorMinimal and a test graph."""
        generator = BlockGeneratorMinimal(model_slot="SLOT32")

        coordinator = PlanCoordinator("AI in Manufacturing", tmp_path)
        plan = coordinator.plan
        builder = TechnicalReportGraphBuilder(plan)
        graph = builder.build(include_optional=True)

        return generator, graph

    def test_generator_initialization(self):
        """Test that BlockGeneratorMinimal initializes with model slot."""
        generator = BlockGeneratorMinimal(model_slot="SLOT32")
        assert generator is not None
        assert generator.model_slot == "SLOT32"

    def test_generate_block_returns_tuple(self, setup_generator_and_graph):
        """Test that generate_block returns (block, quality) tuple."""
        generator, graph = setup_generator_and_graph

        block = list(graph.blocks.values())[0]
        result = generator.generate_block(
            block=block,
            document_context="AI in Manufacturing",
            previous_blocks=[],
        )

        assert isinstance(result, tuple)
        assert len(result) == 2
        block_result, quality = result
        assert isinstance(block_result, DocumentBlock)
        assert isinstance(quality, (float, int))

    def test_generate_block_generates_content(self, setup_generator_and_graph):
        """Test that generated block has content."""
        generator, graph = setup_generator_and_graph

        block = list(graph.blocks.values())[0]
        generated_block, quality = generator.generate_block(
            block=block,
            document_context="AI in Manufacturing",
            previous_blocks=[],
        )

        assert generated_block.generated_content is not None
        assert len(generated_block.generated_content) > 0

    def test_quality_score_in_valid_range(self, setup_generator_and_graph):
        """Test that quality score is in valid range [0.0, 1.0]."""
        generator, graph = setup_generator_and_graph

        block = list(graph.blocks.values())[0]
        _, quality = generator.generate_block(
            block=block,
            document_context="AI in Manufacturing",
            previous_blocks=[],
        )

        assert 0.0 <= quality <= 1.0

    def test_generated_block_has_quality_score(self, setup_generator_and_graph):
        """Test that returned block has quality_score set."""
        generator, graph = setup_generator_and_graph

        block = list(graph.blocks.values())[0]
        generated_block, _ = generator.generate_block(
            block=block,
            document_context="AI in Manufacturing",
            previous_blocks=[],
        )

        assert generated_block.quality_score is not None
        assert 0.0 <= generated_block.quality_score <= 1.0

    def test_generate_multiple_blocks_sequentially(self, setup_generator_and_graph):
        """Test generating multiple blocks in sequence."""
        generator, graph = setup_generator_and_graph

        execution_order = graph.get_execution_order()
        generated_block_ids = []
        all_quality_scores = []

        for block_id in execution_order[:3]:  # Generate first 3 blocks
            block = graph.blocks[block_id]
            previous_blocks = [
                graph.blocks[prev_id]
                for prev_id in generated_block_ids
                if graph.blocks[prev_id].generated_content
            ]

            generated_block, quality = generator.generate_block(
                block=block,
                document_context="AI in Manufacturing",
                previous_blocks=previous_blocks,
            )

            assert generated_block.generated_content is not None
            all_quality_scores.append(quality)
            generated_block_ids.append(block_id)

        assert len(all_quality_scores) == 3
        assert all(0.0 <= q <= 1.0 for q in all_quality_scores)

    def test_generation_with_previous_blocks_context(self, setup_generator_and_graph):
        """Test that generation uses previous blocks as context."""
        generator, graph = setup_generator_and_graph

        execution_order = graph.get_execution_order()
        block_ids = execution_order[:2]

        # Generate first block
        first_block = graph.blocks[block_ids[0]]
        first_generated, first_quality = generator.generate_block(
            block=first_block,
            document_context="AI in Manufacturing",
            previous_blocks=[],
        )

        # Generate second block with first as context
        second_block = graph.blocks[block_ids[1]]
        second_generated, second_quality = generator.generate_block(
            block=second_block,
            document_context="AI in Manufacturing",
            previous_blocks=[first_generated],
        )

        assert second_generated.generated_content is not None
        assert first_generated.generated_content != second_generated.generated_content

    def test_block_retains_original_metadata(self, setup_generator_and_graph):
        """Test that generation preserves original block metadata."""
        generator, graph = setup_generator_and_graph

        block = list(graph.blocks.values())[0]
        original_block_id = block.block_id
        original_required = block.required
        original_type = block.block_type

        generated_block, _ = generator.generate_block(
            block=block,
            document_context="AI in Manufacturing",
            previous_blocks=[],
        )

        assert generated_block.block_id == original_block_id
        assert generated_block.required == original_required
        assert generated_block.block_type == original_type

    def test_generation_attempts_incremented(self, setup_generator_and_graph):
        """Test that generation_attempts counter increments."""
        generator, graph = setup_generator_and_graph

        block = list(graph.blocks.values())[0]
        original_attempts = block.generation_attempts or 0

        generated_block, _ = generator.generate_block(
            block=block,
            document_context="AI in Manufacturing",
            previous_blocks=[],
        )

        assert generated_block.generation_attempts == original_attempts + 1

    def test_estimate_quality_low_word_count(self):
        """Test quality estimation for text with low word count."""
        generator = BlockGeneratorMinimal(model_slot="SLOT32")

        short_text = "This is short."
        mock_block = DocumentBlock(
            block_id="TEST",
            block_type=BlockType.SECTION,
            document_type="technical_report",
            required=False,
        )
        quality = generator._estimate_quality(short_text, mock_block)

        assert quality == 0.2

    def test_estimate_quality_placeholder_text(self):
        """Test quality estimation for placeholder text."""
        generator = BlockGeneratorMinimal(model_slot="SLOT32")

        placeholder_text = "This is a placeholder text that says to be filled in here TBD"
        mock_block = DocumentBlock(
            block_id="TEST",
            block_type=BlockType.SECTION,
            document_type="technical_report",
            required=False,
        )
        quality = generator._estimate_quality(placeholder_text, mock_block)

        assert quality == 0.2

    def test_estimate_quality_ideal_length(self):
        """Test quality estimation for ideal length text."""
        generator = BlockGeneratorMinimal(model_slot="SLOT32")

        ideal_text = " ".join(["word"] * 500)  # 500 words
        mock_block = DocumentBlock(
            block_id="TEST",
            block_type=BlockType.SECTION,
            document_type="technical_report",
            required=False,
        )
        quality = generator._estimate_quality(ideal_text, mock_block)

        assert quality == 0.75

    def test_estimate_quality_too_long(self):
        """Test quality estimation for very long text."""
        generator = BlockGeneratorMinimal(model_slot="SLOT32")

        long_text = " ".join(["word"] * 2000)  # 2000 words
        mock_block = DocumentBlock(
            block_id="TEST",
            block_type=BlockType.SECTION,
            document_type="technical_report",
            required=False,
        )
        quality = generator._estimate_quality(long_text, mock_block)

        assert quality == 0.5

    def test_estimate_quality_empty_text(self):
        """Test quality estimation for empty text."""
        generator = BlockGeneratorMinimal(model_slot="SLOT32")

        mock_block = DocumentBlock(
            block_id="TEST",
            block_type=BlockType.SECTION,
            document_type="technical_report",
            required=False,
        )
        quality = generator._estimate_quality("", mock_block)
        assert quality == 0.0

    def test_estimate_quality_whitespace_only(self):
        """Test quality estimation for whitespace-only text."""
        generator = BlockGeneratorMinimal(model_slot="SLOT32")

        mock_block = DocumentBlock(
            block_id="TEST",
            block_type=BlockType.SECTION,
            document_type="technical_report",
            required=False,
        )
        quality = generator._estimate_quality("   \n\n  ", mock_block)
        assert quality == 0.0
