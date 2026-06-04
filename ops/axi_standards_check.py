"""
axi_standards_check.py
──────────────────────
Standards / compliance check utilities for the Axi bot.
Extracted from axi_bot.py (Phase C Task 2 refactor).

Provides:
  _build_doc_analysis_system
  _wants_standards_docx_result, _build_applied_corrections_section
  _sources_note
  _wants_standards_check, AIMS_ENABLE_CONTEXTUAL_STANDARD_DISCOVERY
  _wants_contextual_discovery
  _wants_registry_list, _wants_db_strategy
  _extract_search_keywords
  _register_corrected_standards_knowledge
  _resolve_doc_path, _fetch_db_docs

Note: async handler functions (_handle_standards_check, _handle_registry_list,
_handle_db_strategy, _handle_contextual_standard_discovery) remain in axi_bot.py
because they depend on Telegram bot state.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("axi")

# ── Config ─────────────────────────────────────────────────────────────────────

AXI_CHAT_SHOW_SOURCES = os.environ.get("AXI_CHAT_SHOW_SOURCES", "0").strip().lower() in ("1", "true", "yes", "on")
AIMS_ENABLE_CONTEXTUAL_STANDARD_DISCOVERY = os.environ.get(
    "AIMS_ENABLE_CONTEXTUAL_STANDARD_DISCOVERY", "0"
).strip().lower() in ("1", "true", "yes", "on")

_OMI_DB_PATH = Path(os.environ.get("OMI_DB_PATH", "/data/aims_registry.db"))
_AIMS_WORKSPACE = Path(os.environ.get("AIMS_WORKSPACE", "/data"))


# ── Document analysis system prompt ───────────────────────────────────────────

def _build_doc_analysis_system(axi_system_prompt: str = "") -> str:
    """
    System prompt override for deep structured technical document analysis
    when the source contains equipment tables, preservation matrices, or PPM guidelines.
    Injected for the docx-output path in _process_analyze_batch when xlsx is present.
    """
    base = axi_system_prompt or os.environ.get("AXI_SYSTEM_PROMPT", "You are Axi, a practical AI assistant.")
    return (
        base + "\n\n"
        "DOCUMENT ANALYSIS MODE — MANDATORY RULES:\n"
        "1. OUTPUT: Write directly as a professional engineering document using Markdown "
        "(# ## ### headings, bullet lists, **bold**). "
        "NEVER output JSON, code blocks, or {\"action\":...} constructs — "
        "write the document text directly with no wrapper.\n"
        "2. COMPLETENESS: If the source document lists equipment types, systems, or processes "
        "— enumerate EVERY item by its exact name. Do not summarize, skip, or merge any item.\n"
        "3. PER-EQUIPMENT DEPTH: For each equipment type identified, provide a dedicated subsection with:\n"
        "   - Gap analysis: what is currently missing or insufficient in the source\n"
        "   - 3–5 specific, actionable improvements with engineering rationale\n"
        "   - Applicable standards with full designation "
        "(e.g., API 610 12th ed. §9.3, ISO 55001:2014 §8.1, NACE SP0169-2013, IEC 60034-1)\n"
        "   - Quantitative acceptance criteria where applicable "
        "(e.g., vibration ≤ 4.5 mm/s RMS per ISO 10816-3, insulation ≥ 100 MΩ at 500 V DC)\n"
        "4. DOCUMENT STRUCTURE (use this unless the user specified otherwise):\n"
        "   # [Document Title]\n"
        "   ## Executive Summary\n"
        "   ## Scope and Applicability\n"
        "   ## Equipment-by-Equipment Analysis\n"
        "   ### [Equipment Type 1]\n"
        "   ### [Equipment Type 2]\n"
        "   ...\n"
        "   ## Cross-Cutting Recommendations\n"
        "   ## Standards and Reference Matrix\n"
        "5. STANDARDS: Always cite specific standard numbers and sections. "
        "Never use vague phrases like 'per industry standards' or 'according to best practice' "
        "without naming the actual standard.\n"
        "6. LENGTH: Do not truncate. Every equipment type in the source must appear as its own "
        "subsection with full analysis. A complete analysis is expected."
    )


# ── Standards detection helpers ────────────────────────────────────────────────

def _wants_standards_docx_result(text: str, *, _wants_docx_fn=None) -> bool:
    low = (text or "").lower()
    if _wants_docx_fn is not None and _wants_docx_fn(low):
        return True
    # Fallback inline docx check
    if re.search(r"(word|docx|\.docx|в word|в ворд|ворд)", low):
        return True
    return any(k in low for k in (
        "correct", "fix", "revise", "update", "redline",
        "исправ", "скоррект", "обнови", "внеси коррект",
    ))


def _build_applied_corrections_section(compliance_review: str) -> str:
    """Build a concise delta block to show what changed vs original."""
    lines = [(ln or "").strip("-• ").strip() for ln in (compliance_review or "").splitlines()]
    candidates: list[str] = []
    seen: set[str] = set()
    markers = ("gap", "non-com", "critical", "major", "minor", "recommend", "clause", "required")
    for ln in lines:
        low = ln.lower()
        if len(ln) < 18:
            continue
        if not any(m in low for m in markers):
            continue
        if ln in seen:
            continue
        seen.add(ln)
        candidates.append(ln[:220])
        if len(candidates) >= 8:
            break
    if not candidates:
        candidates = [
            "Updated procedure steps to align with cited international standards and clauses.",
            "Added missing control points, verification checkpoints, and records required for compliance.",
            "Clarified acceptance criteria, responsibilities, and evidence requirements.",
        ]
    body = "\n".join(f"- {item}" for item in candidates[:8])
    return "## Applied corrections vs original\n" + body


def _sources_note(
    *,
    lang: str,
    use_search: bool,
    has_dialog_context: bool = False,
    uploaded_files_count: int = 0,
) -> str:
    if not AXI_CHAT_SHOW_SOURCES:
        return ""
    if lang == "ru":
        lines = ["Источники:"]
        lines.append("- запрос пользователя")
        if has_dialog_context:
            lines.append("- контекст предыдущего диалога")
        if uploaded_files_count > 0:
            lines.append(f"- содержимое загруженных файлов ({uploaded_files_count})")
        lines.append("- web search" if use_search else "- без web search")
        return "\n".join(lines)
    lines = ["Sources used:"]
    lines.append("- user request")
    if has_dialog_context:
        lines.append("- recent chat context")
    if uploaded_files_count > 0:
        lines.append(f"- uploaded file content ({uploaded_files_count})")
    lines.append("- web search" if use_search else "- no web search")
    return "\n".join(lines)


def _wants_standards_check(
    text: str,
    *,
    recent_chat_context: str = "",
    pending_files_count: int = 0,
) -> bool:
    """Detect "check against standards / compliance check" intent."""
    low = (text or "").lower()
    check_kw = any(k in low for k in (
        "проверь на стандарт", "проверь стандарт", "проверь соответствие",
        "check against standard", "check standard", "check compliance",
        "compliance check", "standards check", "standards review",
        "на соответствие стандарт", "verify standard", "сверь со стандарт",
        "аудит стандарт", "standards audit",
        "international standards", "with standards", "against standards",
        "according to standards", "per standard", "as per standard",
        "международн", "по стандарт", "по международн",
    ))
    contextual_pair = (
        ("standard" in low or "standards" in low or "international" in low)
        and any(v in low for v in ("check", "verify", "review", "audit", "correct", "fix", "update"))
    )
    if check_kw or contextual_pair:
        return True

    deictic_ref = any(k in low for k in (
        "this procedure", "this document", "this file", "that procedure", "that document",
        "эту процедуру", "этот документ", "этот файл", "данную процедуру", "этот регламент",
    ))
    corrective_action = any(k in low for k in (
        "correct", "fix", "revise", "update", "improve", "bring in line", "align",
        "исправ", "скоррект", "обнов", "доработ", "приведи в соответств",
    ))
    context_low = (recent_chat_context or "").lower()
    has_recent_doc_context = ("[doc:" in context_low) or ("uploaded file content" in context_low)
    has_pending_files = pending_files_count > 0
    return deictic_ref and corrective_action and (has_recent_doc_context or has_pending_files)


def _wants_contextual_discovery(text: str) -> bool:
    """Detect contextual standard discovery / benchmark review intent."""
    low = (text or "").lower()
    markers = (
        "standard discovery",
        "benchmark matrix",
        "gap assessment",
        "compare with public guidance",
        "compare against oem guidance",
        "review procedure against standards",
        "contextual standard discovery",
        "document review benchmark",
        "anonymized standards review",
        "подбор стандартов",
        "матрица требований",
        "анализ разрывов",
        "сравни со стандартами",
        "проверь по лучшим практикам",
        "oem рекомендации",
        "бенчмарк документов",
    )
    if any(m in low for m in markers):
        return True
    return (
        ("benchmark" in low or "бенчмарк" in low or "gap" in low or "разрыв" in low)
        and ("document" in low or "procedure" in low or "документ" in low or "процедур" in low)
    )


# ── Registry intent detection ──────────────────────────────────────────────────

def _wants_registry_list(text: str) -> bool:
    """Detect requests to list/show/search the AIMS document registry."""
    low = text.lower()
    list_kw = any(k in low for k in (
        "реестр", "registry", "registered", "зарегистрировано", "зарегистрированы",
        "список документов", "list documents", "what documents", "какие документы",
        "покажи документы", "show documents", "все документы", "all documents",
        "что в базе", "what's in the", "в реестре", "in the registry",
        "сколько документов", "how many documents", "how many files",
    ))
    gen_kw = any(k in low for k in ("стратегия", "strategy", "подготовь", "generate", "сгенерируй"))
    return list_kw and not gen_kw


def _wants_db_strategy(text: str) -> bool:
    low = text.lower()
    has_db = any(k in low for k in ("database", "from database", "из базы", "из реестра", "из бд", "based on document"))
    has_gen = any(k in low for k in ("strategy", "стратегия", "plan", "план", "report", "отчёт",
                                      "prepare", "подготовь", "generate", "сгенерируй", "create", "создай"))
    return has_db and has_gen


# ── Search / DB utilities ──────────────────────────────────────────────────────

def _extract_search_keywords(text: str) -> list[str]:
    from workers.data_worker import extract_search_keywords
    return extract_search_keywords(text)


def _register_corrected_standards_knowledge(
    *,
    docx_path: Path,
    user_request: str,
    compliance_review: str,
    revised_document: str,
    omi_db_path: Path | None = None,
) -> bool:
    """Save corrected standards output into AIMS registry for reuse in future generations."""
    import sqlite3

    db_path = omi_db_path or _OMI_DB_PATH
    if not db_path.exists():
        log.warning("knowledge register skipped: db not found: %s", db_path)
        return False

    now = datetime.now(timezone.utc).isoformat()
    file_name = docx_path.name
    file_path = str(docx_path)
    standards_hits = sorted(set(re.findall(r"\b(?:ISO|API|ASME|NFPA|OSHA|EN)\s*[A-Z0-9./:-]*", compliance_review)))
    standards_kw = ", ".join(s for s in standards_hits if s.strip())[:500]
    summary = (
        "Corrected procedure after international standards compliance review.\n"
        f"Request: {user_request[:300]}\n"
        f"Standards: {standards_kw or 'not explicitly extracted'}\n"
        f"Findings excerpt: {compliance_review[:1200]}"
    )[:3500]
    notes = (
        "[Axi standards correction artifact]\n"
        "This record stores corrected output generated after compliance gap assessment.\n\n"
        f"[REVIEW]\n{compliance_review[:6000]}\n\n"
        f"[REVISED_DOCUMENT]\n{revised_document[:12000]}"
    )[:15000]

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT id FROM documents WHERE file_path = ? OR file_name = ? LIMIT 1",
            (file_path, file_name),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE documents
                SET title = ?, summary = ?, keywords = ?, date_modified = ?, language = ?, source = ?, notes = ?
                WHERE id = ?
                """,
                (
                    "Corrected procedure (standards-reviewed)",
                    summary,
                    standards_kw,
                    now,
                    "en",
                    "axi_standards_correction",
                    notes,
                    int(existing["id"]),
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO documents (
                    file_path, file_name, file_type, title, summary, aims_process,
                    is_master, is_anonymized, language, date_added, date_modified,
                    source, notes, keywords
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_path,
                    file_name,
                    ".docx",
                    "Corrected procedure (standards-reviewed)",
                    summary,
                    "P06",
                    0,
                    0,
                    "en",
                    now,
                    now,
                    "axi_standards_correction",
                    notes,
                    standards_kw,
                ),
            )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log.warning("knowledge register failed: %s", e)
        return False


def _resolve_doc_path(raw_path: str | None, workspace_path: Path | None = None) -> Path | None:
    from workers.data_worker import resolve_doc_path
    ws = workspace_path or _AIMS_WORKSPACE
    return resolve_doc_path(raw_path, workspace_path=ws)


def _fetch_db_docs(keywords: list[str], max_docs: int = 8,
                   db_path: Path | None = None, workspace_path: Path | None = None) -> list[dict]:
    from workers.data_worker import fetch_db_docs
    db = db_path or _OMI_DB_PATH
    ws = workspace_path or _AIMS_WORKSPACE
    return fetch_db_docs(keywords, max_docs, db_path=db, workspace_path=ws)
