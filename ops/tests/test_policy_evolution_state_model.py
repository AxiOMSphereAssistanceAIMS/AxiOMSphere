import pytest

from ops.policy_evolution.state_model import RepairLifecycle, validate_projection


def test_repair_lifecycle_has_deterministic_next_actions_and_restart_path():
    case = RepairLifecycle.start()
    for state in ("DIAGNOSED", "PROPOSAL_READY", "AUDIT_REQUIRED", "AUDITED", "POLICY_EVALUATION", "AUTHORIZED", "QUEUED", "EXECUTING", "STALLED", "REVALIDATION_REQUIRED", "REVALIDATING", "READY_FOR_NEW_PERMIT", "PERMIT_ISSUED", "RESTART_QUEUED", "RESTARTING", "EXECUTING", "VERIFYING", "COMPLETED_VERIFIED"):
        case = case.transition(state)
    assert case.to_dict() == {"state": "COMPLETED_VERIFIED", "next_action_id": "NONE"}


def test_invalid_transition_and_projection_are_rejected():
    with pytest.raises(ValueError, match="INVALID_REPAIR_TRANSITION"):
        RepairLifecycle.start().transition("COMPLETED_VERIFIED")
    with pytest.raises(ValueError, match="NEXT_ACTION_STATE_MISMATCH"):
        validate_projection({"state": "STALLED", "next_action_id": "NONE"})
