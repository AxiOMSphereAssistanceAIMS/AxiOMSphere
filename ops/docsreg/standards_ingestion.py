from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ops.docsreg.standards_registry import register_standard


def _infer_domain(standard_id: str, doc_type: str = "auto") -> str:
    text = standard_id.upper()
    if doc_type and doc_type != "auto":
        return f"standards.ingested.{doc_type.lower()}"
    if text.startswith("ISO"):
        return "standards.ingested.iso"
    if text.startswith("IEC"):
        return "standards.ingested.iec"
    if text.startswith("API"):
        return "standards.ingested.api"
    if text.startswith("ASME"):
        return "standards.ingested.asme"
    if text.startswith("NFPA"):
        return "standards.ingested.nfpa"
    return "standards.ingested.other"


def infer_standard_id(filename: str, text: str = "") -> str:
    combined = f"{filename} {text[:1000]}"
    patterns = [
        r"(ISO\s*\d[\d\-: ]*(?:Part\s+\d+)?)",
        r"(IEC/IEEE\s*\d[\d\-: ]*)",
        r"(IEC\s*\d[\d\-: ]*(?:-\d+)?)",
        r"(API\s*(?:RP\s*)?\d[\d\-: ]*)",
        r"(ASME\s*[A-Z]\d(?:\.\d+)?)",
        r"(NFPA\s*\d+)",
        r"(EN\s*\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, combined, re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip().upper()
    return Path(filename).stem


def register_ingested_standard(
    *,
    standard_id: str,
    source_path: str,
    title: str = "",
    doc_type: str = "auto",
    official_url: str = "",
    status: str = "ingested",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
) -> None:
    payload = {
        "source_path": source_path,
        "title": title or Path(source_path).name,
        "doc_type": doc_type,
        "official_url": official_url,
        "notes": notes,
    }
    if metadata:
        payload.update(metadata)
    register_standard(
        standard_id,
        domain=_infer_domain(standard_id, doc_type=doc_type),
        source=source_path,
        title=title or Path(source_path).name,
        status=status,
        official_url=official_url,
        notes=notes,
        metadata=payload,
        db_path=db_path,
    )

