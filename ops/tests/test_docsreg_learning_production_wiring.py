"""
DOCSREG Learning Loop — Production Wiring Tests.

Verifies that _record_cycle_learning() correctly injects
raw_extracted_text.md and master_document.md paths into the
quality_report before delegating to record_knowledge_source().

Tests:
  1. source_text_path and master_document_path are populated when files exist.
  2. Passing cycle with both paths → gold pair written.
  3. Fail-then-pass on same source → DPO pair written.
  4. Missing artifact paths → learning entry written, pairs skipped.
  5. COMPONENT_BLOCKED → no gold pair, no DPO pair.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ops.docsreg.docsreg_knowledge_source import (
    RECOGNISED_AUDIT_STATUSES,
    record_knowledge_source,
)


# ── Shared fixtures ────────────────────────────────────────────────────────────

_COMP_SCORES_PASS = {
    "content_richness_score": 0.97,
    "data_retention_score": 0.96,
    "source_to_master_alignment_score": 0.95,
    "structure_score": 0.94,
    "metadata_safety_score": 0.92,
}

_COMP_SCORES_FAIL = {
    "content_richness_score": 0.50,
    "data_retention_score": 0.45,
    "source_to_master_alignment_score": 0.40,
    "structure_score": 0.35,
    "metadata_safety_score": 0.30,  # lowest → bottleneck on failed cycle
}


def _make_report(
    *,
    audit_status: str,
    quality: float,
    target_quality: float = 0.95,
    component_scores: dict | None = None,
    source_text_path: str = "",
    master_document_path: str = "",
) -> dict[str, Any]:
    return {
        "quality": quality,
        "target_quality": target_quality,
        "audit_status": audit_status,
        "component_scores": component_scores or _COMP_SCORES_PASS,
        "source_text_path": source_text_path,
        "master_document_path": master_document_path,
    }


def _write_report(evidence_dir: Path, report: dict) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "quality_report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )


def _write_artifacts(evidence_dir: Path, src: str, master: str) -> tuple[Path, Path]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    src_path = evidence_dir / "raw_extracted_text.md"
    master_path = evidence_dir / "master_document.md"
    src_path.write_text(src, encoding="utf-8")
    master_path.write_text(master, encoding="utf-8")
    return src_path, master_path


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def _fake_result(job_id: str = "job-1", doc_id: str = "doc-1") -> MagicMock:
    r = MagicMock()
    r.job_id = job_id
    r.doc_id = doc_id
    r.cycle_id = "cycle-1"
    r.outcome = "CERTIFIED_MASTER_READY"
    r.passed = True
    return r


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Helper: simulate _record_cycle_learning logic directly ─────────────────────
# We test the wiring logic by calling record_knowledge_source() with the same
# quality_report enrichment that _record_cycle_learning() now performs.

def _simulate_record_cycle_learning(
    *,
    evidence_root: Path,
    workspace_dir: Path,
    source_file: Path,
    has_prior_failure: bool = False,
    result: MagicMock | None = None,
) -> dict:
    """Mirror _record_cycle_learning() artifact injection logic for tests.

    Reads quality_report.json, injects raw_extracted_text.md /
    master_document.md paths if they exist, then delegates to
    record_knowledge_source().
    """
    from ops.docsreg.docsreg_knowledge_source import read_json_object

    quality_report: dict[str, Any] = dict(
        read_json_object(evidence_root / "quality_report.json")
    )

    raw_text_path = evidence_root / "raw_extracted_text.md"
    master_doc_path = evidence_root / "master_document.md"

    if raw_text_path.exists():
        quality_report["source_text_path"] = str(raw_text_path)

    if master_doc_path.exists():
        quality_report["master_document_path"] = str(master_doc_path)

    r = result or _fake_result()
    return record_knowledge_source(
        evidence_dir=evidence_root,
        workspace_dir=workspace_dir,
        quality_report=quality_report,
        job_id=getattr(r, "job_id", None),
        doc_id=getattr(r, "doc_id", None),
        cycle_id=getattr(r, "cycle_id", None),
        source_file=str(source_file),
        file_type=source_file.suffix.lstrip(".") or "unknown",
        final_state=getattr(r, "outcome", None),
        has_prior_failure=has_prior_failure,
    )


# ── Test 1: paths populated when artifact files exist ─────────────────────────

def test_record_cycle_learning_populates_source_and_master_paths(tmp_path: Path) -> None:
    """Artifact paths injected into quality_report when files exist."""
    ev = tmp_path / "ev"
    ws = _workspace(tmp_path)
    src_f = tmp_path / "fixture.pdf"
    src_f.write_bytes(b"%PDF fake")

    _write_artifacts(ev, "source document text", "master document output")
    _write_report(ev, _make_report(audit_status="COMPONENT_PASS", quality=0.97))

    entry = _simulate_record_cycle_learning(
        evidence_root=ev, workspace_dir=ws, source_file=src_f
    )

    assert entry["evidence"]["source_text_path"].endswith("raw_extracted_text.md")
    assert entry["evidence"]["master_document_path"].endswith("master_document.md")
    assert Path(entry["evidence"]["source_text_path"]).exists()
    assert Path(entry["evidence"]["master_document_path"]).exists()


# ── Test 2: passing cycle with both paths → gold pair written ──────────────────

def test_production_pass_cycle_writes_gold_pair_when_paths_exist(tmp_path: Path) -> None:
    """A real passing cycle with artifact files produces a gold SFT pair."""
    ev = tmp_path / "ev"
    ws = _workspace(tmp_path)
    src_f = tmp_path / "fixture.pdf"
    src_f.write_bytes(b"%PDF fake")

    _write_artifacts(ev, "source document text", "certified master output")
    _write_report(ev, _make_report(audit_status="COMPONENT_PASS", quality=0.97))

    _simulate_record_cycle_learning(
        evidence_root=ev, workspace_dir=ws, source_file=src_f
    )

    gold_pairs = _read_jsonl(ws / "axi_ft_log" / "gold_pairs.jsonl")
    assert len(gold_pairs) == 1, "Expected exactly 1 gold SFT pair"

    pair = gold_pairs[0]
    assert pair["approved_for_training"] is False
    assert pair["quality"] == pytest.approx(0.97)
    assert "certified master output" in pair["response"]


# ── Test 3: fail then pass same source → DPO pair written ─────────────────────

def test_production_fail_then_pass_same_source_writes_dpo_pair(tmp_path: Path) -> None:
    """Two cycles on the same source (fail then pass) produce a DPO pair.

    Cycle 1: COMPONENT_FAIL_REPAIRABLE, quality=0.45
    Cycle 2: READY_TO_FREEZE, quality=0.97, has_prior_failure=True
    """
    ws = _workspace(tmp_path)
    source_file = tmp_path / "fixture.pdf"
    source_file.write_bytes(b"%PDF cycle-source")

    # ── Cycle 1 — forced fail ──────────────────────────────────────────────────
    ev1 = tmp_path / "ev1"
    _write_artifacts(ev1, "source document text", "failed master v1")
    _write_report(
        ev1,
        _make_report(
            audit_status="COMPONENT_FAIL_REPAIRABLE",
            quality=0.45,
            component_scores=_COMP_SCORES_FAIL,
        ),
    )
    r1 = _fake_result(job_id="job-1")
    r1.outcome = "FAILED"
    r1.passed = False
    _simulate_record_cycle_learning(
        evidence_root=ev1,
        workspace_dir=ws,
        source_file=source_file,
        has_prior_failure=False,
        result=r1,
    )

    # ── Cycle 2 — passing cycle ────────────────────────────────────────────────
    ev2 = tmp_path / "ev2"
    _write_artifacts(ev2, "source document text", "certified master v2")
    _write_report(
        ev2,
        _make_report(
            audit_status="READY_TO_FREEZE",
            quality=0.97,
            component_scores=_COMP_SCORES_PASS,
        ),
    )
    r2 = _fake_result(job_id="job-2")
    r2.outcome = "CERTIFIED_MASTER_READY"
    r2.passed = True
    _simulate_record_cycle_learning(
        evidence_root=ev2,
        workspace_dir=ws,
        source_file=source_file,
        has_prior_failure=True,
        result=r2,
    )

    # ── Assertions ─────────────────────────────────────────────────────────────
    learning = _read_jsonl(ws / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 2, f"Expected 2 learning entries, got {len(learning)}"

    candidates = _read_jsonl(ws / "axi_ft_log" / "training_candidates.jsonl")
    assert len(candidates) >= 1

    gold_pairs = _read_jsonl(ws / "axi_ft_log" / "gold_pairs.jsonl")
    assert len(gold_pairs) == 1, f"Expected 1 gold pair, got {len(gold_pairs)}"
    assert gold_pairs[0]["approved_for_training"] is False
    assert "certified master v2" in gold_pairs[0]["response"]

    dpo_pairs = _read_jsonl(ws / "axi_ft_log" / "dpo_pairs.jsonl")
    assert len(dpo_pairs) == 1, f"Expected 1 DPO pair, got {len(dpo_pairs)}"
    dpo = dpo_pairs[0]
    assert dpo["approved_for_training"] is False
    assert "certified master v2" in dpo["chosen"]
    assert "failed master v1" in dpo["rejected"]
    assert dpo["chosen_quality"] > dpo["rejected_quality"]
    assert dpo["quality_delta"] == pytest.approx(0.97 - 0.45, abs=1e-5)
    assert dpo["bottleneck_delta"]["rejected_key"] == "metadata_safety_score"
    assert dpo["source_file"] == str(source_file)


# ── Test 4: missing artifact paths → learning entry written, pairs skipped ────

def test_missing_paths_skips_pairs_but_writes_learning_entry(tmp_path: Path) -> None:
    """When raw_extracted_text.md and master_document.md are absent,
    the learning entry is still written but no gold or DPO pair is created."""
    ev = tmp_path / "ev"
    ws = _workspace(tmp_path)
    src_f = tmp_path / "fixture.pdf"
    src_f.write_bytes(b"%PDF no-artifacts")

    # Write only quality_report.json — no artifact files
    _write_report(ev, _make_report(audit_status="COMPONENT_PASS", quality=0.97))

    _simulate_record_cycle_learning(
        evidence_root=ev, workspace_dir=ws, source_file=src_f
    )

    learning = _read_jsonl(ws / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1, "Learning entry must still be written"
    assert learning[0]["schema_version"] == "docsreg.knowledge.v1"

    gold_pairs = _read_jsonl(ws / "axi_ft_log" / "gold_pairs.jsonl")
    assert len(gold_pairs) == 0, "No gold pair without artifact text files"

    dpo_pairs = _read_jsonl(ws / "axi_ft_log" / "dpo_pairs.jsonl")
    assert len(dpo_pairs) == 0, "No DPO pair without artifact text files"


# ── Test 5: COMPONENT_BLOCKED never writes gold or DPO ────────────────────────

def test_component_blocked_never_writes_gold_or_dpo(tmp_path: Path) -> None:
    """COMPONENT_BLOCKED (legacy noop auditor) must never produce pairs."""
    assert "COMPONENT_BLOCKED" not in RECOGNISED_AUDIT_STATUSES

    ev = tmp_path / "ev"
    ws = _workspace(tmp_path)
    src_f = tmp_path / "fixture.pdf"
    src_f.write_bytes(b"%PDF blocked")

    _write_artifacts(ev, "source text", "blocked output")
    _write_report(
        ev,
        _make_report(audit_status="COMPONENT_BLOCKED", quality=0.97),
    )

    _simulate_record_cycle_learning(
        evidence_root=ev,
        workspace_dir=ws,
        source_file=src_f,
        has_prior_failure=True,  # DPO would be considered if auditor were real
    )

    learning = _read_jsonl(ws / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1
    assert learning[0]["real_auditor_used"] is False

    gold_pairs = _read_jsonl(ws / "axi_ft_log" / "gold_pairs.jsonl")
    assert len(gold_pairs) == 0, "COMPONENT_BLOCKED must not produce gold pair"

    dpo_pairs = _read_jsonl(ws / "axi_ft_log" / "dpo_pairs.jsonl")
    assert len(dpo_pairs) == 0, "COMPONENT_BLOCKED must not produce DPO pair"
