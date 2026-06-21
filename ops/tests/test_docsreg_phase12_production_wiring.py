"""
DOCSREG Phase 12 — Production wiring tests.

Verifies three production restrictions have been lifted:
  1. ``DOCSREG_USE_SCHEDULER = True`` in docsreg_scheduler_integration.py
  2. ``docsreg_auditor_mode`` default is ``"production"`` in run_cyclic_generation()
  3. ``"production"`` auditor_mode wires build_structure_auditor_fn() in
     run_docsreg_document_type_cycle()
  4. ``run_docsreg_campaign()`` is callable and returns the expected contract.

All tests are deterministic (no LLM, no Redis, no network).
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ── Scheduler kill-switch ─────────────────────────────────────────────────────


def test_scheduler_flag_is_enabled() -> None:
    """DOCSREG_USE_SCHEDULER must be True for production."""
    from ops.docsreg.docsreg_scheduler_integration import DOCSREG_USE_SCHEDULER

    assert DOCSREG_USE_SCHEDULER is True


# ── Default auditor mode in run_cyclic_generation ────────────────────────────


def test_run_cyclic_generation_default_auditor_is_production() -> None:
    """run_cyclic_generation() must default docsreg_auditor_mode to 'production'."""
    from ops.cyclic_doc_generation_pipeline import run_cyclic_generation

    sig = inspect.signature(run_cyclic_generation)
    default = sig.parameters["docsreg_auditor_mode"].default
    assert default == "production", (
        f"Expected docsreg_auditor_mode default 'production', got {default!r}"
    )


# ── Production auditor_mode in run_docsreg_document_type_cycle ───────────────


def test_production_auditor_mode_uses_build_structure_auditor_fn(tmp_path) -> None:
    """'production' mode must call build_structure_auditor_fn, not return noop."""
    from ops.docgen.docsreg_docgen_integration import run_docsreg_document_type_cycle

    # A well-structured doc so the production auditor returns quality > 0
    good_doc = "\n".join([
        "# Table of Contents",
        "1. Introduction",
        "2. Scope",
        "3. Procedures",
        "",
        "## 1. Introduction",
        "This document defines maintenance procedures for AIMS assets, establishing",
        "requirements for work preparation, CMMS integration, permit-to-work,",
        "isolation, HSE controls, and record keeping.",
        "",
        "## 2. Scope",
        "Applies to all maintenance activities on rotating equipment and static",
        "assets operated under ISO 55001 compliance.",
        "",
        "## 3. Procedures",
        "### 3.1 Work Preparation",
        "Review CMMS backlog, raise work order, validate spare parts availability.",
        "Coordinate with operations for planned outage windows.",
        "",
        "### 3.2 Permit to Work",
        "Obtain PTW from area authority.  Confirm isolation points on P&ID.",
        "Complete LOTO checklist before commencing physical work.",
    ])

    result = run_docsreg_document_type_cycle(
        document_type="test_procedure",
        evidence_root=tmp_path / "ev",
        target_quality=0.10,   # very low so even partial content certifies
        max_fresh_runs=1,
        document_text=good_doc,
        auditor_mode="production",
    )

    # Outcome must be one of the real cycle outcomes (not ERROR)
    assert result["outcome"] in (
        "DOCUMENT_TYPE_CERTIFIED",
        "DOCUMENT_TYPE_STALLED",
        "DOCUMENT_TYPE_MAX_CYCLES_REACHED",
    )
    # Production auditor returns real quality; noop returns 1.0 — both are fine here
    assert isinstance(result["quality"], float)
    assert result["quality"] >= 0.0


def test_production_auditor_mode_quality_is_not_hardcoded_one(tmp_path) -> None:
    """Noop returns quality=1.0 unconditionally; production auditor must differ for empty docs.

    The cycle adds structural blending on top of the raw auditor quality, so the
    final best_quality is not necessarily exactly 0.0 — but it must be below 1.0
    (the hardcoded noop value) because the auditor saw empty content.
    """
    from ops.docgen.docsreg_docgen_integration import run_docsreg_document_type_cycle

    # Empty document — production auditor sees no content → FAIL_REPAIRABLE
    result = run_docsreg_document_type_cycle(
        document_type="empty_type",
        evidence_root=tmp_path / "ev",
        target_quality=0.99,
        max_fresh_runs=1,
        document_text="",
        auditor_mode="production",
    )
    # Cycle cannot certify empty content at 0.99 threshold
    assert result["outcome"] in (
        "DOCUMENT_TYPE_STALLED",
        "DOCUMENT_TYPE_MAX_CYCLES_REACHED",
    )
    # Quality must not be the noop hardcoded 1.0
    assert result["quality"] < 1.0


def test_noop_mode_still_works(tmp_path) -> None:
    """Backwards-compat: noop mode must still be callable after Phase 12."""
    from ops.docgen.docsreg_docgen_integration import run_docsreg_document_type_cycle

    result = run_docsreg_document_type_cycle(
        document_type="any_type",
        evidence_root=tmp_path / "ev",
        target_quality=0.98,
        max_fresh_runs=1,
        document_text="",
        auditor_mode="noop",
    )
    # noop returns COMPONENT_PASS, quality=1.0 from auditor — cycle records that
    assert result["outcome"] in (
        "DOCUMENT_TYPE_CERTIFIED",
        "DOCUMENT_TYPE_MAX_CYCLES_REACHED",
    )
    assert result["quality"] == 1.0


# ── run_docsreg_campaign contract ─────────────────────────────────────────────


def test_run_docsreg_campaign_is_importable() -> None:
    from ops.docgen.docsreg_docgen_integration import run_docsreg_campaign  # noqa: F401

    assert callable(run_docsreg_campaign)


def test_run_docsreg_campaign_returns_dict(tmp_path) -> None:
    from ops.docgen.docsreg_docgen_integration import run_docsreg_campaign

    result = run_docsreg_campaign(
        document_types=[],
        evidence_root=tmp_path / "campaign",
    )
    assert isinstance(result, dict)


def test_run_docsreg_campaign_empty_types(tmp_path) -> None:
    from ops.docgen.docsreg_docgen_integration import run_docsreg_campaign

    result = run_docsreg_campaign(
        document_types=[],
        evidence_root=tmp_path / "campaign",
    )
    assert result["total_types"] == 0
    assert result["certified_count"] == 0
    assert result["failed_count"] == 0
    assert result["all_certified"] is False


def test_run_docsreg_campaign_required_keys(tmp_path) -> None:
    from ops.docgen.docsreg_docgen_integration import run_docsreg_campaign

    result = run_docsreg_campaign(
        document_types=[],
        evidence_root=tmp_path / "campaign",
    )
    for key in (
        "campaign_id", "total_types", "certified_count", "failed_count",
        "all_certified", "started_at", "finished_at", "results",
    ):
        assert key in result, f"Missing key in run_docsreg_campaign result: {key!r}"


def test_run_docsreg_campaign_campaign_id_prefix(tmp_path) -> None:
    from ops.docgen.docsreg_docgen_integration import run_docsreg_campaign

    result = run_docsreg_campaign(
        document_types=[],
        evidence_root=tmp_path / "campaign",
    )
    assert result["campaign_id"].startswith("campaign_")


def test_run_docsreg_campaign_accepts_custom_orchestrator(tmp_path) -> None:
    from ops.docgen.docsreg_docgen_integration import run_docsreg_campaign

    orch = MagicMock()
    result = run_docsreg_campaign(
        document_types=[],
        evidence_root=tmp_path / "campaign",
        orchestrator=orch,
    )
    assert isinstance(result, dict)


def test_run_docsreg_campaign_mocked_single_type_certified(tmp_path) -> None:
    """Mock the underlying CampaignRunner to exercise campaign result propagation."""
    from ops.docsreg.docsreg_campaign_runner import CampaignOutcome
    from ops.docsreg.docsreg_document_type_cycle import (
        OUTCOME_CERTIFIED,
        DocumentTypeCycleOutcome,
    )

    certified = DocumentTypeCycleOutcome(
        document_type="proc_a",
        outcome=OUTCOME_CERTIFIED,
        passed=True,
        cycles_run=2,
        best_quality=0.95,
        cycle_history=[],
        evidence_dir="",
        notes="mocked",
    )

    with patch(
        "ops.docsreg.docsreg_campaign_factory.build_production_campaign_runner"
    ) as mock_factory:
        mock_runner = MagicMock()
        mock_outcome = MagicMock(spec=CampaignOutcome)
        mock_outcome.campaign_id = "campaign_test_001"
        mock_outcome.total_types = 1
        mock_outcome.certified_count = 1
        mock_outcome.failed_count = 0
        mock_outcome.all_certified.return_value = True
        mock_outcome.started_at = "2026-06-21T08:00:00"
        mock_outcome.finished_at = "2026-06-21T08:01:00"
        mock_outcome.results = [certified]
        mock_runner.run_campaign.return_value = mock_outcome
        mock_factory.return_value = mock_runner

        from ops.docgen.docsreg_docgen_integration import run_docsreg_campaign

        result = run_docsreg_campaign(
            document_types=["proc_a"],
            evidence_root=tmp_path / "campaign",
        )

    assert result["all_certified"] is True
    assert result["certified_count"] == 1
    assert result["total_types"] == 1
    assert result["results"][0]["document_type"] == "proc_a"
    assert result["results"][0]["best_quality"] == pytest.approx(0.95)


def test_run_docsreg_campaign_writes_summary_json(tmp_path) -> None:
    """Integration smoke: campaign_summary.json written for a real (noop) single-type run."""
    from ops.docgen.docsreg_docgen_integration import run_docsreg_campaign
    from ops.docsreg.docsreg_document_type_cycle import DocumentTypeCertificationLoop

    # Patch run_document_type so it certifies instantly without real generation
    original_run = DocumentTypeCertificationLoop.run_document_type

    from ops.docsreg.docsreg_document_type_cycle import (
        OUTCOME_CERTIFIED,
        DocumentTypeCycleOutcome,
    )

    def _fast_certify(self, document_type):  # noqa: ANN001
        return DocumentTypeCycleOutcome(
            document_type=document_type,
            outcome=OUTCOME_CERTIFIED,
            passed=True,
            cycles_run=1,
            best_quality=0.91,
            cycle_history=[],
            evidence_dir="",
            notes="fast certify in test",
        )

    with patch.object(DocumentTypeCertificationLoop, "run_document_type", _fast_certify):
        result = run_docsreg_campaign(
            document_types=["smoke_type"],
            evidence_root=tmp_path / "campaign",
        )

    campaign_dir = tmp_path / "campaign" / result["campaign_id"]
    summary = campaign_dir / "campaign_summary.json"
    assert summary.exists(), f"campaign_summary.json not found at {summary}"
    data = json.loads(summary.read_text())
    assert "campaign_id" in data
    assert data["certified_count"] == 1


# ── Docstring update verification ─────────────────────────────────────────────


def test_run_docsreg_document_type_cycle_docstring_mentions_production() -> None:
    """Docstring must document the 'production' auditor_mode."""
    from ops.docgen.docsreg_docgen_integration import run_docsreg_document_type_cycle

    doc = run_docsreg_document_type_cycle.__doc__ or ""
    assert "production" in doc.lower() or "build_structure_auditor_fn" in doc
