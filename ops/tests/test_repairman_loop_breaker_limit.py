from ops.orchestrator_planning.repairman_loop_breaker import (
    CLOSURE_FAILED_LIMIT,
    evaluate_attempt_sequence,
)
from ops.orchestrator_planning.repairman_test_rerun_loop import run_test_rerun_loop


def _attempt(number):
    return {
        "failure_signature": "same",
        "attempted_fix": f"fix-{number}",
        "test_result": "FAIL",
        "test_command": f"pytest case-{number}",
    }


def test_attempt_sequence_stops_at_configured_limit():
    result = evaluate_attempt_sequence(
        [_attempt(number) for number in range(1, 6)],
        max_attempts=3,
    )

    assert result["closure_state"] == CLOSURE_FAILED_LIMIT
    assert result["repair_attempts"] == 3
    assert result["attempted_fixes"] == ["fix-1", "fix-2", "fix-3"]
    assert "3 Hermes-reviewed" in result["reason_for_stop"]


def test_rerun_loop_does_not_expose_attempts_beyond_limit():
    result = run_test_rerun_loop(
        {"attempts": [_attempt(number) for number in range(1, 6)]},
        max_attempts=3,
    )

    assert len(result["attempts"]) == 3
    assert len(result["test_commands"]) == 3
    assert result["decision"]["repair_attempts"] == 3
