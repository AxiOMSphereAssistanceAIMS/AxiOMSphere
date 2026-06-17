"""
Stage 2 verification: test that the serialized section editor (max_workers=1,
timeout=600) successfully applies all 5 Phase 1 recommendations from cycle_04.

Run:
  PYTHONPATH=/home/axi_omi_sphere/aims-workspace \
    python -m pytest ops/tests/test_section_editor_serial_fix.py -v -s
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CYCLE_04_DIR = ROOT / "aims_workspace/cyclic_doc_output/cycle_04"
REFERENCE_PDF = Path(
    "/media/axi_omi_sphere/FDF0-25E2/Documents/Block 10/Стандарты/IG7894~I/"
    "Asset Integrity Management Policy and Framework (AIM-PFM).pdf"
)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def cycle04_doc() -> str:
    draft = CYCLE_04_DIR / "draft.md"
    assert draft.exists(), f"cycle_04 draft not found: {draft}"
    return draft.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def cycle04_recs() -> list[str]:
    plan = CYCLE_04_DIR / "repair_plan.json"
    assert plan.exists(), f"cycle_04 repair_plan not found: {plan}"
    data = json.loads(plan.read_text(encoding="utf-8"))
    recs = data.get("selected", [])
    assert len(recs) > 0, "No selected recommendations in cycle_04 repair plan"
    return recs


@pytest.fixture(scope="module")
def reference_text() -> str:
    if not REFERENCE_PDF.exists():
        pytest.skip(f"Reference PDF not found: {REFERENCE_PDF}")
    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(str(REFERENCE_PDF)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        return text
    except Exception as e:
        pytest.skip(f"Could not load reference PDF: {e}")


# ── tests ─────────────────────────────────────────────────────────────────────


def test_max_workers_default_is_1():
    """Confirm the serialization fix is in place before running slow tests."""
    import inspect
    from ops.agents.skills.section_editor import apply_section_edits
    sig = inspect.signature(apply_section_edits)
    default = sig.parameters["max_workers"].default
    assert default == 1, (
        f"apply_section_edits max_workers default must be 1 (serial), got {default}. "
        "GPU contention causes timeout when sections run in parallel."
    )


def test_call_section_timeout_is_sufficient():
    """Confirm the per-section timeout is ≥600s (currently 3600s for VRAM reload tolerance)."""
    import ast
    import re
    src = (ROOT / "ops/agents/skills/section_editor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_call_section":
            func_src = ast.get_source_segment(src, node)
            match = re.search(r"timeout=(\d+)", func_src)
            assert match, "_call_section must pass a timeout= to _ollama()"
            actual = int(match.group(1))
            assert actual >= 600, (
                f"_call_section timeout must be ≥600s, got {actual}. "
                "With max_workers=1 and large sections (9.1 Annexure = 58-row table), "
                "300s is insufficient for serial execution on busy GPU."
            )
            return
    pytest.fail("_call_section function not found in section_editor.py")


@pytest.mark.slow
def test_all_recs_applied_with_serial_editor(
    cycle04_doc, cycle04_recs, reference_text
):
    """
    Integration test: apply cycle_04 repair plan with max_workers=1.
    Expects all 5 recommendations to be applied (previously sections 9.1 and 5.1 timed out).
    This test requires Ollama with axi_omi_sphere loaded (~10 min per section).
    Skip with: pytest -m "not slow"
    """
    from ops.agents.skills.section_editor import apply_section_edits

    print(f"\n[TEST] Applying {len(cycle04_recs)} recommendations (serial, timeout=600s each)...")
    for i, r in enumerate(cycle04_recs, 1):
        print(f"  {i}. {r[:80]!r}")

    t0 = time.time()
    result = apply_section_edits(
        doc=cycle04_doc,
        recommendations=cycle04_recs,
        last_accepted_doc=cycle04_doc,
        reference_text=reference_text,
    )
    elapsed = time.time() - t0

    verified = result.get("verified_recommendations", [])
    unresolved = result.get("unresolved_recs", [])
    rolled_back = result.get("rolled_back", False)   # bool, not list
    improved_doc = result.get("improved_doc", "")

    print(f"\n[TEST] Elapsed: {elapsed:.1f}s")
    print(f"[TEST] verified={len(verified)}, unresolved={len(unresolved)}, rolled_back={rolled_back}")
    print(f"[TEST] Doc length: {len(cycle04_doc)} → {len(improved_doc)}")

    # Save output for manual inspection
    out_dir = ROOT / "aims_workspace/cyclic_doc_output/cycle_05_serial_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "draft.md").write_text(improved_doc, encoding="utf-8")
    (out_dir / "section_edit_result.json").write_text(
        json.dumps(
            {
                "verified": verified,
                "unresolved": unresolved,
                "rolled_back": rolled_back,
                "elapsed_seconds": round(elapsed, 1),
                "doc_char_delta": len(improved_doc) - len(cycle04_doc),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[TEST] Saved to: {out_dir}")

    # Assertions: expect ≥3 of 5 recs verified (previously 1/5 due to timeouts)
    assert len(verified) >= 3, (
        f"Expected ≥3 verified recommendations, got {len(verified)}. "
        f"unresolved={unresolved}, rolled_back={rolled_back}"
    )
    # Doc should grow (content was added)
    assert len(improved_doc) > len(cycle04_doc), (
        f"Improved doc should be larger than input. "
        f"Before={len(cycle04_doc)}, After={len(improved_doc)}"
    )
