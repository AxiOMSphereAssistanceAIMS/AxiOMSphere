from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ops.docsreg.extraction.markitdown_adapter import (
    MARKITDOWN_SUPPORTED_SUFFIXES,
    extract_with_markitdown,
    write_extraction_artifacts,
)


def markitdown_standard_normalization_enabled() -> bool:
    return os.environ.get("DOCGEN_MARKITDOWN_NORMALIZATION", "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
        "YES",
    }


def _safe_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())[:96].strip("._-")
    return safe or "standard"


def _source_path_from_standard(record: dict[str, Any]) -> Path | None:
    candidates = [
        record.get("registered_source_path"),
        record.get("source_path"),
        record.get("path"),
        record.get("source"),
    ]
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        candidates.extend(
            [
                metadata.get("source_path"),
                metadata.get("file_path"),
                metadata.get("path"),
                metadata.get("source"),
            ]
        )
    for value in candidates:
        text = str(value or "").strip()
        if not text:
            continue
        path = Path(text)
        if path.exists() and path.is_file():
            return path
    return None


def _is_forbidden_etalon_source(record: dict[str, Any], source_path: Path | None) -> bool:
    values = [
        record.get("source_type"),
        record.get("source_id"),
        record.get("standard_id"),
        record.get("title"),
        str(source_path or ""),
    ]
    return any("ETALON" in str(value or "").upper() for value in values)


def normalize_standards_for_comparison(
    standards: dict[str, Any],
    output_dir: str | Path,
    *,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Normalize registered standard source files for DOCGEN comparison evidence.

    The produced Markdown is comparison evidence only. It is never returned as
    source text and must not be consumed by generation or authoring stages.
    """

    if enabled is None:
        enabled = markitdown_standard_normalization_enabled()

    root = Path(output_dir)
    selected = list(standards.get("selected_standards") or [])
    if not enabled:
        return {
            "status": "DISABLED",
            "enabled": False,
            "backend": "markitdown",
            "comparison_only": True,
            "generation_context_allowed": False,
            "standards_seen": len(selected),
            "entries": [],
        }

    root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    extracted_count = 0
    failed_count = 0
    skipped_count = 0

    for index, item in enumerate(selected, start=1):
        record = dict(item)
        standard_id = str(record.get("standard_id") or record.get("code") or f"STD-{index}")
        source_path = _source_path_from_standard(record)
        entry: dict[str, Any] = {
            "standard_id": standard_id,
            "backend": "markitdown",
            "comparison_only": True,
            "generation_context_allowed": False,
            "raw_markdown_in_generation_context": False,
        }

        if source_path is None:
            skipped_count += 1
            entry.update(
                {
                    "status": "SKIPPED",
                    "reason": "NO_REGISTERED_SOURCE_PATH",
                    "fallback_needed": True,
                }
            )
            entries.append(entry)
            continue

        entry["source_path"] = str(source_path)
        if _is_forbidden_etalon_source(record, source_path):
            skipped_count += 1
            entry.update(
                {
                    "status": "BLOCKED",
                    "reason": "ETALON_SOURCE_NOT_ALLOWED_IN_DOCGEN_GENERATION_CONTEXT",
                    "fallback_needed": True,
                }
            )
            entries.append(entry)
            continue

        if source_path.suffix.lower() not in MARKITDOWN_SUPPORTED_SUFFIXES:
            skipped_count += 1
            entry.update(
                {
                    "status": "SKIPPED",
                    "reason": f"UNSUPPORTED_FORMAT:{source_path.suffix.lower() or 'none'}",
                    "fallback_needed": True,
                }
            )
            entries.append(entry)
            continue

        result = extract_with_markitdown(source_path)
        standard_dir = root / _safe_id(standard_id)
        artifacts = write_extraction_artifacts(result, standard_dir)
        metadata_path = standard_dir / "normalization_metadata.json"
        metadata = {
            "standard_id": standard_id,
            "source_path": str(source_path),
            "backend": "markitdown",
            "status": result.status,
            "comparison_only": True,
            "generation_context_allowed": False,
            "raw_markdown_in_generation_context": False,
            "word_count": result.word_count,
            "char_count": result.char_count,
            "warnings": result.warnings,
            "metadata": result.metadata,
            "artifacts": artifacts,
        }
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if result.status == "extracted":
            extracted_count += 1
            status = "PASS"
        else:
            failed_count += 1
            status = "FAIL"
        entry.update(
            {
                "status": status,
                "extraction_status": result.status,
                "word_count": result.word_count,
                "char_count": result.char_count,
                "warnings": result.warnings,
                "fallback_needed": result.status != "extracted",
                "raw_extracted_text_path": artifacts["raw_extracted_text"],
                "extraction_report_path": artifacts["extraction_report"],
                "normalization_metadata_path": str(metadata_path),
            }
        )
        entries.append(entry)

    overall = "PASS" if extracted_count and failed_count == 0 else "WARN"
    if failed_count and extracted_count == 0:
        overall = "FAIL"
    if not entries:
        overall = "WARN"

    summary = {
        "status": overall,
        "enabled": True,
        "backend": "markitdown",
        "comparison_only": True,
        "generation_context_allowed": False,
        "raw_markdown_in_generation_context": False,
        "standards_seen": len(selected),
        "standards_extracted": extracted_count,
        "standards_failed": failed_count,
        "standards_skipped": skipped_count,
        "entries": entries,
    }
    (root / "standard_normalization_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def attach_standard_normalization_summary(
    standards: dict[str, Any],
    evidence_dir: str | Path,
) -> dict[str, Any]:
    payload = dict(standards)
    summary = normalize_standards_for_comparison(
        payload,
        Path(evidence_dir) / "standard_comparison_normalization",
    )
    payload["markitdown_standard_normalization"] = {
        key: value
        for key, value in summary.items()
        if key != "entries"
    }
    payload["markitdown_standard_normalization"]["entry_count"] = len(
        summary.get("entries") or []
    )
    return payload
