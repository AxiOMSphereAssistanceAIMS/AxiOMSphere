"""
Canonical gate contract for DOCGEN quality evaluation.

Defines the single source of truth for gate vocabulary, normalization,
and validation across all evaluation modules (BaselineEvalMinimal,
determine_final_verdict, promotion logic).

This module enforces a strict contract between evaluator (producer)
and verdict router (consumer), preventing vocabulary drift and
polarity confusion.
"""

from dataclasses import dataclass
from typing import Dict, Any, Set


# Canonical gate definitions
# Each gate has: name, description, polarity (True = pass is True, False = pass is False)
CANONICAL_GATE_KEYS: Dict[str, Dict[str, Any]] = {
    # Phase 1: Hard blockers — must all be True to avoid BLOCKED verdict
    "all_required_blocks_generated": {
        "description": "All required document sections were successfully generated",
        "polarity": "positive",  # True = good
        "phase": 1,
    },
    "render_success": {
        "description": "Document successfully rendered to DOCX format",
        "polarity": "positive",
        "phase": 1,
    },
    "no_critical_issues": {
        "description": "Document contains no CRITICAL severity issues",
        "polarity": "positive",
        "phase": 1,
    },

    # Phase 2: Repairable issues — guide routing to NEEDS_MORE_REPAIR
    "no_duplicate_blocks": {
        "description": "Document contains no duplicate content blocks",
        "polarity": "positive",
        "phase": 2,
    },
    "no_placeholder_content": {
        "description": "Document contains no placeholder/TODO text",
        "polarity": "positive",
        "phase": 2,
    },
    "evidence_complete": {
        "description": "All required evidence artifacts are staged and ready",
        "polarity": "positive",
        "phase": 2,
    },
    "audit_pass": {
        "description": "Document audit completed successfully without blocking issues",
        "polarity": "positive",
        "phase": 2,
    },

    # Phase 3: Quality gates — determine PASS vs READY_WITH_WARNINGS
    "baseline_score_acceptable": {
        "description": "Baseline quality score meets or exceeds minimum threshold",
        "polarity": "positive",
        "phase": 3,
    },
    "no_internal_metadata_leaks": {
        "description": "No internal metadata appears in user-facing document content",
        "polarity": "positive",
        "phase": 3,
    },
    "coherence_acceptable": {
        "description": "Document coherence score meets minimum requirements",
        "polarity": "positive",
        "phase": 3,
    },
    "structure_correct": {
        "description": "Document structure matches type-specific requirements",
        "polarity": "positive",
        "phase": 3,
    },

    # Phase 4: Training signal gates — determine if document should contribute to training
    "training_pairs_available": {
        "description": "Document generated enough training pair candidates for model improvement",
        "polarity": "positive",
        "phase": 4,
    },
    "improvement_over_baseline": {
        "description": "Document quality improvement exceeds minimum delta threshold",
        "polarity": "positive",
        "phase": 4,
    },
    "regression_within_tolerance": {
        "description": "No metric regression exceeds tolerance bounds",
        "polarity": "positive",
        "phase": 4,
    },
}


@dataclass(frozen=True)
class GateStatus:
    """Immutable record of a single gate evaluation."""
    name: str
    value: bool
    polarity: str
    reason: str = ""


def assert_canonical_gates(gates_dict: Dict[str, Any], phase: int = None) -> None:
    """
    Validate that gates dict contains only canonical gate keys for the given phase.

    Args:
        gates_dict: Dictionary of gate name → boolean value
        phase: Optional phase filter (1-4); if provided, only validate gates for that phase

    Raises:
        ValueError: If non-canonical gates are present or polarity is inconsistent
    """
    canonical_names = {
        k for k, v in CANONICAL_GATE_KEYS.items()
        if phase is None or v.get("phase") == phase
    }

    # Check for non-canonical gates
    for gate_name in gates_dict.keys():
        if gate_name not in canonical_names:
            raise ValueError(
                f"Non-canonical gate '{gate_name}' found. "
                f"Allowed gates for phase {phase}: {canonical_names}"
            )


def normalize_gates(
    producer_gates: Dict[str, Any],
    producer_type: str = "baseline_eval",
    invert_flags: Dict[str, str] = None,
) -> Dict[str, bool]:
    """
    Convert producer-specific gate vocabulary to canonical gates.

    This is the ONLY place where legacy gate names should be mapped.
    All consumers should use canonical names only.

    Args:
        producer_gates: Gates dict from evaluator (e.g., BaselineEvalMinimal._build_gates())
        producer_type: Type of producer ("baseline_eval", "audit", etc.)
        invert_flags: Optional dict mapping producer gate names to their canonical
                     counterparts when the polarity is inverted

    Returns:
        Dict with canonical gate names as keys and boolean values

    Example:
        # BaselineEvalMinimal produces "required_blocks_present"
        # but canonical is "all_required_blocks_generated" with same polarity
        normalized = normalize_gates(
            producer_gates={"required_blocks_present": True, ...},
            producer_type="baseline_eval",
        )
        # Returns {"all_required_blocks_generated": True, ...}
    """
    invert_flags = invert_flags or {}
    normalized: Dict[str, bool] = {}

    # Mapping from producer gate names to canonical names
    # (organized by producer_type)
    mappings = {
        "baseline_eval": {
            "required_blocks_present": "all_required_blocks_generated",
            "no_critical_issues": "no_critical_issues",
            "render_success": "render_success",
            "no_duplicate_blocks": "no_duplicate_blocks",
            "no_placeholder_content": "no_placeholder_content",
            "evidence_complete": "evidence_complete",
            "audit_pass": "audit_pass",
        },
        "audit": {
            "no_critical_findings": "no_critical_issues",
            "audit_complete": "audit_pass",
        },
    }

    producer_mapping = mappings.get(producer_type, {})

    for producer_name, producer_value in producer_gates.items():
        if producer_name not in producer_mapping:
            # Check if this is already a canonical gate name (e.g., training_pairs_available from Phase 4)
            # If so, pass it through unchanged; otherwise skip it
            if producer_name in CANONICAL_GATE_KEYS:
                normalized[producer_name] = producer_value
            # else: skip unmapped, non-canonical gates
            continue

        canonical_name = producer_mapping[producer_name]

        # Apply polarity inversion if needed
        if producer_name in invert_flags:
            canonical_value = not producer_value
        else:
            canonical_value = producer_value

        normalized[canonical_name] = canonical_value

    return normalized


def get_canonical_gate(
    gates: Dict[str, Any],
    canonical_name: str,
    default: bool = False,
) -> bool:
    """
    Safely retrieve a canonical gate value with fallback.

    Args:
        gates: Dictionary of canonical gates
        canonical_name: Name of the gate to retrieve
        default: Value to return if gate not found

    Returns:
        Boolean value of the gate

    Raises:
        ValueError: If canonical_name is not a valid canonical gate
    """
    if canonical_name not in CANONICAL_GATE_KEYS:
        raise ValueError(
            f"Unknown canonical gate '{canonical_name}'. "
            f"Valid gates: {list(CANONICAL_GATE_KEYS.keys())}"
        )

    return gates.get(canonical_name, default)


def get_phase_gates(gates: Dict[str, Any], phase: int) -> Dict[str, bool]:
    """
    Extract only the gates for a specific phase.

    Args:
        gates: Full dictionary of canonical gates
        phase: Phase number (1-4)

    Returns:
        Subset of gates dict containing only phase gates
    """
    phase_gate_names = {
        k for k, v in CANONICAL_GATE_KEYS.items()
        if v.get("phase") == phase
    }

    return {k: v for k, v in gates.items() if k in phase_gate_names}


def validate_gate_value(
    gate_name: str,
    gate_value: Any,
    expected_type: type = bool,
) -> bool:
    """
    Validate that a gate has the expected type and valid value.

    Args:
        gate_name: Name of the gate
        gate_value: Value of the gate
        expected_type: Expected type (default: bool)

    Returns:
        True if valid

    Raises:
        TypeError: If gate value has wrong type
        ValueError: If gate is non-canonical
    """
    if gate_name not in CANONICAL_GATE_KEYS:
        raise ValueError(f"Non-canonical gate '{gate_name}'")

    if not isinstance(gate_value, expected_type):
        raise TypeError(
            f"Gate '{gate_name}' has type {type(gate_value).__name__}, "
            f"expected {expected_type.__name__}"
        )

    return True


def describe_gate_policy(gate_name: str) -> str:
    """
    Return a human-readable description of a gate's policy and purpose.

    Args:
        gate_name: Name of the canonical gate

    Returns:
        Formatted policy description
    """
    if gate_name not in CANONICAL_GATE_KEYS:
        return f"Unknown gate: {gate_name}"

    gate_def = CANONICAL_GATE_KEYS[gate_name]
    return (
        f"{gate_name} (Phase {gate_def['phase']}, {gate_def['polarity']}):\n"
        f"  {gate_def['description']}"
    )
