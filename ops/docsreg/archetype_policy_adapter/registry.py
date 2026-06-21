"""Archetype registry for PHASE 3."""
from typing import Dict, List

from ops.docsreg.archetype_policy_adapter.base import ArchetypeDefinition
from ops.docsreg.archetype_policy_adapter.classification_notation_table import (
    get_classification_notation_table_archetype,
)
from ops.docsreg.archetype_policy_adapter.maintenance_procedure import (
    get_maintenance_procedure_archetype,
)
from ops.docsreg.archetype_policy_adapter.policy_framework import (
    get_policy_framework_archetype,
)


class UnknownArchetypeError(Exception):
    """Raised when archetype is not found in registry."""

    pass


class ConcreteArchetypeRegistry:
    """Registry of document archetype definitions."""

    def __init__(self):
        """Initialize registry with built-in archetypes."""
        self._archetypes: Dict[str, ArchetypeDefinition] = {}
        # Pre-populate with built-in archetypes
        self._register_builtin()

    def _register_builtin(self) -> None:
        """Register built-in archetype definitions."""
        self.register_archetype(get_classification_notation_table_archetype())
        self.register_archetype(get_maintenance_procedure_archetype())
        self.register_archetype(get_policy_framework_archetype())

    def register_archetype(self, archetype: ArchetypeDefinition) -> None:
        """Register an archetype definition."""
        self._archetypes[archetype.archetype_name] = archetype

    def list_archetypes(self) -> List[str]:
        """List all registered archetype names."""
        return list(self._archetypes.keys())

    def get_archetype(self, archetype_name: str) -> ArchetypeDefinition:
        """Get archetype by name.

        Args:
            archetype_name: Name of archetype to retrieve

        Returns:
            ArchetypeDefinition

        Raises:
            UnknownArchetypeError: If archetype not found
        """
        if archetype_name not in self._archetypes:
            raise UnknownArchetypeError(
                f"Archetype '{archetype_name}' not found in registry. "
                f"Available archetypes: {', '.join(self.list_archetypes())}"
            )
        return self._archetypes[archetype_name]
