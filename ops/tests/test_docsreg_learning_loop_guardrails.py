"""
DOCSREG Learning Loop Guardrails — unit tests.

Verifies that:
  1. Failed real audit writes learning entry but NOT a gold pair.
  2. Passed real audit writes learning entry AND a gold pair.
  3. COMPONENT_BLOCKED (noop) audit does NOT write a gold pair.
  4. Malformed quality report raises rather than silently writing garbage.
  5. DPO pair is created only when chosen and rejected share source identity.
  6. DPO pair is NOT created across unrelated (different-source) files.

Step 4 evidence: two-cycle validation (forced fail then pass on the same source
  file) verifying entry count, gold pair count, DPO pair count, bottleneck, and
  component scores.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops.docsreg.docsreg_knowledge_source import (
    RECOGNISED_AUDIT_STATUSES,
    build_dpo_pair_from_entries,
    build_sft_pair_from_entry,
    record_knowledge_source,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

_BASE_SCORES = {
    "content_richness_score": 0.97,
    "data_retention_score": 0.96,
    "source_to_master_alignment_score": 0.95,
    "structure_score": 0.94,
    "metadata_safety_score": 0.92,
}

_PASS_REPORT = {
    "quality": 0.97,
    "target_quality": 0.95,
    "audit_status": "COMPONENT_PASS",
    "component_scores": dict(_BASE_SCORES),
    "source_text_path": "",
    "master_document_path": "",
}

_FAIL_REPORT = {
    "quality": 0.50,
    "target_quality": 0.95,
    "audit_status": "COMPONENT_FAIL_REPAIRABLE",
    "component_scores": dict(_BASE_SCORES),
    "source_text_path": "",
    "master_document_path": "",
}

_BLOCKED_REPORT = {
    "quality": 0.97,
    "target_quality": 0.95,
    "audit_status": "COMPONENT_BLOCKED",  # legacy noop auditor
    "component_scores": dict(_BASE_SCORES),
}


def _write_report(evidence_dir: Path, report: dict) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "quality_report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )


def _write_text_artifacts(evidence_dir: Path, src: str, resp: str) -> tuple[str, str]:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    src_path = evidence_dir / "source.txt"
    resp_path = evidence_dir / "master.txt"
    src_path.write_text(src, encoding="utf-8")
    resp_path.write_text(resp, encoding="utf-8")
    return str(src_path), str(resp_path)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


# ── Test 1: failed real audit → learning entry, NO gold pair ──────────────────


def test_failed_real_audit_writes_learning_but_not_gold(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "ev"
    _write_report(evidence_dir, _FAIL_REPORT)
    ws = _workspace(tmp_path)
    src_p, resp_p = _write_text_artifacts(evidence_dir, "source text", "failed output")

    report = {**_FAIL_REPORT, "source_text_path": src_p, "master_document_path": resp_p}

    entry = record_knowledge_source(
        evidence_dir=evidence_dir,
        workspace_dir=ws,
        quality_report=report,
        source_file="fixture.pdf",
        file_type="pdf",
        final_state="FAILED",
    )

    # Learning entry must exist
    learning = _read_jsonl(ws / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1
    assert learning[0]["outcome"]["passed"] is False

    # Gold pair must NOT be written (quality below target)
    gold = _read_jsonl(ws / "axi_ft_log" / "gold_pairs.jsonl")
    assert gold == []

    # Training state sanity
    assert entry["training"]["eligible_for_sft"] is False
    assert entry["training"]["eligible_for_dpo"] is False
    assert entry["training"]["approved_for_training"] is False


# ── Test 2: passed real audit → learning entry AND gold pair ──────────────────


def test_passed_real_audit_writes_learning_and_gold(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "ev"
    ws = _workspace(tmp_path)
    src_p, resp_p = _write_text_artifacts(evidence_dir, "source text", "master output")

    report = {
        **_PASS_REPORT,
        "source_text_path": src_p,
        "master_document_path": resp_p,
    }

    entry = record_knowledge_source(
        evidence_dir=evidence_dir,
        workspace_dir=ws,
        quality_report=report,
        source_file="fixture.pdf",
        file_type="pdf",
        final_state="CERTIFIED_MASTER_READY",
    )

    # Learning entry must exist
    learning = _read_jsonl(ws / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1
    assert learning[0]["outcome"]["passed"] is True

    # Gold pair must be written
    gold = _read_jsonl(ws / "axi_ft_log" / "gold_pairs.jsonl")
    assert len(gold) == 1
    gold_pair = gold[0]
    assert gold_pair["schema_version"] == "docsreg.sft_pair.v1"
    assert gold_pair["approved_for_training"] is False
    assert "source text" in gold_pair["prompt"]
    assert gold_pair["response"] == "master output"

    # Entry fields
    assert entry["real_auditor_used"] is True
    assert entry["training"]["eligible_for_sft"] is True
    assert entry["training"]["approved_for_training"] is False


# ── Test 3: COMPONENT_BLOCKED → learning entry, NO gold pair ─────────────────


def test_noop_component_blocked_does_not_write_gold(tmp_path: Path) -> None:
    assert "COMPONENT_BLOCKED" not in RECOGNISED_AUDIT_STATUSES

    evidence_dir = tmp_path / "ev"
    ws = _workspace(tmp_path)
    src_p, resp_p = _write_text_artifacts(evidence_dir, "source text", "blocked output")

    report = {
        **_BLOCKED_REPORT,
        "source_text_path": src_p,
        "master_document_path": resp_p,
    }

    entry = record_knowledge_source(
        evidence_dir=evidence_dir,
        workspace_dir=ws,
        quality_report=report,
        source_file="fixture.pdf",
        file_type="pdf",
        final_state="COMPONENT_BLOCKED",
    )

    # Learning entry still written (every real cycle gets an entry)
    learning = _read_jsonl(ws / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 1

    # Gold pair must NOT be written — noop auditor is not recognised
    gold = _read_jsonl(ws / "axi_ft_log" / "gold_pairs.jsonl")
    assert gold == []

    assert entry["real_auditor_used"] is False
    assert entry["training"]["eligible_for_sft"] is False


# ── Test 4: malformed quality report raises, does not write silently ──────────


def test_malformed_quality_report_raises_not_silently_swallowed(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "ev"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    ws = _workspace(tmp_path)

    # Case A: completely missing quality_report.json
    with pytest.raises((FileNotFoundError, OSError, ValueError)):
        record_knowledge_source(
            evidence_dir=evidence_dir,
            workspace_dir=ws,
            source_file="fixture.pdf",
            file_type="pdf",
        )

    # No learning entries written
    assert not (ws / "axi_ft_log" / "docsreg_learning.jsonl").exists()

    # Case B: JSON array instead of object
    (evidence_dir / "quality_report.json").write_text(
        "[1, 2, 3]", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Expected JSON object"):
        record_knowledge_source(
            evidence_dir=evidence_dir,
            workspace_dir=ws,
            source_file="fixture.pdf",
            file_type="pdf",
        )

    # Still no entries
    assert not (ws / "axi_ft_log" / "docsreg_learning.jsonl").exists()


# ── Test 5: DPO pair requires same source identity ────────────────────────────


def test_dpo_pair_requires_same_source_identity(tmp_path: Path) -> None:
    """build_dpo_pair_from_entries must raise when source identities differ."""
    from ops.docsreg.docsreg_knowledge_source import build_knowledge_entry

    ev_a = tmp_path / "ev_a"
    ev_a.mkdir(parents=True, exist_ok=True)
    ev_b = tmp_path / "ev_b"
    ev_b.mkdir(parents=True, exist_ok=True)
    ws = _workspace(tmp_path)

    chosen = build_knowledge_entry(
        quality_report={**_PASS_REPORT},
        evidence_dir=ev_a,
        workspace_dir=ws,
        source_file="file_a.pdf",
        file_type="pdf",
        final_state="CERTIFIED_MASTER_READY",
        has_prior_failure=True,
    )
    rejected = build_knowledge_entry(
        quality_report={**_FAIL_REPORT},
        evidence_dir=ev_b,
        workspace_dir=ws,
        source_file="file_b.pdf",  # DIFFERENT source
        file_type="pdf",
        final_state="FAILED",
        has_prior_failure=False,
    )

    with pytest.raises(ValueError, match="same source identity"):
        build_dpo_pair_from_entries(
            chosen_entry=chosen,
            rejected_entry=rejected,
            chosen_response="good output",
            rejected_response="bad output",
            source_text="source text",
        )


# ── Test 6: DPO pair not created across unrelated files ───────────────────────


def test_dpo_pair_not_created_across_unrelated_files(tmp_path: Path) -> None:
    """record_knowledge_source must not write a DPO pair when the only prior
    failed entry belongs to a different source file."""
    ws = _workspace(tmp_path)

    # Cycle A: fail on file_a.pdf
    ev_a = tmp_path / "ev_a"
    src_a, resp_a = _write_text_artifacts(ev_a, "source A", "failed output A")
    report_a = {**_FAIL_REPORT, "source_text_path": src_a, "master_document_path": resp_a}
    record_knowledge_source(
        evidence_dir=ev_a,
        workspace_dir=ws,
        quality_report=report_a,
        source_file="file_a.pdf",
        file_type="pdf",
        final_state="FAILED",
    )

    # Cycle B: pass on file_b.pdf (different file — no valid DPO partner)
    ev_b = tmp_path / "ev_b"
    src_b, resp_b = _write_text_artifacts(ev_b, "source B", "master output B")
    report_b = {**_PASS_REPORT, "source_text_path": src_b, "master_document_path": resp_b}
    record_knowledge_source(
        evidence_dir=ev_b,
        workspace_dir=ws,
        quality_report=report_b,
        source_file="file_b.pdf",  # different source
        file_type="pdf",
        final_state="CERTIFIED_MASTER_READY",
        has_prior_failure=True,  # would trigger DPO if same source found
    )

    # DPO pair must NOT have been written (no matching prior failure for file_b)
    dpo = _read_jsonl(ws / "axi_ft_log" / "dpo_pairs.jsonl")
    assert dpo == []

    # Gold pair for file_b must have been written
    gold = _read_jsonl(ws / "axi_ft_log" / "gold_pairs.jsonl")
    assert len(gold) == 1


# ── Step 4 — Two-cycle evidence validation ────────────────────────────────────


def test_two_cycle_evidence_fail_then_pass_produces_dpo(tmp_path: Path) -> None:
    """Full evidence validation: fail cycle followed by pass cycle on same file.

    Verifies:
    - 2 learning entries total
    - 1 gold pair (from the passing cycle)
    - 1 DPO pair (chosen=pass, rejected=fail, same source file)
    - bottleneck captured correctly in DPO pair
    - component scores present in both learning entries
    """
    ws = _workspace(tmp_path)
    source_file = "fixture.pdf"

    # ── Cycle 1: forced fail ──────────────────────────────────────────────────
    ev1 = tmp_path / "ev1"
    src1, resp1 = _write_text_artifacts(ev1, "source document text", "failed master v1")
    fail_scores = {
        "content_richness_score": 0.45,
        "data_retention_score": 0.50,
        "source_to_master_alignment_score": 0.40,
        "structure_score": 0.55,
        "metadata_safety_score": 0.30,  # lowest → bottleneck
    }
    report1 = {
        "quality": 0.45,
        "target_quality": 0.95,
        "audit_status": "COMPONENT_FAIL_REPAIRABLE",
        "component_scores": fail_scores,
        "source_text_path": src1,
        "master_document_path": resp1,
    }
    record_knowledge_source(
        evidence_dir=ev1,
        workspace_dir=ws,
        quality_report=report1,
        source_file=source_file,
        file_type="pdf",
        final_state="FAILED",
    )

    # ── Cycle 2: pass after repair ────────────────────────────────────────────
    ev2 = tmp_path / "ev2"
    src2, resp2 = _write_text_artifacts(ev2, "source document text", "certified master v2")
    pass_scores = {
        "content_richness_score": 0.97,
        "data_retention_score": 0.96,
        "source_to_master_alignment_score": 0.95,
        "structure_score": 0.94,
        "metadata_safety_score": 0.92,
    }
    report2 = {
        "quality": 0.97,
        "target_quality": 0.95,
        "audit_status": "COMPONENT_PASS",
        "component_scores": pass_scores,
        "source_text_path": src2,
        "master_document_path": resp2,
    }
    entry2 = record_knowledge_source(
        evidence_dir=ev2,
        workspace_dir=ws,
        quality_report=report2,
        source_file=source_file,
        file_type="pdf",
        final_state="CERTIFIED_MASTER_READY",
        has_prior_failure=True,
    )

    # ── Verify learning entries ───────────────────────────────────────────────
    learning = _read_jsonl(ws / "axi_ft_log" / "docsreg_learning.jsonl")
    assert len(learning) == 2, f"Expected 2 learning entries, got {len(learning)}"

    e_fail, e_pass = learning[0], learning[1]
    assert e_fail["outcome"]["passed"] is False
    assert e_pass["outcome"]["passed"] is True

    # Component scores in both entries
    for e in learning:
        cs = e["component_scores"]
        assert set(cs.keys()) == {
            "content_richness_score",
            "data_retention_score",
            "source_to_master_alignment_score",
            "structure_score",
            "metadata_safety_score",
        }

    # Bottleneck in fail entry
    assert e_fail["bottleneck"]["key"] == "metadata_safety_score"
    assert e_fail["bottleneck"]["score"] == pytest.approx(0.30)

    # ── Verify gold pair ──────────────────────────────────────────────────────
    gold = _read_jsonl(ws / "axi_ft_log" / "gold_pairs.jsonl")
    assert len(gold) == 1, f"Expected 1 gold pair, got {len(gold)}"
    gp = gold[0]
    assert gp["schema_version"] == "docsreg.sft_pair.v1"
    assert gp["response"] == "certified master v2"
    assert gp["approved_for_training"] is False
    assert gp["quality"] == pytest.approx(0.97)

    # ── Verify DPO pair ───────────────────────────────────────────────────────
    dpo = _read_jsonl(ws / "axi_ft_log" / "dpo_pairs.jsonl")
    assert len(dpo) == 1, f"Expected 1 DPO pair, got {len(dpo)}"
    dp = dpo[0]
    assert dp["schema_version"] == "docsreg.dpo_pair.v1"
    assert dp["chosen"] == "certified master v2"
    assert dp["rejected"] == "failed master v1"
    assert dp["approved_for_training"] is False
    assert dp["chosen_quality"] == pytest.approx(0.97)
    assert dp["rejected_quality"] == pytest.approx(0.45)
    assert dp["quality_delta"] == pytest.approx(0.97 - 0.45)

    # Bottleneck delta captured
    assert dp["bottleneck_delta"]["rejected_key"] == "metadata_safety_score"
    assert dp["bottleneck_delta"]["rejected_score"] == pytest.approx(0.30)

    # Same-source identity
    assert dp["source_file"] == source_file

    # Invariant
    assert entry2["training"]["approved_for_training"] is False
