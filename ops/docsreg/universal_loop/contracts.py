"""Protocol contracts for pluggable universal loop components.

Dependency injection interfaces enabling loose coupling between stages.
"""
from typing import Any, Protocol

from ops.docsreg.universal_loop.data_retention_validator import DocumentSnapshot


class DocumentGenerator(Protocol):
    """Generate improved document content."""

    async def generate(
        self, content: str, archetype_type: str, context: dict[str, Any]
    ) -> str:
        """Generate improved document."""
        ...


class QualityValidator(Protocol):
    """Validate document structure and format."""

    async def validate(self, content: str, archetype_type: str) -> tuple[bool, list[str]]:
        """Validate document, return (is_valid, errors)."""
        ...


class QualityScorer(Protocol):
    """Score document quality (0.0-1.0)."""

    async def score(self, content: str, archetype_type: str) -> float:
        """Score document quality."""
        ...


class ContentAuditor(Protocol):
    """Audit document content for compliance."""

    async def audit(self, content: str, archetype_type: str) -> dict[str, Any]:
        """Audit content, return diagnostics."""
        ...


class RepairService(Protocol):
    """Repair document content."""

    async def repair(
        self, content: str, archetype_type: str, failure_class: str
    ) -> str:
        """Repair document based on failure class."""
        ...


class SnapshotBuilder(Protocol):
    """Build immutable document snapshots."""

    async def build(self, content: str, archetype_type: str) -> DocumentSnapshot:
        """Build snapshot from content."""
        ...
