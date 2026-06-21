"""Standalone CLI batch runner for DOCSREG pipeline with archive support.

Usage:
    python -m ops.docsreg.pipelines.run_batch \\
        --input-root PATH \\
        --output-root PATH \\
        --evidence-root PATH

The runner:
1. Walks input_root recursively and classifies all files.
2. Extracts supported files from archives.
3. Builds a processing queue from direct + extracted processable files.
4. Calls run_docsreg_cycle() for each file in the queue.
5. Writes manifests to output_root and evidence_root.
6. Prints a summary to stdout.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, List, Optional

from ops.docsreg.batch.archive_extractor import (
    ARCHIVE_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    extract_archive,
)
from ops.docsreg.batch.archive_models import (
    ArchiveRecord,
    ArchiveStatus,
    ExtractedFileRecord,
    ExtractionResult,
    MemberStatus,
)
from ops.docsreg import run_docsreg_cycle  # noqa: E402 — module-level for mock patching

log = logging.getLogger("docsreg.run_batch")

# Files that are completely ignored (system metadata, thumbnails, etc.)
_SKIP_NAMES: frozenset = frozenset({
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
    ".gitkeep",
    ".gitignore",
})

# Recognised unsupported extensions (tracked separately from truly unknown)
_RECOGNISED_UNSUPPORTED: frozenset = frozenset({
    ".doc", ".xls", ".xlsx", ".jpg", ".jpeg",
    ".png", ".tif", ".tiff", ".tmp", ".lock",
})


def _is_archive(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        return True
    return path.suffix.lower() in ARCHIVE_EXTENSIONS


def _classify_file(path: Path) -> str:
    """Return one of: processable, archive, unsupported, skipped."""
    if path.name.lower() in _SKIP_NAMES:
        return "skipped"
    if _is_archive(path):
        return "archive"
    ext = path.suffix.lower()
    if ext in SUPPORTED_EXTENSIONS:
        return "processable"
    return "unsupported"


def _walk_input_root(input_root: Path):
    """Yield all files under input_root recursively."""
    if input_root.is_file():
        yield input_root
        return
    if not input_root.is_dir():
        return
    for p in sorted(input_root.rglob("*")):
        if p.is_file():
            yield p


@dataclass
class BatchFileEntry:
    path: str
    classification: str
    provenance: str  # "direct" or "archive_member"
    archive_path: Optional[str] = None
    archive_chain: Optional[List[str]] = None
    member_path: Optional[str] = None
    extension: Optional[str] = None


@dataclass
class BatchResult:
    path: str
    provenance: str
    outcome: str  # "registered", "failed", "skipped_unsupported", "extraction_failed"
    error: Optional[str] = None
    passed: bool = False


def _run_batch(
    input_root: Path,
    output_root: Path,
    evidence_root: Path,
    document_type: str = "procedure",
    teacher_mode: str = "noop",
    target_quality: float = 0.98,
    max_cycles: int = 7,
) -> int:
    """Core batch processing. Returns exit code (0=success, 1=partial failures)."""
    output_root.mkdir(parents=True, exist_ok=True)
    evidence_root.mkdir(parents=True, exist_ok=True)

    # --- Phase 1: classify all input files ---
    processable_files: List[Path] = []
    archive_files: List[Path] = []
    unsupported_files: List[Path] = []
    skipped_files: List[Path] = []
    source_manifest_entries: List[BatchFileEntry] = []

    for fpath in _walk_input_root(input_root):
        cls = _classify_file(fpath)
        if cls == "processable":
            processable_files.append(fpath)
            source_manifest_entries.append(BatchFileEntry(
                path=str(fpath),
                classification="processable",
                provenance="direct",
                extension=fpath.suffix.lower(),
            ))
        elif cls == "archive":
            archive_files.append(fpath)
            source_manifest_entries.append(BatchFileEntry(
                path=str(fpath),
                classification="archive",
                provenance="direct",
                extension=fpath.suffix.lower(),
            ))
        elif cls == "skipped":
            skipped_files.append(fpath)
        else:
            unsupported_files.append(fpath)
            source_manifest_entries.append(BatchFileEntry(
                path=str(fpath),
                classification="unsupported",
                provenance="direct",
                extension=fpath.suffix.lower(),
            ))

    # --- Phase 2: extract archives ---
    archive_records: List[ArchiveRecord] = []
    extraction_results: List[ExtractionResult] = []
    extracted_all_records: List[ExtractedFileRecord] = []
    extracted_processable: List[ExtractedFileRecord] = []
    extraction_failures = 0

    for arch_path in archive_files:
        ext = arch_path.suffix.lower()
        from ops.docsreg.batch.archive_extractor import _sha256_of_path
        sha = _sha256_of_path(arch_path)

        arch_record = ArchiveRecord(
            path=arch_path,
            extension=ext,
            sha256=sha,
            status=ArchiveStatus.queued_for_extraction,
        )

        extract_root = output_root / "extracted" / arch_path.stem
        extract_root.mkdir(parents=True, exist_ok=True)

        try:
            result, file_records = extract_archive(
                archive_path=arch_path,
                extraction_root=extract_root,
            )
        except Exception as exc:
            result = ExtractionResult(
                archive_path=arch_path,
                archive_sha256=sha,
                status=ArchiveStatus.corrupt_archive,
                error=str(exc),
            )
            file_records = []
            extraction_failures += 1

        arch_record.status = result.status
        if result.error:
            arch_record.error = result.error

        if result.status not in (ArchiveStatus.extracted,):
            extraction_failures += 1

        archive_records.append(arch_record)
        extraction_results.append(result)
        extracted_all_records.extend(file_records)

        for rec in file_records:
            if rec.status == MemberStatus.queued:
                extracted_processable.append(rec)
                source_manifest_entries.append(BatchFileEntry(
                    path=str(rec.path),
                    classification="processable",
                    provenance="archive_member",
                    archive_path=str(rec.archive_path),
                    archive_chain=rec.archive_chain,
                    member_path=rec.member_path,
                    extension=rec.extension,
                ))
            elif rec.status == MemberStatus.unsupported_format:
                source_manifest_entries.append(BatchFileEntry(
                    path=str(rec.path),
                    classification="unsupported",
                    provenance="archive_member",
                    archive_path=str(rec.archive_path),
                    archive_chain=rec.archive_chain,
                    member_path=rec.member_path,
                    extension=rec.extension,
                ))

    # --- Phase 3: build final processing queue ---
    direct_queue = [(p, "direct") for p in processable_files]
    archive_queue = [(rec.path, "archive_member") for rec in extracted_processable]
    full_queue = direct_queue + archive_queue

    # --- Phase 4: run docsreg_cycle for each file ---
    batch_results: List[BatchResult] = []
    processed = 0
    registered = 0
    failed_registration = 0

    for fpath, provenance in full_queue:
        processed += 1
        file_evidence_root = evidence_root / f"{processed:04d}_{Path(fpath).stem}"
        try:
            result = run_docsreg_cycle(
                document_type=document_type,
                draft_path=fpath,
                evidence_root=file_evidence_root,
                teacher_mode=teacher_mode,  # type: ignore[arg-type]
                target_quality=target_quality,
                max_cycles=max_cycles,
            )
            passed = getattr(result, "passed", False)
            outcome = getattr(result, "outcome", "UNKNOWN")
            if passed:
                registered += 1
                batch_results.append(BatchResult(
                    path=str(fpath),
                    provenance=provenance,
                    outcome="registered",
                    passed=True,
                ))
            else:
                failed_registration += 1
                batch_results.append(BatchResult(
                    path=str(fpath),
                    provenance=provenance,
                    outcome="failed",
                    error=str(outcome),
                    passed=False,
                ))
        except Exception as exc:  # noqa: BLE001
            failed_registration += 1
            batch_results.append(BatchResult(
                path=str(fpath),
                provenance=provenance,
                outcome="failed",
                error=f"{type(exc).__name__}: {exc}",
                passed=False,
            ))

    # Count unsupported inside archives
    unsupported_in_archives = sum(
        1 for rec in extracted_all_records
        if rec.status == MemberStatus.unsupported_format
    )

    # --- Phase 5: write manifests ---
    def _write_jsonl(path: Path, items):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for item in items:
                if hasattr(item, "__dict__"):
                    row = {k: str(v) if isinstance(v, Path) else v
                           for k, v in item.__dict__.items()}
                else:
                    row = item
                fh.write(json.dumps(row, default=str) + "\n")

    _write_jsonl(output_root / "archive_files.jsonl", archive_records)
    _write_jsonl(output_root / "archive_extraction_results.jsonl", extraction_results)
    _write_jsonl(output_root / "extracted_processable_files.jsonl", extracted_processable)
    _write_jsonl(output_root / "batch_results.jsonl", batch_results)

    # Source manifest (full inventory with provenance)
    source_manifest = {
        "input_root": str(input_root),
        "output_root": str(output_root),
        "evidence_root": str(evidence_root),
        "total_files_found": len(source_manifest_entries) + len(skipped_files),
        "entries": [
            {k: str(v) if isinstance(v, Path) else v
             for k, v in e.__dict__.items()}
            for e in source_manifest_entries
        ],
    }
    with (output_root / "source_manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(source_manifest, fh, indent=2, default=str)

    # --- Phase 6: print summary ---
    total_files = len(processable_files) + len(archive_files) + len(unsupported_files) + len(skipped_files)
    files_extracted_from_archives = len(extracted_all_records)
    skipped_unsupported = len(unsupported_files) + unsupported_in_archives

    print("")
    print("DOCSREG BATCH SUMMARY")
    print("=====================")
    print(f"Total files found:          {total_files}")
    print(f"Direct processable:         {len(processable_files)}")
    print(f"Archives found:             {len(archive_files)}")
    print(f"Files extracted from archives: {files_extracted_from_archives}")
    print(f"Extracted processable:      {len(extracted_processable)}")
    print(f"Unsupported direct:         {len(unsupported_files)}")
    print(f"Unsupported inside archives: {unsupported_in_archives}")
    print(f"Processed:                  {processed}")
    print(f"Registered:                 {registered}")
    print(f"Failed registration:        {failed_registration}")
    print(f"Skipped unsupported:        {skipped_unsupported}")
    print(f"Archive extraction failed:  {extraction_failures}")
    print(f"Evidence path:              {evidence_root}")
    print("")

    return 0 if failed_registration == 0 else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="DOCSREG standalone batch runner with archive support."
    )
    parser.add_argument("--input-root", required=True, type=Path,
                        help="Root directory containing source documents.")
    parser.add_argument("--output-root", required=True, type=Path,
                        help="Directory for manifests and extracted files.")
    parser.add_argument("--evidence-root", required=True, type=Path,
                        help="Directory for DOCSREG cycle evidence artifacts.")
    parser.add_argument("--document-type", default="procedure",
                        help="DOCSREG document type (default: procedure).")
    parser.add_argument("--teacher-mode", default="noop",
                        choices=["noop", "claude_code"],
                        help="Teacher/auditor mode (default: noop).")
    parser.add_argument("--target-quality", type=float, default=0.98,
                        help="Target quality score (default: 0.98).")
    parser.add_argument("--max-cycles", type=int, default=7,
                        help="Max improvement cycles per document (default: 7).")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Logging level (default: INFO).")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    return _run_batch(
        input_root=args.input_root,
        output_root=args.output_root,
        evidence_root=args.evidence_root,
        document_type=args.document_type,
        teacher_mode=args.teacher_mode,
        target_quality=args.target_quality,
        max_cycles=args.max_cycles,
    )


if __name__ == "__main__":
    sys.exit(main())
