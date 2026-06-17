"""
DOCSREG Registration Precheck — unit tests.

Validates all 8 gates, aggregate verdict logic, minimal precheck API,
and can_proceed semantics.

Run:
  PYTHONPATH=/home/axi_omi_sphere/aims-workspace \
    python -m pytest ops/tests/test_docsreg_registration_precheck.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ops.agents.skills.docsreg_registration_precheck import (
    DEFAULT_COVERAGE_THRESHOLD,
    DEFAULT_QUALITY_THRESHOLD,
    PRECHECK_VERSION,
    GateVerdict,
    PrecheckResult,
    RegistrationGate,
    conflict_gate,
    duplicate_gate,
    evidence_gate,
    quality_gate,
    reference_governance_gate,
    run_registration_precheck,
    run_registration_precheck_minimal,
    section_coverage_gate,
    traceability_gate,
    write_policy_gate,
)


# ── Document builders ──────────────────────────────────────────────────────────

def _clean_doc() -> str:
    return (
        "### 1.0 Introduction\n\n"
        "This document covers asset integrity management per ISO 55001.\n"
        "Requirements apply across all asset classes.\n"
    )


def _doc_with_api_ref() -> str:
    return (
        "### 6.2 Inspection\n\n"
        "Inspection intervals governed by API 580 risk-based inspection code.\n"
    )


def _doc_with_iso_only() -> str:
    return (
        "### 1.0 Scope\n\n"
        "This document is governed by ISO 55001:2014 requirements.\n"
        "Asset management per ISO 55001 is mandatory.\n"
    )


# ── Test 1: Clean doc + high scores → PASS + can_proceed ──────────────────────


class TestCleanDocQualityPass:
    def test_can_proceed_is_true(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert result.can_proceed is True

    def test_overall_verdict_is_pass(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert result.overall_verdict == GateVerdict.PASS

    def test_no_blocking_gates(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert result.blocking_gates == []

    def test_all_8_gates_present(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert len(result.gates_run) == 8


# ── Test 2: Fabricated ref → FAIL + can_proceed=False ─────────────────────────


class TestFabricatedRefBlocksPrecheck:
    def test_fabricated_ref_blocks_precheck(self):
        result = run_registration_precheck(
            document=_doc_with_api_ref(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert result.can_proceed is False

    def test_overall_verdict_is_fail(self):
        result = run_registration_precheck(
            document=_doc_with_api_ref(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert result.overall_verdict == GateVerdict.FAIL

    def test_reference_governance_in_blocking_gates(self):
        result = run_registration_precheck(
            document=_doc_with_api_ref(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert RegistrationGate.REFERENCE_GOVERNANCE.value in result.blocking_gates


# ── Test 3: Low quality score → FAIL ──────────────────────────────────────────


class TestLowQualityBlocksPrecheck:
    def test_low_quality_blocks_precheck(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.70,
            completeness_ratio=0.90,
        )
        assert result.can_proceed is False

    def test_quality_gate_in_blocking_gates(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.70,
            completeness_ratio=0.90,
        )
        assert RegistrationGate.QUALITY.value in result.blocking_gates

    def test_custom_threshold_passes_high_score(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.70,
            completeness_ratio=0.90,
            quality_threshold=0.65,
        )
        # With lower threshold 0.65, score 0.70 should pass quality gate
        assert RegistrationGate.QUALITY.value not in result.blocking_gates


# ── Test 4: Low coverage ratio → FAIL ─────────────────────────────────────────


class TestLowCoverageBlocksPrecheck:
    def test_low_coverage_blocks_precheck(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.50,
        )
        assert result.can_proceed is False

    def test_section_coverage_in_blocking_gates(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.50,
        )
        assert RegistrationGate.SECTION_COVERAGE.value in result.blocking_gates


# ── Test 5: Both fabricated ref and low quality → FAIL ───────────────────────


class TestBothRefAndQualityBlocks:
    def test_both_blockers_in_blocking_gates(self):
        result = run_registration_precheck(
            document=_doc_with_api_ref(),
            overall_score=0.60,
            completeness_ratio=0.90,
        )
        assert RegistrationGate.REFERENCE_GOVERNANCE.value in result.blocking_gates
        assert RegistrationGate.QUALITY.value in result.blocking_gates

    def test_can_proceed_is_false(self):
        result = run_registration_precheck(
            document=_doc_with_api_ref(),
            overall_score=0.60,
            completeness_ratio=0.90,
        )
        assert result.can_proceed is False

    def test_multiple_blocking_gates_reported(self):
        result = run_registration_precheck(
            document=_doc_with_api_ref(),
            overall_score=0.60,
            completeness_ratio=0.90,
        )
        assert len(result.blocking_gates) >= 2


# ── Test 6: SKIPPED gates don't affect verdict ────────────────────────────────


class TestSkippedGatesDontBlock:
    def test_skipped_gates_dont_block(self):
        # source_documents=None → TRACEABILITY SKIPPED
        # registry_check=None → DUPLICATE, CONFLICT SKIPPED
        # evidence_paths=None → EVIDENCE SKIPPED
        # write_policy=None → WRITE_POLICY SKIPPED
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert result.can_proceed is True

    def test_skipped_gates_are_not_in_blocking_gates(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        skipped_gates = {
            RegistrationGate.TRACEABILITY.value,
            RegistrationGate.DUPLICATE.value,
            RegistrationGate.CONFLICT.value,
            RegistrationGate.EVIDENCE.value,
            RegistrationGate.WRITE_POLICY.value,
        }
        for gate_name in skipped_gates:
            assert gate_name not in result.blocking_gates


# ── Test 7: minimal precheck returns plain dict ───────────────────────────────


class TestMinimalPrecheckReturnsDict:
    def test_minimal_precheck_returns_dict(self):
        result = run_registration_precheck_minimal(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert isinstance(result, dict)

    def test_minimal_precheck_has_expected_keys(self):
        result = run_registration_precheck_minimal(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        expected_keys = {
            "overall_verdict", "blocking_gates", "warnings",
            "can_proceed", "gates", "precheck_version",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_minimal_precheck_pass_can_proceed(self):
        result = run_registration_precheck_minimal(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert result["can_proceed"] is True
        assert result["overall_verdict"] == "PASS"

    def test_minimal_precheck_fail_on_fabricated(self):
        result = run_registration_precheck_minimal(
            document=_doc_with_api_ref(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert result["can_proceed"] is False
        assert result["overall_verdict"] == "FAIL"

    def test_minimal_precheck_has_3_gates(self):
        result = run_registration_precheck_minimal(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert len(result["gates"]) == 3


# ── Test 8: PrecheckResult has all gate results ───────────────────────────────


class TestPrecheckResultHasAllGateResults:
    def test_precheck_result_is_dataclass(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert isinstance(result, PrecheckResult)

    def test_gates_run_contains_all_8_gates(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        gate_names = {r.gate for r in result.gates_run}
        assert gate_names == set(RegistrationGate)

    def test_each_gate_result_has_verdict(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        for gr in result.gates_run:
            assert isinstance(gr.verdict, GateVerdict)


# ── Test 9: precheck_version is v1 ───────────────────────────────────────────


class TestPrecheckVersionIsV1:
    def test_precheck_version_is_v1(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert result.precheck_version == "v1"

    def test_minimal_precheck_version_is_v1(self):
        result = run_registration_precheck_minimal(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
        )
        assert result["precheck_version"] == "v1"

    def test_constant_is_v1(self):
        assert PRECHECK_VERSION == "v1"


# ── Test 10: write policy BLOCKED → FAIL ──────────────────────────────────────


class TestWritePolicyBlockedFails:
    def test_write_policy_blocked_fails(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
            write_policy="BLOCKED",
        )
        assert result.can_proceed is False

    def test_write_policy_blocked_in_blocking_gates(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
            write_policy="BLOCKED",
        )
        assert RegistrationGate.WRITE_POLICY.value in result.blocking_gates

    def test_write_policy_allow_passes(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
            write_policy="ALLOW",
        )
        assert RegistrationGate.WRITE_POLICY.value not in result.blocking_gates

    def test_write_policy_dry_run_passes(self):
        result = run_registration_precheck(
            document=_clean_doc(),
            overall_score=0.97,
            completeness_ratio=0.90,
            write_policy="DRY_RUN",
        )
        assert RegistrationGate.WRITE_POLICY.value not in result.blocking_gates


# ── Individual gate unit tests ─────────────────────────────────────────────────


class TestQualityGateUnit:
    def test_passes_at_threshold(self):
        assert quality_gate(0.95).verdict == GateVerdict.PASS

    def test_passes_above_threshold(self):
        assert quality_gate(0.99).verdict == GateVerdict.PASS

    def test_fails_below_threshold(self):
        assert quality_gate(0.94).verdict == GateVerdict.FAIL

    def test_custom_threshold(self):
        assert quality_gate(0.80, threshold=0.75).verdict == GateVerdict.PASS
        assert quality_gate(0.74, threshold=0.75).verdict == GateVerdict.FAIL


class TestSectionCoverageGateUnit:
    def test_passes_at_threshold(self):
        assert section_coverage_gate(0.85).verdict == GateVerdict.PASS

    def test_fails_below_threshold(self):
        assert section_coverage_gate(0.84).verdict == GateVerdict.FAIL

    def test_custom_threshold(self):
        assert section_coverage_gate(0.60, threshold=0.55).verdict == GateVerdict.PASS


class TestTraceabilityGateUnit:
    def test_skipped_when_none(self):
        assert traceability_gate(None).verdict == GateVerdict.SKIPPED

    def test_passes_with_sources(self):
        assert traceability_gate(["source1.txt"]).verdict == GateVerdict.PASS

    def test_fails_with_empty_list(self):
        assert traceability_gate([]).verdict == GateVerdict.FAIL


class TestDuplicateGateUnit:
    def test_skipped_when_none(self):
        assert duplicate_gate(None).verdict == GateVerdict.SKIPPED

    def test_fails_when_duplicate_found(self):
        assert duplicate_gate({"duplicate_found": True, "existing_id": "DOC-001"}).verdict == GateVerdict.FAIL

    def test_passes_when_no_duplicate(self):
        assert duplicate_gate({"duplicate_found": False}).verdict == GateVerdict.PASS


class TestConflictGateUnit:
    def test_skipped_when_none(self):
        assert conflict_gate(None).verdict == GateVerdict.SKIPPED

    def test_fails_when_conflict_found(self):
        assert conflict_gate({"conflict_found": True, "conflict_reason": "version mismatch"}).verdict == GateVerdict.FAIL

    def test_passes_when_no_conflict(self):
        assert conflict_gate({"conflict_found": False}).verdict == GateVerdict.PASS


class TestEvidenceGateUnit:
    def test_skipped_when_none(self):
        assert evidence_gate(None).verdict == GateVerdict.SKIPPED

    def test_passes_when_files_exist(self, tmp_path):
        f1 = tmp_path / "metrics.json"
        f1.write_text("{}")
        f2 = tmp_path / "draft.md"
        f2.write_text("# Draft")
        assert evidence_gate([str(f1), str(f2)]).verdict == GateVerdict.PASS

    def test_fails_when_file_missing(self, tmp_path):
        f1 = tmp_path / "metrics.json"
        f1.write_text("{}")
        missing = str(tmp_path / "nonexistent.json")
        result = evidence_gate([str(f1), missing])
        assert result.verdict == GateVerdict.FAIL
        assert missing in result.details.get("missing_paths", [])


class TestReferenceGovernanceGateUnit:
    def test_pass_on_clean_doc(self):
        result = reference_governance_gate(_clean_doc())
        assert result.verdict == GateVerdict.PASS

    def test_fail_on_fabricated_doc(self):
        result = reference_governance_gate(_doc_with_api_ref())
        assert result.verdict == GateVerdict.FAIL

    def test_pass_on_iso_only_doc(self):
        result = reference_governance_gate(_doc_with_iso_only())
        assert result.verdict == GateVerdict.PASS

    def test_repair_plan_in_details_on_fail(self):
        result = reference_governance_gate(_doc_with_api_ref())
        assert "repair_plan" in result.details
        assert len(result.details["repair_plan"]) >= 1
