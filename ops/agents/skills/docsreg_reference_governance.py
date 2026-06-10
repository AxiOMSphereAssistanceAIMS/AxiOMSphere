"""
DOCSREG Reference Governance Gate — deterministic fabricated-standards detector.

Scans a document for standards citations that are NOT present in the AIM-PFM
reference (ISO 9000, ISO 55001, ISO 55002).  Common LLM hallucinations such as
API 510/570/580/581, NACE SP0169, ASME B31.3 are classified as FABRICATED and
block certification until removed.

This module is intentionally free of LLM calls and HTTP calls.
Policy (approved standards lists, fabricated patterns) is loaded once at import
time via :mod:`ops.docsreg.docsreg_standards_policy`.

Usage::

    from ops.agents.skills.docsreg_reference_governance import (
        run_reference_governance_gate,
        select_reference_governance_recommendations,
        strip_fabricated_standards,
    )

    result = run_reference_governance_gate(document=doc_text)
    # result.decision        → ReferenceGateDecision
    # result.repair_plan     → list[str] of "Section X.X: remove '...'" strings
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ops.docsreg.docsreg_standards_policy import load_policy as _load_policy

log = logging.getLogger("docsreg_reference_governance")


def _compile_fabricated_patterns() -> re.Pattern:  # type: ignore[type-arg]
    """Compile all FABRICATED_STANDARDS_PATTERNS into a single regex."""
    combined = "|".join(f"(?:{p})" for p in FABRICATED_STANDARDS_PATTERNS)
    return re.compile(combined, re.IGNORECASE)


# ── Load policy and set module-level constants ─────────────────────────────────

REFERENCE_STANDARDS, FABRICATED_STANDARDS_PATTERNS, _ISO_PREFIXES = _load_policy()

# Compiled once at import time — reused across all calls
_FABRICATED_RE: re.Pattern = _compile_fabricated_patterns()  # type: ignore[type-arg]


# ── Enumerations ───────────────────────────────────────────────────────────────


class ReferenceStatus(Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    FABRICATED_SUSPECTED = "FABRICATED_SUSPECTED"
    MISSING_SOURCE = "MISSING_SOURCE"
    OBSOLETE = "OBSOLETE"


class ReferenceGateDecision(Enum):
    PASS = "PASS"
    CERTIFICATION_BLOCKER = "CERTIFICATION_BLOCKER"
    USER_DECISION_REQUIRED = "USER_DECISION_REQUIRED"
    BLOCKED_INSUFFICIENT_EVIDENCE = "BLOCKED_INSUFFICIENT_EVIDENCE"


# ── Data structures ────────────────────────────────────────────────────────────


@dataclass
class ReferenceOccurrence:
    """A single standards reference found in the document."""
    reference_text: str
    status: ReferenceStatus
    appears_in_sections: list[str]
    action: str  # "keep" | "remove" | "replace" | "needs_user_decision"


@dataclass
class ReferenceGateResult:
    """Full outcome of a reference governance gate run."""
    decision: ReferenceGateDecision
    total_references_found: int
    fabricated_count: int
    verified_count: int
    unverified_count: int
    fabricated_references: list[ReferenceOccurrence]
    verified_references: list[ReferenceOccurrence]
    certification_blockers: list[str]
    repair_plan: list[str]
    sections_with_fabricated: list[str]
    gate_version: str = "v1"


# ── Internal helpers ───────────────────────────────────────────────────────────

# Pattern to capture any ISO standards reference in text
_ISO_REF_RE: re.Pattern = re.compile(  # type: ignore[type-arg]
    r"\bISO\s+\d[\d\-:. ]*(?:Series|Family)?\b",
    re.IGNORECASE,
)


def _split_into_sections(
    document: str,
) -> list[tuple[str, str, str]]:
    """Split *document* into (section_id, heading_line, body) tuples.

    Only numeric headings are captured (e.g. ``### 8.4 Leadership``).
    Non-numeric headings (e.g. ``## Table of Contents``) are skipped.
    Identical logic to Phase 3's DocumentContentScanner._split_into_sections.
    """
    sections: list[tuple[str, str, str]] = []
    heading_re = re.compile(
        r"^(#{1,6})\s+(\d+(?:\.\d+)*)\s+(.*?)$",
        re.MULTILINE,
    )

    matches = list(heading_re.finditer(document))
    for idx, match in enumerate(matches):
        section_id = match.group(2)
        title = match.group(3).strip()
        heading_line = f"{match.group(1)} {section_id} {title}"

        body_start = match.end()
        body_end = (
            matches[idx + 1].start() if idx + 1 < len(matches) else len(document)
        )
        body = document[body_start:body_end].strip()

        sections.append((section_id, heading_line, body))

    return sections


def _is_verified_iso(text: str) -> bool:
    """Return True if *text* begins with one of the canonical ISO prefixes."""
    normalised = re.sub(r"\s+", " ", text).strip().upper()
    return any(normalised.startswith(prefix.upper()) for prefix in _ISO_PREFIXES)


# ── Public API ─────────────────────────────────────────────────────────────────


def extract_references(document: str) -> dict[str, list[str]]:
    """Scan the entire document and return a mapping of reference_text to section_ids.

    Captures both fabricated references (API, NACE, ASME, etc.) and canonical
    ISO references (ISO 55001, ISO 9000, ISO 55002).

    Args:
        document: Full document text in markdown format.

    Returns:
        dict mapping reference text to a list of section IDs where it was found.
    """
    ref_to_sections: dict[str, list[str]] = {}

    for section_id, _heading, body in _split_into_sections(document):
        # Fabricated standards
        for match in _FABRICATED_RE.finditer(body):
            normalised = re.sub(r"\s+", " ", match.group()).strip()
            ref_to_sections.setdefault(normalised, [])
            if section_id not in ref_to_sections[normalised]:
                ref_to_sections[normalised].append(section_id)

        # Canonical ISO references
        for match in _ISO_REF_RE.finditer(body):
            raw = match.group()
            normalised = re.sub(r"\s+", " ", raw).strip()
            # Skip ISO refs that are part of fabricated patterns
            # (e.g. "BS EN ISO 14001" — the outer fabricated pattern catches those)
            if _FABRICATED_RE.search(normalised):
                continue
            ref_to_sections.setdefault(normalised, [])
            if section_id not in ref_to_sections[normalised]:
                ref_to_sections[normalised].append(section_id)

    return ref_to_sections


def classify_references(
    document: str,
    source_documents: Optional[list[str]] = None,
) -> list[ReferenceOccurrence]:
    """Classify every standards reference found in the document.

    Classification priority (first match wins):
    1. Matches FABRICATED_STANDARDS_PATTERNS → FABRICATED_SUSPECTED, action="remove"
    2. Matches canonical ISO prefixes → VERIFIED, action="keep"
    3. Found in source_documents → UNVERIFIED, action="needs_user_decision"
    4. Not found anywhere → MISSING_SOURCE, action="needs_user_decision"

    Args:
        document: Full document text.
        source_documents: Optional list of source document texts.

    Returns:
        List of ReferenceOccurrence, one per unique reference string found.
    """
    ref_map = extract_references(document)
    occurrences: list[ReferenceOccurrence] = []

    for ref_text, section_ids in ref_map.items():
        # Priority 1: fabricated pattern match
        if _FABRICATED_RE.search(ref_text):
            occurrences.append(ReferenceOccurrence(
                reference_text=ref_text,
                status=ReferenceStatus.FABRICATED_SUSPECTED,
                appears_in_sections=list(section_ids),
                action="remove",
            ))
            continue

        # Priority 2: canonical ISO reference
        if _is_verified_iso(ref_text):
            occurrences.append(ReferenceOccurrence(
                reference_text=ref_text,
                status=ReferenceStatus.VERIFIED,
                appears_in_sections=list(section_ids),
                action="keep",
            ))
            continue

        # Priority 3/4: check source documents
        found_in_source = False
        if source_documents:
            for src in source_documents:
                if ref_text in src:
                    found_in_source = True
                    break

        status = ReferenceStatus.UNVERIFIED if found_in_source else ReferenceStatus.MISSING_SOURCE
        occurrences.append(ReferenceOccurrence(
            reference_text=ref_text,
            status=status,
            appears_in_sections=list(section_ids),
            action="needs_user_decision",
        ))

    return occurrences


def run_reference_governance_gate(
    document: str,
    source_documents: Optional[list[str]] = None,
) -> ReferenceGateResult:
    """Run the reference governance gate on *document*.

    Args:
        document: Full document text in markdown format.
        source_documents: Optional list of reference source texts.

    Returns:
        ReferenceGateResult with decision, counts, repair plan, and blockers.
    """
    occurrences = classify_references(document, source_documents)

    fabricated = [o for o in occurrences if o.status == ReferenceStatus.FABRICATED_SUSPECTED]
    verified = [o for o in occurrences if o.status == ReferenceStatus.VERIFIED]
    unverified = [
        o for o in occurrences
        if o.status in (ReferenceStatus.UNVERIFIED, ReferenceStatus.MISSING_SOURCE)
    ]

    fabricated_count = len(fabricated)
    verified_count = len(verified)
    unverified_count = len(unverified)
    total = len(occurrences)

    # Gate decision — evaluated in priority order
    if fabricated_count > 0:
        decision = ReferenceGateDecision.CERTIFICATION_BLOCKER
    elif unverified_count > 0 and not source_documents:
        decision = ReferenceGateDecision.BLOCKED_INSUFFICIENT_EVIDENCE
    elif unverified_count > 0:
        decision = ReferenceGateDecision.USER_DECISION_REQUIRED
    else:
        decision = ReferenceGateDecision.PASS

    # One blocker message per fabricated reference
    certification_blockers: list[str] = [
        f"Fabricated standard '{o.reference_text}' found in sections "
        f"{o.appears_in_sections} — must be removed before certification."
        for o in fabricated
    ]

    # One repair instruction per (fabricated ref × section)
    repair_plan: list[str] = []
    for o in fabricated:
        for section_id in o.appears_in_sections:
            repair_plan.append(
                f"Section {section_id}: remove reference '{o.reference_text}'"
            )

    sections_with_fabricated: list[str] = []
    for o in fabricated:
        for section_id in o.appears_in_sections:
            if section_id not in sections_with_fabricated:
                sections_with_fabricated.append(section_id)

    log.info(
        "Reference governance gate: decision=%s total=%d fabricated=%d "
        "verified=%d unverified=%d",
        decision.value,
        total,
        fabricated_count,
        verified_count,
        unverified_count,
    )

    return ReferenceGateResult(
        decision=decision,
        total_references_found=total,
        fabricated_count=fabricated_count,
        verified_count=verified_count,
        unverified_count=unverified_count,
        fabricated_references=fabricated,
        verified_references=verified,
        certification_blockers=certification_blockers,
        repair_plan=repair_plan,
        sections_with_fabricated=sections_with_fabricated,
    )


def select_reference_governance_recommendations(document: str) -> dict:
    """Top-level function compatible with Phase 3's select_phase3_recommendations() pattern.

    Wraps run_reference_governance_gate(document, source_documents=None).

    Returns:
        dict with decision, counts, sections, repair plan, blockers, status, gate_version.
    """
    result = run_reference_governance_gate(document, source_documents=None)
    status = "CERTIFICATION_BLOCKED" if result.fabricated_count > 0 else "PASS"

    log.info(
        "Reference governance recommendations: status=%s fabricated=%d verified=%d",
        status,
        result.fabricated_count,
        result.verified_count,
    )

    return {
        "decision": result.decision.value,
        "fabricated_count": result.fabricated_count,
        "verified_count": result.verified_count,
        "sections_with_fabricated": result.sections_with_fabricated,
        "repair_plan": result.repair_plan,
        "certification_blockers": result.certification_blockers,
        "status": status,
        "gate_version": result.gate_version,
    }


def strip_fabricated_standards(document: str) -> tuple[str, list[str]]:
    """Remove lines containing fabricated standards from *document*.

    Markdown headings (lines starting with ``#``) are NEVER removed.
    Any other line matching a fabricated standard pattern is removed.

    Args:
        document: Full document text.

    Returns:
        Tuple of (cleaned_document, list_of_removed_lines).
    """
    kept: list[str] = []
    removed: list[str] = []

    for line in document.splitlines(keepends=True):
        stripped = line.lstrip()

        # Preserve all markdown headings unconditionally
        if stripped.startswith("#"):
            kept.append(line)
            continue

        # Remove any non-heading line that matches a fabricated pattern
        if _FABRICATED_RE.search(line):
            removed.append(line.rstrip("\n"))
            continue

        kept.append(line)

    if removed:
        log.info(
            "strip_fabricated_standards: removed %d line(s) containing fabricated references",
            len(removed),
        )

    return "".join(kept), removed
