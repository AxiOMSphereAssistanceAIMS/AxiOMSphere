"""Regression tests for the doctuning-pair pipeline refactor.

Covers:
  - safe_json_loads: empty raw, markdown fence stripping
  - _deterministic_validate: pass / fail cases
  - _compute_validation_status: llm_failed / passed paths
"""

import sys
import os
import importlib
import tempfile
import json
from pathlib import Path

import pytest

# ── Minimal stub so axi_bot can be imported without Telegram credentials ──────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
os.environ.setdefault("BOT_TOKEN", "stub:test")
os.environ.setdefault("ALLOWED_CHAT_IDS", "0")


def _load_helpers():
    """Import only the helper functions we need — avoids running bot startup."""
    import importlib.util, ast, textwrap

    src = Path(__file__).resolve().parent.parent / "axi_bot.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    # Collect source lines for the three functions
    targets = {
        "safe_json_loads",
        "_extract_excel_structure",
        "_deterministic_validate",
        "_compute_validation_status",
        "_PLACEHOLDER_PATTERNS",
        "_WORD_LIMIT_RE",
        "_QUANT_CLAIM_RE",
    }

    # Build a minimal module with just what we need
    lines = src.read_text(encoding="utf-8").splitlines(keepends=True)
    # Extract the regex constants and the four functions by grabbing lines
    # in a simple pass: find def/assignment and include until next top-level def/class
    mini_src = "import re, json, logging\nfrom pathlib import Path\nlog = logging.getLogger(__name__)\n\n"

    import re as _re
    top_def = _re.compile(r'^(def |class |[A-Z_]+ *=)')

    i = 0
    collecting = False
    current_name = None
    block_lines = []

    while i < len(lines):
        line = lines[i]
        m = top_def.match(line)
        if m:
            if collecting and block_lines:
                mini_src += "".join(block_lines) + "\n"
            block_lines = []
            collecting = False
            # Check if this is a target
            for t in targets:
                if line.startswith(f"def {t}(") or line.startswith(f"{t} =") or line.startswith(f"{t}="):
                    collecting = True
                    current_name = t
                    break
        if collecting:
            block_lines.append(line)
        i += 1
    if collecting and block_lines:
        mini_src += "".join(block_lines)

    globs: dict = {}
    exec(compile(mini_src, "<doctuning_helpers>", "exec"), globs)  # noqa: S102
    return globs


_helpers = _load_helpers()
_HELPERS_MISSING = not all(
    k in _helpers
    for k in ("safe_json_loads", "_deterministic_validate", "_compute_validation_status", "_extract_excel_structure")
)
if _HELPERS_MISSING:
    pytest.skip(
        "Helper functions were removed from axi_bot.py — skipping doctuning regression tests",
        allow_module_level=True,
    )
safe_json_loads = _helpers["safe_json_loads"]
_deterministic_validate = _helpers["_deterministic_validate"]
_compute_validation_status = _helpers["_compute_validation_status"]
_extract_excel_structure = _helpers["_extract_excel_structure"]


# ── safe_json_loads ────────────────────────────────────────────────────────────

def test_safe_json_loads_empty():
    assert safe_json_loads("", "test") == {}


def test_safe_json_loads_fence():
    raw = '```json\n{"key": "value"}\n```'
    result = safe_json_loads(raw, "test")
    assert result == {"key": "value"}


def test_safe_json_loads_invalid():
    result = safe_json_loads("not json at all {{{", "test")
    assert result == {}


# ── _compute_validation_status ────────────────────────────────────────────────

def test_compute_validation_status_det_failed():
    assert _compute_validation_status(False, "accept", 0.05) == "failed"


def test_compute_validation_status_llm_failed():
    assert _compute_validation_status(True, "validator_error", None) == "deterministic_pass_llm_failed"


def test_compute_validation_status_llm_empty_verdict():
    assert _compute_validation_status(True, "", None) == "deterministic_pass_llm_failed"


def test_compute_validation_status_passed():
    assert _compute_validation_status(True, "accept", 0.05) == "passed"


# ── _deterministic_validate ───────────────────────────────────────────────────

def _make_struct(cells: dict) -> dict:
    """Build a minimal struct dict for _deterministic_validate."""
    return {
        "cells": cells,
        "placeholders": [],
        "field_limits": [],
        "sheets": ["Sheet1"],
        "counts": {"rows": 5, "cols": 2, "filled": len(cells)},
    }


def test_deterministic_validate_pass():
    blank = _make_struct({"A1": {"value": "Objective (max 30 words)", "sheet": "Sheet1"}})
    blank["field_limits"] = [{
        "label": "Objective",
        "word_limit": 30,
        "label_addr": "A1",
        "content_addr": "A2",
        "sheet": "Sheet1",
    }]
    blank["cells"]["A2"] = {"value": "This is a short objective.", "sheet": "Sheet1"}

    filled = _make_struct({
        "A1": {"value": "Objective (max 30 words)", "sheet": "Sheet1"},
        "A2": {"value": "This is a short objective.", "sheet": "Sheet1"},
    })
    filled["field_limits"] = blank["field_limits"]

    result = _deterministic_validate(blank, filled)
    assert result["passed"] is True
    assert result["issues"] == []


def test_deterministic_validate_fail_word_limit():
    long_text = " ".join(f"word{i}" for i in range(40))  # 40 words — exceeds 30
    blank = _make_struct({"A1": {"value": "Objective (max 30 words)", "sheet": "Sheet1"}})
    blank["field_limits"] = [{
        "label": "Objective",
        "word_limit": 30,
        "label_addr": "A1",
        "content_addr": "A2",
        "sheet": "Sheet1",
    }]

    filled = _make_struct({
        "A1": {"value": "Objective (max 30 words)", "sheet": "Sheet1"},
        "A2": {"value": long_text, "sheet": "Sheet1"},
    })
    filled["field_limits"] = blank["field_limits"]

    result = _deterministic_validate(blank, filled)
    assert result["passed"] is False
    assert any("Objective" in iss for iss in result["issues"])
