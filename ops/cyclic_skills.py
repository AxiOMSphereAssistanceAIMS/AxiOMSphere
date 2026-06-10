#!/usr/bin/env python3
"""
cyclic_skills.py
────────────────
Four quality-control skills for the cyclic doc generation pipeline.

Skills:
  1. validate_structure(doc)             — TOC vs body completeness ratio
  2. verify_recommendations(recs, before, after) — check each rec was applied
  3. quality_gate(metrics, threshold)    — block bad learning pairs
  4. section_expand(section, standards)  — force-expand stub sections via SLOT120

These run between pipeline stages to block regressions and bad training data
before they reach the model fine-tuning pipeline.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("cyclic_skills")

OLLAMA_URL = "http://127.0.0.1:11434"


# ── Data types ─────────────────────────────────────────────────

@dataclass
class StructureReport:
    toc_sections: list[str]           # sections declared in TOC
    body_sections: list[str]          # sections found with content in body
    empty_sections: list[str]         # declared but empty/stub
    stub_sections: list[str]          # body exists but only placeholder text
    completeness_ratio: float         # body_with_content / toc_declared
    passed: bool                      # True if ratio >= threshold
    threshold: float = 0.90


@dataclass
class RecommendationVerification:
    applied: list[str]    = field(default_factory=list)
    skipped: list[str]    = field(default_factory=list)
    partial: list[str]    = field(default_factory=list)
    apply_rate: float     = 0.0       # applied / total
    passed: bool          = False     # True if apply_rate >= threshold


@dataclass
class QualityGateResult:
    allowed: bool
    reason: str
    scores: dict


# ── SKILL 1: validate_structure ────────────────────────────────

_STUB_PATTERNS = [
    r"^\s*\*?\(Refer to.*\)\*?\s*$",
    r"^\s*\[.*placeholder.*\]\s*$",
    r"^\s*TBD\s*$",
    r"^\s*\(to be defined\)\s*$",
    r"^\s*N/A\s*$",
    # r"^\s*$" intentionally omitted: the len(stripped)<30 check in _is_stub()
    # already catches empty bodies, and this pattern with MULTILINE would match
    # any blank line inside a filled section when used with .search().
]
# No re.MULTILINE: ^ and $ must anchor to the full body string, not to
# individual lines.  .search() is called on the raw body in validate_structure
# (line ~198); MULTILINE would cause false positives on any matching line
# inside an otherwise filled section.
_STUB_RE = [re.compile(p, re.IGNORECASE) for p in _STUB_PATTERNS]


def _is_stub(text: str) -> bool:
    """Return True if section body is empty or a known placeholder pattern."""
    stripped = text.strip()
    if len(stripped) < 30:
        return True
    for pat in _STUB_RE:
        if pat.match(stripped):
            return True
    return False


def _extract_toc_sections(doc: str) -> list[str]:
    """Extract section numbers/names from the Table of Contents block."""
    toc_match = re.search(
        r"(?i)(table\s+of\s+contents|contents)(.*?)(?=\n#{1,3}\s|\Z)",
        doc,
        re.DOTALL,
    )
    if not toc_match:
        return []

    toc_text = toc_match.group(2)
    sections = re.findall(r"(\d+\.[\d.]*\s+[A-Z][^\n]{3,60})", toc_text)
    return [s.strip() for s in sections]


def _extract_body_sections(doc: str) -> dict[str, str]:
    """
    Split document into sections by Markdown headings.
    Returns {heading_text: body_content}.
    """
    sections: dict[str, str] = {}
    # Support all Markdown heading levels used by generated documents.
    pattern = re.compile(r"^(#{1,6})\s+(.+?)$", re.MULTILINE)
    matches = list(pattern.finditer(doc))

    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        start   = match.end()
        end     = matches[i + 1].start() if i + 1 < len(matches) else len(doc)
        body    = doc[start:end].strip()
        sections[heading] = body

    return sections


def validate_structure(doc: str, threshold: float = 0.90) -> StructureReport:
    """
    Skill 1: Validate document structure completeness.

    Checks:
    - All TOC-declared sections exist in body
    - No section is a stub/placeholder
    - completeness_ratio = sections_with_real_content / toc_declared
    """
    toc_sections  = _extract_toc_sections(doc)
    body_sections = _extract_body_sections(doc)

    # Normalize for matching
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    body_norm = {_norm(k): k for k in body_sections}
    toc_norm  = [_norm(s) for s in toc_sections]

    def _section_number(value: str) -> str:
        match = re.match(r"^\s*(\d+(?:\.\d+)*)", value)
        return match.group(1) if match else ""

    def _has_populated_child(parent: str) -> bool:
        parent_number = _section_number(parent)
        # Method 1: numeric prefix matching (e.g. "5.1", "5.2" are children of "5.0")
        if parent_number:
            parent_base = (
                parent_number[:-2]
                if parent_number.endswith(".0")
                else parent_number
            )
            prefix = parent_base + "."
            if any(
                _section_number(heading).startswith(prefix)
                and _section_number(heading) != parent_number
                and not _is_stub(body)
                for heading, body in body_sections.items()
            ):
                return True

        # Method 2: raw-document scan for unnumbered sub-section content.
        # body_sections is a plain dict so repeated sub-heading names (e.g.
        # "### Overview" in every section) keep only the FIRST insertion position,
        # making forward-scan on the keys list unreliable.  We scan the raw `doc`
        # text instead: find the parent heading, extract all text until the next
        # same-or-higher-level heading, strip sub-heading lines, and check if the
        # remaining content is substantive.
        esc_parent = re.escape(parent.strip())
        m_parent = re.search(
            r"^(#{1,6})\s+" + esc_parent + r"\s*$", doc, re.MULTILINE
        )
        if m_parent is None:
            return False
        parent_level = len(m_parent.group(1))
        search_start = m_parent.end()
        # Find the next heading at the same or higher level (fewer # marks)
        next_sibling = re.search(
            r"^#{1," + str(parent_level) + r"}\s+",
            doc[search_start:],
            re.MULTILINE,
        )
        section_end = (
            search_start + next_sibling.start() if next_sibling else len(doc)
        )
        section_text = doc[search_start:section_end]
        # Strip heading lines; the leftover is pure prose / list content
        content_only = re.sub(r"^#{1,6}\s+.+$", "", section_text, flags=re.MULTILINE)
        return not _is_stub(content_only)

    # If TOC not found, fall back to counting headings
    if not toc_sections:
        all_headings = list(body_sections.keys())
        # Use _has_populated_child to rescue sections whose direct body is empty
        # because the model placed content under ### sub-headings (the parent
        # section heading is followed immediately by a child heading, making the
        # direct body text empty even though the section has real content).
        empty = [h for h, b in body_sections.items()
                 if _is_stub(b) and not _has_populated_child(h)]
        stub  = [h for h, b in body_sections.items()
                 if not _is_stub(b) and any(p.search(b) for p in _STUB_RE)]
        filled = len(all_headings) - len(empty) - len(stub)
        ratio  = filled / max(len(all_headings), 1)
        return StructureReport(
            toc_sections=all_headings,
            body_sections=list(body_sections.keys()),
            empty_sections=empty,
            stub_sections=stub,
            completeness_ratio=ratio,
            passed=ratio >= threshold,
            threshold=threshold,
        )

    empty_sections = []
    stub_sections  = []
    found_sections = []

    for toc_n, toc_s in zip(toc_norm, toc_sections):
        # Find matching body section
        matched_key = next((body_norm[k] for k in body_norm if toc_n in k or k in toc_n), None)
        if matched_key is None:
            empty_sections.append(toc_s + " [MISSING FROM BODY]")
            continue

        body = body_sections[matched_key]
        if _is_stub(body):
            if _has_populated_child(matched_key):
                found_sections.append(matched_key)
            else:
                stub_sections.append(toc_s + " [STUB/EMPTY]")
        else:
            found_sections.append(matched_key)

    total = max(len(toc_sections), 1)
    filled = len(found_sections)
    ratio  = filled / total

    report = StructureReport(
        toc_sections=toc_sections,
        body_sections=list(body_sections.keys()),
        empty_sections=empty_sections,
        stub_sections=stub_sections,
        completeness_ratio=ratio,
        passed=ratio >= threshold,
        threshold=threshold,
    )

    status = "PASS" if report.passed else "FAIL"
    log.info(
        f"[SKILL:validate_structure] {status} — "
        f"completeness={ratio:.0%} (filled={filled}/{total}), "
        f"empty={len(empty_sections)}, stubs={len(stub_sections)}"
    )
    return report


# ── SKILL 2: verify_recommendations ───────────────────────────

def verify_recommendations(
    recommendations: list[str],
    doc_before: str,
    doc_after: str,
    threshold: float = 0.60,
) -> RecommendationVerification:
    """
    Skill 2: Verify each Axi recommendation was applied in the improved document.

    For each recommendation extracts keywords and checks presence in doc_after
    but not (or less) in doc_before. Flags as applied / partial / skipped.
    """
    applied: list[str] = []
    partial: list[str] = []
    skipped: list[str] = []

    # Normalize text for searching
    before_lower = doc_before.lower()
    after_lower  = doc_after.lower()

    for rec in recommendations:
        # Extract keywords: section name + key technical terms
        words = re.findall(r"\b[A-Z][a-z]{3,}|[A-Z]{2,}[\d.]*|[a-z]{5,}", rec)
        keywords = [w.lower() for w in words if len(w) >= 4][:6]  # top 6 keywords

        if not keywords:
            partial.append(rec)
            continue

        hits_before = sum(1 for kw in keywords if kw in before_lower)
        hits_after  = sum(1 for kw in keywords if kw in after_lower)

        improvement = hits_after - hits_before
        coverage    = hits_after / len(keywords)

        if coverage >= 0.7 and improvement >= 1:
            applied.append(rec)
        elif coverage >= 0.4 or improvement >= 1:
            partial.append(rec)
        else:
            skipped.append(rec)

    total     = len(recommendations)
    apply_rate = (len(applied) + 0.5 * len(partial)) / max(total, 1)
    passed    = apply_rate >= threshold

    result = RecommendationVerification(
        applied=applied,
        skipped=skipped,
        partial=partial,
        apply_rate=apply_rate,
        passed=passed,
    )

    status = "PASS" if passed else "FAIL"
    log.info(
        f"[SKILL:verify_recommendations] {status} — "
        f"apply_rate={apply_rate:.0%} "
        f"(applied={len(applied)}, partial={len(partial)}, skipped={len(skipped)}/{total})"
    )
    if skipped:
        log.info(f"[SKILL:verify_recommendations] Skipped recs: {skipped[:3]}")

    return result


# ── SKILL 3: quality_gate ──────────────────────────────────────

def quality_gate(
    structure_score: float,
    standards_score: float,
    overall_score: float,
    document_type: str = "technical_report",
    structure_threshold: float = None,
    standards_threshold: float = None,
    overall_threshold: float = None,
) -> QualityGateResult:
    """
    Skill 3: Block recording of learning pairs when quality is below threshold.

    Learning pairs recorded from bad documents poison the training set.
    Gate requires ALL three conditions to pass.

    Now document-type-aware: loads type-specific thresholds from ValidationProfileLoader.

    Args:
        structure_score: Document structure coherence (0–1)
        standards_score: Conformance to document-type standards (0–1)
        overall_score: Composite quality score (0–1)
        document_type: Document type for threshold lookup (e.g., "technical_report", "memo")
        structure_threshold: Override default structure threshold (optional)
        standards_threshold: Override default standards threshold (optional)
        overall_threshold: Override default overall threshold (optional)
    """
    from ops.docgen.validation_profile_loader import ValidationProfileLoader

    # Load type-specific thresholds if not explicitly provided
    if structure_threshold is None or standards_threshold is None or overall_threshold is None:
        profile = ValidationProfileLoader.get_profile(document_type)
        if structure_threshold is None:
            structure_threshold = profile.quality_thresholds.structure
        if standards_threshold is None:
            standards_threshold = profile.quality_thresholds.standards
        if overall_threshold is None:
            overall_threshold = profile.quality_thresholds.overall

    scores = {
        "structure": structure_score,
        "standards": standards_score,
        "overall": overall_score,
        "document_type": document_type,  # Track which type was used
    }
    failures = []

    if structure_score < structure_threshold:
        failures.append(
            f"structure={structure_score:.1%} < {structure_threshold:.0%}"
        )
    if standards_score < standards_threshold:
        failures.append(
            f"standards={standards_score:.1%} < {standards_threshold:.0%}"
        )
    if overall_score < overall_threshold:
        failures.append(f"overall={overall_score:.1%} < {overall_threshold:.0%}")

    allowed = len(failures) == 0
    reason = "OK" if allowed else "BLOCKED: " + ", ".join(failures)

    log.info(
        f"[SKILL:quality_gate] [{document_type}] {'ALLOW' if allowed else 'BLOCK'} — {reason}"
    )
    return QualityGateResult(allowed=allowed, reason=reason, scores=scores)


# ── SKILL 4: section_expand ────────────────────────────────────

def _ollama_generate(model: str, prompt: str, timeout: int = 300, num_predict: int = 1500) -> str:
    payload = {
        "model": model,
        "prompt": (
            "<|im_start|>system\n"
            "You write only final document content, without hidden reasoning."
            "<|im_end|>\n"
            f"<|im_start|>user\n{prompt}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        ),
        "raw": True,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": num_predict},
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode()).get("response", "").strip()


def section_expand(
    section_name: str,
    section_body: str,
    standards_context: str,
    topic: str,
    model: str = "qwen36-reasoning-35b-v1:latest",
    min_words: int = 150,
) -> str:
    """
    Skill 4: Force-expand a stub or thin section using SLOT120.

    Generates a proper section body with:
    - Minimum word count enforced
    - Mandatory standard citations
    - Oil & Gas domain specifics
    - No placeholder text

    Returns the expanded section body (without heading).
    """
    is_stub = _is_stub(section_body)
    current = section_body.strip() if not is_stub else "(EMPTY — needs full content)"

    prompt = f"""You are writing a section of a professional Oil & Gas Asset Integrity Management document.

DOCUMENT TOPIC: {topic}

SECTION TO EXPAND: {section_name}
CURRENT CONTENT: {current}

RELEVANT STANDARDS:
{standards_context[:1000] if standards_context else "ISO 55001, API 580, API 510, ASME B31.3"}

REQUIREMENTS:
- Write at minimum {min_words} words of substantive content
- Include specific references to applicable standards (e.g., "per ISO 55001 Clause 7.2...")
- Use professional Oil & Gas technical language
- NO placeholders, NO "TBD", NO "Refer to..."
- Include definitions, requirements, and/or procedures as appropriate for this section type
- Format as continuous prose or structured list — no Markdown headings inside

Write ONLY the section body content (no heading, no section number):"""

    log.info(f"[SKILL:section_expand] Expanding '{section_name}' (stub={is_stub}, model={model})")
    try:
        expanded = _ollama_generate(model, prompt, timeout=300, num_predict=2000)
        # Strip <think>...</think> blocks — must not appear in document text.
        # Two-pass: closed blocks first, then unclosed tail (qwen35 may not close block)
        import re as _re
        think_count = len(_re.findall(r"<think>.*?</think>", expanded, flags=_re.DOTALL))
        if think_count:
            expanded = _re.sub(r"<think>.*?</think>\s*", "", expanded, flags=_re.DOTALL).strip()
            log.debug(f"[SKILL:section_expand] Stripped {think_count} closed <think> block(s) from '{section_name}'")
        if "<think>" in expanded:
            before = len(expanded)
            expanded = _re.sub(r"<think>.*$", "", expanded, flags=_re.DOTALL).strip()
            log.warning(f"[SKILL:section_expand] Stripped unclosed <think> tail from '{section_name}' ({before - len(expanded)} chars)")
        word_count = len(expanded.split())
        log.info(f"[SKILL:section_expand] Expanded '{section_name}': {word_count} words")
        return expanded
    except Exception as e:
        log.error(f"[SKILL:section_expand] Failed for '{section_name}': {e}")
        return section_body  # return original if expansion fails


def expand_stub_sections(
    doc: str,
    standards_context: str,
    topic: str,
    model: str = "qwen36-reasoning-35b-v1:latest",
) -> tuple[str, list[str]]:
    """
    Run validate_structure, then expand all stub/empty sections in-place.
    Returns (improved_doc, list_of_expanded_section_names).
    """
    report   = validate_structure(doc)
    expanded = []

    if report.passed:
        log.info("[SKILL:expand_stub_sections] Structure OK — no expansion needed")
        return doc, []

    # Rebuild document with expanded sections
    body_sections = _extract_body_sections(doc)
    result_doc    = doc

    stubs_to_fix = [
        s.replace(" [STUB/EMPTY]", "").replace(" [MISSING FROM BODY]", "")
        for s in report.stub_sections + report.empty_sections
    ]

    for section_name_raw in stubs_to_fix:
        # Find the section in the body
        matched = next(
            (k for k in body_sections if section_name_raw.lower() in k.lower() or k.lower() in section_name_raw.lower()),
            None
        )
        if not matched:
            continue

        old_body   = body_sections[matched]
        new_body   = section_expand(matched, old_body, standards_context, topic, model)

        if new_body != old_body and len(new_body.split()) >= 50:
            # Replace in document — find heading + old content, replace content
            heading_pattern = re.compile(
                r"(#{1,6}\s+" + re.escape(matched) + r"\s*\n)(.*?)(?=\n#{1,6}\s|\Z)",
                re.DOTALL | re.IGNORECASE,
            )
            result_doc = heading_pattern.sub(
                lambda m: m.group(1) + "\n" + new_body + "\n\n",
                result_doc,
            )
            expanded.append(matched)
            log.info(f"[SKILL:expand_stub_sections] Replaced stub: '{matched}'")

    if expanded:
        log.info(f"[SKILL:expand_stub_sections] Expanded {len(expanded)} sections: {expanded}")
    else:
        log.info("[SKILL:expand_stub_sections] No sections successfully expanded")

    return result_doc, expanded
