"""Snapshot builder for document extraction and archetype-aware capture."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ops.docsreg.archetype_policy_adapter.base import ArchetypeDefinition
from ops.docsreg.archetype_policy_adapter.registry import (
    ConcreteArchetypeRegistry,
    UnknownArchetypeError,
)
from ops.docsreg.archetype_policy_adapter.structural_validator import (
    DocumentValidator,
)


@dataclass(frozen=True)
class DocumentSnapshot:
    """Immutable snapshot of document extraction results."""

    document_id: Optional[str]
    archetype_name: str
    original_content: str
    original_token_count: int
    extracted_sections: Tuple[str, ...] = field(default_factory=tuple)
    extracted_fields: Dict[str, Optional[str]] = field(default_factory=dict)
    extracted_references: Tuple[str, ...] = field(default_factory=tuple)
    extracted_tables: Tuple[str, ...] = field(default_factory=tuple)
    extracted_semantic_claims: Tuple[str, ...] = field(default_factory=tuple)


class ArchetypeSnapshotBuilder:
    """Builder for creating document snapshots with archetype-aware extraction."""

    def __init__(self):
        """Initialize builder with archetype registry and validator."""
        self.registry = ConcreteArchetypeRegistry()
        self.validator = DocumentValidator()

    def extract_present_sections(self, content: str) -> Tuple[str, ...]:
        """Extract section names from markdown-style headers.

        Returns:
            Tuple of section names in order of appearance
        """
        _, section_contents = self.validator._extract_sections(content)
        return tuple(section_contents.keys())

    def _estimate_tokens(self, content: str) -> int:
        """Estimate token count using word-based heuristic.

        Heuristic: 1 token ≈ 1.3 words (common ML convention)
        """
        word_count = len(content.split())
        return int(word_count * 1.3)

    async def build(
        self, content: str, archetype_name: str, document_id: Optional[str] = None
    ) -> DocumentSnapshot:
        """Build document snapshot with archetype-aware extraction.

        Args:
            content: Document content (markdown or plain text)
            archetype_name: Name of archetype to validate against
            document_id: Optional document identifier

        Returns:
            DocumentSnapshot with all extraction results

        Raises:
            UnknownArchetypeError: If archetype is not registered
        """
        # Verify archetype exists (raises UnknownArchetypeError if not)
        archetype = self.registry.get_archetype(archetype_name)

        # Extract all components
        sections, section_contents = self.validator._extract_sections(content)
        fields = self.validator._extract_fields(content, archetype.required_fields)
        references = self.validator._extract_references(content)
        tables = self.validator._extract_tables(content)
        semantic_claims = self.validator._extract_semantic_claims(
            content, archetype.semantic_claim_patterns
        )

        # Estimate token count
        token_count = self._estimate_tokens(content)

        # Create immutable snapshot
        return DocumentSnapshot(
            document_id=document_id,
            archetype_name=archetype_name,
            original_content=content,
            original_token_count=token_count,
            extracted_sections=tuple(sections),
            extracted_fields=fields,
            extracted_references=tuple(references),
            extracted_tables=tuple(tables),
            extracted_semantic_claims=tuple(semantic_claims),
        )
