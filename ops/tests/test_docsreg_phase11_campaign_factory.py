"""
DOCSREG Phase 11 — Campaign factory tests.

Tests ``build_production_campaign_runner()`` — the single entry point that
wires the Phase 10 production auditor, a ``DocumentTypeCertificationLoop``,
and a ``CampaignRunner`` together.

All tests are deterministic (no LLM, no Redis, no network).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ops.docsreg.docsreg_campaign_factory import build_production_campaign_runner
from ops.docsreg.docsreg_campaign_runner import CampaignOutcome, CampaignRunner
from ops.docsreg.docsreg_document_type_cycle import (
    OUTCOME_CERTIFIED,
    OUTCOME_STALLED,
    DocumentTypeCertificationLoop,
    DocumentTypeCycleOutcome,
    _noop_auditor,
)
from ops.docsreg.docsreg_production_auditor import build_structure_auditor_fn


# ── Helpers ────────────────────────────────────────────────────────────────────


def _certified_outcome(doc_type: str, quality: float = 0.95) -> DocumentTypeCycleOutcome:
    """Stub a certified DocumentTypeCycleOutcome for a given type."""
    return DocumentTypeCycleOutcome(
        document_type=doc_type,
        outcome=OUTCOME_CERTIFIED,
        passed=True,
        cycles_run=1,
        best_quality=quality,
        cycle_history=[],
        evidence_dir="",
        notes="certified in test",
    )


def _failed_outcome(doc_type: str) -> DocumentTypeCycleOutcome:
    """Stub a stalled (not certified) DocumentTypeCycleOutcome."""
    return DocumentTypeCycleOutcome(
        document_type=doc_type,
        outcome=OUTCOME_STALLED,
        passed=False,
        cycles_run=1,
        best_quality=0.0,
        cycle_history=[],
        evidence_dir="",
        notes="stalled in test",
    )


# ── Factory contract tests ─────────────────────────────────────────────────────


def test_factory_returns_campaign_runner(tmp_path) -> None:
    orchestrator = MagicMock()
    runner = build_production_campaign_runner(
        orchestrator=orchestrator,
        evidence_root=tmp_path / "evidence",
    )
    assert isinstance(runner, CampaignRunner)


def test_factory_wires_production_auditor_not_noop(tmp_path) -> None:
    """The loop inside the runner must use the production auditor, not _noop_auditor."""
    orchestrator = MagicMock()
    runner = build_production_campaign_runner(
        orchestrator=orchestrator,
        evidence_root=tmp_path / "evidence",
    )
    loop: DocumentTypeCertificationLoop = runner._loop
    assert loop._auditor_fn is not _noop_auditor


def test_factory_loop_is_certification_loop(tmp_path) -> None:
    orchestrator = MagicMock()
    runner = build_production_campaign_runner(
        orchestrator=orchestrator,
        evidence_root=tmp_path / "evidence",
    )
    assert isinstance(runner._loop, DocumentTypeCertificationLoop)


def test_factory_respects_auditor_threshold(tmp_path) -> None:
    """Two factories with different thresholds must inject distinct callables."""
    orch = MagicMock()
    runner_strict = build_production_campaign_runner(
        orchestrator=orch,
        evidence_root=tmp_path / "strict",
        auditor_threshold=0.99,
    )
    runner_loose = build_production_campaign_runner(
        orchestrator=orch,
        evidence_root=tmp_path / "loose",
        auditor_threshold=0.10,
    )
    # The injected functions should be distinct objects (each factory call
    # builds a fresh closure capturing the threshold).
    assert runner_strict._loop._auditor_fn is not runner_loose._loop._auditor_fn


def test_factory_sets_evidence_root(tmp_path) -> None:
    ev_root = tmp_path / "campaign_ev"
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=ev_root,
    )
    assert runner._evidence_root == ev_root


def test_factory_passes_max_cycles(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
        max_cycles=3,
    )
    assert runner._loop._max_cycles == 3


def test_factory_passes_target_quality(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
        target_quality=0.75,
    )
    assert runner._loop._target_quality == 0.75


def test_factory_passes_document_text(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
        document_text="seed content for testing",
    )
    assert runner._loop._document_text == "seed content for testing"


# ── Empty document types list ──────────────────────────────────────────────────


def test_empty_document_types_returns_skipped_campaign(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    outcome = runner.run_campaign(document_types=[])
    assert isinstance(outcome, CampaignOutcome)
    assert outcome.total_types == 0
    assert outcome.certified_count == 0
    assert outcome.failed_count == 0
    assert not outcome.all_certified()


# ── E2E campaign with mocked loop ─────────────────────────────────────────────


def test_run_campaign_single_type_certified(tmp_path) -> None:
    """E2E: one type, mock loop returns certified → CampaignOutcome.all_certified()."""
    orchestrator = MagicMock()
    runner = build_production_campaign_runner(
        orchestrator=orchestrator,
        evidence_root=tmp_path / "ev",
    )
    runner._loop.run_document_type = MagicMock(
        return_value=_certified_outcome("test_procedure")
    )

    outcome = runner.run_campaign(document_types=["test_procedure"])

    assert outcome.total_types == 1
    assert outcome.certified_count == 1
    assert outcome.failed_count == 0
    assert outcome.all_certified()


def test_run_campaign_single_type_failed(tmp_path) -> None:
    """E2E: one type, mock loop returns stalled → not all_certified."""
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    runner._loop.run_document_type = MagicMock(
        return_value=_failed_outcome("test_procedure")
    )

    outcome = runner.run_campaign(document_types=["test_procedure"])

    assert outcome.total_types == 1
    assert outcome.certified_count == 0
    assert outcome.failed_count == 1
    assert not outcome.all_certified()


def test_run_campaign_multiple_types_all_certified(tmp_path) -> None:
    doc_types = ["procedure_a", "procedure_b", "policy_c"]
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    runner._loop.run_document_type = MagicMock(
        side_effect=lambda document_type: _certified_outcome(document_type)
    )

    outcome = runner.run_campaign(document_types=doc_types)

    assert outcome.total_types == 3
    assert outcome.certified_count == 3
    assert outcome.failed_count == 0
    assert outcome.all_certified()
    assert [r.document_type for r in outcome.results] == doc_types


def test_run_campaign_mixed_results(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    runner._loop.run_document_type = MagicMock(
        side_effect=lambda document_type: (
            _certified_outcome(document_type)
            if document_type == "type_pass"
            else _failed_outcome(document_type)
        )
    )

    outcome = runner.run_campaign(document_types=["type_pass", "type_fail"])

    assert outcome.total_types == 2
    assert outcome.certified_count == 1
    assert outcome.failed_count == 1
    assert not outcome.all_certified()


# ── Campaign summary JSON written ──────────────────────────────────────────────


def test_run_campaign_writes_summary_json(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    runner._loop.run_document_type = MagicMock(
        return_value=_certified_outcome("summary_type")
    )

    outcome = runner.run_campaign(document_types=["summary_type"])

    # Summary is written inside <evidence_root>/<campaign_id>/campaign_summary.json
    campaign_dir = tmp_path / "ev" / outcome.campaign_id
    summary_path = campaign_dir / "campaign_summary.json"
    assert summary_path.exists(), f"campaign_summary.json not found at {summary_path}"


def test_campaign_summary_json_has_required_fields(tmp_path) -> None:
    import json

    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    runner._loop.run_document_type = MagicMock(
        return_value=_certified_outcome("field_check_type")
    )

    outcome = runner.run_campaign(document_types=["field_check_type"])
    summary_path = tmp_path / "ev" / outcome.campaign_id / "campaign_summary.json"
    data = json.loads(summary_path.read_text())

    for key in ("campaign_id", "started_at", "finished_at", "total_types",
                "certified_count", "failed_count", "results"):
        assert key in data, f"Missing key in campaign_summary.json: {key!r}"


# ── all_certified semantics ────────────────────────────────────────────────────


def test_all_certified_true_when_all_pass(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    runner._loop.run_document_type = MagicMock(
        side_effect=lambda document_type: _certified_outcome(document_type)
    )
    outcome = runner.run_campaign(document_types=["t1", "t2"])
    assert outcome.all_certified() is True


def test_all_certified_false_when_zero_types(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    outcome = runner.run_campaign(document_types=[])
    assert outcome.all_certified() is False


def test_all_certified_false_when_partial_pass(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    runner._loop.run_document_type = MagicMock(
        side_effect=lambda document_type: (
            _certified_outcome(document_type) if document_type == "pass"
            else _failed_outcome(document_type)
        )
    )
    outcome = runner.run_campaign(document_types=["pass", "fail"])
    assert outcome.all_certified() is False


# ── CampaignOutcome fields ─────────────────────────────────────────────────────


def test_campaign_outcome_has_campaign_id(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    runner._loop.run_document_type = MagicMock(
        return_value=_certified_outcome("doc_type")
    )
    outcome = runner.run_campaign(document_types=["doc_type"])
    assert outcome.campaign_id.startswith("campaign_")


def test_campaign_outcome_timestamps_present(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    runner._loop.run_document_type = MagicMock(
        return_value=_certified_outcome("ts_type")
    )
    outcome = runner.run_campaign(document_types=["ts_type"])
    assert outcome.started_at
    assert outcome.finished_at


def test_campaign_result_best_quality_propagated(tmp_path) -> None:
    runner = build_production_campaign_runner(
        orchestrator=MagicMock(),
        evidence_root=tmp_path / "ev",
    )
    runner._loop.run_document_type = MagicMock(
        return_value=_certified_outcome("quality_type", quality=0.97)
    )
    outcome = runner.run_campaign(document_types=["quality_type"])
    assert outcome.results[0].best_quality == pytest.approx(0.97)
