"""
section_editor.py — Section-Batched Transactional Editing
──────────────────────────────────────────────────────────
Replaces _apply_improvements / recommendation_application_skill.

Architecture (per user spec):
  1. Build section catalog from document
  2. Normalize recommendations → {id, target_section_id, operation, criteria}
  3. Group by target section (5-12 calls vs 30)
  4. Per-section call: full target body + TOC + neighbor summaries → SLOT120
     → strict JSON: {section_id, revised_body, applied[], skipped[]}
  5. Transaction: validate applied[] independently, check criteria, no placeholders
     → PASS: commit   FAIL: rollback this section only
  6. Global recs (TOC, cross-refs, new sections) in separate pass
  7. Reassemble → global validate_structure
     → critical regression → rollback entire candidate to last_accepted_draft

Mandatory conditions:
  1. Model returns strict JSON — headings/boundaries changed only by code
  2. applied[] verified by validator, not model's word
  3. Parallel edits from one snapshot, committed deterministically
  4. Full rollback on critical regression
"""
from __future__ import annotations

import json
import logging
import re
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from ops.cyclic_skills import validate_structure

log = logging.getLogger("section_editor")

OLLAMA_URL   = "http://127.0.0.1:11434"
SLOT120      = "axi_omi_sphere"  # SLOT32 (32B) is optimal for section editing

# ── Data structures ──────────────────────────────────────────────

@dataclass
class SectionEntry:
    section_id: str        # "8.3", "5.0", "INTRO"
    heading:    str        # full heading text
    level:      int        # 1-4
    start:      int        # char offset in doc
    end:        int        # char offset in doc
    body:       str        # content without heading line


@dataclass
class NormalizedRec:
    rec_id:    str
    raw:       str
    target:    str         # section_id or "GLOBAL" or "UNRESOLVED"
    operation: str         # ADD_CONTENT, ADD_TABLE, EXPAND, UPDATE, NEW_SECTION, GLOBAL
    criteria:  list[str] = field(default_factory=list)
    target_heading: str = ""


@dataclass
class SectionEditResult:
    section_id:   str
    revised_body: str
    applied:      list[str]   # rec_ids model claims applied
    skipped:      list[str]
    verified:     list[str]   # rec_ids confirmed by validator
    status:       str         # COMMITTED | ROLLED_BACK | SKIPPED
    reason:       str = ""


# ── Ollama call ──────────────────────────────────────────────────

def _ollama(prompt: str, timeout: int = 300) -> str:
    import urllib.request
    payload_obj = {
        "model": SLOT120,
        "prompt": (
            "<|im_start|>system\nYou are a precise document editor. "
            "Always respond with valid JSON only.<|im_end|>\n"
            f"<|im_start|>user\n{prompt}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n"
        ),
        "raw": True,
        "stream": False,
        "options": {"temperature": 0.10, "num_predict": 4096},
    }
    raw = ""
    for _attempt in range(3):
        payload = json.dumps(payload_obj).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = json.loads(r.read().decode()).get("response", "").strip()
        # Strip think blocks
        raw = re.sub(r"<think>.*?</think>\s*", "", raw, flags=re.DOTALL)
        if "<think>" in raw:
            raw = re.sub(r"<think>.*$", "", raw, flags=re.DOTALL).strip()
        if raw:
            return raw
        log.warning("[OLLAMA] Empty response on attempt %d/3, retrying...", _attempt + 1)
    return raw  # empty string; _call_section() will raise on json.loads and roll back


# ── Step 1: Build section catalog ───────────────────────────────

def build_catalog(doc: str) -> list[SectionEntry]:
    """Parse document into ordered SectionEntry list."""
    entries: list[SectionEntry] = []
    pattern = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(doc))

    for i, m in enumerate(matches):
        level   = len(m.group(1))
        heading = m.group(2).strip()
        start   = m.start()
        end     = matches[i + 1].start() if i + 1 < len(matches) else len(doc)
        body    = doc[m.end():end].strip()

        # Derive section_id: leading number like "8.3" or slug
        num_m = re.match(r"^(\d+(?:\.\d+)*)", heading)
        section_id = num_m.group(1) if num_m else re.sub(r"\W+", "_", heading[:20]).strip("_")

        entries.append(SectionEntry(
            section_id=section_id,
            heading=heading,
            level=level,
            start=start,
            end=end,
            body=body,
        ))
    return entries


def catalog_to_toc(catalog: list[SectionEntry]) -> str:
    return "\n".join(
        f"{'  ' * (e.level - 1)}{e.section_id}. {e.heading}"
        for e in catalog
    )


# ── Step 2: Normalize recommendations ───────────────────────────

_EXPLICIT_SECTION_RE = re.compile(
    r"\b[Ss]ection[s]?\s+(\d+(?:\.\d+)*)"
)
_DECIMAL_SECTION_RE = re.compile(r"(?:^|\s)(\d+\.\d+(?:\.\d+)?)")
_ELEMENT_SECTION_RE = re.compile(
    r"\bElement\s+(\d+(?:\.\d+)*)\b",
    re.IGNORECASE,
)
_ADD_ELEMENT_RE = re.compile(
    r"\b(?:Add|Create)\s+(?:a\s+)?(?:new\s+)?Element\s+"
    r"(\d+(?:\.\d+)*)\b",
    re.IGNORECASE,
)
_RENAME_TITLE_RE = re.compile(
    r"(?:title\s+to|subject\s*:)\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_GLOBAL_KEYWORDS = re.compile(
    r"\b(TOC|table of contents|cross.reference|definition|revision table"
    r"|new section|new element|add section|appendix)\b",
    re.IGNORECASE,
)
_OPERATION_MAP = {
    "add table": "ADD_TABLE",
    "add matrix": "ADD_TABLE",
    "add raci": "ADD_TABLE",
    "expand": "EXPAND",
    "replace": "REPLACE",
    "update": "UPDATE",
    "add": "ADD_CONTENT",
    "include": "ADD_CONTENT",
    "define": "ADD_CONTENT",
    "new section": "NEW_SECTION",
    "create section": "NEW_SECTION",
}


def normalize_rec(rec_id: str, raw: str) -> NormalizedRec:
    # Resolve an explicit section before classifying broad keywords such as
    # "cross-reference". Otherwise a targeted recommendation is silently
    # diverted into the global bucket.
    if re.match(
        r"^\s*(?:Section\s+)?(?:TABLE OF CONTENTS|TOC)\s*:",
        raw,
        re.IGNORECASE,
    ):
        return NormalizedRec(
            rec_id=rec_id,
            raw=raw,
            target="GLOBAL",
            operation="GLOBAL",
        )

    if re.match(r"^\s*Appendix\s+[A-Z0-9]+", raw, re.IGNORECASE):
        return NormalizedRec(
            rec_id=rec_id,
            raw=raw,
            target="GLOBAL",
            operation="GLOBAL",
        )

    add_element = _ADD_ELEMENT_RE.search(raw)
    if add_element:
        return NormalizedRec(
            rec_id=rec_id,
            raw=raw,
            target=add_element.group(1),
            operation="NEW_SECTION",
        )

    m = _EXPLICIT_SECTION_RE.search(raw)
    if not m:
        m = _DECIMAL_SECTION_RE.search(raw)
    if not m:
        m = _ELEMENT_SECTION_RE.search(raw)
    if m:
        target = m.group(1)
    else:
        target = "UNRESOLVED"

    # Detect operation
    operation = "ADD_CONTENT"
    raw_lower = raw.lower()
    rename_match = _RENAME_TITLE_RE.search(raw)
    if target != "UNRESOLVED" and rename_match:
        return NormalizedRec(
            rec_id=rec_id,
            raw=raw,
            target=target,
            operation="RENAME_SECTION",
            target_heading=rename_match.group(1).strip(),
        )
    for kw, op in sorted(_OPERATION_MAP.items(), key=lambda item: -len(item[0])):
        if kw in raw_lower:
            operation = op
            break

    if operation == "NEW_SECTION":
        return NormalizedRec(
            rec_id=rec_id,
            raw=raw,
            target=target,
            operation=operation,
        )

    if target == "UNRESOLVED" and _GLOBAL_KEYWORDS.search(raw):
        return NormalizedRec(
            rec_id=rec_id,
            raw=raw,
            target="GLOBAL",
            operation="GLOBAL",
        )

    # Simple acceptance criteria
    criteria: list[str] = []
    if operation == "ADD_TABLE":
        criteria.append("table present in section")
    if "standard" in raw_lower or "iso" in raw_lower or "api" in raw_lower:
        criteria.append("standard reference cited")

    return NormalizedRec(rec_id=rec_id, raw=raw,
                         target=target, operation=operation, criteria=criteria)


def normalize_all(recs: list[str]) -> list[NormalizedRec]:
    return [normalize_rec(f"REC-{i:03d}", r) for i, r in enumerate(recs, 1)]


# ── Step 3: Group by section ─────────────────────────────────────

def _resolve_target_id(target: str, catalog_ids: set[str]) -> str | None:
    """
    Fuzzy-resolve a recommendation target ID against the document catalog.

    Handles two common mismatches produced by the Claude audit:
    1. Short IDs: "1" or "8" → document has "1.0" or "8.0"
    2. Sub-section targets for non-existent subsections:
       "8.4.1" → parent "8.4" exists → route to parent so the editor
       can add the sub-content within the existing section.
    """
    if target in catalog_ids:
        return target

    # Attempt 1: append ".0" (e.g. "1" → "1.0", "8" → "8.0")
    candidate = target + ".0"
    if candidate in catalog_ids:
        return candidate

    # Attempt 2: strip trailing components until a parent is found
    # e.g. "8.4.1" → "8.4" → "8"
    parts = target.split(".")
    while len(parts) > 1:
        parts = parts[:-1]
        parent = ".".join(parts)
        if parent in catalog_ids:
            return parent
        # Also try parent + ".0"
        parent0 = parent + ".0"
        if parent0 in catalog_ids:
            return parent0

    return None


def group_by_section(
    norm_recs: list[NormalizedRec],
    catalog: list[SectionEntry],
) -> dict[str, list[NormalizedRec]]:
    """Map section_id to recommendations; tries fuzzy fallback before unresolved."""
    groups: dict[str, list[NormalizedRec]] = {}
    catalog_ids = {e.section_id for e in catalog}

    for rec in norm_recs:
        if rec.target == "GLOBAL" or rec.operation == "NEW_SECTION":
            groups.setdefault("GLOBAL", []).append(rec)
            continue

        target = rec.target
        resolved = _resolve_target_id(target, catalog_ids)
        if resolved is None:
            groups.setdefault("UNRESOLVED", []).append(rec)
            log.warning("[EDITOR] Unresolved target '%s' for: %s", rec.target, rec.raw[:60])
            continue

        if resolved != target:
            log.info("[EDITOR] Target '%s' fuzzy-resolved to '%s'", target, resolved)
        groups.setdefault(resolved, []).append(rec)

    return groups


# ── Step 4: Per-section SLOT120 call ────────────────────────────

def _neighbor_summaries(section_id: str, catalog: list[SectionEntry]) -> str:
    idx = next((i for i, e in enumerate(catalog) if e.section_id == section_id), None)
    if idx is None:
        return ""
    parts = []
    if idx > 0:
        prev = catalog[idx - 1]
        summary = prev.body[:300] + ("..." if len(prev.body) > 300 else "")
        parts.append(f"PREVIOUS — {prev.heading}:\n{summary}")
    if idx < len(catalog) - 1:
        nxt = catalog[idx + 1]
        summary = nxt.body[:300] + ("..." if len(nxt.body) > 300 else "")
        parts.append(f"NEXT — {nxt.heading}:\n{summary}")
    return "\n\n".join(parts)


def _extract_reference_section(reference_text: str, section_id: str) -> str:
    """Extract content matching section_id from the reference document.

    Looks for headings like "8.1", "8.1 ", "8.1." followed by a title,
    then captures text until the next same-level or higher section heading.
    Returns at most 2000 chars to avoid flooding the editing prompt.
    """
    if not reference_text or not section_id:
        return ""
    lines = reference_text.splitlines()
    # Build a regex that matches this section heading at start of a line.
    escaped = re.escape(section_id)
    heading_re = re.compile(
        rf"^\s*{escaped}[\s\.]+\S",
        re.IGNORECASE,
    )
    # Determine the "level" of this section (number of dot-separated parts).
    level = len(section_id.split("."))
    # Regex for any heading at the same level or higher (terminates the section).
    higher_re = re.compile(
        r"^\s*(\d+(?:\.\d+){0," + str(level - 1) + r"})\s+\S",
    )

    collecting = False
    collected: list[str] = []
    for line in lines:
        if not collecting:
            if heading_re.match(line):
                collecting = True
                collected.append(line.strip())
        else:
            # Stop at next sibling or parent heading.
            m = re.match(r"^\s*(\d+(?:\.\d+)*)\s+\S", line)
            if m:
                parts = m.group(1).split(".")
                if len(parts) <= level and m.group(1) != section_id:
                    break
            collected.append(line.rstrip())

    content = "\n".join(collected).strip()
    return content[:2000]


def _edit_section_prompt(
    entry: SectionEntry,
    recs: list[NormalizedRec],
    toc: str,
    neighbor_summaries: str,
    reference_section: str = "",
) -> str:
    recs_text = "\n".join(
        f"  {r.rec_id} [{r.operation}]: {r.raw}" for r in recs
    )
    rec_ids = [r.rec_id for r in recs]

    # Check if any REPLACE recommendations exist
    replace_recs = [r for r in recs if r.operation == "REPLACE"]
    replace_note = ""
    if replace_recs:
        replace_note = "\n⚠️ IMPORTANT: REPLACE recommendations mean this section's current content is incomplete/incorrect and should be COMPLETELY REWRITTEN based on the recommendations. Do not preserve old content unless explicitly stated."

    ref_block = ""
    if reference_section:
        ref_block = f"""
REFERENCE DOCUMENT — this section in the source standard (use exact terminology, requirements, and structure from here):
{reference_section}
"""

    return f"""You are editing one section of a professional Oil & Gas Asset Integrity Management document.

DOCUMENT OUTLINE (TOC):
{toc}

NEIGHBOR CONTEXT (read-only):
{neighbor_summaries}
{ref_block}
TARGET SECTION TO EDIT:
Heading: {entry.heading}
Current body:
{entry.body}

RECOMMENDATIONS TO APPLY TO THIS SECTION:
{recs_text}{replace_note}

RULES:
- Return ONLY valid JSON — no markdown, no explanation outside JSON
- revised_body: the new section body text (WITHOUT the heading line)
- applied: list of rec_ids you successfully applied
- skipped: list of rec_ids you could not apply
- Do NOT change the heading or section number
- Do NOT add placeholder text like "TBD" or "(to be defined)"
- For ADD_CONTENT/EXPAND/UPDATE: expand or improve existing content using REFERENCE DOCUMENT content
- For REPLACE: rewrite the section completely based on REFERENCE DOCUMENT and recommendations
- Preserve all existing standards references

RESPOND WITH THIS EXACT JSON STRUCTURE:
{{"section_id": "{entry.section_id}", "revised_body": "...", "applied": {json.dumps(rec_ids)}, "skipped": []}}"""


def _parse_section_response(
    raw: str,
    expected_section_id: str,
    expected_rec_ids: set[str],
) -> dict:
    """Reject wrappers, missing fields, wrong types, and invented IDs."""
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("response must be a JSON object")

    required = {"section_id", "revised_body", "applied", "skipped"}
    if set(data) != required:
        raise ValueError(
            f"response keys must be exactly {sorted(required)}, got {sorted(data)}"
        )
    if data["section_id"] != expected_section_id:
        raise ValueError(
            f"section_id mismatch: expected {expected_section_id}, got {data['section_id']}"
        )
    if not isinstance(data["revised_body"], str) or not data["revised_body"].strip():
        raise ValueError("revised_body must be a non-empty string")
    if not isinstance(data["applied"], list) or not all(
        isinstance(item, str) for item in data["applied"]
    ):
        raise ValueError("applied must be a list of strings")
    if not isinstance(data["skipped"], list) or not all(
        isinstance(item, str) for item in data["skipped"]
    ):
        raise ValueError("skipped must be a list of strings")

    applied = set(data["applied"])
    skipped = set(data["skipped"])
    if applied & skipped:
        raise ValueError("the same rec_id cannot be both applied and skipped")
    if applied | skipped != expected_rec_ids:
        raise ValueError("applied and skipped must account for every expected rec_id")
    return data


_REC_STOPWORDS = {
    "add", "and", "with", "that", "this", "from", "into", "section",
    "element", "include", "update", "expand", "define", "covering",
    "explicitly", "applicable", "aligned", "current", "document",
}


def _recommendation_terms(raw: str) -> list[str]:
    terms = [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9.-]{3,}", raw)
        if token.lower() not in _REC_STOPWORDS
    ]
    return list(dict.fromkeys(terms))[:10]


def _verify_recommendation(
    rec: NormalizedRec,
    original_body: str,
    revised_body: str,
) -> bool:
    if revised_body.strip() == original_body.strip():
        return False

    for criterion in rec.criteria:
        if "table" in criterion and not re.search(
            r"(?m)^\s*\|.+\|\s*$", revised_body
        ):
            return False
        if "standard" in criterion and not re.search(
            r"\b(ISO|API|ASME|IEC|NACE|AMPP|NORSOK|IOGP)\b", revised_body
        ):
            return False

    if rec.operation == "EXPAND":
        return len(revised_body.split()) > len(original_body.split())

    # REPLACE: section may already contain rec terms from a prior-cycle expansion.
    # Don't require *new* terms — just sufficient word count and term coverage.
    # Threshold is 0.25 (not 0.4) because rec text contains action verbs like
    # "replace", "fabricated", "narrative" that describe the operation, not the content.
    if rec.operation == "REPLACE":
        if len(revised_body.split()) < 50:
            return False
        terms = _recommendation_terms(rec.raw)
        if not terms:
            return len(revised_body.split()) >= 50
        after = revised_body.lower()
        after_hits = sum(term in after for term in terms)
        return after_hits / len(terms) >= 0.25

    terms = _recommendation_terms(rec.raw)
    if not terms:
        return False
    before = original_body.lower()
    after = revised_body.lower()
    after_hits = sum(term in after for term in terms)
    new_hits = sum(term in after and term not in before for term in terms)
    # Accept significant word-count growth as alternative to new_hits — handles
    # cases where domain terms already exist in original (e.g. adding equipment
    # list to a Scope section that already mentioned "equipment").
    significant_growth = len(revised_body.split()) > len(original_body.split()) * 1.3
    return after_hits / len(terms) >= 0.4 and (new_hits >= 1 or significant_growth)


def _resolve_global_target(
    rec: NormalizedRec,
    catalog: list[SectionEntry],
) -> str | None:
    """Resolve only high-confidence global aliases to existing sections."""
    raw = rec.raw.lower()
    aliases = []
    if "definition" in raw or "acronym" in raw:
        aliases = ["definition", "acronym"]
    elif "revision table" in raw or "document control" in raw:
        aliases = ["revision", "document control"]
    elif "cross-reference" in raw or "cross reference" in raw:
        aliases = ["standard", "reference", "applicable document"]
    elif "appendix" in raw:
        aliases = ["appendi"]

    matches = [
        entry.section_id
        for entry in catalog
        if any(alias in entry.heading.lower() for alias in aliases)
    ]
    return matches[0] if len(matches) == 1 else None


def _new_section_heading(rec: NormalizedRec, section_id: str) -> str:
    raw = rec.raw.strip()
    tail = re.split(r"\b(?:add|create)\b", raw, maxsplit=1, flags=re.IGNORECASE)
    heading = (tail[-1] if len(tail) > 1 else raw).strip()
    heading = re.sub(
        r"^(?:new\s+)?(?:section|element)\s+\d+(?:\.\d+)*\s*[:—-]?\s*",
        "",
        heading,
        flags=re.IGNORECASE,
    )
    heading = re.split(r"\s+[—–]\s+", heading, maxsplit=1)[0].strip()
    heading = heading.split(" covering ", 1)[0].strip(" :'\"—-")
    if not heading:
        heading = "New Required Section"
    return f"{section_id} {heading}"


def _allocate_new_section_ids(
    recs: list[NormalizedRec],
    catalog: list[SectionEntry],
) -> list[tuple[NormalizedRec, str]]:
    existing = {entry.section_id for entry in catalog}
    allocated: list[tuple[NormalizedRec, str]] = []
    next_child: dict[str, int] = {}

    for rec in recs:
        if rec.target not in existing and rec.target != "UNRESOLVED":
            section_id = rec.target
        elif rec.target in existing:
            parent = (
                rec.target[:-2]
                if rec.target.endswith(".0")
                else rec.target
            )
            child_numbers = []
            for section_id in existing:
                match = re.fullmatch(re.escape(parent) + r"\.(\d+)", section_id)
                if match:
                    child_numbers.append(int(match.group(1)))
            next_child.setdefault(parent, max(child_numbers, default=0) + 1)
            section_id = f"{parent}.{next_child[parent]}"
            next_child[parent] += 1
        else:
            continue
        existing.add(section_id)
        allocated.append((rec, section_id))
    return allocated


def _call_new_section(
    rec: NormalizedRec,
    section_id: str,
    toc: str,
) -> tuple[str, str] | None:
    heading = rec.target_heading or _new_section_heading(rec, section_id)
    prompt = f"""Create one new section for a professional Oil & Gas Asset Integrity Management document.

DOCUMENT OUTLINE:
{toc}

RECOMMENDATION:
{rec.rec_id}: {rec.raw}

RULES:
- Return ONLY valid JSON with exactly: section_id, body, applied
- section_id must be "{section_id}"
- body must contain at least 100 substantive words
- body must contain no nested Markdown headings and no placeholders
- applied must be ["{rec.rec_id}"]

RESPOND:
{{"section_id":"{section_id}","body":"...","applied":["{rec.rec_id}"]}}"""
    try:
        data = json.loads(_ollama(prompt, timeout=3600))
        required = {"section_id", "body", "applied"}
        if not isinstance(data, dict) or set(data) != required:
            raise ValueError("new-section response has invalid keys")
        if data["section_id"] != section_id or data["applied"] != [rec.rec_id]:
            raise ValueError("new-section identity mismatch")
        body = data["body"]
        if not isinstance(body, str) or len(body.split()) < 100:
            raise ValueError("new-section body is too short")
        if re.search(r"(?m)^#{1,6}\s", body):
            raise ValueError("new-section body contains nested headings")
        if re.search(r"\b(TBD|to be defined|placeholder|N/A)\b", body, re.IGNORECASE):
            raise ValueError("new-section body contains placeholders")
        if not _verify_recommendation(rec, "", f"{heading}\n{body}"):
            raise ValueError("new-section recommendation verification failed")
        return heading, body.strip()
    except Exception as exc:
        log.warning(
            "[EDITOR] New section %s rolled back: %s",
            section_id,
            exc,
        )
        return None


def _insert_new_sections(
    doc: str,
    generated: list[tuple[str, str, str]],
) -> str:
    """Insert sections into their numeric hierarchy with code-owned levels."""
    result = doc.rstrip() + "\n"

    def numeric_key(item: tuple[str, str, str]) -> tuple[int, ...]:
        return tuple(int(part) for part in item[0].split("."))

    for section_id, heading, body in sorted(generated, key=numeric_key):
        catalog = build_catalog(result)
        parent_id = ""
        if "." in section_id and not section_id.endswith(".0"):
            parent_id = section_id.rsplit(".", 1)[0]
            if "." not in parent_id:
                parent_id += ".0"
        parent = next(
            (entry for entry in catalog if entry.section_id == parent_id),
            None,
        )

        if parent:
            level = min(parent.level + 1, 6)
            parent_index = catalog.index(parent)
            following = catalog[parent_index + 1:]
            boundary = next(
                (
                    entry.start
                    for entry in following
                    if entry.level <= parent.level
                ),
                len(result),
            )
        else:
            top_levels = [
                entry.level
                for entry in catalog
                if re.fullmatch(r"\d+\.0", entry.section_id)
            ]
            level = (
                max(set(top_levels), key=top_levels.count)
                if top_levels
                else 2
            )
            current_number = numeric_key((section_id, heading, body))
            boundary = next(
                (
                    entry.start
                    for entry in catalog
                    if entry.level == level
                    and re.fullmatch(r"\d+\.0", entry.section_id)
                    and tuple(
                        int(part) for part in entry.section_id.split(".")
                    ) > current_number
                ),
                len(result),
            )

        block = (
            f"\n{'#' * level} {heading}\n\n"
            f"{body.strip()}\n"
        )
        result = result[:boundary].rstrip() + block + "\n" + result[boundary:].lstrip()

    return result.rstrip() + "\n"


def _refresh_toc(doc: str) -> tuple[str, bool]:
    catalog = build_catalog(doc)
    toc_entry = next(
        (
            entry
            for entry in catalog
            if entry.heading.lower() in {"table of contents", "contents"}
        ),
        None,
    )
    if toc_entry is None:
        return doc, False

    lines = []
    for entry in catalog:
        if entry is toc_entry or entry.level == 1:
            continue
        indent = "  " * max(entry.level - 2, 0)
        lines.append(f"{indent}{entry.heading}")
    if not lines:
        return doc, False

    newline = doc.find("\n", toc_entry.start)
    heading_end = len(doc) if newline < 0 else newline + 1
    replacement = doc[toc_entry.start:heading_end] + "\n".join(lines) + "\n\n"
    return doc[:toc_entry.start] + replacement + doc[toc_entry.end:], True


def _normalize_numeric_section_order(doc: str) -> tuple[str, bool]:
    """Sort numbered sections and repair child heading levels in code."""
    catalog = build_catalog(doc)
    first_numbered = next(
        (
            index
            for index, entry in enumerate(catalog)
            if re.fullmatch(r"\d+(?:\.\d+)*", entry.section_id)
        ),
        None,
    )
    if first_numbered is None:
        return doc, False

    numbered = catalog[first_numbered:]
    if any(
        not re.fullmatch(r"\d+(?:\.\d+)*", entry.section_id)
        for entry in numbered
    ):
        return doc, False

    top_levels = [
        entry.level
        for entry in numbered
        if re.fullmatch(r"\d+\.0", entry.section_id)
    ]
    top_level = (
        max(set(top_levels), key=top_levels.count)
        if top_levels
        else 2
    )

    def numeric_key(entry: SectionEntry) -> tuple[int, ...]:
        return tuple(int(part) for part in entry.section_id.split("."))

    prefix = doc[:numbered[0].start].rstrip()
    blocks = []
    for entry in sorted(numbered, key=numeric_key):
        level = (
            top_level
            if entry.section_id.endswith(".0")
            else min(
                top_level + len(entry.section_id.split(".")) - 1,
                6,
            )
        )
        blocks.append(
            f"{'#' * level} {entry.heading}\n\n{entry.body.strip()}"
        )

    normalized = prefix + "\n\n" + "\n\n".join(blocks) + "\n"
    return normalized, normalized != doc


def _call_section(
    entry: SectionEntry,
    recs: list[NormalizedRec],
    toc: str,
    catalog: list[SectionEntry],
    reference_section: str = "",
) -> SectionEditResult:
    neighbor_ctx = _neighbor_summaries(entry.section_id, catalog)
    prompt = _edit_section_prompt(entry, recs, toc, neighbor_ctx, reference_section)

    try:
        raw = _ollama(prompt, timeout=3600)
        expected_rec_ids = {rec.rec_id for rec in recs}
        data = _parse_section_response(
            raw,
            expected_section_id=entry.section_id,
            expected_rec_ids=expected_rec_ids,
        )
    except Exception as e:
        log.error("[EDITOR] Section %s call failed: %s", entry.section_id, e)
        return SectionEditResult(
            section_id=entry.section_id,
            revised_body=entry.body,
            applied=[], skipped=[r.rec_id for r in recs],
            verified=[], status="ROLLED_BACK", reason=f"invalid_response: {e}",
        )

    revised_body = data.get("revised_body", "").strip()
    model_applied = data.get("applied", [])
    model_skipped = data.get("skipped", [])

    # ── Transaction: validate independently ─────────────────────
    verified: list[str] = []
    rollback = False

    # Check 1: no placeholders
    placeholder_re = re.compile(r"\b(TBD|to be defined|placeholder|N/A)\b", re.IGNORECASE)
    if placeholder_re.search(revised_body):
        log.warning("[EDITOR] Section %s has placeholders — rolling back", entry.section_id)
        rollback = True

    # Check 2: not shorter than original (no shrinkage)
    if len(revised_body.split()) < len(entry.body.split()) * 0.7:
        log.warning("[EDITOR] Section %s shrank >30%% — rolling back", entry.section_id)
        rollback = True

    reason = ""
    expected = {rec.rec_id for rec in recs}  # always compute — needed in return
    if not rollback:
        # Verify every claimed application independently.
        # Partial commit: rollback only when NOTHING verified.
        # Unverified recs surface in skipped[] for re-injection next cycle.
        for rec_id in model_applied:
            rec = next(r for r in recs if r.rec_id == rec_id)
            if _verify_recommendation(rec, entry.body, revised_body):
                verified.append(rec_id)

        # Also rollback when the model explicitly reports skipping a rec that
        # was expected — the model refused to apply an assigned change.
        expected_skipped = {rid for rid in model_skipped if rid in expected}
        if not verified or expected_skipped:
            rollback = True
            reason = (
                f"verification_failed: verified={sorted(verified)} "
                f"expected={sorted(expected)} skipped={sorted(model_skipped)}"
            )

    if not rollback:
        status = "COMMITTED"
        unverified = sorted(expected - set(verified))
        if unverified or model_skipped:
            reason = f"partial_commit: verified={sorted(verified)} unverified={unverified}"
            log.info(
                "[EDITOR] Section %s COMMITTED (partial) — verified %d/%d recs; unverified: %s",
                entry.section_id, len(verified), len(recs), unverified,
            )
        else:
            log.info(
                "[EDITOR] Section %s COMMITTED — verified %d/%d recs",
                entry.section_id, len(verified), len(recs),
            )
    else:
        revised_body = entry.body  # restore original
        status = "ROLLED_BACK"
        verified = []
        reason = reason or "section_safety_check_failed"
        log.warning("[EDITOR] Section %s ROLLED BACK: %s", entry.section_id, reason)

    return SectionEditResult(
        section_id=entry.section_id,
        revised_body=revised_body,
        applied=model_applied,
        skipped=sorted(expected - set(verified)) if not rollback else model_skipped,
        verified=verified,
        status=status,
        reason=reason,
    )


# ── Step 5: Parallel execution from one snapshot ─────────────────

def _can_run_parallel(sections: list[str], catalog: list[SectionEntry]) -> list[list[str]]:
    """
    Group sections into parallel batches.
    Sections at same level with no shared references → parallel.
    Parent-child relationships → sequential.
    """
    if not sections:
        return []

    # Every call reads the same immutable snapshot and code performs the
    # deterministic commit later, so distinct section IDs are independent.
    return [sections]


# ── Step 6: Reassemble ───────────────────────────────────────────

def reassemble(
    original_doc: str,
    catalog: list[SectionEntry],
    results: dict[str, SectionEditResult],
    groups: dict[str, list[NormalizedRec]] | None = None,
) -> str:
    """Rebuild document by replacing committed section bodies."""
    # Work on character offsets — apply in reverse order to preserve positions
    doc = original_doc
    for entry in reversed(catalog):
        result = results.get(entry.section_id)
        if not result or result.status != "COMMITTED":
            continue
        heading_text = entry.heading
        rename_targets = [
            rec.target_heading
            for rec in (groups or {}).get(entry.section_id, [])
            if rec.operation == "RENAME_SECTION" and rec.target_heading
        ]
        if len(rename_targets) == 1:
            target_heading = rename_targets[0]
            if target_heading.startswith(entry.section_id):
                heading_text = target_heading
            else:
                element_prefix = re.match(
                    rf"^{re.escape(entry.section_id)}\s+"
                    r"(Element\s+\d+\s*:)\s*",
                    entry.heading,
                    re.IGNORECASE,
                )
                preserved_prefix = (
                    f"{element_prefix.group(1)} "
                    if element_prefix
                    and not target_heading.lower().startswith("element ")
                    else ""
                )
                heading_text = (
                    f"{entry.section_id} {preserved_prefix}{target_heading}"
                )
        heading_line = f"{'#' * entry.level} {heading_text}\n"
        new_section = heading_line + result.revised_body.strip() + "\n\n"
        doc = doc[:entry.start] + new_section + doc[entry.end:]
    return doc


# ── Main entry point ─────────────────────────────────────────────

def apply_section_edits(
    doc: str,
    recommendations: list[str],
    last_accepted_doc: str = "",
    max_workers: int = 1,
    reference_text: str = "",
) -> dict:
    """
    Section-batched transactional editing.

    Returns:
        improved_doc      : str
        changes_applied   : list[str]  — verified rec_ids
        section_results   : list[dict]
        global_recs       : list[str]  — unprocessed global recs
        unresolved_recs   : list[str]
        rolled_back       : bool       — True if full rollback triggered
    """
    log.info("[EDITOR] Starting section-batched editing (%d recs)", len(recommendations))

    # Step 1
    catalog = build_catalog(doc)
    toc     = catalog_to_toc(catalog)
    log.info("[EDITOR] Catalog: %d sections", len(catalog))

    # Step 2
    norm_recs = normalize_all(recommendations)
    structure = validate_structure(doc)
    declared_headings: dict[str, str] = {}
    for heading in structure.toc_sections:
        match = re.match(r"^\s*(\d+(?:\.\d+)*)", heading)
        if match:
            declared_headings[match.group(1)] = heading.strip()

    catalog_ids = {entry.section_id for entry in catalog}
    for rec in norm_recs:
        if (
            rec.target in declared_headings
            and rec.target not in catalog_ids
            and rec.operation != "GLOBAL"
        ):
            rec.operation = "NEW_SECTION"
            rec.target_heading = declared_headings[rec.target]
        # Convert NEW_SECTION to REPLACE if section already exists (conflicts)
        elif (
            rec.operation == "NEW_SECTION"
            and rec.target in catalog_ids
            and rec.target != "GLOBAL"
        ):
            log.info(
                "[EDITOR] Section %s exists but rec says 'Add new' — converting to REPLACE",
                rec.target,
            )
            rec.operation = "REPLACE"

    resolved = [
        r for r in norm_recs
        if r.target not in ("GLOBAL", "UNRESOLVED")
        and r.operation not in ("NEW_SECTION",)  # NEW_SECTION handled separately
    ]
    new_section_norm = [r for r in norm_recs if r.operation == "NEW_SECTION"]
    # Track sections with REPLACE operations to skip post-reassembly stub revert for them
    replace_sections = {r.target for r in resolved if r.operation == "REPLACE"}
    toc_norm: list[NormalizedRec] = []
    pending_global_norm: list[NormalizedRec] = []
    for rec in norm_recs:
        if rec.target != "GLOBAL" or rec.operation == "NEW_SECTION":
            continue
        if re.search(r"\b(TOC|table of contents)\b", rec.raw, re.IGNORECASE):
            toc_norm.append(rec)
            continue
        target = _resolve_global_target(rec, catalog)
        if target:
            rec.target = target
            rec.operation = "ADD_CONTENT"
            resolved.append(rec)
        else:
            pending_global_norm.append(rec)
    unresolved_norm = [r for r in norm_recs if r.target == "UNRESOLVED"]

    # Step 3
    groups = group_by_section(resolved, catalog)
    unresolved_norm.extend(groups.pop("UNRESOLVED", []))
    pending_global_norm.extend(groups.pop("GLOBAL", []))
    unresolved_recs = [r.raw for r in unresolved_norm]
    log.info(
        "[EDITOR] Normalized: %d targeted, %d new-section, %d TOC, "
        "%d pending-global, %d unresolved",
        sum(len(group) for group in groups.values()),
        len(new_section_norm),
        len(toc_norm),
        len(pending_global_norm),
        len(unresolved_recs),
    )
    log.info("[EDITOR] Groups: %s", {k: len(v) for k, v in groups.items() if k != "GLOBAL"})

    # Step 4+5: parallel from one snapshot (original doc)
    results: dict[str, SectionEditResult] = {}
    section_ids = [sid for sid in groups if sid not in ("GLOBAL", "UNRESOLVED")]
    batches     = _can_run_parallel(section_ids, catalog)

    for batch in batches:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(batch))) as ex:
            futures = {}
            for sid in batch:
                entry = next((e for e in catalog if e.section_id == sid), None)
                if not entry:
                    continue
                ref_sec = _extract_reference_section(reference_text, sid) if reference_text else ""
                futures[ex.submit(_call_section, entry, groups[sid], toc, catalog, ref_sec)] = sid

            for future in as_completed(futures):
                sid = futures[future]
                try:
                    results[sid] = future.result()
                except Exception as e:
                    log.error("[EDITOR] Section %s failed: %s", sid, e)

    # Step 6: Reassemble
    improved = reassemble(doc, catalog, results, groups)
    original_headings = [(e.level, e.section_id, e.heading) for e in catalog]
    body_edit_headings = [
        (e.level, e.section_id, e.heading) for e in build_catalog(improved)
    ]
    body_topology_valid = [
        (level, section_id)
        for level, section_id, _ in body_edit_headings
    ] == [
        (level, section_id)
        for level, section_id, _ in original_headings
    ]

    global_verified: list[str] = []
    global_results: list[dict] = []
    if body_topology_valid:
        generated_sections: list[tuple[str, str, str]] = []
        allocations = _allocate_new_section_ids(
            new_section_norm,
            build_catalog(improved),
        )
        generated_by_rec: dict[str, tuple[str, str] | None] = {}
        new_section_toc = catalog_to_toc(build_catalog(improved))
        with ThreadPoolExecutor(
            max_workers=min(max_workers, len(allocations)) or 1
        ) as executor:
            futures = {
                executor.submit(
                    _call_new_section,
                    rec,
                    section_id,
                    new_section_toc,
                ): rec.rec_id
                for rec, section_id in allocations
            }
            for future in as_completed(futures):
                rec_id = futures[future]
                try:
                    generated_by_rec[rec_id] = future.result()
                except Exception as exc:
                    log.warning(
                        "[EDITOR] New section call %s failed: %s",
                        rec_id,
                        exc,
                    )
                    generated_by_rec[rec_id] = None

        for rec, section_id in allocations:
            generated = generated_by_rec.get(rec.rec_id)
            if generated is None:
                pending_global_norm.append(rec)
                global_results.append(
                    {
                        "rec_id": rec.rec_id,
                        "operation": "NEW_SECTION",
                        "status": "ROLLED_BACK",
                    }
                )
                continue
            heading, body = generated
            generated_sections.append((section_id, heading, body))
            global_verified.append(rec.rec_id)
            global_results.append(
                {
                    "rec_id": rec.rec_id,
                    "operation": "NEW_SECTION",
                    "status": "COMMITTED",
                    "section_id": section_id,
                }
            )
        improved = _insert_new_sections(improved, generated_sections)

        toc_refreshed = False
        rename_committed = any(
            results.get(section_id)
            and results[section_id].status == "COMMITTED"
            and any(
                rec.operation == "RENAME_SECTION"
                for rec in recs
            )
            for section_id, recs in groups.items()
        )
        if rename_committed:
            improved, toc_refreshed = _refresh_toc(improved)
        if generated_sections or toc_norm:
            improved, _ = _normalize_numeric_section_order(improved)
            improved, toc_refreshed = _refresh_toc(improved)

        if toc_norm:
            if not toc_refreshed:
                improved, toc_refreshed = _refresh_toc(improved)
            for rec in toc_norm:
                if toc_refreshed:
                    global_verified.append(rec.rec_id)
                else:
                    pending_global_norm.append(rec)
                global_results.append(
                    {
                        "rec_id": rec.rec_id,
                        "operation": "REFRESH_TOC",
                        "status": "COMMITTED" if toc_refreshed else "ROLLED_BACK",
                    }
                )
    else:
        pending_global_norm.extend(new_section_norm)
        pending_global_norm.extend(toc_norm)

    # Step 6b: Post-reassembly stub check — silently revert any committed section
    # that validate_structure still sees as stub/empty after reassembly.
    # Root cause: model may introduce sub-headings within a committed section body;
    # _extract_body_sections() splits on ALL heading levels, so the parent section
    # text (text before first sub-heading) can be < 30 chars (_is_stub=True) while
    # _has_populated_child() also fails when sub-headings lack matching numeric
    # prefixes.  Without this check the Step 7 gate fires a full global rollback
    # even though the committed recs are genuinely valid — just misclassified.
    _post_check = validate_structure(improved)
    _post_stub_ids: set[str] = set()
    for _s in _post_check.stub_sections + _post_check.empty_sections:
        _m = re.match(r"^\s*(\d+(?:\.\d+)*)", _s)
        if _m:
            _post_stub_ids.add(_m.group(1))
    # Pre-compute which section IDs in the ORIGINAL doc were also stubs/empty —
    # reverting a committed section back to an original stub makes things WORSE,
    # not better. Only revert if the original body was actually filled content.
    _orig_check = validate_structure(doc)
    _orig_stub_ids: set[str] = set()
    for _s in _orig_check.stub_sections + _orig_check.empty_sections:
        _m = re.match(r"^\s*(\d+(?:\.\d+)*)", _s)
        if _m:
            _orig_stub_ids.add(_m.group(1))
    _stub_reverted = False
    for _sid, _res in results.items():
        # Skip post-reassembly stub revert for sections with REPLACE operations.
        # REPLACE generates fresh content which may be < 30 chars initially but is
        # valid. _is_stub() threshold (30 chars) is too aggressive for new content.
        if _sid in replace_sections:
            continue
        if _res.status == "COMMITTED" and _sid in _post_stub_ids:
            _entry = next((e for e in catalog if e.section_id == _sid), None)
            if _entry:
                # If the original body was ALSO a stub, reverting would go backwards.
                # Keep the committed revision — it is at least no worse than original.
                if _sid in _orig_stub_ids:
                    log.info(
                        "[EDITOR] Post-reassembly stub check: section %s is stub but "
                        "original was also stub — keeping committed revision to avoid regression",
                        _sid,
                    )
                    continue
                # If the model verified at least one recommendation, the section
                # was substantively edited. The post-reassembly stub classification
                # is a false positive: the model likely wrote content that starts
                # with sub-headings (leaving the parent direct body < 30 chars),
                # but the section IS populated. Keep the committed revision.
                if _res.verified:
                    log.info(
                        "[EDITOR] Post-reassembly stub check: section %s has %d verified rec(s) "
                        "— keeping committed revision (model proved content is substantive)",
                        _sid,
                        len(_res.verified),
                    )
                    continue
                log.warning(
                    "[EDITOR] Post-reassembly stub revert: section %s committed but "
                    "validate_structure sees it as stub/empty — reverting to original body",
                    _sid,
                )
                _res.status = "ROLLED_BACK"
                _res.revised_body = _entry.body
                _stub_reverted = True
    if _stub_reverted:
        improved = reassemble(doc, catalog, results, groups)
        # Recompute topology after reversion — the stub sections may have added
        # sub-headings that caused body_topology_valid=False; with original bodies
        # restored, the topology should now match again.
        _body_edit_headings_post = [
            (e.level, e.section_id, e.heading) for e in build_catalog(improved)
        ]
        body_topology_valid = [
            (level, section_id)
            for level, section_id, _ in _body_edit_headings_post
        ] == [
            (level, section_id)
            for level, section_id, _ in original_headings
        ]

    # Step 7: Global validation + full rollback on structural regression.
    # Two conditions that warrant full rollback:
    # 1. Topology violation with zero committed sections — unverified heading
    #    hallucination (committed sections may legitimately add sub-headings).
    # 2. Filled section count dropped — existing sections lost content.
    #    NOTE: ratio alone is unreliable because adding new sections (Section 9.0,
    #    sub-sections) legitimately grows the TOC denominator while those new
    #    sections are still empty, causing ratio to drop without any real loss.
    #    We only flag regression when we actually lost previously-filled sections.
    #    ALSO: When REPLACE operations are active, validate_structure() may
    #    incorrectly mark fresh content as stubs (< 30 char threshold).
    #    We allow more lenient validation when REPLACE operations exist.
    rolled_back = False
    orig_struct  = validate_structure(doc)
    new_struct   = validate_structure(improved)

    # Adjust filled count calculation: for REPLACE-ed sections, exclude them from
    # stub count since fresh content should not be penalized by the 30-char threshold.
    orig_filled = (len(orig_struct.toc_sections)
                   - len(orig_struct.empty_sections)
                   - len(orig_struct.stub_sections))
    new_filled_stubs = [s for s in new_struct.stub_sections
                        if not any(re.match(r"^\s*" + re.escape(sid), s)
                                   for sid in replace_sections)]
    new_filled  = (len(new_struct.toc_sections)
                   - len(new_struct.empty_sections)
                   - len(new_filled_stubs))

    committed_sections = [r for r in results.values() if r.status == "COMMITTED"]
    # Topology violation always triggers rollback — no exemption for committed
    # sections.  The exemption (`and not committed_sections`) was removed because
    # a committed section that injects a spurious heading (e.g. ## 99.0) is still
    # a hallucination and must cause global rollback.  Body topology is evaluated
    # before the global new-section pass, so legitimate section additions (9.0)
    # do not affect this flag.
    topology_violated  = not body_topology_valid
    # Always use lenient thresholds — REPLACE stub compensation is already handled
    # via new_filled_stubs above.  Tightening thresholds when REPLACE sections exist
    # paradoxically makes the global rollback *more* likely: a rec that classifies as
    # REPLACE (e.g. "Replace the fabricated paragraph with the compliance matrix")
    # but then fails per-section verification still appears in replace_sections
    # (computed before results), which would force filled_loss_threshold=0 and trigger
    # global rollback on a single filled-section reclassification.
    regression_threshold = 0.05
    filled_loss_threshold = 1
    significant_regression = (
        new_struct.completeness_ratio < orig_struct.completeness_ratio - regression_threshold
        and new_filled < orig_filled - filled_loss_threshold
    )

    if topology_violated or significant_regression:
        log.error(
            "[EDITOR] CRITICAL REGRESSION: structure %.1f%% → %.1f%% "
            "(filled %d→%d, topology_violated=%s, significant_regression=%s) — "
            "rolling back entire candidate to last_accepted_draft",
            orig_struct.completeness_ratio * 100,
            new_struct.completeness_ratio * 100,
            orig_filled,
            new_filled,
            topology_violated,
            significant_regression,
        )
        improved    = last_accepted_doc if last_accepted_doc else doc
        rolled_back = True
    elif not body_topology_valid and committed_sections:
        log.info(
            "[EDITOR] Topology changed by %d committed section(s) — "
            "sub-heading additions are permitted; no global rollback",
            len(committed_sections),
        )

    # Collect verified changes
    all_verified = []
    for res in results.values():
        all_verified.extend(res.verified)
    all_verified.extend(global_verified)
    if rolled_back:
        all_verified = []
        pending_global_norm.extend(
            rec for rec in norm_recs if rec.rec_id in set(global_verified)
        )
        global_results = [
            {**result, "status": "ROLLED_BACK_BY_GLOBAL_VALIDATION"}
            for result in global_results
        ]

    global_recs = list(
        dict.fromkeys(rec.raw for rec in pending_global_norm)
    )

    log.info(
        "[EDITOR] Done — committed=%d sections, verified=%d recs, "
        "global=%d, unresolved=%d, rolled_back=%s",
        sum(1 for r in results.values() if r.status == "COMMITTED"),
        len(all_verified), len(global_recs), len(unresolved_recs), rolled_back,
    )

    return {
        "improved_doc":    improved,
        "changes_applied": all_verified,
        "verified_recommendations": [
            rec.raw for rec in norm_recs if rec.rec_id in set(all_verified)
        ],
        "section_results": [
            {"section_id": r.section_id, "status": r.status,
             "verified": r.verified, "skipped": r.skipped, "reason": r.reason}
            for _, r in sorted(results.items())
        ],
        "global_recs":     global_recs,
        "global_results":  global_results,
        "unresolved_recs": unresolved_recs,
        "rolled_back":     rolled_back,
    }
