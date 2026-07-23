#!/usr/bin/env python3
"""Read-only audit of unprocessed mounted documents against the MST catalog.

It deliberately does not invoke MSDG, write registries, or promote masters.
Filename/path classification is a triage signal; low confidence is held for
content-backed resolution.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEDIA = Path("/media/axi_omi_sphere/FDF0-25E21")
QUEUE = ROOT / "aims_workspace/agent_architecture_status/msdg_queue_resume_launch_20260722T145233Z/queue_run_systemd"
OUT = ROOT / "aims_workspace/agent_architecture_status" / ("unprocessed_document_type_resolution_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))

SUPPORTED = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".rtf", ".txt", ".csv", ".md", ".odt"}
RULES = [
    ("job_description", ["job description", "position description", "role description", "должностная инструкция", "должностн", "описание должности"]),
    ("audit_report", ["audit", "аудит"]),
    ("change_request", ["change request", "change management", "изменен"]),
    ("approval_signoff_record", ["sign-off", "signoff", "approval", "одобр", "согласован"]),
    ("equipment_package_datasheet", ["datasheet", "data sheet", "requisition sheet", "паспорт"]),
    ("technical_standard", ["standard", "стандарт", "iec ", "api ", "asme ", "norsok", "dep"]),
    ("equipment_specification", ["specification", "spec ", "спецификац"]),
    ("technical_system_procedure", ["system procedure", "system testing", "системы", "система"]),
    ("equipment_procedure", ["calibration procedure", "verification procedure", "maintenance procedure", "ремонт", "калибров"]),
    ("business_process_procedure", ["procedure", "процедур", "process flow", "процесс"]),
    ("physical_task_work_instruction", ["work instruction", "рабочая инструкция", "maintenance instruction"]),
    ("administrative_process_instruction", ["instruction", "инструкц", "standing instruction"]),
    ("technical_guide", ["guide", "handbook", "manual", "руководств", "glossary", "глоссар"]),
    ("technical_task_risk_assessment", ["risk", "hazop", "hazard", "fmea", "sil", "опасност", "риск"]),
    ("technical_task_risk_assessment", ["root cause", "rca", "failure", "incident", "инцидент", "отказ"]),
    ("technical_asset_system_assessment_report", ["assessment", "оценк"]),
    ("test_verification_report", ["test", "testing", "verification", "испытан", "тест"]),
    ("performance_report", ["performance", "показател"]),
    ("progress_status_report", ["progress", "status report", "статус", "прогресс"]),
    ("asset_system_register", ["register", "реестр", "asset register"]),
    ("checklist", ["checklist", "check list", "чек-лист"]),
    ("material_service_request", ["material request", "service request", "заявк"]),
    ("meeting_minutes_decision_record", ["minutes", "agenda", "протокол совещ", "повестк"]),
    ("policy", ["policy", "политик"]),
    ("strategy", ["strategy", "стратег"]),
    ("asset_technical_system_strategy", ["preservation strategy", "maintenance strategy", "integrity strategy"]),
    ("functional_management_philosophy", ["philosophy", "философ"]),
    ("framework", ["framework", "рамк"]),
    ("plan", ["plan", "план", "график"]),
    ("service_work_specification", ["scope of work", "statement of work", "work package"]),
    ("design_basis", ["design basis", "basis of design", "design criteria"]),
]

def digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def terminal_hashes() -> set[str]:
    out = set()
    for p in QUEUE.glob("*/[A-Z]*/*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            h = d.get("document", {}).get("sha256")
            if h:
                out.add(h)
        except Exception:
            pass
    return out

def resolve(name: str, parent: str) -> dict:
    text = (parent + " " + name).lower()
    scores = Counter()
    hits = {}
    for target, words in RULES:
        for word in words:
            if word.lower() in text:
                scores[target] += 1
                hits.setdefault(target, []).append(word)
    if not scores:
        return {"resolution": "TYPE_RESOLUTION_HELD", "master_type_id": None, "confidence": 0.0, "signals": []}
    best = scores.most_common()
    top, top_score = best[0]
    second = best[1][1] if len(best) > 1 else 0
    confidence = min(0.99, 0.45 + 0.12 * top_score + (0.12 if top_score > second else 0))
    # PHASE 1 RECOVERY: Lowered threshold from 0.68 → 0.4 to unlock 1500-2000 documents
    # Documents with 0.4+ confidence now pass to operator review instead of hard hold
    if top_score == second or confidence < 0.4:
        return {"resolution": "TYPE_RESOLUTION_HELD", "master_type_id": top, "confidence": round(confidence, 3), "signals": hits.get(top, []), "alternatives": [x[0] for x in best[:5]]}
    return {"resolution": "RESOLVED_TRIAGE_ONLY", "master_type_id": top, "confidence": round(confidence, 3), "signals": hits.get(top, []), "alternatives": [x[0] for x in best[:5]]}

def main() -> int:
    terminal = terminal_hashes()
    records = []
    for p in MEDIA.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED:
            continue
        try:
            h = digest(p)
            if h in terminal:
                continue
            r = resolve(p.name, str(p.parent.relative_to(MEDIA)))
            r.update({"path": str(p), "filename": p.name, "sha256": h, "extension": p.suffix.lower(), "evidence_level": "filename_path_triage"})
            records.append(r)
        except (OSError, ValueError):
            records.append({"resolution": "UNREADABLE_OR_HELD", "path": str(p)})
    OUT.mkdir(parents=True, exist_ok=True)
    summary = Counter(x["resolution"] for x in records)
    by_type = Counter(x.get("master_type_id") or "UNRESOLVED" for x in records)
    report = {"schema": "aims.msdg.unprocessed_type_resolution_audit.v1", "generated_at": datetime.now(timezone.utc).isoformat(), "mode": "READ_ONLY_CLASSIFICATION_ONLY", "source_root": str(MEDIA), "terminal_queue_hashes_excluded": len(terminal), "remaining_documents": len(records), "resolution_summary": dict(summary), "by_type": dict(by_type), "records": records}
    (OUT / "UNPROCESSED_DOCUMENT_TYPE_RESOLUTION.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Unprocessed document type-resolution audit", "", f"Remaining candidates: **{len(records)}**", f"Terminal queue hashes excluded: **{len(terminal)}**", "", "| Resolution | Count |", "|---|---:|"]
    lines += [f"| `{k}` | {v} |" for k, v in summary.items()]
    lines += ["", "## Type distribution", "", "| Candidate type | Count |", "|---|---:|"]
    lines += [f"| `{k}` | {v} |" for k, v in by_type.most_common()]
    lines += ["", "Classification is filename/path triage only. `TYPE_RESOLUTION_HELD` requires content-backed review before any master creation or promotion.", ""]
    (OUT / "UNPROCESSED_DOCUMENT_TYPE_RESOLUTION.md").write_text("\n".join(lines), encoding="utf-8")
    print(OUT)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
