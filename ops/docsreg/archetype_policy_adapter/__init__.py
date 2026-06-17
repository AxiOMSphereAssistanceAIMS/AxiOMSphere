"""Archetype policy adapter for DOCSREG PHASE 3.

Validates documents against document-type-specific policies and constraints.
Enforces required sections, fields, references, and semantic claims.
Detects archetype violations and produces structured error reports.
"""

from ops.docsreg.archetype_policy_adapter.base import (
    ArchetypeDefinition,
    ConstraintType,
    PolicyConstraint,
    StructuralViolation,
    ViolationSeverity,
)
from ops.docsreg.archetype_policy_adapter.maintenance_procedure import (
    get_maintenance_procedure_archetype,
)
from ops.docsreg.archetype_policy_adapter.policy_framework import (
    get_policy_framework_archetype,
)
from ops.docsreg.archetype_policy_adapter.registry import (
    ConcreteArchetypeRegistry,
    UnknownArchetypeError,
)
from ops.docsreg.archetype_policy_adapter.snapshot_builder import (
    ArchetypeSnapshotBuilder,
)
from ops.docsreg.archetype_policy_adapter.structural_validator import (
    DocumentValidator,
)

__all__ = [
    # Base types
    "ArchetypeDefinition",
    "ConstraintType",
    "PolicyConstraint",
    "StructuralViolation",
    "ViolationSeverity",
    # Registry
    "ConcreteArchetypeRegistry",
    "UnknownArchetypeError",
    # Archetypes
    "get_maintenance_procedure_archetype",
    "get_policy_framework_archetype",
    # Validation
    "DocumentValidator",
    "ArchetypeSnapshotBuilder",
]
