"""Policy framework archetype definition for PHASE 3."""
from ops.docsreg.archetype_policy_adapter.base import (
    ArchetypeDefinition,
    ConstraintType,
    PolicyConstraint,
    ViolationSeverity,
)


def get_policy_framework_archetype() -> ArchetypeDefinition:
    """Return policy_framework archetype definition."""
    constraints = [
        PolicyConstraint(
            constraint_id="POLICY_001",
            constraint_type=ConstraintType.SECTION_REQUIRED,
            target="policy_statement",
            description="Policy statement section is required",
            params={},
            severity=ViolationSeverity.CRITICAL,
            remediation_hint="Add policy_statement section clearly stating the policy intent and scope",
            skill_category="REPAIR_SECTION",
        ),
        PolicyConstraint(
            constraint_id="POLICY_002",
            constraint_type=ConstraintType.SECTION_REQUIRED,
            target="approval_and_sign_off",
            description="Approval and sign-off section is required for policy authorization",
            params={},
            severity=ViolationSeverity.CRITICAL,
            remediation_hint="Add approval_and_sign_off section with authorized approver names and dates",
            skill_category="REPAIR_SECTION",
        ),
        PolicyConstraint(
            constraint_id="POLICY_003",
            constraint_type=ConstraintType.FIELD_REQUIRED,
            target="policy_owner",
            description="Policy owner field is required",
            params={},
            severity=ViolationSeverity.CRITICAL,
            remediation_hint="Add policy_owner field identifying the owner/steward of the policy",
            skill_category="REPAIR_FIELD",
        ),
        PolicyConstraint(
            constraint_id="POLICY_004",
            constraint_type=ConstraintType.FIELD_REQUIRED,
            target="review_cycle",
            description="Review cycle field is required for ongoing policy management",
            params={},
            severity=ViolationSeverity.HIGH,
            remediation_hint="Add review_cycle field specifying review frequency (e.g., annual, bi-annual)",
            skill_category="REPAIR_FIELD",
        ),
        PolicyConstraint(
            constraint_id="POLICY_005",
            constraint_type=ConstraintType.SEMANTIC_CLAIM_REQUIRED,
            target="policy_semantics",
            description="Policy must contain semantic enforcement keywords (must, shall, responsible, compliance)",
            params={"keywords": ["must", "shall", "responsible", "compliance"]},
            severity=ViolationSeverity.HIGH,
            remediation_hint="Ensure policy statement uses strong mandatory language (must, shall) and clear responsibility assignments",
            skill_category="REPAIR_CONTENT",
        ),
    ]

    return ArchetypeDefinition(
        archetype_name="policy_framework",
        display_name="Policy Framework",
        version="1.0",
        description="Organizational policy document defining governance, roles, responsibilities, and compliance requirements",
        required_sections=[
            "document_control",
            "policy_objective",
            "scope_and_definitions",
            "policy_statement",
            "roles_and_responsibilities",
            "implementation_guidelines",
            "compliance_and_monitoring",
            "approval_and_sign_off",
        ],
        required_fields=[
            "policy_id",
            "policy_owner",
            "version",
            "effective_date",
            "approval_authority",
            "review_cycle",
            "exception_process",
        ],
        required_references=[
            "governance_reference",
            "compliance_reference",
        ],
        required_tables=[
            "compliance_matrix",
        ],
        semantic_claim_patterns=[
            "must",
            "shall",
            "responsible",
            "compliance",
            "monitoring",
            "exception",
        ],
        critical_data_markers=[
            "MANDATORY",
            "APPROVAL",
            "EXCEPTION",
            "MONITORING",
            "COMPLIANCE",
        ],
        optional_sections=[
            "frequently_asked_questions",
            "references_and_attachments",
            "amendment_history",
        ],
        constraints=constraints,
        target_quality=0.95,
        aspirational_quality=0.98,
        enabled=True,
    )
