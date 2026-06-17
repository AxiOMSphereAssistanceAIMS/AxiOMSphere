"""Terminal states for document improvement cycle.

16 possible end states route documents to appropriate handlers after
inner cycle completion.
"""
from enum import StrEnum


class TerminalState(StrEnum):
    """Final state after inner cycle completes."""

    INPUT_BLOCKED = "input_blocked"
    VALIDATION_FAILED = "validation_failed"
    REPAIR_REQUIRED = "repair_required"
    REPAIR_REJECTED_DATA_LOSS = "repair_rejected_data_loss"
    PLATEAU_DETECTED = "plateau_detected"
    MAX_ITERATIONS_REACHED = "max_iterations_reached"
    READY_FOR_REVIEW = "ready_for_review"
    QUALITY_TARGET_EXCEEDED = "quality_target_exceeded"
    READY_FOR_BEST_VERSION_SELECTION = "ready_for_best_version_selection"
    READY_FOR_REGISTRATION = "ready_for_registration"
    REGISTRATION_COMPLETED = "registration_completed"
    OPERATOR_REVIEW_REQUIRED = "operator_review_required"
    SKILL_CREATION_REQUIRED = "skill_creation_required"
    POLICY_PATCH_REQUIRED = "policy_patch_required"
    TRAINING_DATASET_REQUIRED = "training_dataset_required"
    UNKNOWN_FAILURE_REQUIRES_TRIAGE = "unknown_failure_requires_triage"
