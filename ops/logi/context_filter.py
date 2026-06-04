"""Context Filter — applied by LogiOrchestrator before every DociAgent call.

Takes raw KnomiAgent search results and filters by:
- status: only 'approved' documents
- quality_score: >= 85
- doc_type: must match requested type
- top_k: max 5 results

Returns filtered and re-ranked list.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("aims.context_filter")

# ── constants ──────────────────────────────────────────────────────────────────

QUALITY_THRESHOLD = 85
TOP_K = 5

VALID_INDUSTRIES = frozenset({"oil_gas", "mining", "process", "industrial"})
VALID_DOC_TYPES = frozenset({"procedure", "policy", "work_instruction", "risk_matrix"})
VALID_LEVELS = frozenset({"policy", "procedure", "work_instruction"})

# Keywords used for industry inference
_INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "oil_gas": [
        "oil", "gas", "petroleum", "refinery", "pipeline", "drilling",
        "wellhead", "upstream", "downstream", "lng", "lpg", "ngl",
    ],
    "mining": [
        "mine", "mining", "ore", "quarry", "excavation", "tailings",
        "blasting", "overburden", "mineral", "coal",
    ],
    "process": [
        "process", "chemical", "reactor", "distillation", "separation",
        "catalyst", "pressure vessel", "heat exchanger", "plant",
    ],
}


# ── inference helpers ──────────────────────────────────────────────────────────

def infer_industry(raw_input: dict[str, Any]) -> str:
    """Infer the industry from raw_input fields.

    Checks raw_input.get("industry") first, then scans content/title/description
    for keyword signals.

    Returns one of: oil_gas, mining, process, industrial (default).
    """
    explicit = str(raw_input.get("industry", "")).strip().lower()
    if explicit in VALID_INDUSTRIES:
        return explicit

    # Scan text fields for keyword signals
    text_to_scan = " ".join([
        str(raw_input.get("content", "")),
        str(raw_input.get("title", "")),
        str(raw_input.get("description", "")),
    ]).lower()

    # Count keyword hits per industry
    scores: dict[str, int] = {ind: 0 for ind in _INDUSTRY_KEYWORDS}
    for industry, keywords in _INDUSTRY_KEYWORDS.items():
        for kw in keywords:
            if kw in text_to_scan:
                scores[industry] += 1

    best = max(scores, key=lambda k: scores[k])
    if scores[best] > 0:
        log.debug("infer_industry: inferred '%s' (score=%d)", best, scores[best])
        return best

    return "industrial"


def classify_type(raw_input: dict[str, Any]) -> str:
    """Classify the document type from raw_input.

    Checks raw_input.get("doc_type") first; if not a known type, infers from content.

    Returns one of: procedure, policy, work_instruction, risk_matrix (default: procedure).
    """
    explicit = str(raw_input.get("doc_type", "")).strip().lower()
    if explicit in VALID_DOC_TYPES:
        return explicit

    content = str(raw_input.get("content", "")).lower()

    if any(kw in content for kw in ["policy", "regulation", "compliance", "governance", "directive"]):
        return "policy"
    if any(kw in content for kw in ["risk", "hazard", "severity", "likelihood", "mitigation", "matrix"]):
        return "risk_matrix"
    if any(kw in content for kw in ["instruction", "work instruction", "wi-", "step-by-step", "task"]):
        return "work_instruction"

    return "procedure"


def determine_level(raw_input: dict[str, Any]) -> str:
    """Determine the document hierarchy level from raw_input.

    Maps doc_type to an appropriate level in the document hierarchy.

    Returns one of: policy, procedure, work_instruction.
    """
    doc_type = classify_type(raw_input)

    if doc_type == "policy":
        return "policy"
    if doc_type == "work_instruction":
        return "work_instruction"
    # procedure and risk_matrix both sit at the procedure level
    return "procedure"


# ── main filter ────────────────────────────────────────────────────────────────

def context_filter(search_results: list[dict[str, Any]], raw_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Filter and re-rank search results for DociAgent context injection.

    Filtering rules (applied in order):
    1. status == "approved"  (only if the field is present on the result)
    2. quality_score >= 85   (only if the field is present on the result)
    3. doc_type match        (only if both result and raw_input carry doc_type)
    4. Sort by score descending
    5. Return top 5

    Args:
        search_results: raw list of dicts returned by KnomiAgent /search
        raw_input:      original task/request dict from the user/orchestrator

    Returns:
        Filtered and re-ranked list, max 5 items.
    """
    requested_doc_type = str(raw_input.get("doc_type", "")).strip().lower() or None

    filtered: list[dict[str, Any]] = []
    for doc in search_results:
        # 1. Status filter — only approved
        status = doc.get("status")
        if status is not None and str(status).lower() != "approved":
            log.debug("context_filter: skip doc id=%s — status=%s", doc.get("id"), status)
            continue

        # 2. Quality score filter
        quality = doc.get("quality_score")
        if quality is not None:
            try:
                if float(quality) < QUALITY_THRESHOLD:
                    log.debug(
                        "context_filter: skip doc id=%s — quality_score=%.1f < %d",
                        doc.get("id"), float(quality), QUALITY_THRESHOLD,
                    )
                    continue
            except (TypeError, ValueError):
                pass  # unparseable quality scores are not filtered out

        # 3. doc_type strict match (only when both sides carry the field)
        result_type = str(doc.get("doc_type", "")).strip().lower() or None
        if requested_doc_type and result_type and result_type != requested_doc_type:
            log.debug(
                "context_filter: skip doc id=%s — doc_type=%s != %s",
                doc.get("id"), result_type, requested_doc_type,
            )
            continue

        filtered.append(doc)

    # 4. Sort by score descending (Knomi results carry a float 'score' field)
    filtered.sort(key=lambda d: float(d.get("score", 0.0)), reverse=True)

    # 5. Top-K cap
    result = filtered[:TOP_K]
    log.info(
        "context_filter: input=%d → after_filter=%d → top_%d=%d",
        len(search_results), len(filtered), TOP_K, len(result),
    )
    return result
