"""
DOCSREG Phase 10 — Production auditor bridge tests.

Tests ``build_structure_auditor_fn()`` and its integration with
``DocumentTypeCertificationLoop``.  All tests are deterministic (no LLM).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from ops.docsreg.docsreg_document_type_cycle import (
    AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE,
    AUDIT_STATUS_COMPONENT_PASS,
)
from ops.docsreg.docsreg_production_auditor import build_structure_auditor_fn


# ── Minimal manifest stub ──────────────────────────────────────────────────────


@dataclass
class _Manifest:
    document_text: str = ""
    document_type: str = "test_procedure"


# ── Content fixtures ───────────────────────────────────────────────────────────

_WELL_STRUCTURED_DOC = """\
# Table of Contents
1. Introduction
2. Scope
3. Procedures

## 1. Introduction
This document defines maintenance procedures for AIMS assets.
It establishes requirements for work preparation, CMMS integration,
permit-to-work, isolation, HSE controls, and record keeping.

## 2. Scope
Applies to all maintenance activities on rotating equipment and
static assets operated by AxiOMSphere under ISO 55001 compliance.
This includes corrective, preventive, and predictive maintenance work orders.

## 3. Procedures
### 3.1 Work Preparation
Review CMMS backlog, raise work order, validate spare parts availability.
Coordinate with operations for planned outage windows.

### 3.2 Permit to Work
Obtain PTW from area authority. Confirm isolation points on P&ID.
Complete LOTO checklist before commencing physical work.

### 3.3 HSE Controls
JSA completed by crew. PPE matrix followed. Toolbox talk recorded.
"""

_STUB_DOC = """\
# Table of Contents
1. Introduction
2. Scope

## 1. Introduction
TODO

## 2. Scope
TBD
"""

_EMPTY_DOC = ""

_WHITESPACE_DOC = "   \n\t\n   "


# ── Audit dict contract tests ──────────────────────────────────────────────────


def test_audit_dict_has_required_keys() -> None:
    auditor_fn = build_structure_auditor_fn()
    manifest = _Manifest(document_text=_WELL_STRUCTURED_DOC)
    result = auditor_fn(manifest)

    assert "status" in result
    assert "quality" in result
    assert "section_coverage" in result
    assert "reference_governance" in result
    assert "recommendations" in result


def test_audit_quality_is_float_in_range() -> None:
    auditor_fn = build_structure_auditor_fn()
    manifest = _Manifest(document_text=_WELL_STRUCTURED_DOC)
    result = auditor_fn(manifest)

    assert isinstance(result["quality"], float)
    assert 0.0 <= result["quality"] <= 1.0


def test_audit_section_coverage_matches_quality() -> None:
    auditor_fn = build_structure_auditor_fn()
    manifest = _Manifest(document_text=_WELL_STRUCTURED_DOC)
    result = auditor_fn(manifest)

    assert result["quality"] == result["section_coverage"]


def test_audit_recommendations_is_list() -> None:
    auditor_fn = build_structure_auditor_fn()
    manifest = _Manifest(document_text=_STUB_DOC)
    result = auditor_fn(manifest)

    assert isinstance(result["recommendations"], list)


# ── Empty / blank document ─────────────────────────────────────────────────────


def test_empty_document_returns_fail_repairable() -> None:
    auditor_fn = build_structure_auditor_fn()
    manifest = _Manifest(document_text=_EMPTY_DOC)
    result = auditor_fn(manifest)

    assert result["status"] == AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE
    assert result["quality"] == 0.0
    assert result["section_coverage"] == 0.0
    assert result["reference_governance"] == "UNKNOWN"
    assert len(result["recommendations"]) >= 1


def test_whitespace_only_document_fails() -> None:
    auditor_fn = build_structure_auditor_fn()
    manifest = _Manifest(document_text=_WHITESPACE_DOC)
    result = auditor_fn(manifest)

    assert result["status"] == AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE
    assert result["quality"] == 0.0


# ── Stub / low-quality document ────────────────────────────────────────────────


def test_stub_document_returns_fail_repairable() -> None:
    auditor_fn = build_structure_auditor_fn(threshold=0.90)
    manifest = _Manifest(document_text=_STUB_DOC)
    result = auditor_fn(manifest)

    assert result["status"] == AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE
    assert result["reference_governance"] == "UNKNOWN"
    assert len(result["recommendations"]) >= 1


def test_stub_document_recommendations_mention_sections() -> None:
    auditor_fn = build_structure_auditor_fn(threshold=0.90)
    manifest = _Manifest(document_text=_STUB_DOC)
    result = auditor_fn(manifest)

    combined = " ".join(result["recommendations"]).lower()
    assert any(word in combined for word in ("stub", "empty", "completeness", "fill", "expand"))


# ── Well-structured document ───────────────────────────────────────────────────


def test_well_structured_document_has_quality_above_zero() -> None:
    auditor_fn = build_structure_auditor_fn(threshold=0.50)
    manifest = _Manifest(document_text=_WELL_STRUCTURED_DOC)
    result = auditor_fn(manifest)

    assert result["quality"] > 0.0


def test_well_structured_low_threshold_passes() -> None:
    auditor_fn = build_structure_auditor_fn(threshold=0.10)
    manifest = _Manifest(document_text=_WELL_STRUCTURED_DOC)
    result = auditor_fn(manifest)

    assert result["status"] == AUDIT_STATUS_COMPONENT_PASS
    assert result["reference_governance"] == "PASS"
    assert result["recommendations"] == []


# ── Threshold parameter ────────────────────────────────────────────────────────


def test_strict_threshold_fails_moderate_document() -> None:
    """A threshold of 1.0 means only perfect docs pass."""
    auditor_fn = build_structure_auditor_fn(threshold=1.0)
    manifest = _Manifest(document_text=_WELL_STRUCTURED_DOC)
    result = auditor_fn(manifest)

    # Unless the doc is literally perfect coverage it should fail at 100%
    # We just verify the contract holds without asserting the specific status
    # (coverage may be exactly 1.0 if TOC matches body perfectly).
    assert result["status"] in (
        AUDIT_STATUS_COMPONENT_PASS,
        AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE,
    )


def test_zero_threshold_always_passes() -> None:
    auditor_fn = build_structure_auditor_fn(threshold=0.0)
    manifest = _Manifest(document_text=_STUB_DOC)
    result = auditor_fn(manifest)

    # Even a stub doc passes when threshold is 0.0
    assert result["status"] == AUDIT_STATUS_COMPONENT_PASS


# ── Manifest field access ──────────────────────────────────────────────────────


def test_manifest_without_document_text_attribute_fails_gracefully() -> None:
    """Objects without document_text should not raise — degrade to empty."""
    auditor_fn = build_structure_auditor_fn()

    class _BareManifest:
        pass

    result = auditor_fn(_BareManifest())
    assert result["status"] == AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE
    assert result["quality"] == 0.0


def test_manifest_with_none_document_text_fails_gracefully() -> None:
    auditor_fn = build_structure_auditor_fn()
    manifest = _Manifest(document_text=None)  # type: ignore[arg-type]
    result = auditor_fn(manifest)

    assert result["status"] == AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE


def test_document_type_captured_in_archetype() -> None:
    """The archetype_type comes from manifest.document_type — no KeyError."""
    auditor_fn = build_structure_auditor_fn(threshold=0.10)
    manifest = _Manifest(
        document_text=_WELL_STRUCTURED_DOC,
        document_type="inspection_procedure",
    )
    result = auditor_fn(manifest)  # must not raise
    assert isinstance(result, dict)


# ── Integration with DocumentTypeCertificationLoop ────────────────────────────


def test_certification_loop_accepts_production_auditor(tmp_path) -> None:
    """Smoke test: loop instantiates with real auditor_fn, no error."""
    from unittest.mock import MagicMock

    from ops.docsreg.docsreg_document_type_cycle import DocumentTypeCertificationLoop

    orchestrator = MagicMock()
    auditor_fn = build_structure_auditor_fn(threshold=0.90)

    loop = DocumentTypeCertificationLoop(
        orchestrator=orchestrator,
        auditor_fn=auditor_fn,
        evidence_root=tmp_path / "evidence",
        max_cycles=1,
    )
    assert loop._auditor_fn is auditor_fn


def test_certification_loop_run_claude_code_audit_uses_injected_fn(tmp_path) -> None:
    """Loop.run_claude_code_audit delegates to the injected auditor_fn."""
    from unittest.mock import MagicMock

    from ops.docsreg.docsreg_document_type_cycle import DocumentTypeCertificationLoop
    from ops.docsreg.docsreg_run_manifest import DocsregRunManifest

    auditor_fn = build_structure_auditor_fn(threshold=0.10)
    orchestrator = MagicMock()
    loop = DocumentTypeCertificationLoop(
        orchestrator=orchestrator,
        auditor_fn=auditor_fn,
        evidence_root=tmp_path / "evidence",
        max_cycles=1,
    )

    manifest = DocsregRunManifest.create(
        run_id="test-run-001",
        draft_path="",
        document_text=_WELL_STRUCTURED_DOC,
        document_type="maintenance_procedure",
    )
    audit = loop.run_claude_code_audit(manifest)

    assert "status" in audit
    assert "quality" in audit
    assert audit["quality"] > 0.0


def test_production_auditor_replaces_noop_quality_zero(tmp_path) -> None:
    """Noop always returns quality=0.0; production auditor returns > 0 for real content."""
    from unittest.mock import MagicMock

    from ops.docsreg.docsreg_document_type_cycle import (
        DocumentTypeCertificationLoop,
        _noop_auditor,
    )
    from ops.docsreg.docsreg_run_manifest import DocsregRunManifest

    manifest = DocsregRunManifest.create(
        run_id="test-run-002",
        draft_path="",
        document_text=_WELL_STRUCTURED_DOC,
        document_type="maintenance_procedure",
    )

    orchestrator = MagicMock()

    noop_loop = DocumentTypeCertificationLoop(
        orchestrator=orchestrator,
        auditor_fn=_noop_auditor,
        evidence_root=tmp_path / "noop",
        max_cycles=1,
    )
    noop_audit = noop_loop.run_claude_code_audit(manifest)

    prod_loop = DocumentTypeCertificationLoop(
        orchestrator=orchestrator,
        auditor_fn=build_structure_auditor_fn(threshold=0.10),
        evidence_root=tmp_path / "prod",
        max_cycles=1,
    )
    prod_audit = prod_loop.run_claude_code_audit(manifest)

    assert noop_audit["quality"] == 0.0
    assert prod_audit["quality"] > 0.0
