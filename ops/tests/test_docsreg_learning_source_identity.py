"""
DOCSREG Learning Loop — Source Identity Tests.

Verifies that DPO same-source matching uses stable sha256 identity with
strict fall-through rules, and that the sha256 is written to every learning
entry so future cycles can match it.

Matching rules under test:
  sha256 + sha256 equal        → match
  sha256 + sha256 different    → no match
  sha256 present + other absent → no match (strict; no filename fallback)
  both sha256 absent + same filename → filename fallback match

Tests:
  1. test_dpo_matches_same_source_sha256
  2. test_dpo_rejects_different_sha256_same_filename
  3. test_dpo_rejects_missing_sha256_when_other_has_sha256
  4. test_dpo_filename_fallback_only_when_both_sha256_missing
  5. test_archive_member_uses_extracted_sha256_for_identity
  6. test_source_sha256_written_to_learning_entry
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ops.docsreg.docsreg_knowledge_source import (
    _find_prior_failed_entry,
    build_knowledge_entry,
    compute_file_sha256,
    record_knowledge_source,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

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
    "metadata_safety_score": 0.30,
}


def _make_report(
    *,
    audit_status: str = "COMPONENT_PASS",
    quality: float = 0.97,
    target_quality: float = 0.95,
    component_scores: dict | None = None,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    r: dict[str, Any] = {
        "quality": quality,
        "target_quality": target_quality,
        "audit_status": audit_status,
        "component_scores": component_scores or _COMP_SCORES_PASS,
    }
    if source_sha256 is not None:
        r["source_sha256"] = source_sha256
    return r


def _write_report(ev: Path, report: dict) -> None:
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "quality_report.json").write_text(json.dumps(report), encoding="utf-8")


def _write_artifacts(ev: Path, src: str = "source text", master: str = "master text") -> None:
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "raw_extracted_text.md").write_text(src, encoding="utf-8")
    (ev / "master_document.md").write_text(master, encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_learning_entry(
    learning_path: Path,
    *,
    source_file: str,
    source_sha256: str | None,
    passed: bool,
    quality: float = 0.45,
    master_path: str = "",
) -> None:
    """Append a minimal failed/passed learning entry for scan tests."""
    learning_path.parent.mkdir(parents=True, exist_ok=True)
    entry: dict[str, Any] = {
        "schema_version": "docsreg.knowledge.v1",
        "source_file": source_file,
        "outcome": {"passed": passed, "quality": quality, "audit_status": "COMPONENT_FAIL_REPAIRABLE"},
        "evidence": {"master_document_path": master_path},
    }
    if source_sha256 is not None:
        entry["source_sha256"] = source_sha256
    with learning_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


# ── Test 1: sha256 match → DPO found ──────────────────────────────────────────

def test_dpo_matches_same_source_sha256(tmp_path: Path) -> None:
    """_find_prior_failed_entry returns the entry when sha256 values match."""
    learning = tmp_path / "axi_ft_log" / "docsreg_learning.jsonl"
    sha = "aabbcc112233"

    _write_learning_entry(
        learning, source_file="/docs/doc.pdf", source_sha256=sha, passed=False
    )

    result = _find_prior_failed_entry(learning, "/docs/doc.pdf", sha)
    assert result is not None
    assert result["source_sha256"] == sha


# ── Test 2: different sha256, same filename → no match ────────────────────────

def test_dpo_rejects_different_sha256_same_filename(tmp_path: Path) -> None:
    """When both entries carry sha256 but they differ, filename match is not used."""
    learning = tmp_path / "axi_ft_log" / "docsreg_learning.jsonl"

    _write_learning_entry(
        learning,
        source_file="/docs/doc.pdf",
        source_sha256="sha_old_version",
        passed=False,
    )

    # Query with same filename but different sha256 (different file content).
    result = _find_prior_failed_entry(learning, "/docs/doc.pdf", "sha_new_version")
    assert result is None, "Different sha256 must not match even if filename is identical"


# ── Test 3: one sha256 present, other absent → no match ───────────────────────

def test_dpo_rejects_missing_sha256_when_other_has_sha256(tmp_path: Path) -> None:
    """Strict rule: one-has-sha256, other-absent is not a match in either direction."""
    learning = tmp_path / "axi_ft_log" / "docsreg_learning.jsonl"

    # Case A: stored entry has sha256, query has none.
    _write_learning_entry(
        learning,
        source_file="/docs/doc.pdf",
        source_sha256="existing_sha",
        passed=False,
    )
    result_a = _find_prior_failed_entry(learning, "/docs/doc.pdf", None)
    assert result_a is None, "Stored sha256 + query sha256 absent must not match"

    # Case B: stored entry has no sha256, query has one.
    learning2 = tmp_path / "axi_ft_log2" / "docsreg_learning.jsonl"
    _write_learning_entry(
        learning2,
        source_file="/docs/doc.pdf",
        source_sha256=None,
        passed=False,
    )
    result_b = _find_prior_failed_entry(learning2, "/docs/doc.pdf", "query_sha")
    assert result_b is None, "Stored sha256 absent + query sha256 present must not match"


# ── Test 4: both sha256 absent + same filename → filename fallback ─────────────

def test_dpo_filename_fallback_only_when_both_sha256_missing(tmp_path: Path) -> None:
    """When neither entry has a sha256, filename is the only identity signal and IS used."""
    learning = tmp_path / "axi_ft_log" / "docsreg_learning.jsonl"

    _write_learning_entry(
        learning,
        source_file="/docs/legacy.pdf",
        source_sha256=None,
        passed=False,
    )

    # Both have no sha256 → filename fallback allowed.
    result = _find_prior_failed_entry(learning, "/docs/legacy.pdf", None)
    assert result is not None, "Filename fallback must work when both sha256 are absent"

    # Different filename → no match.
    result_diff = _find_prior_failed_entry(learning, "/docs/other.pdf", None)
    assert result_diff is None, "Different filename must not match when both sha256 absent"


# ── Test 5: archive member sha256 propagated via quality_report ───────────────

def test_archive_member_uses_extracted_sha256_for_identity(tmp_path: Path) -> None:
    """When quality_report carries source_sha256, build_knowledge_entry stores it.

    Simulates an archive extraction workflow where the caller pre-computes
    the sha256 of the extracted member and injects it into quality_report.
    The resulting entry must carry that exact sha256 — not the sha256 of the
    source_file path (which might be the archive itself or a temp extraction).
    """
    ev = tmp_path / "ev"
    ws = tmp_path / "ws"
    ev.mkdir(parents=True, exist_ok=True)
    ws.mkdir(parents=True, exist_ok=True)

    # Write a real file so sha256_file() would return a different value.
    source_file = tmp_path / "archive_member.txt"
    source_file.write_text("extracted member content", encoding="utf-8")
    real_sha = compute_file_sha256(source_file)

    # Caller pre-computes sha256 of extraction and injects it.
    injected_sha = "deadbeef" * 8  # 64 hex chars — a plausible sha256 override
    report = _make_report(source_sha256=injected_sha)

    entry = build_knowledge_entry(
        quality_report=report,
        evidence_dir=ev,
        workspace_dir=ws,
        source_file=str(source_file),
        file_type="txt",
    )

    assert entry["source_sha256"] == injected_sha, (
        "build_knowledge_entry must use quality_report['source_sha256'] over computed sha256"
    )
    assert entry["source_sha256"] != real_sha, "Must not have fallen back to file sha256"


# ── Test 6: source_sha256 written to every learning entry ─────────────────────

def test_source_sha256_written_to_learning_entry(tmp_path: Path) -> None:
    """record_knowledge_source() stores source_sha256 in the learning entry."""
    ev = tmp_path / "ev"
    ws = tmp_path / "ws"
    src_f = tmp_path / "fixture.pdf"
    src_f.write_bytes(b"%PDF identity-test")

    _write_artifacts(ev)
    _write_report(ev, _make_report(audit_status="COMPONENT_PASS", quality=0.97))

    expected_sha = compute_file_sha256(src_f)

    entry = record_knowledge_source(
        evidence_dir=ev,
        workspace_dir=ws,
        quality_report=_make_report(audit_status="COMPONENT_PASS", quality=0.97),
        source_file=str(src_f),
        file_type="pdf",
        job_id="job-sha-test",
        doc_id="doc-sha-test",
        cycle_id="cycle-sha-test",
    )

    assert entry["source_sha256"] == expected_sha, (
        "source_sha256 must be present and match the actual file sha256"
    )

    learning = _read_jsonl(ws / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1
    assert learning[0]["source_sha256"] == expected_sha, (
        "source_sha256 must be persisted in docsreg_learning.jsonl"
    )
