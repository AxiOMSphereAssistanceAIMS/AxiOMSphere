"""
Tests for DOCGEN gate contract validation and normalization.

Validates the canonical gate system, normalization functions, and
polarity handling for consistent gate vocabulary across all evaluators.
"""

import pytest
from ops.docgen.gate_contract import (
    CANONICAL_GATE_KEYS,
    normalize_gates,
    assert_canonical_gates,
    get_canonical_gate,
    get_phase_gates,
    validate_gate_value,
    describe_gate_policy,
)


class TestCanonicalGateDefinitions:
    """Test canonical gate definitions and structure."""

    def test_canonical_gates_dict_exists(self):
        """Test that CANONICAL_GATE_KEYS dict is properly defined."""
        assert isinstance(CANONICAL_GATE_KEYS, dict)
        assert len(CANONICAL_GATE_KEYS) >= 14

    def test_all_gates_have_required_fields(self):
        """Test that each gate definition has required fields."""
        for gate_name, gate_def in CANONICAL_GATE_KEYS.items():
            assert "description" in gate_def
            assert "polarity" in gate_def
            assert "phase" in gate_def
            assert gate_def["polarity"] in ("positive", "negative")
            assert gate_def["phase"] in (1, 2, 3, 4)

    def test_phase1_gates_are_blockers(self):
        """Test that Phase 1 gates are hard blockers."""
        phase1_gates = {k for k, v in CANONICAL_GATE_KEYS.items() if v["phase"] == 1}
        assert "all_required_blocks_generated" in phase1_gates
        assert "render_success" in phase1_gates
        assert "no_critical_issues" in phase1_gates

    def test_phase2_gates_are_repairable(self):
        """Test that Phase 2 gates are repairable issues."""
        phase2_gates = {k for k, v in CANONICAL_GATE_KEYS.items() if v["phase"] == 2}
        assert "no_duplicate_blocks" in phase2_gates
        assert "no_placeholder_content" in phase2_gates
        assert "evidence_complete" in phase2_gates

    def test_phase3_gates_are_quality(self):
        """Test that Phase 3 gates are quality gates."""
        phase3_gates = {k for k, v in CANONICAL_GATE_KEYS.items() if v["phase"] == 3}
        assert "baseline_score_acceptable" in phase3_gates
        assert "no_internal_metadata_leaks" in phase3_gates
        assert "structure_correct" in phase3_gates

    def test_phase4_gates_are_training_signals(self):
        """Test that Phase 4 gates are training signal gates."""
        phase4_gates = {k for k, v in CANONICAL_GATE_KEYS.items() if v["phase"] == 4}
        assert "training_pairs_available" in phase4_gates
        assert "improvement_over_baseline" in phase4_gates
        assert "regression_within_tolerance" in phase4_gates


class TestNormalizeGates:
    """Test gate normalization from producer-specific to canonical vocabulary."""

    def test_normalize_gates_baseline_eval_basic(self):
        """Test basic normalization from baseline_eval producer."""
        producer_gates = {
            "required_blocks_present": True,
            "render_success": True,
            "no_critical_issues": True,
        }

        normalized = normalize_gates(producer_gates, producer_type="baseline_eval")

        assert normalized["all_required_blocks_generated"] is True
        assert normalized["render_success"] is True
        assert normalized["no_critical_issues"] is True

    def test_normalize_gates_all_baseline_eval_fields(self):
        """Test normalization of all baseline_eval fields."""
        producer_gates = {
            "required_blocks_present": True,
            "no_critical_issues": True,
            "render_success": True,
            "no_duplicate_blocks": False,
            "no_placeholder_content": False,
            "evidence_complete": True,
            "audit_pass": True,
        }

        normalized = normalize_gates(producer_gates, producer_type="baseline_eval")

        assert normalized["all_required_blocks_generated"] is True
        assert normalized["no_critical_issues"] is True
        assert normalized["render_success"] is True
        assert normalized["no_duplicate_blocks"] is False
        assert normalized["no_placeholder_content"] is False
        assert normalized["evidence_complete"] is True
        assert normalized["audit_pass"] is True

    def test_normalize_gates_audit_producer(self):
        """Test normalization from audit producer with inverted gates."""
        producer_gates = {
            "no_critical_findings": True,
            "audit_complete": True,
        }

        normalized = normalize_gates(producer_gates, producer_type="audit")

        assert normalized["no_critical_issues"] is True
        assert normalized["audit_pass"] is True

    def test_normalize_gates_skips_unmapped_fields(self):
        """Test that unmapped fields are skipped during normalization."""
        producer_gates = {
            "required_blocks_present": True,
            "unknown_field": True,  # Not in mapping
            "another_unknown": False,
        }

        normalized = normalize_gates(producer_gates, producer_type="baseline_eval")

        assert "all_required_blocks_generated" in normalized
        assert "unknown_field" not in normalized
        assert "another_unknown" not in normalized

    def test_normalize_gates_empty_input(self):
        """Test normalization with empty input."""
        normalized = normalize_gates({}, producer_type="baseline_eval")

        assert isinstance(normalized, dict)
        assert len(normalized) == 0

    def test_normalize_gates_preserves_false_values(self):
        """Test that False values are preserved during normalization."""
        producer_gates = {
            "required_blocks_present": False,
            "render_success": False,
        }

        normalized = normalize_gates(producer_gates, producer_type="baseline_eval")

        assert normalized["all_required_blocks_generated"] is False
        assert normalized["render_success"] is False


class TestAssertCanonicalGates:
    """Test gate validation and canonicality assertions."""

    def test_assert_canonical_gates_valid(self):
        """Test that valid canonical gates pass validation."""
        gates = {
            "all_required_blocks_generated": True,
            "render_success": True,
            "no_critical_issues": True,
        }

        # Should not raise
        assert_canonical_gates(gates)

    def test_assert_canonical_gates_non_canonical_raises(self):
        """Test that non-canonical gates raise ValueError."""
        gates = {
            "all_required_blocks_generated": True,
            "invalid_gate_name": True,
        }

        with pytest.raises(ValueError) as exc_info:
            assert_canonical_gates(gates)

        assert "Non-canonical gate" in str(exc_info.value)
        assert "invalid_gate_name" in str(exc_info.value)

    def test_assert_canonical_gates_phase_filter(self):
        """Test that phase filter works correctly."""
        # Phase 1 gates only
        phase1_gates = {
            "all_required_blocks_generated": True,
            "render_success": True,
        }

        # Should not raise for phase 1
        assert_canonical_gates(phase1_gates, phase=1)

        # Should raise if we try phase 2 filter (phase 2 gate not in phase1_gates)
        phase2_gates = {
            "no_duplicate_blocks": True,
        }

        # No error because phase2_gates contains no phase 1 gates
        assert_canonical_gates(phase2_gates, phase=2)

    def test_assert_canonical_gates_empty_dict(self):
        """Test that empty gates dict is valid."""
        # Should not raise
        assert_canonical_gates({})
        assert_canonical_gates({}, phase=1)


class TestGetCanonicalGate:
    """Test safe retrieval of canonical gate values."""

    def test_get_canonical_gate_exists(self):
        """Test retrieval of existing gate."""
        gates = {
            "all_required_blocks_generated": True,
            "render_success": False,
        }

        assert get_canonical_gate(gates, "all_required_blocks_generated") is True
        assert get_canonical_gate(gates, "render_success") is False

    def test_get_canonical_gate_missing_returns_default(self):
        """Test that missing gate returns default value."""
        gates = {"all_required_blocks_generated": True}

        assert get_canonical_gate(gates, "render_success", default=False) is False
        assert get_canonical_gate(gates, "render_success", default=True) is True

    def test_get_canonical_gate_invalid_name_raises(self):
        """Test that invalid canonical name raises ValueError."""
        gates = {"all_required_blocks_generated": True}

        with pytest.raises(ValueError) as exc_info:
            get_canonical_gate(gates, "invalid_gate_name")

        assert "Unknown canonical gate" in str(exc_info.value)

    def test_get_canonical_gate_default_default_is_false(self):
        """Test that default value for missing gate is False."""
        gates = {}

        assert get_canonical_gate(gates, "all_required_blocks_generated") is False


class TestGetPhaseGates:
    """Test extraction of phase-specific gates."""

    def test_get_phase_gates_phase1(self):
        """Test extraction of Phase 1 gates."""
        gates = {
            "all_required_blocks_generated": True,
            "render_success": True,
            "no_critical_issues": True,
            "no_duplicate_blocks": False,  # Phase 2, should be excluded
        }

        phase1 = get_phase_gates(gates, phase=1)

        assert "all_required_blocks_generated" in phase1
        assert "render_success" in phase1
        assert "no_critical_issues" in phase1
        assert "no_duplicate_blocks" not in phase1

    def test_get_phase_gates_phase2(self):
        """Test extraction of Phase 2 gates."""
        gates = {
            "no_duplicate_blocks": True,
            "no_placeholder_content": False,
            "evidence_complete": True,
            "audit_pass": False,
            "all_required_blocks_generated": True,  # Phase 1, should be excluded
        }

        phase2 = get_phase_gates(gates, phase=2)

        assert "no_duplicate_blocks" in phase2
        assert "no_placeholder_content" in phase2
        assert "evidence_complete" in phase2
        assert "audit_pass" in phase2
        assert "all_required_blocks_generated" not in phase2

    def test_get_phase_gates_empty_for_phase(self):
        """Test that phases with no gates return empty dict."""
        gates = {
            "all_required_blocks_generated": True,
        }

        # phase 4 gates not in input
        phase4 = get_phase_gates(gates, phase=4)

        assert len(phase4) == 0
        assert isinstance(phase4, dict)


class TestValidateGateValue:
    """Test gate value validation."""

    def test_validate_gate_value_valid_bool(self):
        """Test validation of valid boolean gate value."""
        assert validate_gate_value("all_required_blocks_generated", True) is True
        assert validate_gate_value("render_success", False) is True

    def test_validate_gate_value_non_canonical_raises(self):
        """Test that non-canonical gate raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            validate_gate_value("invalid_gate", True)

        assert "Non-canonical gate" in str(exc_info.value)

    def test_validate_gate_value_wrong_type_raises(self):
        """Test that wrong type raises TypeError."""
        with pytest.raises(TypeError) as exc_info:
            validate_gate_value("all_required_blocks_generated", "true")

        assert "has type str" in str(exc_info.value)
        assert "expected bool" in str(exc_info.value)

    def test_validate_gate_value_none_raises(self):
        """Test that None value raises TypeError."""
        with pytest.raises(TypeError):
            validate_gate_value("render_success", None)


class TestDescribeGatePolicy:
    """Test gate policy descriptions."""

    def test_describe_gate_policy_valid_gate(self):
        """Test description of valid canonical gate."""
        description = describe_gate_policy("all_required_blocks_generated")

        assert "all_required_blocks_generated" in description
        assert "Phase" in description
        assert "positive" in description or "negative" in description

    def test_describe_gate_policy_unknown_gate(self):
        """Test description of unknown gate."""
        description = describe_gate_policy("invalid_gate")

        assert "Unknown gate" in description

    def test_describe_gate_policy_includes_details(self):
        """Test that description includes full details."""
        description = describe_gate_policy("render_success")

        assert "render_success" in description
        assert "Phase" in description
        assert "positive" in description


class TestGateContractIntegration:
    """Integration tests for gate contract workflow."""

    def test_full_workflow_baseline_eval_to_canonical(self):
        """Test full workflow from BaselineEvalMinimal to canonical gates."""
        # Simulate BaselineEvalMinimal output
        producer_gates = {
            "required_blocks_present": True,
            "no_critical_issues": True,
            "render_success": True,
            "no_duplicate_blocks": False,
            "no_placeholder_content": False,
            "evidence_complete": True,
            "audit_pass": True,
        }

        # Normalize to canonical
        canonical = normalize_gates(producer_gates, producer_type="baseline_eval")

        # Validate canonicality
        assert_canonical_gates(canonical)

        # Extract Phase 1 gates
        phase1 = get_phase_gates(canonical, phase=1)

        assert "all_required_blocks_generated" in phase1
        assert "render_success" in phase1
        assert phase1["all_required_blocks_generated"] is True

    def test_gate_contract_prevents_vocabulary_drift(self):
        """Test that gate contract prevents producer/consumer vocabulary drift."""
        # If BaselineEvalMinimal ever outputs a different name, normalization catches it
        producer_gates = {
            "required_blocks": True,  # Slightly different name
            "render_success": True,
        }

        normalized = normalize_gates(producer_gates, producer_type="baseline_eval")

        # The misnamed gate is skipped
        assert "required_blocks" not in normalized
        assert "all_required_blocks_generated" not in normalized
        assert normalized["render_success"] is True

    def test_validation_after_normalization(self):
        """Test that validated gates pass through normalization."""
        producer_gates = {
            "required_blocks_present": True,
            "render_success": True,
            "no_critical_issues": False,
        }

        # Normalize
        canonical = normalize_gates(producer_gates, producer_type="baseline_eval")

        # All gates should pass validation
        for gate_name, gate_value in canonical.items():
            assert validate_gate_value(gate_name, gate_value) is True
