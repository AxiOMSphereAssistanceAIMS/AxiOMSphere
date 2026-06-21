"""
DOCSREG Phase 10 — Production auditor bridge.

Provides ``build_structure_auditor_fn()`` which constructs a synchronous
``auditor_fn(manifest) -> dict`` compatible with
:class:`~ops.docsreg.docsreg_document_type_cycle.DocumentTypeCertificationLoop`.

The returned callable uses :func:`ops.cyclic_skills.validate_structure` —
pure text analysis, no LLM calls — so it is safe to use in unit tests and
deterministic in CI.

Audit dict contract (same schema as ``_noop_auditor``)::

    {
        "status":               str,    # AUDIT_STATUS_* constant
        "quality":              float,  # 0.0–1.0
        "section_coverage":     float,  # 0.0–1.0
        "reference_governance": str,    # "PASS" | "UNKNOWN"
        "recommendations":      list,   # human-readable repair hints
    }

Typical usage::

    from ops.docsreg.docsreg_production_auditor import build_structure_auditor_fn
    from ops.docsreg.docsreg_document_type_cycle import DocumentTypeCertificationLoop

    auditor_fn = build_structure_auditor_fn(threshold=0.90)
    loop = DocumentTypeCertificationLoop(orchestrator, auditor_fn=auditor_fn)
"""
from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger("docsreg_production_auditor")

# Maximum number of section names echoed in recommendations (keeps output terse).
_MAX_SECTION_ECHO = 3


def build_structure_auditor_fn(threshold: float = 0.90) -> Callable[[Any], dict]:
    """Return a synchronous ``auditor_fn`` backed by ``validate_structure()``.

    Parameters
    ----------
    threshold:
        Completeness ratio (0.0–1.0) required for COMPONENT_PASS verdict.
        Default 0.90 matches the ArchetypeQualityValidator default.

    Returns
    -------
    Callable[[manifest], dict]
        Drop-in replacement for ``_noop_auditor``.
    """
    from ops.docsreg.docsreg_document_type_cycle import (  # noqa: PLC0415
        AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE,
        AUDIT_STATUS_COMPONENT_PASS,
    )

    def auditor_fn(manifest: Any) -> dict:  # noqa: ANN401
        content: str = getattr(manifest, "document_text", "") or ""
        archetype_type: str = getattr(manifest, "document_type", "unknown") or "unknown"

        if not content.strip():
            log.warning(
                "production_auditor: document_text empty for type=%r — FAIL_REPAIRABLE",
                archetype_type,
            )
            return {
                "status": AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE,
                "quality": 0.0,
                "section_coverage": 0.0,
                "reference_governance": "UNKNOWN",
                "recommendations": ["document_text is empty — regenerate document before audit"],
            }

        from ops.cyclic_skills import validate_structure  # noqa: PLC0415

        report = validate_structure(content, threshold)
        quality = report.completeness_ratio
        section_coverage = report.completeness_ratio

        recommendations: list[str] = []
        if report.empty_sections:
            echoed = report.empty_sections[:_MAX_SECTION_ECHO]
            recommendations.append(
                f"Fill {len(report.empty_sections)} empty section(s): {', '.join(echoed)}"
            )
        if report.stub_sections:
            echoed = report.stub_sections[:_MAX_SECTION_ECHO]
            recommendations.append(
                f"Expand {len(report.stub_sections)} stub section(s): {', '.join(echoed)}"
            )
        if not report.passed:
            recommendations.append(
                f"Completeness {quality:.1%} below threshold {threshold:.0%}"
            )

        status = (
            AUDIT_STATUS_COMPONENT_PASS
            if report.passed
            else AUDIT_STATUS_COMPONENT_FAIL_REPAIRABLE
        )
        reference_governance = "PASS" if report.passed else "UNKNOWN"

        log.info(
            "production_auditor: type=%r quality=%.4f coverage=%.4f status=%s",
            archetype_type,
            quality,
            section_coverage,
            status,
        )
        return {
            "status": status,
            "quality": quality,
            "section_coverage": section_coverage,
            "reference_governance": reference_governance,
            "recommendations": recommendations,
        }

    return auditor_fn
