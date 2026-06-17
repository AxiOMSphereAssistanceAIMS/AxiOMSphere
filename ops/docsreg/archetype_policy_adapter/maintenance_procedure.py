"""Maintenance procedure archetype definition for PHASE 3."""
from ops.docsreg.archetype_policy_adapter.base import (
    ArchetypeDefinition,
    ConstraintType,
    PolicyConstraint,
    ViolationSeverity,
)


def get_maintenance_procedure_archetype() -> ArchetypeDefinition:
    """Return maintenance_procedure archetype definition."""
    constraints = [
        PolicyConstraint(
            constraint_id="MAINT_001",
            constraint_type=ConstraintType.SECTION_REQUIRED,
            target="document_control",
            description="Document control section is required for maintenance procedures",
            params={},
            severity=ViolationSeverity.CRITICAL,
            remediation_hint="Add document_control section with document_id, revision, and approval_authority",
            skill_category="REPAIR_SECTION",
        ),
        PolicyConstraint(
            constraint_id="MAINT_002",
            constraint_type=ConstraintType.SECTION_REQUIRED,
            target="safety_precautions",
            description="Safety precautions section is required for maintenance procedures",
            params={},
            severity=ViolationSeverity.CRITICAL,
            remediation_hint="Add safety_precautions section detailing all safety measures and PPE requirements",
            skill_category="REPAIR_SECTION",
        ),
        PolicyConstraint(
            constraint_id="MAINT_003",
            constraint_type=ConstraintType.SECTION_MIN_LENGTH,
            target="step_by_step_procedure",
            description="Step-by-step procedure section must be comprehensive (minimum 800 characters)",
            params={"min_length": 800},
            severity=ViolationSeverity.CRITICAL,
            remediation_hint="Expand step_by_step_procedure with detailed, numbered steps (minimum 800 characters)",
            skill_category="REPAIR_SECTION",
        ),
        PolicyConstraint(
            constraint_id="MAINT_004",
            constraint_type=ConstraintType.FIELD_REQUIRED,
            target="approval_authority",
            description="Approval authority field is required",
            params={},
            severity=ViolationSeverity.CRITICAL,
            remediation_hint="Add approval_authority field identifying the authorized reviewer/approver",
            skill_category="REPAIR_FIELD",
        ),
        PolicyConstraint(
            constraint_id="MAINT_005",
            constraint_type=ConstraintType.FIELD_REQUIRED,
            target="acceptance_criteria",
            description="Acceptance criteria field is required for quality verification",
            params={},
            severity=ViolationSeverity.HIGH,
            remediation_hint="Add acceptance_criteria field defining success metrics for the maintenance task",
            skill_category="REPAIR_FIELD",
        ),
    ]

    return ArchetypeDefinition(
        archetype_name="maintenance_procedure",
        display_name="Maintenance Procedure",
        version="1.0",
        description="Industrial asset maintenance procedure with safety controls and step-by-step instructions",
        required_sections=[
            "document_control",
            "scope_and_applicability",
            "safety_precautions",
            "tools_and_equipment",
            "step_by_step_procedure",
            "quality_verification",
        ],
        required_fields=[
            "document_id",
            "revision",
            "approval_authority",
            "effective_date",
            "asset_or_system",
            "ppe_requirements",
            "acceptance_criteria",
        ],
        required_references=[
            "maintenance_standard",
            "safety_standard",
        ],
        required_tables=[
            "tools_table",
        ],
        semantic_claim_patterns=[
            "lockout",
            "inspection",
            "verification",
            "acceptance",
            "record",
        ],
        critical_data_markers=[
            "LOCKOUT",
            "HAZARD",
            "SAFETY",
            "INSPECTION",
            "APPROVAL",
        ],
        optional_sections=[
            "troubleshooting",
            "maintenance_history",
            "appendix",
        ],
        constraints=constraints,
        target_quality=0.95,
        aspirational_quality=0.98,
        enabled=True,
    )
