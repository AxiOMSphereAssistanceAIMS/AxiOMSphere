"""Archive extraction layer for the DOCSREG batch pipeline.

Supports .zip, .tar, .tar.gz, .tgz natively via stdlib.
Supports .7z via py7zr (pip) or subprocess 7z.
Supports .rar via subprocess unar or bsdtar.

Security rules enforced:
  - Path traversal: all extracted paths must be children of extraction_root.
  - Symlink escape: symlinks pointing outside extraction_root are skipped.
  - Size limit: aborts if total extracted bytes exceeds max_extracted_size_mb.
  - File count limit: aborts if members exceed max_files_per_archive.
  - Nesting depth limit: nested archives at depth >= max_nested_depth are
    skipped with status=skipped_nested_archive_depth_limit.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

from ops.docsreg.batch.archive_models import (
    ArchiveStatus,
    ExtractedFileRecord,
    ExtractionResult,
    MemberStatus,
)

log = logging.getLogger("docsreg.archive_extractor")

SUPPORTED_EXTENSIONS = frozenset(
    {
        ".md",
        ".txt",
        ".rst",
        ".docx",
        ".pdf",
        ".pptx",
        ".xlsx",
        ".xls",
        ".csv",
        ".html",
        ".htm",
    }
)
ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".rar", ".tar", ".gz", ".tgz"})

LIMITS: dict = {
    "max_archive_size_mb": 2048,
    "max_extracted_size_mb": 8192,
    "max_files_per_archive": 5000,
    "max_nested_depth": 2,
}


def _sha256_of_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_archive_member(member_name: str) -> bool:
    name_lower = member_name.lower()
    return any(name_lower.endswith(ext) for ext in ARCHIVE_EXTENSIONS) or \
           name_lower.endswith(".tar.gz")


def _extension_of_member(member_name: str) -> str:
    name_lower = member_name.lower()
    if name_lower.endswith(".tar.gz"):
        return ".tar.gz"
    return Path(member_name).suffix.lower()


def _resolve_safe(path: Path, extraction_root: Path) -> Optional[Path]:
    """Return resolved path only if it is inside extraction_root, else None."""
    try:
        resolved = path.resolve()
        extraction_root_resolved = extraction_root.resolve()
        resolved.relative_to(extraction_root_resolved)
        return resolved
    except (ValueError, OSError):
        return None


def _check_symlink_safe(path: Path, extraction_root: Path) -> bool:
    """Return True if symlink target is inside extraction_root."""
    if not path.is_symlink():
        return True
    try:
        target = Path(os.readlink(str(path)))
        if not target.is_absolute():
            target = path.parent / target
        target_resolved = target.resolve()
        extraction_root_resolved = extraction_root.resolve()
        target_resolved.relative_to(extraction_root_resolved)
        return True
    except (ValueError, OSError):
        return False


def _try_import_py7zr() -> bool:
    try:
        import py7zr  # noqa: F401
        return True
    except ImportError:
        return False


def _try_subprocess_7z() -> bool:
    return shutil.which("7z") is not None


def _try_subprocess_unar() -> bool:
    return shutil.which("unar") is not None


def _try_subprocess_bsdtar() -> bool:
    return shutil.which("bsdtar") is not None


def _extract_zip(
    archive_path: Path,
    extraction_root: Path,
    nested_depth: int,
    archive_chain: List[str],
) -> Tuple[ExtractionResult, List[ExtractedFileRecord]]:
    records: List[ExtractedFileRecord] = []
    extracted_size = 0
    files_found = 0
    processable_found = 0
    unsupported_found = 0

    archive_sha256 = _sha256_of_path(archive_path)

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
    except (zipfile.BadZipFile, Exception) as exc:
        return ExtractionResult(
            archive_path=archive_path,
            archive_sha256=archive_sha256,
            status=ArchiveStatus.corrupt_archive,
            error=str(exc),
        ), []

    max_files = LIMITS["max_files_per_archive"]
    max_size_bytes = LIMITS["max_extracted_size_mb"] * 1024 * 1024
    max_depth = LIMITS["max_nested_depth"]

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            for member in members:
                files_found += 1
                if files_found > max_files:
                    return ExtractionResult(
                        archive_path=archive_path,
                        archive_sha256=archive_sha256,
                        status=ArchiveStatus.rejected_archive_safety_limit,
                        files_found=files_found,
                        processable_found=processable_found,
                        unsupported_found=unsupported_found,
                        extracted_size_bytes=extracted_size,
                        error=f"Exceeded max_files_per_archive={max_files}",
                    ), records

                member_name = member.filename
                # Security: path traversal check
                dest_path = extraction_root / member_name
                safe = _resolve_safe(dest_path.parent, extraction_root)
                if safe is None:
                    log.warning("Skipping path-traversal member: %s", member_name)
                    continue

                ext = _extension_of_member(member_name)
                is_arch = _is_archive_member(member_name)

                # Nested archive depth limit
                if is_arch and nested_depth >= max_depth:
                    rec = ExtractedFileRecord(
                        path=dest_path,
                        archive_path=archive_path,
                        member_path=member_name,
                        extension=ext,
                        extracted_sha256="",
                        nested_depth=nested_depth,
                        status=MemberStatus.skipped_nested_archive_depth_limit,
                        archive_chain=list(archive_chain),
                    )
                    records.append(rec)
                    continue

                # Extract file
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(dest_path, "wb") as dst:
                    data = src.read()
                    dst.write(data)

                # Check symlink safety after extraction
                if dest_path.is_symlink() and not _check_symlink_safe(dest_path, extraction_root):
                    log.warning("Removing unsafe symlink: %s", dest_path)
                    dest_path.unlink(missing_ok=True)
                    continue

                file_size = len(data)
                extracted_size += file_size

                if extracted_size > max_size_bytes:
                    return ExtractionResult(
                        archive_path=archive_path,
                        archive_sha256=archive_sha256,
                        status=ArchiveStatus.rejected_archive_safety_limit,
                        files_found=files_found,
                        processable_found=processable_found,
                        unsupported_found=unsupported_found,
                        extracted_size_bytes=extracted_size,
                        error=f"Exceeded max_extracted_size_mb={LIMITS['max_extracted_size_mb']}",
                    ), records

                file_sha256 = _sha256_of_bytes(data)

                if is_arch and nested_depth < max_depth:
                    # Recurse into nested archive
                    nested_chain = list(archive_chain) + [str(archive_path)]
                    nested_result, nested_records = extract_archive(
                        archive_path=dest_path,
                        extraction_root=extraction_root / f"_nested_{Path(member_name).stem}",
                        nested_depth=nested_depth + 1,
                        archive_chain=nested_chain,
                    )
                    records.extend(nested_records)
                    extracted_size += nested_result.extracted_size_bytes
                    processable_found += nested_result.processable_found
                    unsupported_found += nested_result.unsupported_found
                elif ext in SUPPORTED_EXTENSIONS:
                    processable_found += 1
                    rec = ExtractedFileRecord(
                        path=dest_path,
                        archive_path=archive_path,
                        member_path=member_name,
                        extension=ext,
                        extracted_sha256=file_sha256,
                        nested_depth=nested_depth,
                        status=MemberStatus.queued,
                        archive_chain=list(archive_chain),
                    )
                    records.append(rec)
                else:
                    unsupported_found += 1
                    rec = ExtractedFileRecord(
                        path=dest_path,
                        archive_path=archive_path,
                        member_path=member_name,
                        extension=ext,
                        extracted_sha256=file_sha256,
                        nested_depth=nested_depth,
                        status=MemberStatus.unsupported_format,
                        archive_chain=list(archive_chain),
                    )
                    records.append(rec)

    except (zipfile.BadZipFile, Exception) as exc:
        return ExtractionResult(
            archive_path=archive_path,
            archive_sha256=archive_sha256,
            status=ArchiveStatus.corrupt_archive,
            error=str(exc),
        ), records

    return ExtractionResult(
        archive_path=archive_path,
        archive_sha256=archive_sha256,
        status=ArchiveStatus.extracted,
        files_found=files_found,
        processable_found=processable_found,
        unsupported_found=unsupported_found,
        extracted_size_bytes=extracted_size,
    ), records


def _extract_tar(
    archive_path: Path,
    extraction_root: Path,
    nested_depth: int,
    archive_chain: List[str],
) -> Tuple[ExtractionResult, List[ExtractedFileRecord]]:
    records: List[ExtractedFileRecord] = []
    extracted_size = 0
    files_found = 0
    processable_found = 0
    unsupported_found = 0

    archive_sha256 = _sha256_of_path(archive_path)

    try:
        tf = tarfile.open(str(archive_path))
    except (tarfile.TarError, Exception) as exc:
        return ExtractionResult(
            archive_path=archive_path,
            archive_sha256=archive_sha256,
            status=ArchiveStatus.corrupt_archive,
            error=str(exc),
        ), []

    max_files = LIMITS["max_files_per_archive"]
    max_size_bytes = LIMITS["max_extracted_size_mb"] * 1024 * 1024
    max_depth = LIMITS["max_nested_depth"]

    try:
        members = [m for m in tf.getmembers() if m.isfile()]
    except (tarfile.TarError, Exception) as exc:
        tf.close()
        return ExtractionResult(
            archive_path=archive_path,
            archive_sha256=archive_sha256,
            status=ArchiveStatus.corrupt_archive,
            error=str(exc),
        ), []

    try:
        for member in members:
            files_found += 1
            if files_found > max_files:
                return ExtractionResult(
                    archive_path=archive_path,
                    archive_sha256=archive_sha256,
                    status=ArchiveStatus.rejected_archive_safety_limit,
                    files_found=files_found,
                    processable_found=processable_found,
                    unsupported_found=unsupported_found,
                    extracted_size_bytes=extracted_size,
                    error=f"Exceeded max_files_per_archive={max_files}",
                ), records

            member_name = member.name
            # Security: path traversal check
            dest_path = extraction_root / member_name
            safe = _resolve_safe(dest_path.parent, extraction_root)
            if safe is None:
                log.warning("Skipping path-traversal tar member: %s", member_name)
                continue

            ext = _extension_of_member(member_name)
            is_arch = _is_archive_member(member_name)

            if is_arch and nested_depth >= max_depth:
                rec = ExtractedFileRecord(
                    path=dest_path,
                    archive_path=archive_path,
                    member_path=member_name,
                    extension=ext,
                    extracted_sha256="",
                    nested_depth=nested_depth,
                    status=MemberStatus.skipped_nested_archive_depth_limit,
                    archive_chain=list(archive_chain),
                )
                records.append(rec)
                continue

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fobj = tf.extractfile(member)
                if fobj is None:
                    continue
                data = fobj.read()
            except (tarfile.TarError, Exception) as exc:
                log.warning("Failed to extract tar member %s: %s", member_name, exc)
                continue

            with open(dest_path, "wb") as dst:
                dst.write(data)

            # Symlink safety
            if dest_path.is_symlink() and not _check_symlink_safe(dest_path, extraction_root):
                log.warning("Removing unsafe symlink: %s", dest_path)
                dest_path.unlink(missing_ok=True)
                continue

            file_size = len(data)
            extracted_size += file_size

            if extracted_size > max_size_bytes:
                return ExtractionResult(
                    archive_path=archive_path,
                    archive_sha256=archive_sha256,
                    status=ArchiveStatus.rejected_archive_safety_limit,
                    files_found=files_found,
                    processable_found=processable_found,
                    unsupported_found=unsupported_found,
                    extracted_size_bytes=extracted_size,
                    error=f"Exceeded max_extracted_size_mb={LIMITS['max_extracted_size_mb']}",
                ), records

            file_sha256 = _sha256_of_bytes(data)

            if is_arch and nested_depth < max_depth:
                nested_chain = list(archive_chain) + [str(archive_path)]
                nested_result, nested_records = extract_archive(
                    archive_path=dest_path,
                    extraction_root=extraction_root / f"_nested_{Path(member_name).stem}",
                    nested_depth=nested_depth + 1,
                    archive_chain=nested_chain,
                )
                records.extend(nested_records)
                extracted_size += nested_result.extracted_size_bytes
                processable_found += nested_result.processable_found
                unsupported_found += nested_result.unsupported_found
            elif ext in SUPPORTED_EXTENSIONS:
                processable_found += 1
                rec = ExtractedFileRecord(
                    path=dest_path,
                    archive_path=archive_path,
                    member_path=member_name,
                    extension=ext,
                    extracted_sha256=file_sha256,
                    nested_depth=nested_depth,
                    status=MemberStatus.queued,
                    archive_chain=list(archive_chain),
                )
                records.append(rec)
            else:
                unsupported_found += 1
                rec = ExtractedFileRecord(
                    path=dest_path,
                    archive_path=archive_path,
                    member_path=member_name,
                    extension=ext,
                    extracted_sha256=file_sha256,
                    nested_depth=nested_depth,
                    status=MemberStatus.unsupported_format,
                    archive_chain=list(archive_chain),
                )
                records.append(rec)
    finally:
        tf.close()

    return ExtractionResult(
        archive_path=archive_path,
        archive_sha256=archive_sha256,
        status=ArchiveStatus.extracted,
        files_found=files_found,
        processable_found=processable_found,
        unsupported_found=unsupported_found,
        extracted_size_bytes=extracted_size,
    ), records


def _extract_7z(
    archive_path: Path,
    extraction_root: Path,
    nested_depth: int,
    archive_chain: List[str],
) -> Tuple[ExtractionResult, List[ExtractedFileRecord]]:
    """Extract .7z archives via py7zr or subprocess 7z."""
    archive_sha256 = _sha256_of_path(archive_path)
    extraction_root.mkdir(parents=True, exist_ok=True)

    # Try py7zr first
    if _try_import_py7zr():
        try:
            import py7zr
            with py7zr.SevenZipFile(str(archive_path), mode="r") as z:
                z.extractall(path=str(extraction_root))
        except Exception as exc:
            return ExtractionResult(
                archive_path=archive_path,
                archive_sha256=archive_sha256,
                status=ArchiveStatus.corrupt_archive,
                error=str(exc),
            ), []
    elif _try_subprocess_7z():
        result = subprocess.run(
            ["7z", "x", str(archive_path), f"-o{extraction_root}", "-y"],
            capture_output=True,
            timeout=300,
        )
        if result.returncode != 0:
            return ExtractionResult(
                archive_path=archive_path,
                archive_sha256=archive_sha256,
                status=ArchiveStatus.corrupt_archive,
                error=result.stderr.decode(errors="replace"),
            ), []
    else:
        return ExtractionResult(
            archive_path=archive_path,
            archive_sha256=archive_sha256,
            status=ArchiveStatus.unsupported_archive_extractor,
            error="py7zr not installed and 7z not found in PATH",
        ), []

    # Now scan extracted files
    return _scan_extracted_dir(archive_path, archive_sha256, extraction_root, nested_depth, archive_chain)


def _extract_rar(
    archive_path: Path,
    extraction_root: Path,
    nested_depth: int,
    archive_chain: List[str],
) -> Tuple[ExtractionResult, List[ExtractedFileRecord]]:
    """Extract .rar archives via unar or bsdtar subprocess."""
    archive_sha256 = _sha256_of_path(archive_path)
    extraction_root.mkdir(parents=True, exist_ok=True)

    cmd = None
    if _try_subprocess_unar():
        cmd = ["unar", "-o", str(extraction_root), "-f", str(archive_path)]
    elif _try_subprocess_bsdtar():
        cmd = ["bsdtar", "-x", "-f", str(archive_path), "-C", str(extraction_root)]

    if cmd is None:
        return ExtractionResult(
            archive_path=archive_path,
            archive_sha256=archive_sha256,
            status=ArchiveStatus.unsupported_archive_extractor,
            error="unar and bsdtar not found in PATH",
        ), []

    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        return ExtractionResult(
            archive_path=archive_path,
            archive_sha256=archive_sha256,
            status=ArchiveStatus.corrupt_archive,
            error=result.stderr.decode(errors="replace"),
        ), []

    return _scan_extracted_dir(archive_path, archive_sha256, extraction_root, nested_depth, archive_chain)


def _scan_extracted_dir(
    archive_path: Path,
    archive_sha256: str,
    extraction_root: Path,
    nested_depth: int,
    archive_chain: List[str],
) -> Tuple[ExtractionResult, List[ExtractedFileRecord]]:
    """Scan a directory of already-extracted files and build records."""
    records: List[ExtractedFileRecord] = []
    extracted_size = 0
    files_found = 0
    processable_found = 0
    unsupported_found = 0
    max_size_bytes = LIMITS["max_extracted_size_mb"] * 1024 * 1024
    max_files = LIMITS["max_files_per_archive"]
    max_depth = LIMITS["max_nested_depth"]

    for fpath in sorted(extraction_root.rglob("*")):
        if not fpath.is_file():
            continue

        files_found += 1
        if files_found > max_files:
            return ExtractionResult(
                archive_path=archive_path,
                archive_sha256=archive_sha256,
                status=ArchiveStatus.rejected_archive_safety_limit,
                files_found=files_found,
                processable_found=processable_found,
                unsupported_found=unsupported_found,
                extracted_size_bytes=extracted_size,
                error=f"Exceeded max_files_per_archive={max_files}",
            ), records

        # Security: traversal check
        safe = _resolve_safe(fpath, extraction_root)
        if safe is None:
            log.warning("Skipping path-traversal file: %s", fpath)
            continue

        # Symlink check
        if fpath.is_symlink() and not _check_symlink_safe(fpath, extraction_root):
            log.warning("Skipping unsafe symlink: %s", fpath)
            continue

        ext = _extension_of_member(fpath.name)
        is_arch = _is_archive_member(fpath.name)
        member_name = str(fpath.relative_to(extraction_root))

        file_size = fpath.stat().st_size
        extracted_size += file_size

        if extracted_size > max_size_bytes:
            return ExtractionResult(
                archive_path=archive_path,
                archive_sha256=archive_sha256,
                status=ArchiveStatus.rejected_archive_safety_limit,
                files_found=files_found,
                processable_found=processable_found,
                unsupported_found=unsupported_found,
                extracted_size_bytes=extracted_size,
                error=f"Exceeded max_extracted_size_mb={LIMITS['max_extracted_size_mb']}",
            ), records

        file_sha256 = _sha256_of_path(fpath)

        if is_arch and nested_depth >= max_depth:
            rec = ExtractedFileRecord(
                path=fpath,
                archive_path=archive_path,
                member_path=member_name,
                extension=ext,
                extracted_sha256="",
                nested_depth=nested_depth,
                status=MemberStatus.skipped_nested_archive_depth_limit,
                archive_chain=list(archive_chain),
            )
            records.append(rec)
        elif is_arch and nested_depth < max_depth:
            nested_chain = list(archive_chain) + [str(archive_path)]
            nested_result, nested_records = extract_archive(
                archive_path=fpath,
                extraction_root=extraction_root / f"_nested_{fpath.stem}",
                nested_depth=nested_depth + 1,
                archive_chain=nested_chain,
            )
            records.extend(nested_records)
            extracted_size += nested_result.extracted_size_bytes
            processable_found += nested_result.processable_found
            unsupported_found += nested_result.unsupported_found
        elif ext in SUPPORTED_EXTENSIONS:
            processable_found += 1
            rec = ExtractedFileRecord(
                path=fpath,
                archive_path=archive_path,
                member_path=member_name,
                extension=ext,
                extracted_sha256=file_sha256,
                nested_depth=nested_depth,
                status=MemberStatus.queued,
                archive_chain=list(archive_chain),
            )
            records.append(rec)
        else:
            unsupported_found += 1
            rec = ExtractedFileRecord(
                path=fpath,
                archive_path=archive_path,
                member_path=member_name,
                extension=ext,
                extracted_sha256=file_sha256,
                nested_depth=nested_depth,
                status=MemberStatus.unsupported_format,
                archive_chain=list(archive_chain),
            )
            records.append(rec)

    return ExtractionResult(
        archive_path=archive_path,
        archive_sha256=archive_sha256,
        status=ArchiveStatus.extracted,
        files_found=files_found,
        processable_found=processable_found,
        unsupported_found=unsupported_found,
        extracted_size_bytes=extracted_size,
    ), records


def extract_archive(
    archive_path: Path,
    extraction_root: Path,
    nested_depth: int = 0,
    archive_chain: Optional[List[str]] = None,
) -> Tuple[ExtractionResult, List[ExtractedFileRecord]]:
    """Extract an archive and return (ExtractionResult, list[ExtractedFileRecord]).

    Security guarantees:
    - All extracted paths are verified to be children of extraction_root.
    - Path traversal members are silently skipped with a warning.
    - Symlinks pointing outside extraction_root are removed.
    - Extraction aborts with rejected_archive_safety_limit if:
        * total extracted bytes > max_extracted_size_mb
        * files extracted > max_files_per_archive
    - Nested archives at nested_depth >= max_nested_depth are skipped.
    """
    if archive_chain is None:
        archive_chain = []

    archive_sha256 = _sha256_of_path(archive_path)
    extraction_root.mkdir(parents=True, exist_ok=True)

    name_lower = archive_path.name.lower()

    if name_lower.endswith(".tar.gz") or name_lower.endswith(".tgz") or name_lower.endswith(".tar"):
        return _extract_tar(archive_path, extraction_root, nested_depth, archive_chain)
    elif name_lower.endswith(".zip"):
        return _extract_zip(archive_path, extraction_root, nested_depth, archive_chain)
    elif name_lower.endswith(".7z"):
        return _extract_7z(archive_path, extraction_root, nested_depth, archive_chain)
    elif name_lower.endswith(".rar"):
        return _extract_rar(archive_path, extraction_root, nested_depth, archive_chain)
    else:
        return ExtractionResult(
            archive_path=archive_path,
            archive_sha256=archive_sha256,
            status=ArchiveStatus.unsupported_archive_extractor,
            error=f"Unsupported archive format: {archive_path.suffix}",
        ), []
