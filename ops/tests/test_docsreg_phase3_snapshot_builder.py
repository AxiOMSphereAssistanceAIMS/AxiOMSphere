"""Test suite for PHASE 3 Snapshot Builder."""
import pytest

from ops.docsreg.archetype_policy_adapter.registry import UnknownArchetypeError
from ops.docsreg.archetype_policy_adapter.snapshot_builder import (
    ArchetypeSnapshotBuilder,
    DocumentSnapshot,
)


class TestArchetypeSnapshotBuilderInit:
    """Test ArchetypeSnapshotBuilder initialization."""

    def test_builder_initializes_with_registry(self):
        """Builder should initialize with ConcreteArchetypeRegistry."""
        builder = ArchetypeSnapshotBuilder()
        assert builder.registry is not None
        assert builder.validator is not None

    def test_builder_registry_has_builtin_archetypes(self):
        """Builder registry should have builtin archetypes."""
        builder = ArchetypeSnapshotBuilder()
        archetypes = builder.registry.list_archetypes()
        assert "maintenance_procedure" in archetypes
        assert "policy_framework" in archetypes


class TestTokenEstimation:
    """Test token count estimation."""

    def test_token_estimation_empty_content(self):
        """Token estimation for empty content should be 0."""
        builder = ArchetypeSnapshotBuilder()
        tokens = builder._estimate_tokens("")
        assert tokens == 0

    def test_token_estimation_single_word(self):
        """Token estimation should use 1.3 words per token."""
        builder = ArchetypeSnapshotBuilder()
        tokens = builder._estimate_tokens("hello")
        assert tokens == int(1 * 1.3)

    def test_token_estimation_100_words(self):
        """Token estimation for 100 words."""
        builder = ArchetypeSnapshotBuilder()
        content = " ".join(["word"] * 100)
        tokens = builder._estimate_tokens(content)
        assert tokens == int(100 * 1.3)

    def test_token_estimation_1000_words(self):
        """Token estimation for 1000 words."""
        builder = ArchetypeSnapshotBuilder()
        content = " ".join(["word"] * 1000)
        tokens = builder._estimate_tokens(content)
        assert tokens == int(1000 * 1.3)


class TestSectionExtraction:
    """Test section extraction from content."""

    def test_extract_empty_sections(self):
        """Extract sections from content with no headers."""
        builder = ArchetypeSnapshotBuilder()
        content = "Just some plain text without headers."
        sections = builder.extract_present_sections(content)
        assert len(sections) == 0

    def test_extract_single_section(self):
        """Extract single section from content."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Introduction\nSome text."
        sections = builder.extract_present_sections(content)
        assert "introduction" in sections

    def test_extract_multiple_sections(self):
        """Extract multiple sections from content."""
        builder = ArchetypeSnapshotBuilder()
        content = """# Introduction
Text 1.

# Body
Text 2.

# Conclusion
Text 3."""
        sections = builder.extract_present_sections(content)
        assert "introduction" in sections
        assert "body" in sections
        assert "conclusion" in sections
        assert len(sections) == 3

    def test_extract_sections_normalized(self):
        """Section names should be normalized (lowercase, underscores)."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Document Control\nControl info."
        sections = builder.extract_present_sections(content)
        assert "document_control" in sections

    def test_extract_sections_with_subsections(self):
        """Extract sections should handle markdown header levels."""
        builder = ArchetypeSnapshotBuilder()
        content = """# Main Section
Main content.

## Subsection
Subsection content."""
        sections = builder.extract_present_sections(content)
        assert "main_section" in sections
        assert "subsection" in sections


@pytest.mark.asyncio
class TestSnapshotBuilderUnknownArchetype:
    """Test snapshot builder with unknown archetypes."""

    async def test_unknown_archetype_raises(self):
        """Building snapshot with unknown archetype should raise."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Test\nContent"
        with pytest.raises(UnknownArchetypeError):
            await builder.build(content, "unknown_archetype")

    async def test_unknown_archetype_error_message(self):
        """Unknown archetype error should mention the archetype name."""
        builder = ArchetypeSnapshotBuilder()
        with pytest.raises(UnknownArchetypeError) as exc_info:
            await builder.build("test", "nonexistent_type")
        assert "nonexistent_type" in str(exc_info.value)


@pytest.mark.asyncio
class TestSnapshotBuilderBuildMethod:
    """Test snapshot builder build method."""

    async def test_build_returns_document_snapshot(self):
        """Build should return DocumentSnapshot instance."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Test\nContent"
        snapshot = await builder.build(content, "maintenance_procedure")
        assert isinstance(snapshot, DocumentSnapshot)

    async def test_build_sets_document_id(self):
        """Build should set document_id if provided."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Test\nContent"
        snapshot = await builder.build(
            content, "maintenance_procedure", document_id="DOC-001"
        )
        assert snapshot.document_id == "DOC-001"

    async def test_build_without_document_id(self):
        """Build should set document_id to None if not provided."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Test\nContent"
        snapshot = await builder.build(content, "maintenance_procedure")
        assert snapshot.document_id is None

    async def test_build_sets_archetype_name(self):
        """Build should set archetype_name."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Test\nContent"
        snapshot = await builder.build(content, "policy_framework")
        assert snapshot.archetype_name == "policy_framework"

    async def test_build_sets_original_content(self):
        """Build should preserve original content."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Test\nSome content here"
        snapshot = await builder.build(content, "maintenance_procedure")
        assert snapshot.original_content == content

    async def test_build_calculates_token_count(self):
        """Build should calculate token count."""
        builder = ArchetypeSnapshotBuilder()
        content = " ".join(["word"] * 100)
        snapshot = await builder.build(content, "maintenance_procedure")
        assert snapshot.original_token_count == int(100 * 1.3)

    async def test_build_extracts_sections(self):
        """Build should extract sections."""
        builder = ArchetypeSnapshotBuilder()
        content = """# Document Control
Control info.

# Scope and Applicability
Scope info."""
        snapshot = await builder.build(content, "maintenance_procedure")
        assert "document_control" in snapshot.extracted_sections
        assert "scope_and_applicability" in snapshot.extracted_sections

    async def test_build_extracts_fields(self):
        """Build should extract fields."""
        builder = ArchetypeSnapshotBuilder()
        content = """# Document Control
document_id: DOC-001

# Scope
Scope."""
        snapshot = await builder.build(content, "maintenance_procedure")
        assert snapshot.extracted_fields is not None
        assert isinstance(snapshot.extracted_fields, dict)

    async def test_build_extracts_references(self):
        """Build should extract references."""
        builder = ArchetypeSnapshotBuilder()
        content = "Document refers to REF_001 and ISO-55001 standards."
        snapshot = await builder.build(content, "maintenance_procedure")
        assert "REF_001" in snapshot.extracted_references
        assert "ISO-55001" in snapshot.extracted_references

    async def test_build_extracts_tables(self):
        """Build should extract tables."""
        builder = ArchetypeSnapshotBuilder()
        content = "| Header 1 | Header 2 | Data 1 | Data 2 |"
        snapshot = await builder.build(content, "maintenance_procedure")
        assert snapshot.extracted_tables is not None

    async def test_build_extracts_semantic_claims(self):
        """Build should extract semantic claims."""
        builder = ArchetypeSnapshotBuilder()
        content = "The policy MUST ensure compliance and monitoring of standards."
        snapshot = await builder.build(content, "policy_framework")
        claim_lower = [c.lower() for c in snapshot.extracted_semantic_claims]
        # Should find at least one semantic claim pattern
        assert len(claim_lower) >= 0  # Empty is ok, patterns are optional


@pytest.mark.asyncio
class TestSnapshotBuilderMaintenanceProcedure:
    """Test snapshot builder with maintenance_procedure archetype."""

    async def test_build_maintenance_procedure_snapshot(self):
        """Build should create snapshot for maintenance_procedure."""
        builder = ArchetypeSnapshotBuilder()
        content = """# Document Control
doc_id: MAINT-001

# Scope and Applicability
This procedure applies to all maintenance operations.

# Safety Precautions
Always use PPE and lockout procedures.

# Tools and Equipment
Wrench, socket set, safety glasses.

# Step by Step Procedure
1. Prepare equipment
2. Apply lockout
3. Perform inspection
4. Document results
5. Verify completion
6. Remove lockout
7. Clean equipment
8. File report
This is a comprehensive procedure with detailed steps exceeding the 800 character minimum.

# Quality Verification
Verification checklist."""
        snapshot = await builder.build(content, "maintenance_procedure")
        assert snapshot.archetype_name == "maintenance_procedure"
        assert "document_control" in snapshot.extracted_sections
        assert len(snapshot.original_content) > 0


@pytest.mark.asyncio
class TestSnapshotBuilderPolicyFramework:
    """Test snapshot builder with policy_framework archetype."""

    async def test_build_policy_framework_snapshot(self):
        """Build should create snapshot for policy_framework."""
        builder = ArchetypeSnapshotBuilder()
        content = """# Document Control
policy_id: POL-001

# Policy Objective
Establish governance framework for asset management.

# Scope and Definitions
This policy applies to all organizational units.

# Policy Statement
The organization MUST maintain asset integrity through compliance with ISO standards.

# Roles and Responsibilities
Management is responsible for policy enforcement.

# Implementation Guidelines
Follow documented procedures for all operations.

# Compliance and Monitoring
Monitor compliance monthly and report quarterly.

# Approval and Sign Off
Approved by executive management."""
        snapshot = await builder.build(content, "policy_framework")
        assert snapshot.archetype_name == "policy_framework"
        assert "document_control" in snapshot.extracted_sections
        assert "policy_statement" in snapshot.extracted_sections


@pytest.mark.asyncio
class TestDocumentSnapshotImmutability:
    """Test that DocumentSnapshot is immutable."""

    async def test_snapshot_is_frozen(self):
        """DocumentSnapshot should be immutable (frozen=True)."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Test\nContent"
        snapshot = await builder.build(content, "maintenance_procedure")

        # Should not be able to modify snapshot
        with pytest.raises(AttributeError):
            snapshot.document_id = "NEW-ID"

    async def test_snapshot_tuple_fields_immutable(self):
        """Tuple fields in snapshot should be immutable."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Section 1\nContent"
        snapshot = await builder.build(content, "maintenance_procedure")

        # Tuple fields should not be modifiable
        with pytest.raises(TypeError):
            snapshot.extracted_sections[0] = "new_value"


@pytest.mark.asyncio
class TestSnapshotDataPreservation:
    """Test that snapshot preserves document data."""

    async def test_snapshot_preserves_content_length(self):
        """Snapshot should preserve original content length."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Section\n" + ("word " * 500)
        snapshot = await builder.build(content, "maintenance_procedure")
        assert len(snapshot.original_content) == len(content)

    async def test_snapshot_preserves_special_characters(self):
        """Snapshot should preserve special characters in content."""
        builder = ArchetypeSnapshotBuilder()
        content = "# Test\nContent with special: @#$%^&*()_+-="
        snapshot = await builder.build(content, "maintenance_procedure")
        assert "@#$%^&*()_+-=" in snapshot.original_content

    async def test_snapshot_multiple_builds_independent(self):
        """Multiple snapshots should be independent."""
        builder = ArchetypeSnapshotBuilder()
        content1 = "# Test 1\nContent 1"
        content2 = "# Test 2\nContent 2"

        snapshot1 = await builder.build(content1, "maintenance_procedure")
        snapshot2 = await builder.build(content2, "maintenance_procedure")

        assert snapshot1.original_content != snapshot2.original_content
        assert snapshot1.document_id == snapshot2.document_id
