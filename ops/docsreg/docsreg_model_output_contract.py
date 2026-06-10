"""
DOCSREG model output contract guard.

Validates raw Ollama model output JSON before it is applied as edits to
the document.  This module is intentionally free of LLM calls, HTTP calls,
and filesystem IO.

Exports
-------
EMPTY_MODEL_OUTPUT : str
MALFORMED_JSON : str
MISSING_EDITS_FIELD : str
PASS : str
    The four possible status constants.
ContractCheckResult : dataclass
    Outcome of a single contract check.
check_model_output(raw_output) -> ContractCheckResult
    Public entry point — never raises.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

log = logging.getLogger("docsreg_model_output_contract")

# ── Status constants ───────────────────────────────────────────────────────────

EMPTY_MODEL_OUTPUT: str = "EMPTY_MODEL_OUTPUT"
MALFORMED_JSON: str = "MALFORMED_JSON"
MISSING_EDITS_FIELD: str = "MISSING_EDITS_FIELD"
PASS: str = "PASS"

# ── Result dataclass ───────────────────────────────────────────────────────────


@dataclass
class ContractCheckResult:
    """Outcome of a single model-output contract check."""

    status: str
    """One of EMPTY_MODEL_OUTPUT, MALFORMED_JSON, MISSING_EDITS_FIELD, PASS."""

    passed: bool
    """True iff status == PASS."""

    raw_output: str
    """The raw string that was checked (normalised to '' when None was supplied)."""

    parsed: dict | None
    """The parsed JSON object, or None if parsing failed."""

    edits: list | None
    """The value of parsed["edits"], or None when not available."""

    violations: list[str] = field(default_factory=list)
    """Human-readable descriptions of every contract violation found."""


# ── Public API ─────────────────────────────────────────────────────────────────


def check_model_output(raw_output: str) -> ContractCheckResult:
    """Validate raw model output against the DOCSREG edit-contract.

    Args:
        raw_output: The raw string returned by the Ollama model.  May be
            ``None`` — treated identically to an empty string.

    Returns:
        A :class:`ContractCheckResult` describing the outcome.  ``result.passed``
        is ``True`` only when the output contains a well-formed JSON object
        with a non-null ``"edits"`` key.

    This function never raises.
    """
    # Normalise None → empty string so all subsequent logic is uniform.
    if raw_output is None:
        raw_output = ""

    # ── Step 1: empty check ────────────────────────────────────────────────────
    if raw_output.strip() == "":
        log.warning("model_output_contract: EMPTY_MODEL_OUTPUT")
        return ContractCheckResult(
            status=EMPTY_MODEL_OUTPUT,
            passed=False,
            raw_output=raw_output,
            parsed=None,
            edits=None,
            violations=["raw output is empty or contains only whitespace"],
        )

    # ── Step 2: JSON parse ─────────────────────────────────────────────────────
    try:
        parsed = json.loads(raw_output)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("model_output_contract: MALFORMED_JSON — %s", exc)
        return ContractCheckResult(
            status=MALFORMED_JSON,
            passed=False,
            raw_output=raw_output,
            parsed=None,
            edits=None,
            violations=[f"JSON parse error: {exc}"],
        )

    # ── Step 3: "edits" key presence and non-null check ───────────────────────
    # parsed must be a dict; non-dict JSON values (bool, int, list, None) are
    # treated as if the "edits" key is absent.
    if not isinstance(parsed, dict) or "edits" not in parsed or parsed["edits"] is None:
        if not isinstance(parsed, dict):
            reason = (
                f"parsed JSON is not an object (got {type(parsed).__name__}); "
                'key "edits" cannot be present'
            )
        elif "edits" not in parsed:
            reason = 'key "edits" is absent from parsed JSON'
        else:
            reason = 'key "edits" is present but null'
        log.warning("model_output_contract: MISSING_EDITS_FIELD — %s", reason)
        return ContractCheckResult(
            status=MISSING_EDITS_FIELD,
            passed=False,
            raw_output=raw_output,
            parsed=parsed,
            edits=None,
            violations=[reason],
        )

    # ── Step 4: PASS ──────────────────────────────────────────────────────────
    edits = parsed["edits"]
    log.info(
        "model_output_contract: PASS — edits count=%d",
        len(edits) if isinstance(edits, list) else -1,
    )
    return ContractCheckResult(
        status=PASS,
        passed=True,
        raw_output=raw_output,
        parsed=parsed,
        edits=edits,
        violations=[],
    )
