from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ops.docsreg.docsreg_knowledge_source import (
    compute_file_sha256,
    read_json_object,
    record_knowledge_source,
)


def _first_existing_path(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def _candidate_quality_report_paths(source_file: Path, evidence_root: Path) -> list[Path]:
    source_dir = source_file.parent
    candidates = [
        evidence_root / "quality_report.json",
    ]
    candidates.extend(sorted(evidence_root.rglob("quality_report.json")))
    candidates.extend(
        [
            source_dir / "quality_report.json",
            source_dir / "pipeline_run" / "quality_report.json",
        ]
    )
    return candidates


def _candidate_artifact_paths(source_file: Path, evidence_root: Path, filename: str) -> list[Path]:
    source_dir = source_file.parent
    candidates = [
        evidence_root / filename,
    ]
    candidates.extend(sorted(evidence_root.rglob(filename)))
    candidates.extend(
        [
            source_dir / filename,
            source_dir / "pipeline_run" / filename,
        ]
    )
    return candidates


def _select_workspace_dir(workspace_dir: Path | None) -> Path:
    candidates: list[Path] = []
    if workspace_dir is not None:
        candidates.append(Path(workspace_dir))

    try:
        from aims_paths import workspace_root as _workspace_root  # type: ignore[import-not-found]

        candidates.append(_workspace_root())
    except Exception:
        pass

    try:
        from ops.aims_paths import workspace_root as _ops_workspace_root

        candidates.append(_ops_workspace_root())
    except Exception:
        pass

    candidates.append(Path.cwd())

    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            test_dir = candidate / "axi_ft_log"
            test_dir.mkdir(parents=True, exist_ok=True)
            probe = test_dir / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except Exception:
            continue

    fallback = Path.cwd()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def record_attempted_cycle_learning(
    *,
    result: Any,
    source_file: Path,
    evidence_root: Path,
    workspace_dir: Path | None = None,
) -> dict[str, Any]:
    """Record learning artifacts for an attempted DOCSREG cycle.

    The helper is intentionally lenient about artifact placement: in current
    DOCSREG flows, ``quality_report.json`` is usually written next to the source
    file, while batch evidence may live elsewhere. The function searches both
    the source directory and the evidence root so that attempted cycles still
    write learning entries even when the master package is not certified.
    """
    ws = _select_workspace_dir(workspace_dir)
    source = Path(source_file)
    evidence = Path(evidence_root)

    quality_report_path = _first_existing_path(
        _candidate_quality_report_paths(source, evidence)
    )
    if quality_report_path is None:
        raise FileNotFoundError(
            f"quality_report.json not found near {source} or {evidence}"
        )

    quality_report: dict[str, Any] = dict(read_json_object(quality_report_path))

    try:
        quality_report["source_sha256"] = compute_file_sha256(source)
    except Exception:
        pass

    raw_text_path = _first_existing_path(
        _candidate_artifact_paths(source, evidence, "raw_extracted_text.md")
    )
    if raw_text_path is not None:
        quality_report["source_text_path"] = str(raw_text_path)

    master_doc_path = _first_existing_path(
        _candidate_artifact_paths(source, evidence, "master_document.md")
    )
    if master_doc_path is not None:
        quality_report["master_document_path"] = str(master_doc_path)

    return record_knowledge_source(
        evidence_dir=quality_report_path.parent,
        workspace_dir=ws,
        quality_report=quality_report,
        job_id=getattr(result, "job_id", None),
        doc_id=getattr(result, "doc_id", None),
        cycle_id=getattr(result, "cycle_id", None),
        source_file=str(source),
        file_type=source.suffix.lstrip(".") or "unknown",
        final_state=getattr(result, "outcome", None),
        has_prior_failure=False,
    )
