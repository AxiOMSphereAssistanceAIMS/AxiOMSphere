"""
Tests for ops/docsreg/docsreg_model_output_contract.py

Coverage areas
--------------
1. ContractCheckResult dataclass — field types, defaults, passed semantics
2. Empty model output — empty string, whitespace-only, None input
3. Malformed JSON — broken JSON, non-JSON text, incomplete JSON
4. Missing edits field — valid JSON without "edits", "edits": null
5. PASS cases — empty edits list, single edit dict, multiple edits, extra fields
6. Never-raises guarantee — all failure paths return ContractCheckResult
"""
from __future__ import annotations

import json

import pytest

from ops.docsreg.docsreg_model_output_contract import (
    EMPTY_MODEL_OUTPUT,
    MALFORMED_JSON,
    MISSING_EDITS_FIELD,
    PASS,
    ContractCheckResult,
    check_model_output,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _dumps(obj) -> str:
    return json.dumps(obj)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ContractCheckResult dataclass
# ═══════════════════════════════════════════════════════════════════════════════


class TestContractCheckResultDataclass:
    """Field types, defaults, and passed=True iff status==PASS."""

    def test_status_is_string(self):
        r = ContractCheckResult(
            status=PASS, passed=True, raw_output="{}", parsed={}, edits=[]
        )
        assert isinstance(r.status, str)

    def test_passed_true_when_status_pass(self):
        r = ContractCheckResult(
            status=PASS, passed=True, raw_output="{}", parsed={}, edits=[]
        )
        assert r.passed is True

    def test_passed_false_for_non_pass_statuses(self):
        for status in (EMPTY_MODEL_OUTPUT, MALFORMED_JSON, MISSING_EDITS_FIELD):
            r = ContractCheckResult(
                status=status, passed=False, raw_output="", parsed=None, edits=None
            )
            assert r.passed is False, f"expected passed=False for status={status}"

    def test_violations_defaults_to_empty_list(self):
        r = ContractCheckResult(
            status=PASS, passed=True, raw_output="{}", parsed={}, edits=[]
        )
        assert r.violations == []

    def test_violations_is_mutable_list(self):
        r = ContractCheckResult(
            status=PASS, passed=True, raw_output="{}", parsed={}, edits=[]
        )
        r.violations.append("x")
        assert r.violations == ["x"]

    def test_default_violations_not_shared_between_instances(self):
        r1 = ContractCheckResult(
            status=PASS, passed=True, raw_output="{}", parsed={}, edits=[]
        )
        r2 = ContractCheckResult(
            status=PASS, passed=True, raw_output="{}", parsed={}, edits=[]
        )
        r1.violations.append("only in r1")
        assert r2.violations == []

    def test_edits_and_parsed_can_be_none(self):
        r = ContractCheckResult(
            status=EMPTY_MODEL_OUTPUT,
            passed=False,
            raw_output="",
            parsed=None,
            edits=None,
        )
        assert r.parsed is None
        assert r.edits is None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Empty model output
# ═══════════════════════════════════════════════════════════════════════════════


class TestEmptyModelOutput:
    """Empty string, whitespace-only, and None all return EMPTY_MODEL_OUTPUT."""

    def test_empty_string(self):
        r = check_model_output("")
        assert r.status == EMPTY_MODEL_OUTPUT
        assert r.passed is False

    def test_single_space(self):
        r = check_model_output(" ")
        assert r.status == EMPTY_MODEL_OUTPUT
        assert r.passed is False

    def test_tab_and_newlines(self):
        r = check_model_output("\t\n\r\n  \t")
        assert r.status == EMPTY_MODEL_OUTPUT
        assert r.passed is False

    def test_none_input(self):
        r = check_model_output(None)  # type: ignore[arg-type]
        assert r.status == EMPTY_MODEL_OUTPUT
        assert r.passed is False

    def test_none_raw_output_is_empty_string_in_result(self):
        r = check_model_output(None)  # type: ignore[arg-type]
        assert r.raw_output == ""

    def test_empty_violations_list_is_non_empty(self):
        r = check_model_output("")
        assert len(r.violations) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Malformed JSON
# ═══════════════════════════════════════════════════════════════════════════════


class TestMalformedJson:
    """Broken JSON, non-JSON strings, and incomplete JSON return MALFORMED_JSON."""

    def test_plain_text(self):
        r = check_model_output("This is not JSON at all.")
        assert r.status == MALFORMED_JSON
        assert r.passed is False

    def test_truncated_json(self):
        r = check_model_output('{"edits": [{"section": "1.0"')
        assert r.status == MALFORMED_JSON
        assert r.passed is False

    def test_json_with_trailing_comma(self):
        r = check_model_output('{"edits": [],}')
        assert r.status == MALFORMED_JSON
        assert r.passed is False

    def test_single_string_value(self):
        # A JSON string is valid JSON but not a mapping — "edits" cannot be
        # present as a top-level key, so MISSING_EDITS_FIELD is also acceptable.
        # However, if json.loads returns a str, "edits" in str is False → MISSING.
        # Either result is acceptable but we verify it does not crash and that
        # passed is False.
        r = check_model_output('"just a string"')
        assert r.passed is False

    def test_raw_output_preserved_on_malformed(self):
        bad = "{{not valid}}"
        r = check_model_output(bad)
        assert r.raw_output == bad

    def test_parsed_is_none_on_malformed(self):
        r = check_model_output("{bad json}")
        assert r.parsed is None

    def test_violations_non_empty_on_malformed(self):
        r = check_model_output("not json")
        assert len(r.violations) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Missing edits field
# ═══════════════════════════════════════════════════════════════════════════════


class TestMissingEditsField:
    """Valid JSON but absent or null edits key returns MISSING_EDITS_FIELD."""

    def test_empty_json_object(self):
        r = check_model_output(_dumps({}))
        assert r.status == MISSING_EDITS_FIELD
        assert r.passed is False

    def test_json_with_other_keys_only(self):
        r = check_model_output(_dumps({"sections": [], "version": 2}))
        assert r.status == MISSING_EDITS_FIELD
        assert r.passed is False

    def test_edits_null(self):
        r = check_model_output(_dumps({"edits": None}))
        assert r.status == MISSING_EDITS_FIELD
        assert r.passed is False

    def test_parsed_is_populated_on_missing_edits(self):
        payload = {"other": "data"}
        r = check_model_output(_dumps(payload))
        assert r.parsed == payload

    def test_edits_is_none_on_missing_edits(self):
        r = check_model_output(_dumps({}))
        assert r.edits is None

    def test_violations_non_empty_on_missing_edits(self):
        r = check_model_output(_dumps({"edits": None}))
        assert len(r.violations) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 5. PASS cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestPassCases:
    """All valid payloads with a non-null edits value should return PASS."""

    def test_empty_edits_list(self):
        r = check_model_output(_dumps({"edits": []}))
        assert r.status == PASS
        assert r.passed is True

    def test_single_edit_entry(self):
        payload = {"edits": [{"section": "1.0", "content": "Updated content."}]}
        r = check_model_output(_dumps(payload))
        assert r.status == PASS
        assert r.passed is True

    def test_multiple_edits(self):
        payload = {
            "edits": [
                {"section": "1.0", "content": "Intro updated."},
                {"section": "2.1", "content": "Scope revised."},
                {"section": "4.3", "content": "References added."},
            ]
        }
        r = check_model_output(_dumps(payload))
        assert r.status == PASS
        assert r.passed is True

    def test_edits_with_extra_top_level_fields(self):
        payload = {
            "edits": [{"section": "1.0", "content": "x"}],
            "model": "qwen3:32b",
            "confidence": 0.95,
        }
        r = check_model_output(_dumps(payload))
        assert r.status == PASS
        assert r.passed is True

    def test_edits_value_is_returned_in_result(self):
        edits_list = [{"section": "3.0", "content": "Detail."}]
        r = check_model_output(_dumps({"edits": edits_list}))
        assert r.edits == edits_list

    def test_parsed_object_is_returned_in_result(self):
        payload = {"edits": [], "extra": 42}
        r = check_model_output(_dumps(payload))
        assert r.parsed == payload

    def test_violations_empty_on_pass(self):
        r = check_model_output(_dumps({"edits": []}))
        assert r.violations == []

    def test_raw_output_preserved_on_pass(self):
        raw = _dumps({"edits": []})
        r = check_model_output(raw)
        assert r.raw_output == raw


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Never-raises guarantee
# ═══════════════════════════════════════════════════════════════════════════════


class TestNeverRaises:
    """check_model_output must always return ContractCheckResult, never raise."""

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            "not json",
            "{bad}",
            '{"edits": null}',
            '{"edits": []}',
            '{"edits": [{"section": "A", "content": "B"}]}',
            "{}",
            '[1, 2, 3]',
            "\x00\xff\xfe",
            "true",
            "42",
            "null",
        ],
    )
    def test_returns_contract_check_result(self, raw):
        result = check_model_output(raw)  # type: ignore[arg-type]
        assert isinstance(result, ContractCheckResult), (
            f"expected ContractCheckResult for input {raw!r}, got {type(result)}"
        )
