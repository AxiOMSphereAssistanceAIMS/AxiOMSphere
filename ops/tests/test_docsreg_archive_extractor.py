"""Tests for ops.docsreg.batch.archive_extractor.

All tests are deterministic — no network, no LLM calls.
Archives are created using stdlib zipfile / tarfile.
"""
from __future__ import annotations

import io
import tarfile
import types
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import ops.docsreg.batch.archive_extractor as extractor_mod
from ops.docsreg.batch.archive_extractor import (
    LIMITS,
    SUPPORTED_EXTENSIONS,
    extract_archive,
)
from ops.docsreg.batch.archive_models import (
    ArchiveStatus,
    ExtractedFileRecord,
    MemberStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_zip(dest: Path, members: dict[str, bytes]) -> Path:
    """Create a zip archive at *dest* with {member_name: content} mapping."""
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return dest


def _make_tar_gz(dest: Path, members: dict[str, bytes]) -> Path:
    """Create a .tar.gz archive at *dest* with {member_name: content} mapping."""
    with tarfile.open(str(dest), "w:gz") as tf:
        for name, content in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return dest


# ---------------------------------------------------------------------------
# test_zip_extracts_pdf_docx_txt
# ---------------------------------------------------------------------------

def test_zip_extracts_pdf_docx_txt(tmp_path):
    arch = _make_zip(tmp_path / "docs.zip", {
        "report.pdf": b"%PDF-1.4 dummy",
        "spec.docx": b"PK dummy docx",
        "readme.txt": b"Hello world",
    })
    result, records = extract_archive(arch, tmp_path / "out")

    assert result.status == ArchiveStatus.extracted
    assert result.files_found == 3
    assert result.processable_found == 3
    assert result.unsupported_found == 0

    extensions = {r.extension for r in records}
    assert extensions == {".pdf", ".docx", ".txt"}
    for rec in records:
        assert rec.status == MemberStatus.queued
        assert rec.path.exists()


# ---------------------------------------------------------------------------
# test_tar_gz_extracts_supported_files
# ---------------------------------------------------------------------------

def test_tar_gz_extracts_supported_files(tmp_path):
    arch = _make_tar_gz(tmp_path / "archive.tar.gz", {
        "docs/manual.md": b"# Manual",
        "docs/guide.rst": b"Guide content",
        "data/image.jpg": b"\xff\xd8\xff dummy jpg",
    })
    result, records = extract_archive(arch, tmp_path / "out")

    assert result.status == ArchiveStatus.extracted
    supported = [r for r in records if r.status == MemberStatus.queued]
    unsupported = [r for r in records if r.status == MemberStatus.unsupported_format]
    assert len(supported) == 2
    assert len(unsupported) == 1
    assert {r.extension for r in supported} == {".md", ".rst"}


# ---------------------------------------------------------------------------
# test_archive_path_traversal_blocked
# ---------------------------------------------------------------------------

def test_archive_path_traversal_blocked(tmp_path):
    # member with a path-traversal name
    arch = _make_zip(tmp_path / "evil.zip", {
        "../../../etc/passwd": b"root:x:0:0",
        "safe.txt": b"safe content",
    })
    result, records = extract_archive(arch, tmp_path / "out")

    assert result.status == ArchiveStatus.extracted
    # The traversal member must NOT be extracted
    escaped = tmp_path / "etc" / "passwd"
    assert not escaped.exists()
    # Only the safe file should be recorded
    safe_records = [r for r in records if r.status == MemberStatus.queued]
    assert len(safe_records) == 1
    assert safe_records[0].extension == ".txt"


# ---------------------------------------------------------------------------
# test_archive_size_limit_enforced
# ---------------------------------------------------------------------------

def test_archive_size_limit_enforced(tmp_path, monkeypatch):
    # 1 KB of content; patch the limit to 0 MB so any content triggers it
    monkeypatch.setitem(extractor_mod.LIMITS, "max_extracted_size_mb", 0)
    arch = _make_zip(tmp_path / "big.zip", {
        "file.txt": b"x" * 1024,
    })
    result, records = extract_archive(arch, tmp_path / "out")

    assert result.status == ArchiveStatus.rejected_archive_safety_limit
    assert result.error is not None


# ---------------------------------------------------------------------------
# test_nested_archive_depth_limit
# ---------------------------------------------------------------------------

def test_nested_archive_depth_limit(tmp_path):
    # Create an inner zip
    inner_zip_path = tmp_path / "inner.zip"
    _make_zip(inner_zip_path, {"inner.txt": b"inner content"})

    # Wrap it in an outer zip (depth 0 → inner is depth 1)
    # At depth=2 recursion should stop
    outer_zip_path = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer_zip_path, "w") as zf:
        zf.write(inner_zip_path, "inner.zip")
        # Also add a normal file
        zf.writestr("outer.txt", b"outer content")

    # Extract with nested_depth=2 (already at limit)
    result, records = extract_archive(
        outer_zip_path,
        tmp_path / "out",
        nested_depth=2,
    )

    assert result.status == ArchiveStatus.extracted
    # The inner.zip member should be skipped due to depth limit
    skipped = [r for r in records if r.status == MemberStatus.skipped_nested_archive_depth_limit]
    assert len(skipped) >= 1


# ---------------------------------------------------------------------------
# test_archive_members_get_provenance
# ---------------------------------------------------------------------------

def test_archive_members_get_provenance(tmp_path):
    arch = _make_zip(tmp_path / "provenance.zip", {
        "folder/doc.pdf": b"%PDF-1.4",
        "notes.txt": b"notes",
    })
    result, records = extract_archive(arch, tmp_path / "out")

    assert result.status == ArchiveStatus.extracted
    for rec in records:
        assert isinstance(rec, ExtractedFileRecord)
        assert rec.source_kind == "archive_member"
        assert rec.archive_path == arch
        assert rec.member_path is not None
        assert rec.extension in SUPPORTED_EXTENSIONS
        assert len(rec.extracted_sha256) == 64  # sha256 hex
        assert isinstance(rec.archive_chain, list)
        assert rec.nested_depth == 0


# ---------------------------------------------------------------------------
# test_extracted_supported_files_enter_queue
# ---------------------------------------------------------------------------

def test_extracted_supported_files_enter_queue(tmp_path):
    """Extracted processable files must be passed to run_docsreg_cycle."""
    arch = _make_zip(tmp_path / "batch.zip", {
        "doc.md": b"# Doc",
    })

    # Use the batch runner logic
    from ops.docsreg.pipelines.run_batch import _run_batch

    mock_result = SimpleNamespace(passed=True, outcome="DOCUMENT_TYPE_CERTIFIED")
    call_args = []

    def mock_run_docsreg_cycle(**kwargs):
        call_args.append(kwargs["draft_path"])
        return mock_result

    with patch("ops.docsreg.pipelines.run_batch.run_docsreg_cycle", mock_run_docsreg_cycle):
        _run_batch(
            input_root=tmp_path,
            output_root=tmp_path / "output",
            evidence_root=tmp_path / "evidence",
            document_type="procedure",
        )

    # The extracted doc.md should have been processed
    processed_paths = [str(p) for p in call_args]
    assert any("doc.md" in p for p in processed_paths), (
        f"doc.md not found in processed paths: {processed_paths}"
    )


# ---------------------------------------------------------------------------
# test_unsupported_archive_members_not_failed_registration
# ---------------------------------------------------------------------------

def test_unsupported_archive_members_not_failed_registration(tmp_path):
    """A .doc inside a zip should be skipped, not counted as registration failure."""
    arch = _make_zip(tmp_path / "mixed.zip", {
        "old.doc": b"\xd0\xcf\x11\xe0 dummy doc",  # legacy Word
        "new.docx": b"PK dummy docx",
    })

    result, records = extract_archive(arch, tmp_path / "out")

    unsupported = [r for r in records if r.status == MemberStatus.unsupported_format]
    supported = [r for r in records if r.status == MemberStatus.queued]

    assert len(unsupported) == 1
    assert unsupported[0].extension == ".doc"
    assert len(supported) == 1
    assert supported[0].extension == ".docx"


# ---------------------------------------------------------------------------
# test_corrupt_archive_reported_separately
# ---------------------------------------------------------------------------

def test_corrupt_archive_reported_separately(tmp_path):
    bad_zip = tmp_path / "corrupt.zip"
    bad_zip.write_bytes(b"this is not a valid zip file at all")

    result, records = extract_archive(bad_zip, tmp_path / "out")

    assert result.status == ArchiveStatus.corrupt_archive
    assert result.error is not None
    assert records == []


# ---------------------------------------------------------------------------
# test_final_summary_has_archive_counts
# ---------------------------------------------------------------------------

def test_final_summary_has_archive_counts(tmp_path, capsys):
    """Full batch run summary output must include archive-related count lines."""
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)
    _make_zip(input_dir / "docs.zip", {
        "guide.md": b"# Guide",
        "spec.pdf": b"%PDF-1.4",
    })
    # also add a direct txt
    (input_dir / "direct.txt").write_text("direct text file")

    mock_result = SimpleNamespace(passed=True, outcome="DOCUMENT_TYPE_CERTIFIED")

    from ops.docsreg.pipelines.run_batch import _run_batch

    with patch("ops.docsreg.pipelines.run_batch.run_docsreg_cycle", return_value=mock_result):
        _run_batch(
            input_root=input_dir,
            output_root=tmp_path / "output",
            evidence_root=tmp_path / "evidence",
        )

    captured = capsys.readouterr()
    summary = captured.out

    assert "DOCSREG BATCH SUMMARY" in summary
    assert "Archives found:" in summary
    assert "Files extracted from archives:" in summary
    assert "Extracted processable:" in summary
    assert "Archive extraction failed:" in summary
    assert "Evidence path:" in summary
