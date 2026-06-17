"""Base types for archetype policy adapter."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class ConstraintType(str, Enum):
    """Policy constraint type classification."""

    SECTION_REQUIRED = "SECTION_REQUIRED"
    SECTION_MIN_LENGTH = "SECTION_MIN_LENGTH"
    FIELD_REQUIRED = "FIELD_REQUIRED"
    FIELD_REGEX_MATCH = "FIELD_REGEX_MATCH"
    REFERENCE_REQUIRED = "REFERENCE_REQUIRED"
    TABLE_REQUIRED = "TABLE_REQUIRED"
    SEMANTIC_CLAIM_REQUIRED = "SEMANTIC_CLAIM_REQUIRED"
    APPROVAL_CHAIN = "APPROVAL_CHAIN"
    METADATA_COMPLETENESS = "METADATA_COMPLETENESS"


class ViolationSeverity(str, Enum):
    """Violation severity levels."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    ADVISORY = "ADVISORY"


@dataclass(frozen=True)
class PolicyConstraint:
    """Immutable policy constraint definition."""

    constraint_id: str
    constraint_type: ConstraintType
    target: str  # section name, field name, or reference type
    description: str
    params: Dict[str, Any]  # min_length, regex_pattern, etc.
    severity: ViolationSeverity
    remediation_hint: str
    skill_category: str  # "REPAIR_SECTION", "REPAIR_FIELD", etc.


@dataclass(frozen=True)
class StructuralViolation:
    """Immutable structural violation record."""

    constraint_id: str
    constraint_type: ConstraintType
    target: str
    severity: ViolationSeverity
    message: str
    actual_value: Optional[Any] = None
    expected_value: Optional[Any] = None
    section_name: Optional[str] = None
    field_name: Optional[str] = None
    context_excerpt: Optional[str] = None
    remediation_hint: Optional[str] = None
    skill_category: Optional[str] = None
    failure_class: Optional[str] = None  # "UNKNOWN_ARCHETYPE", "MISSING_SECTION", etc.


@dataclass(frozen=True)
class ArchetypeDefinition:
    """Immutable archetype definition."""

    archetype_name: str
    display_name: str
    version: str
    description: str
    required_sections: List[str]
    required_fields: List[str]
    required_references: List[str]
    required_tables: List[str]
    semantic_claim_patterns: List[str]
    critical_data_markers: List[str]
    optional_sections: List[str]
    constraints: List[PolicyConstraint]
    target_quality: float = 0.95
    aspirational_quality: float = 0.98
    enabled: bool = True
