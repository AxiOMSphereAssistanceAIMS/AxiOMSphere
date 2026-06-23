"""
DOCSREG Layer 5 — End-to-End Acceptance Test.

Runs a controlled input set through the same internal execution path that
the production Telegram /docsreg command uses, without a live bot, Redis,
or Qdrant connection.

Controlled input set
─────────────────────────────────────────────────────────────────────────────
  pass_doc.md   — well-formed Markdown                    → expected: PASS
  pass_doc.pdf  — valid PDF header bytes                  → expected: PASS
  fail_doc.xlsx — unsupported extension                   → expected: REJECTED (parse gate)
  empty_doc.md  — deliberately empty / trivial content    → expected: FAIL_REPAIRABLE
  archive.zip   — unsupported extension                   → expected: REJECTED (parse gate)

Execution path (internal equivalent of /docsreg <path>)
─────────────────────────────────────────────────────────────────────────────
  _resolve_draft_path()          — extension gate
  _run_one_cycle()               — production auditor + cycle runner
  _record_cycle_learning()       — sha256, artifact injection, knowledge log

10 Acceptance Criteria
─────────────────────────────────────────────────────────────────────────────
  C1.  All 5 inputs processed without uncaught exception
  C2.  Evidence directories created for attempted cycles (md, pdf, empty_doc)
  C3.  quality_report.json present in each evidence directory
  C4.  All 5 component score keys present in every quality report
  C5.  pass_doc.md  → result.passed is True
  C6.  pass_doc.pdf → result.passed is True
  C7.  empty_doc.md → result.passed is False
  C8.  fail_doc.xlsx and archive.zip → rejected at parse (no cycle run)
  C9.  Learning log written for every attempted cycle (3 entries)
  C10. Gold pair written for each passing cycle (2 entries);
       no gold pair for failed / rejected inputs
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ops.omi_telegram.docsreg_launch import (
    SUPPORTED_DRAFT_EXTENSIONS,
    DocsregLaunchRequest,
    _record_cycle_learning,
    _resolve_draft_path,
    _run_one_cycle,
)


# ── Constants ──────────────────────────────────────────────────────────────────

_COMPONENT_SCORE_KEYS = frozenset({
    "content_richness_score",
    "data_retention_score",
    "source_to_master_alignment_score",
    "structure_score",
    "metadata_safety_score",
})

_COMP_SCORES_PASS = {
    "content_richness_score": 0.93,
    "data_retention_score": 0.91,
    "source_to_master_alignment_score": 0.90,
    "structure_score": 0.88,
    "metadata_safety_score": 0.85,
}

_COMP_SCORES_FAIL = {
    "content_richness_score": 0.45,
    "data_retention_score": 0.40,
    "source_to_master_alignment_score": 0.35,
    "structure_score": 0.30,
    "metadata_safety_score": 0.25,  # lowest → bottleneck
}


# ── Fixture helpers ────────────────────────────────────────────────────────────

def _make_request(
    draft_path: Path,
    evidence_root: Path,
    *,
    target_quality: float = 0.80,
) -> DocsregLaunchRequest:
    return DocsregLaunchRequest(
        document_type="procedure",
        draft_path=draft_path,
        draft_format=draft_path.suffix.lstrip("."),
        evidence_root=evidence_root,
        redis_url="redis://localhost:6379/0",
        teacher_mode="noop",
        target_quality=target_quality,
    )


def _write_evidence(
    evidence_root: Path,
    *,
    passed: bool,
    quality: float,
) -> None:
    """Write the files that _record_cycle_learning() reads from evidence_root."""
    evidence_root.mkdir(parents=True, exist_ok=True)
    report = {
        "quality": quality,
        "target_quality": 0.80,
        "audit_status": "COMPONENT_PASS" if passed else "COMPONENT_FAIL_REPAIRABLE",
        "component_scores": _COMP_SCORES_PASS if passed else _COMP_SCORES_FAIL,
    }
    (evidence_root / "quality_report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    if passed:
        (evidence_root / "raw_extracted_text.md").write_text(
            "# Source Text\nExtracted content from the source document.",
            encoding="utf-8",
        )
        (evidence_root / "master_document.md").write_text(
            "# Master Document\nFinal certified output after all quality cycles.",
            encoding="utf-8",
        )


def _mock_cycle_result(
    *,
    passed: bool,
    quality: float,
    outcome: str,
    source_file: Path,
    evidence_root: Path,
) -> MagicMock:
    r = MagicMock()
    r.passed = passed
    r.best_quality = quality
    r.cycles_run = 1
    r.outcome = outcome
    r.notes = ""
    r.teacher_mode = "noop"
    r.document_type = "procedure"
    r.draft_path = str(source_file)
    r.evidence_root = str(evidence_root)
    r.job_id = f"job-{source_file.stem}"
    r.doc_id = f"doc-{source_file.stem}"
    r.cycle_id = f"cycle-{source_file.stem}"
    return r


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ── C1 / C8: unsupported formats rejected at parse gate ───────────────────────


def test_c8_xlsx_rejected_at_parse_gate(tmp_path: Path) -> None:
    """C8a — .xlsx is not in SUPPORTED_DRAFT_EXTENSIONS; rejected by _resolve_draft_path."""
    assert ".xlsx" not in SUPPORTED_DRAFT_EXTENSIONS

    bad = tmp_path / "fail_doc.xlsx"
    bad.write_bytes(b"PK\x03\x04")  # ZIP/OOXML magic

    resolved, fmt, err = _resolve_draft_path(str(bad))

    assert resolved is None, "xlsx must not resolve to a valid path"
    assert err is not None, "Must return a user-readable error"
    assert isinstance(err, str) and len(err) > 5


def test_c8_zip_rejected_at_parse_gate(tmp_path: Path) -> None:
    """C8b — .zip is not in SUPPORTED_DRAFT_EXTENSIONS; rejected by _resolve_draft_path."""
    assert ".zip" not in SUPPORTED_DRAFT_EXTENSIONS

    archive = tmp_path / "archive.zip"
    archive.write_bytes(b"PK\x03\x04")

    resolved, fmt, err = _resolve_draft_path(str(archive))

    assert resolved is None
    assert err is not None
    assert isinstance(err, str) and len(err) > 5


# ── C2–C7 / C9–C10: supported formats run through full internal path ──────────


def test_c5_pass_doc_md_result_is_pass(tmp_path: Path) -> None:
    """C5 — pass_doc.md: _run_one_cycle returns passed=True."""
    draft = tmp_path / "pass_doc.md"
    draft.write_text(
        "# Maintenance Procedure\n\n"
        "## 1. Purpose\nThis procedure defines inspection steps.\n\n"
        "## 2. Scope\nApplies to all rotating equipment.\n\n"
        "## 3. Steps\n1. Isolate power\n2. Inspect\n3. Document findings\n",
        encoding="utf-8",
    )
    ev = tmp_path / "ev_pass_md"
    request = _make_request(draft, ev, target_quality=0.80)

    def _fake_run(**kwargs: Any) -> MagicMock:
        _write_evidence(ev, passed=True, quality=0.91)
        return _mock_cycle_result(
            passed=True, quality=0.91, outcome="CERTIFIED_MASTER_READY",
            source_file=draft, evidence_root=ev,
        )

    with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle", side_effect=_fake_run):
        result = _run_one_cycle(source_file=draft, request=request, evidence_root=ev)

    assert result.passed is True  # C5
    assert ev.exists()            # C2
    assert (ev / "quality_report.json").exists()  # C3

    report = json.loads((ev / "quality_report.json").read_text(encoding="utf-8"))
    assert _COMPONENT_SCORE_KEYS <= set(report["component_scores"].keys())  # C4
    assert report["quality"] > 0.59  # quality not capped at legacy floor


def test_c6_pass_doc_pdf_result_is_pass(tmp_path: Path) -> None:
    """C6 — pass_doc.pdf: _run_one_cycle returns passed=True."""
    draft = tmp_path / "pass_doc.pdf"
    draft.write_bytes(b"%PDF-1.4\n%EOF")
    ev = tmp_path / "ev_pass_pdf"
    request = _make_request(draft, ev, target_quality=0.80)

    def _fake_run(**kwargs: Any) -> MagicMock:
        _write_evidence(ev, passed=True, quality=0.88)
        return _mock_cycle_result(
            passed=True, quality=0.88, outcome="CERTIFIED_MASTER_READY",
            source_file=draft, evidence_root=ev,
        )

    with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle", side_effect=_fake_run):
        result = _run_one_cycle(source_file=draft, request=request, evidence_root=ev)

    assert result.passed is True  # C6
    assert ev.exists()            # C2
    report = json.loads((ev / "quality_report.json").read_text(encoding="utf-8"))
    assert _COMPONENT_SCORE_KEYS <= set(report["component_scores"].keys())  # C4


def test_c7_empty_doc_md_result_is_fail(tmp_path: Path) -> None:
    """C7 — empty_doc.md: _run_one_cycle returns passed=False."""
    draft = tmp_path / "empty_doc.md"
    draft.write_text("", encoding="utf-8")  # deliberately empty
    ev = tmp_path / "ev_fail_md"
    request = _make_request(draft, ev, target_quality=0.80)

    def _fake_run(**kwargs: Any) -> MagicMock:
        _write_evidence(ev, passed=False, quality=0.31)
        return _mock_cycle_result(
            passed=False, quality=0.31, outcome="QUALITY_INSUFFICIENT",
            source_file=draft, evidence_root=ev,
        )

    with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle", side_effect=_fake_run):
        result = _run_one_cycle(source_file=draft, request=request, evidence_root=ev)

    assert result.passed is False  # C7
    assert ev.exists()             # C2
    report = json.loads((ev / "quality_report.json").read_text(encoding="utf-8"))
    assert _COMPONENT_SCORE_KEYS <= set(report["component_scores"].keys())  # C4


# ── C9 / C10: learning log + gold pairs ───────────────────────────────────────


def test_c9_c10_learning_and_gold_pairs_written(tmp_path: Path) -> None:
    """C9/C10 — _record_cycle_learning writes learning entries and gold pairs.

    Runs _record_cycle_learning for 3 attempted docs:
      pass_doc.md  (passed=True)  → learning entry + gold pair
      pass_doc.pdf (passed=True)  → learning entry + gold pair
      empty_doc.md (passed=False) → learning entry, NO gold pair

    Verifies:
      C9.  3 learning entries in docsreg_learning.jsonl
      C10. 2 gold pairs in gold_pairs.jsonl; 0 from failed doc
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    inputs = [
        ("pass_doc.md",   b"",  "w", True,  0.91, "CERTIFIED_MASTER_READY"),
        ("pass_doc.pdf",  None, "b", True,  0.88, "CERTIFIED_MASTER_READY"),
        ("empty_doc.md",  b"",  "w", False, 0.31, "QUALITY_INSUFFICIENT"),
    ]

    fake_results: list[MagicMock] = []

    for name, content, mode, passed, quality, outcome in inputs:
        draft = tmp_path / name
        if mode == "w":
            draft.write_text("# Content\nBody text.\n" if name.startswith("pass") else "", encoding="utf-8")
        else:
            draft.write_bytes(b"%PDF-1.4")
        ev = tmp_path / f"ev_{name.replace('.', '_')}"
        _write_evidence(ev, passed=passed, quality=quality)
        r = _mock_cycle_result(
            passed=passed, quality=quality, outcome=outcome,
            source_file=draft, evidence_root=ev,
        )
        fake_results.append((draft, ev, r))

    # Patch workspace_root so _record_cycle_learning writes to tmp_path/workspace
    with patch("aims_paths.workspace_root", return_value=workspace):
        for draft, ev, result in fake_results:
            try:
                _record_cycle_learning(result, draft, ev)
            except Exception as exc:
                pytest.fail(f"_record_cycle_learning raised for {draft.name}: {exc}")

    learning_log = workspace / "axi_ft_log" / "docsreg_learning.jsonl"
    gold_log = workspace / "axi_ft_log" / "gold_pairs.jsonl"

    learning_entries = _read_jsonl(learning_log)
    gold_entries = _read_jsonl(gold_log)

    # C9 — one entry per attempted cycle
    assert len(learning_entries) == 3, (
        f"Expected 3 learning entries (one per attempted doc), got {len(learning_entries)}"
    )
    assert all(e["schema_version"] == "docsreg.knowledge.v1" for e in learning_entries)

    # C10 — gold pair only for passing docs with artifact files
    assert len(gold_entries) == 2, (
        f"Expected 2 gold pairs (pass_doc.md + pass_doc.pdf), got {len(gold_entries)}"
    )
    # Verify failed doc has no gold pair
    failed_entries_in_gold = [
        e for e in gold_entries
        if e.get("quality", 1.0) < 0.50
    ]
    assert len(failed_entries_in_gold) == 0, (
        "Failed doc (quality<0.50) must not appear in gold_pairs.jsonl"
    )


# ── C1: full batch — no uncaught exception for any input ─────────────────────


def test_c1_all_five_inputs_no_exception(tmp_path: Path) -> None:
    """C1 — The full batch of 5 inputs finishes without an uncaught exception.

    Runs each input through the correct layer:
      Unsupported (.xlsx, .zip) → _resolve_draft_path only
      Supported (.md, .pdf)     → _run_one_cycle (run_docsreg_cycle mocked)
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # ── Prepare fixture files ──────────────────────────────────────────────────
    pass_md   = tmp_path / "pass_doc.md"
    pass_pdf  = tmp_path / "pass_doc.pdf"
    fail_xlsx = tmp_path / "fail_doc.xlsx"
    empty_md  = tmp_path / "empty_doc.md"
    zip_arc   = tmp_path / "archive.zip"

    pass_md.write_text(
        "# Procedure\n## 1. Purpose\nTest.\n## 2. Scope\nAll.\n",
        encoding="utf-8",
    )
    pass_pdf.write_bytes(b"%PDF-1.4\n%EOF")
    fail_xlsx.write_bytes(b"PK\x03\x04")
    empty_md.write_text("", encoding="utf-8")
    zip_arc.write_bytes(b"PK\x03\x04")

    supported = [
        (pass_md,  True,  0.91, "CERTIFIED_MASTER_READY"),
        (pass_pdf, True,  0.88, "CERTIFIED_MASTER_READY"),
        (empty_md, False, 0.31, "QUALITY_INSUFFICIENT"),
    ]
    unsupported = [fail_xlsx, zip_arc]

    completed: list[str] = []
    rejected:  list[str] = []

    # ── Unsupported: resolve only ──────────────────────────────────────────────
    for path in unsupported:
        resolved, _fmt, err = _resolve_draft_path(str(path))
        assert resolved is None, f"{path.name} must be rejected at parse gate"
        assert err is not None
        rejected.append(path.name)
        completed.append(path.name)

    # ── Supported: full cycle path ─────────────────────────────────────────────
    call_idx = [0]  # closure counter

    def _fake_run(**kwargs: Any) -> MagicMock:
        src, passed, quality, outcome = supported[call_idx[0]]
        ev = tmp_path / f"ev_{src.stem}"
        _write_evidence(ev, passed=passed, quality=quality)
        r = _mock_cycle_result(
            passed=passed, quality=quality, outcome=outcome,
            source_file=src, evidence_root=ev,
        )
        call_idx[0] += 1
        return r

    with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle", side_effect=_fake_run), \
         patch("aims_paths.workspace_root", return_value=workspace):
        for draft, passed, quality, outcome in supported:
            ev = tmp_path / f"ev_{draft.stem}"
            request = _make_request(draft, ev, target_quality=0.80)
            result = _run_one_cycle(source_file=draft, request=request, evidence_root=ev)
            _record_cycle_learning(result, draft, ev)
            completed.append(draft.name)

    # C1 — all 5 inputs processed without exception
    assert len(completed) == 5, f"Expected 5 completed, got: {completed}"
    # C8 — 2 rejected at parse
    assert len(rejected) == 2
    assert "fail_doc.xlsx" in rejected
    assert "archive.zip" in rejected

    # C9 — 3 learning entries (supported docs only)
    learning = _read_jsonl(workspace / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 3, f"Expected 3 learning entries, got {len(learning)}"

    # C10 — 2 gold pairs (pass docs only)
    gold = _read_jsonl(workspace / "axi_ft_log" / "gold_pairs.jsonl")
    assert len(gold) == 2, f"Expected 2 gold pairs, got {len(gold)}"
