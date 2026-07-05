"""Tests for model_self_check.py"""
import pytest
from ops.agents.model_self_check import run_self_check, SelfCheckResult


def _check(request, output, action_results=None, policy=None):
    return run_self_check(
        user_request=request,
        actor_output=output,
        action_results=action_results or [],
        policy_context=policy or {},
    )


def test_clean_output_returns_pass():
    result = _check(
        "show project status",
        "FINAL:\nanswer: M10 PASSED\nstatus: PASS\nevidence:\n- master_status.json\nnext:\n- none",
        action_results=[{"type": "test_result", "status": "VERIFIED_PASS"}],
    )
    assert result.status == "PASS"
    assert result.learning_candidate is False


def test_fake_command_output_detected():
    """Self-check must catch known fake output patterns."""
    result = _check(
        "list files",
        "Output:\nfile1.py 1234\nfile2.py 5678\nfile3.py 9101",
    )
    assert result.status != "PASS"
    assert result.mistake_class == "FAKE_OUTPUT"
    assert result.learning_candidate is True


def test_static_only_operational_detected():
    """Static-only answer to an operational/today query must be flagged."""
    result = _check(
        "есть ли сегодня обучение модели?",
        "According to the static schedule, training runs at 00:30 UTC.",
    )
    assert result.status != "PASS"
    assert result.mistake_class == "STATIC_ONLY_OPERATIONAL"


def test_pass_without_verifier_detected():
    """PASSED claimed without verifier evidence in action_results."""
    result = _check(
        "run the tests",
        "Tests PASSED. All checks complete.",
        action_results=[],  # no verifier result
    )
    assert result.status != "PASS"
    assert result.mistake_class == "PASS_WITHOUT_EVIDENCE"
    assert result.learning_candidate is True


def test_pass_with_verifier_accepted():
    """PASSED with real verifier result should not flag PASS_WITHOUT_EVIDENCE."""
    result = _check(
        "run the tests",
        "Tests PASSED. Status: PASS.",
        action_results=[{"type": "test_result", "status": "VERIFIED_PASS", "passed": 365}],
    )
    # The PASS claim is backed by a verifier result
    assert result.mistake_class != "PASS_WITHOUT_EVIDENCE"


def test_destructive_action_without_confirmation():
    """Destructive keyword without operator confirmation is flagged."""
    result = _check(
        "clean up",
        "I will run rm -rf /tmp/evidence to clean up.",
        policy={"confirmed_by_operator": False},
    )
    assert result.status == "POLICY_VIOLATION"
    assert result.mistake_class == "DESTRUCTIVE_UNCONFIRMED"


def test_destructive_with_confirmation_not_flagged():
    """Destructive action is allowed when confirmed_by_operator=True."""
    result = _check(
        "clean up",
        "I will run rm -rf /tmp/test_scratch to clean up.",
        policy={"confirmed_by_operator": True},
    )
    assert result.mistake_class != "DESTRUCTIVE_UNCONFIRMED"


def test_self_check_result_has_required_fields():
    result = _check("any", "any")
    assert hasattr(result, "status")
    assert hasattr(result, "mistake_class")
    assert hasattr(result, "findings")
    assert hasattr(result, "evidence_gaps")
    assert hasattr(result, "correction_recommendations")
    assert hasattr(result, "learning_candidate")
