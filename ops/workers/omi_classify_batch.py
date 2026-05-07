#!/usr/bin/env python3
"""
omi_classify_batch.py
─────────────────────
Batch-classify documents in aims_registry.db by AIMS process (P00-P07)
and element (E01-E23) using local AI (Ollama).

Reads document text, sends to Qwen for classification, updates DB.

Usage:
    python omi_classify_batch.py --dry-run   # preview
    python omi_classify_batch.py             # classify for real
    python omi_classify_batch.py --limit 10  # first 10 only
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))

from sqlite_helpers import sqlite_connect_wal

# ── Config ────────────────────────────────────────────────────────────────────

def _data_root() -> Path:
    repo_root = Path(__file__).resolve().parent.parent
    aw = repo_root / "aims_workspace"
    return aw if aw.is_dir() else Path("/data")

AIMS_DB = Path(os.environ.get("AIMS_REGISTRY_DB", str(_data_root() / "aims_registry.db")))
MODEL = os.environ.get("OMI_CLASSIFY_MODEL", os.environ.get("OMI_MODEL", "qwen3.5:27b")).strip() or "qwen3.5:27b"


def _ollama_url() -> str:
    from ollama_resolve import effective_ollama_base_url

    return effective_ollama_base_url()


def _nim_url() -> str:
    return os.environ.get("NVIDIA_NIM_URL", "http://127.0.0.1:8082").rstrip("/")


def _nim_key() -> str:
    return os.environ.get("NVIDIA_NIM_API_KEY", "").strip()

# ── AIMS taxonomy ─────────────────────────────────────────────────────────────

PROCESSES = {
    "P01": "Purpose & Context: asset integrity policy (definition, approval, communication, maintenance), organizational objectives, scope, stakeholders",
    "P02": "Leadership & Governance: leadership commitment, governance structures, compliance assurance, auditing (internal/external), legal register",
    "P03": "Organization & People: organizational structure, roles/responsibilities, RACI, competence management, training, communication, coordination",
    "P04": "Strategy & Planning: asset integrity strategy, SAMP, lifecycle cost optimization, supplier/contractor management, prequalification",
    "P05": "Asset Management Decision-Making: lifecycle decisions, CAPEX vs OPEX, risk-based decisions, management of change (MOC)",
    "P06": "Life Cycle Delivery: lifecycle definition (design, procurement, construction, operation, maintenance, decommissioning), projects, operational integrity, SOPs, inspection/testing (RBI, NDT), maintenance management, emergency response",
    "P07": "Information Management: data governance, data lifecycle, data standards, data acquisition/validation/storage/analysis",
    "P08": "Risk: risk identification (HAZID), failure modes (FMEA/FMECA), risk analysis/evaluation/treatment, anomaly management, alarm systems",
    "P09": "Review & Continual Improvement: KPI management, performance reporting, incident investigation (RCA), lessons learned, PDCA cycle, process optimization",
    "P10": "Value & Outcomes: performance targets/KPIs/thresholds, external/regulatory communication, stakeholder engagement, QC activities (inspection checks, testing validation)",
    "P00": "General AIMS / asset management: general framework, overview, multi-domain, doesn't fit specific process",
}

ELEMENTS = {
    "E01": "Asset Integrity Policy",
    "E02": "Asset Integrity Strategy",
    "E03": "Asset Life Cycle Management",
    "E04": "Leadership and Commitment",
    "E05": "Compliance Assurance",
    "E06": "Organization, Roles and Responsibilities",
    "E07": "Competence Management and Training",
    "E08": "Communication and Coordination",
    "E09": "Risk Identification, Assessment and Management",
    "E10": "Data Management",
    "E11": "Asset Integrity Management in Projects",
    "E12": "Operational Integrity Management",
    "E13": "Inspection and Testing",
    "E14": "Maintenance Management",
    "E15": "Anomaly Management",
    "E16": "Management of Change (MOC)",
    "E17": "Emergency Response, Recovery and Repairs",
    "E18": "Supplier and Contractor Management",
    "E19": "Performance and Reporting",
    "E20": "Incident and Failure Investigation",
    "E21": "Integrity Management Auditing",
    "E22": "Quality Control and Quality Assurance",
    "E23": "Performance Improvement",
}


def _build_prompt(file_name: str, title: str, summary: str | None, text_sample: str) -> str:
    proc_list = "\n".join(f"  {k}: {v}" for k, v in PROCESSES.items())
    elem_list = "\n".join(f"  {k}: {v}" for k, v in ELEMENTS.items())
    return f"""Classify this document into the AIMS framework.

AIMS PROCESSES (choose ONE):
{proc_list}

AIMS ELEMENTS (choose ONE or TWO most relevant):
{elem_list}

DOCUMENT:
  File: {file_name}
  Title: {title or file_name}
  Summary: {summary or '(none)'}
  Content sample: {text_sample[:3000]}

Return ONLY JSON: {{"process": "P05", "element": "E14", "reason": "short reason"}}
If the document is a CV/resume or non-technical, use P00 with no element.
If uncertain between two processes, pick the most specific one (P05 Operation is most common for technical docs)."""


def _llm_classify(prompt: str) -> str | None:
    """Call NVIDIA NIM API for classification (Anthropic-compatible). Falls back to Ollama."""
    # Try NIM first if configured
    nim_url = _nim_url()
    nim_key = _nim_key()

    if nim_url and nim_key:
        import urllib.request
        try:
            url = f"{nim_url}/v1/chat/completions"
            payload = json.dumps({
                "model": "meta/llama-3.1-405b-instruct",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 200,
            }).encode()
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {nim_key}",
            }
            req = urllib.request.Request(url, data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
        except Exception as e:
            print(f"  NIM error: {e}")

    # Fallback to Ollama
    try:
        payload = json.dumps({
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 200},
        }).encode()
        req = urllib.request.Request(
            f"{_ollama_url()}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            return data.get("response", "")
    except Exception as e:
        print(f"  Ollama error: {e}")
        return None


def _parse_classification(raw: str | None) -> tuple[str | None, str | None, str]:
    """Parse JSON response from LLM. Returns (process, element, reason)."""
    if not raw:
        return None, None, "no_response"
    s = raw.strip()
    first = s.find("{")
    last = s.rfind("}")
    if first == -1 or last <= first:
        return None, None, f"no_json: {s[:100]}"
    try:
        data = json.loads(s[first:last + 1])
        proc = str(data.get("process", "")).strip().upper()
        elem = str(data.get("element", "")).strip().upper()
        reason = str(data.get("reason", ""))[:200]
        if proc not in PROCESSES:
            proc = None
        if elem not in ELEMENTS:
            elem = None
        return proc, elem, reason
    except json.JSONDecodeError:
        return None, None, f"json_error: {s[:100]}"


def _read_text_sample(file_path: str, max_chars: int = 3000) -> str:
    """Read text from file for classification."""
    p = Path(file_path)
    if not p.is_file():
        return ""
    ext = p.suffix.lower()
    try:
        if ext in (".txt", ".md"):
            return p.read_text(encoding="utf-8", errors="ignore")[:max_chars]
        if ext == ".docx":
            try:
                from docx import Document
                doc = Document(str(p))
                return "\n".join(para.text for para in doc.paragraphs if para.text)[:max_chars]
            except Exception:
                return ""
    except Exception:
        pass
    return ""


def run(*, dry_run: bool = False, limit: int = 0) -> None:
    if not AIMS_DB.is_file():
        print(f"[classify] DB not found: {AIMS_DB}")
        return

    conn = sqlite_connect_wal(AIMS_DB)
    conn.row_factory = sqlite3.Row

    docs = conn.execute(
        "SELECT id, file_path, file_name, title, summary FROM documents "
        "WHERE aims_process IS NULL OR aims_process = '' "
        "ORDER BY id"
    ).fetchall()

    print(f"[classify] Unclassified docs: {len(docs)}, model: {MODEL}")
    if limit > 0:
        docs = docs[:limit]

    classified = 0
    failed = 0

    for doc in docs:
        fpath = doc["file_path"] or ""
        fname = doc["file_name"] or ""
        title = doc["title"] or ""
        summary = doc["summary"] or ""

        text_sample = _read_text_sample(fpath)
        if not text_sample and not title and not summary:
            print(f"  SKIP (no text): {fname}")
            failed += 1
            continue

        prompt = _build_prompt(fname, title, summary, text_sample)
        raw = _llm_classify(prompt)
        proc, elem, reason = _parse_classification(raw)

        if not proc:
            print(f"  FAIL: {fname} — {reason}")
            failed += 1
            continue

        elem_label = f" / {elem}" if elem else ""
        if dry_run:
            print(f"  DRY: {fname} → {proc}{elem_label} ({reason})")
        else:
            conn.execute(
                "UPDATE documents SET aims_process = ?, aims_element = ? WHERE id = ?",
                (proc, elem, doc["id"]),
            )
            conn.commit()
            print(f"  OK: {fname} → {proc}{elem_label} ({reason})")
        classified += 1

    conn.close()
    print(f"\n[classify] Done: classified={classified} failed={failed}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch classify documents by AIMS process/element")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    run(dry_run=args.dry_run, limit=args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
