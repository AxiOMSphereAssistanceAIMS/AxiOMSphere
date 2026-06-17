import json

import pytest

from ops.ft.scripts.claude_judge import parse_cli_output, validate_judgment
from ops.ft.scripts.run_golden_v4_benchmark_claude_cli_parallel import aggregate


def valid_judgment(verdict="model_a_wins"):
    return {
        "accuracy_a": 9,
        "accuracy_b": 2,
        "instruction_adherence_a": 8,
        "instruction_adherence_b": 3,
        "coherence_a": 9,
        "coherence_b": 4,
        "verdict": verdict,
        "reasoning": "Model A is clearly better.",
    }


def test_parses_structured_output_envelope():
    raw = json.dumps({"structured_output": valid_judgment()})
    assert parse_cli_output(raw)["verdict"] == "model_a_wins"


def test_rejects_missing_verdict_instead_of_tie_fallback():
    value = valid_judgment()
    del value["verdict"]
    with pytest.raises(ValueError, match="missing required"):
        validate_judgment(value)


def test_explicit_zero_scores_are_valid():
    value = valid_judgment("tie")
    for field in [key for key in value if key.endswith(("_a", "_b"))]:
        value[field] = 0
    assert validate_judgment(value)["verdict"] == "tie"


def test_aggregate_fails_closed_on_judge_failure():
    cases = [
        {"judge": {"status": "PASS", "judgment": valid_judgment()}},
        {"judge": {"status": "JUDGE_FAILURE", "judgment": None}},
    ]
    result = aggregate(cases, failure_threshold=0)
    assert result["status"] == "BENCHMARK_INVALID_JUDGE_FAILURE"
    assert result["decision_allowed"] is False
