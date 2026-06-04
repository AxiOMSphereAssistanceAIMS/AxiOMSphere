"""
AIMS Phase 17 — Hermes Skill Reference Mapper.

Maps Hermes skill categories to AIMS-native adaptations.
Read-only: no Hermes runtime invocation, no model calls.
"""
from __future__ import annotations

import json
import pathlib
from typing import Any

try:
    from .hermes_inspired_skill_curator_schema import (
        HERMES_REFERENCE_CATEGORIES,
        HermesSkillReference,
    )
except ImportError:
    from agents.self_learning.hermes_inspired_skill_curator_schema import (  # type: ignore
        HERMES_REFERENCE_CATEGORIES,
        HermesSkillReference,
    )

# Hermes → AIMS adaptation mapping (static, no runtime calls)
_REFERENCE_MAP: dict[str, dict[str, Any]] = {
    "skill-authoring": {
        "pattern_name": "structured-skill-authoring",
        "aims_notes": (
            "Hermes uses markdown skill files with frontmatter. "
            "AIMS adapts this as JSON skill specs with safety policy headers, "
            "phase tags, and explicit authoring_policy_violations field."
        ),
        "applicable_phases": [5, 6, 7, 17],
        "safety_constraints": [
            "no_self_approval",
            "sandbox_required_before_certification",
            "human_review_required_before_activation",
        ],
    },
    "dogfood": {
        "pattern_name": "self-consumption-pattern",
        "aims_notes": (
            "Hermes dogfoods its own skills. AIMS adapts this as internal "
            "skill observation from document generation and repair workflows, "
            "feeding the OBSERVED_PATTERN lifecycle stage."
        ),
        "applicable_phases": [5, 6, 17],
        "safety_constraints": [
            "no_active_registry_modification",
            "observation_only_no_activation",
        ],
    },
    "systematic-debugging": {
        "pattern_name": "structured-diagnosis-pattern",
        "aims_notes": (
            "Hermes systematic-debugging maps to AIMS Repairman skill patterns: "
            "root-cause analysis → patch proposal → Poli approval gate → Mainy execution."
        ),
        "applicable_phases": [7, 8, 9, 17],
        "safety_constraints": [
            "no_model_endpoint_calls",
            "no_service_restart_without_approval",
        ],
    },
    "codebase-inspection": {
        "pattern_name": "read-only-exploration-pattern",
        "aims_notes": (
            "Maps to AIMS Phase 5 Hermes skill pattern study: read-only inspection "
            "of skill files, no writes, no activation."
        ),
        "applicable_phases": [5, 17],
        "safety_constraints": [
            "read_only",
            "no_file_writes",
        ],
    },
    "requesting-code-review": {
        "pattern_name": "peer-review-gate-pattern",
        "aims_notes": (
            "Maps to AIMS Phase 13 approval gate: all proposals enter PENDING_APPROVAL "
            "state; human review required before any state transition."
        ),
        "applicable_phases": [13, 17],
        "safety_constraints": [
            "no_self_approval",
            "human_reviewer_required",
        ],
    },
    "test-driven-development": {
        "pattern_name": "smoke-first-pattern",
        "aims_notes": (
            "Each AIMS phase has a dedicated smoke test that must pass before "
            "the phase output is accepted. Maps directly to the per-phase "
            "sentinel/acceptance gate pattern."
        ),
        "applicable_phases": [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17],
        "safety_constraints": [
            "smoke_must_pass_before_certification",
        ],
    },
    "plan": {
        "pattern_name": "phase-plan-pattern",
        "aims_notes": (
            "Hermes plan skill maps to AIMS phase planning: each phase has a "
            "defined acceptance gate, artifact list, and sentinel string before "
            "implementation begins."
        ),
        "applicable_phases": [17],
        "safety_constraints": [
            "plan_must_precede_implementation",
        ],
    },
    "writing-plans": {
        "pattern_name": "structured-spec-pattern",
        "aims_notes": (
            "Maps to AIMS skill spec generation in Phase 7 (candidate skill plans). "
            "Each plan includes: name, description, authoring_policy_violations, "
            "sandbox_inputs, expected_outputs."
        ),
        "applicable_phases": [7, 17],
        "safety_constraints": [
            "no_live_execution_during_planning",
        ],
    },
    "subagent-driven-development": {
        "pattern_name": "agent-delegation-pattern",
        "aims_notes": (
            "Maps to AIMS PipelineCoordinator delegating to KnomiAgent, DociAgent, "
            "PoliAgent. Each sub-agent has a bounded role; cross-agent calls go "
            "through the coordinator, not directly."
        ),
        "applicable_phases": [17],
        "safety_constraints": [
            "no_direct_cross_agent_activation",
            "coordinator_mediated_only",
        ],
    },
    "ocr-and-documents": {
        "pattern_name": "document-pipeline-pattern",
        "aims_notes": (
            "Maps to AIMS OmiAgent OCR pipeline and DocAgent document generation. "
            "Skills derived from repeated OCR + generation patterns enter "
            "OBSERVED_PATTERN state for curator evaluation."
        ),
        "applicable_phases": [5, 6, 17],
        "safety_constraints": [
            "no_registry_write_without_omi_approval",
        ],
    },
}


def load_hermes_references() -> list[HermesSkillReference]:
    """Return all Hermes reference mappings as HermesSkillReference objects."""
    refs = []
    for category in HERMES_REFERENCE_CATEGORIES:
        mapping = _REFERENCE_MAP.get(category, {})
        refs.append(HermesSkillReference(
            hermes_category=category,
            hermes_pattern_name=mapping.get("pattern_name", category),
            aims_adaptation_notes=mapping.get("aims_notes", ""),
            applicable_aims_phases=mapping.get("applicable_phases", []),
            safety_constraints=mapping.get("safety_constraints", []),
        ))
    return refs


def load_hermes_references_from_file(path: pathlib.Path) -> list[HermesSkillReference]:
    """Load references from a JSON fixture file (for testing)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    refs = []
    for entry in data:
        refs.append(HermesSkillReference(
            hermes_category=entry["hermes_category"],
            hermes_pattern_name=entry["hermes_pattern_name"],
            aims_adaptation_notes=entry.get("aims_adaptation_notes", ""),
            applicable_aims_phases=entry.get("applicable_aims_phases", []),
            safety_constraints=entry.get("safety_constraints", []),
        ))
    return refs


def get_reference_by_category(category: str) -> HermesSkillReference | None:
    """Retrieve a single reference mapping by Hermes category name."""
    for ref in load_hermes_references():
        if ref.hermes_category == category:
            return ref
    return None


def build_reference_index() -> dict[str, HermesSkillReference]:
    """Return category → reference mapping for fast lookup."""
    return {ref.hermes_category: ref for ref in load_hermes_references()}
