"""Integration-style tests for the DOCSREG batch runner with archives.

Uses tmp_path with real archives (stdlib zipfile/tarfile).
Mocks run_docsreg_cycle to avoid LLM calls.
"""
from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_zip(dest: Path, members: dict[str, bytes]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return dest


def _make_tar_gz(dest: Path, members: dict[str, bytes]) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(dest), "w:gz") as tf:
        for name, content in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return dest


def _build_mixed_input_root(root: Path) -> dict:
    """Build a directory with direct processable, archives, and unsupported files."""
    (root / "direct").mkdir(parents=True, exist_ok=True)
    (root / "archives").mkdir(exist_ok=True)

    # Direct processable files
    direct_md = root / "direct" / "procedure.md"
    direct_md.write_text("# Procedure\n\nStep 1.")
    direct_txt = root / "direct" / "notes.txt"
    direct_txt.write_text("Some notes.")

    # Direct unsupported
    direct_doc = root / "direct" / "legacy.doc"
    direct_doc.write_bytes(b"\xd0\xcf\x11\xe0 dummy")

    # Archive with supported + unsupported members
    arch_zip = _make_zip(root / "archives" / "batch1.zip", {
        "guide.pdf": b"%PDF-1.4 dummy",
        "spec.docx": b"PK dummy docx",
        "old.xls": b"\xd0\xcf\x11\xe0 dummy xls",
    })

    # Tar.gz archive
    arch_tar = _make_tar_gz(root / "archives" / "batch2.tar.gz", {
        "manual.rst": b"Manual\n======\n",
    })

    # Corrupt archive
    corrupt = root / "archives" / "corrupt.zip"
    corrupt.write_bytes(b"not a zip at all")

    return {
        "direct_md": direct_md,
        "direct_txt": direct_txt,
        "direct_doc": direct_doc,
        "arch_zip": arch_zip,
        "arch_tar": arch_tar,
        "corrupt": corrupt,
    }


# ---------------------------------------------------------------------------
# Core integration test
# ---------------------------------------------------------------------------

def test_batch_processes_direct_and_extracted_files(tmp_path):
    """Direct + extracted processable files both go to run_docsreg_cycle."""
    input_root = tmp_path / "input"
    _build_mixed_input_root(input_root)

    output_root = tmp_path / "output"
    evidence_root = tmp_path / "evidence"

    mock_result = SimpleNamespace(passed=True, outcome="DOCUMENT_TYPE_CERTIFIED")
    call_paths = []

    def mock_cycle(**kwargs):
        call_paths.append(Path(kwargs["draft_path"]))
        return mock_result

    from ops.docsreg.pipelines.run_batch import _run_batch

    with patch("ops.docsreg.pipelines.run_batch.run_docsreg_cycle", mock_cycle):
        _run_batch(
            input_root=input_root,
            output_root=output_root,
            evidence_root=evidence_root,
        )

    # Direct files: procedure.md + notes.txt = 2
    direct_names = {p.name for p in call_paths if p.suffix in {".md", ".txt"}}
    assert "procedure.md" in direct_names
    assert "notes.txt" in direct_names

    # Archive extracted: guide.pdf + spec.docx (from batch1.zip) + manual.rst (from batch2.tar.gz) = 3
    extracted_names = {p.name for p in call_paths}
    assert "guide.pdf" in extracted_names
    assert "spec.docx" in extracted_names
    assert "manual.rst" in extracted_names

    # Total processable calls: 2 direct + 3 extracted = 5
    assert len(call_paths) == 5


def test_unsupported_inside_archives_not_counted_as_registration_failed(tmp_path):
    """Unsupported members (e.g. .xls inside zip) must NOT count as failed registration."""
    input_root = tmp_path / "input"
    input_root.mkdir()

    _make_zip(input_root / "test.zip", {
        "good.pdf": b"%PDF-1.4",
        "bad.xls": b"\xd0\xcf\x11\xe0",
    })

    mock_result = SimpleNamespace(passed=True, outcome="DOCUMENT_TYPE_CERTIFIED")

    from ops.docsreg.pipelines.run_batch import _run_batch

    call_count = [0]

    def mock_cycle(**kwargs):
        call_count[0] += 1
        return mock_result

    with patch("ops.docsreg.pipelines.run_batch.run_docsreg_cycle", mock_cycle):
        _run_batch(
            input_root=input_root,
            output_root=tmp_path / "output",
            evidence_root=tmp_path / "evidence",
        )

    # Only good.pdf should be called
    assert call_count[0] == 1

    # batch_results.jsonl should show 1 registered, 0 failed
    results_path = tmp_path / "output" / "batch_results.jsonl"
    assert results_path.exists()
    rows = [json.loads(l) for l in results_path.read_text().splitlines() if l.strip()]
    failed = [r for r in rows if r["outcome"] == "failed"]
    assert len(failed) == 0


def test_archive_extraction_failures_tracked_separately(tmp_path):
    """Corrupt archives must be tracked separately, not as registration failures."""
    input_root = tmp_path / "input"
    input_root.mkdir()

    # Corrupt archive
    (input_root / "bad.zip").write_bytes(b"not a valid zip")
    # Good direct file
    (input_root / "good.txt").write_text("good content")

    mock_result = SimpleNamespace(passed=True, outcome="DOCUMENT_TYPE_CERTIFIED")

    from ops.docsreg.pipelines.run_batch import _run_batch

    with patch("ops.docsreg.pipelines.run_batch.run_docsreg_cycle", return_value=mock_result):
        _run_batch(
            input_root=input_root,
            output_root=tmp_path / "output",
            evidence_root=tmp_path / "evidence",
        )

    # archive_extraction_results.jsonl must record the failure
    results_path = tmp_path / "output" / "archive_extraction_results.jsonl"
    assert results_path.exists()
    rows = [json.loads(l) for l in results_path.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["status"] in ("corrupt_archive", "rejected_archive_safety_limit")

    # batch_results.jsonl must NOT have a failure for bad.zip (it's an extraction failure, not registration failure)
    batch_path = tmp_path / "output" / "batch_results.jsonl"
    if batch_path.exists():
        batch_rows = [json.loads(l) for l in batch_path.read_text().splitlines() if l.strip()]
        # Only good.txt should appear
        assert all("bad.zip" not in r.get("path", "") for r in batch_rows)


def test_final_manifest_written(tmp_path):
    """source_manifest.json must be written with correct structure."""
    input_root = tmp_path / "input"
    input_root.mkdir()

    _make_zip(input_root / "pack.zip", {
        "doc.md": b"# Doc",
    })
    (input_root / "note.txt").write_text("note")

    mock_result = SimpleNamespace(passed=True, outcome="DOCUMENT_TYPE_CERTIFIED")

    from ops.docsreg.pipelines.run_batch import _run_batch

    with patch("ops.docsreg.pipelines.run_batch.run_docsreg_cycle", return_value=mock_result):
        _run_batch(
            input_root=input_root,
            output_root=tmp_path / "output",
            evidence_root=tmp_path / "evidence",
        )

    manifest_path = tmp_path / "output" / "source_manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text())
    assert "input_root" in manifest
    assert "entries" in manifest
    assert "total_files_found" in manifest

    # Entries must include both direct and archive_member provenance
    provenances = {e["provenance"] for e in manifest["entries"]}
    assert "direct" in provenances
    assert "archive_member" in provenances


def test_archive_files_jsonl_written(tmp_path):
    """archive_files.jsonl must list all discovered archives."""
    input_root = tmp_path / "input"
    input_root.mkdir()

    _make_zip(input_root / "arch1.zip", {"a.txt": b"text"})
    _make_zip(input_root / "arch2.zip", {"b.pdf": b"%PDF"})

    mock_result = SimpleNamespace(passed=True, outcome="DOCUMENT_TYPE_CERTIFIED")

    from ops.docsreg.pipelines.run_batch import _run_batch

    with patch("ops.docsreg.pipelines.run_batch.run_docsreg_cycle", return_value=mock_result):
        _run_batch(
            input_root=input_root,
            output_root=tmp_path / "output",
            evidence_root=tmp_path / "evidence",
        )

    arch_path = tmp_path / "output" / "archive_files.jsonl"
    assert arch_path.exists()
    rows = [json.loads(l) for l in arch_path.read_text().splitlines() if l.strip()]
    assert len(rows) == 2
    archive_names = {Path(r["path"]).name for r in rows}
    assert "arch1.zip" in archive_names
    assert "arch2.zip" in archive_names


def test_extracted_processable_files_jsonl_written(tmp_path):
    """extracted_processable_files.jsonl must list processable files from archives."""
    input_root = tmp_path / "input"
    input_root.mkdir()

    _make_zip(input_root / "docs.zip", {
        "report.pdf": b"%PDF-1.4",
        "junk.tmp": b"temp",
    })

    mock_result = SimpleNamespace(passed=True, outcome="DOCUMENT_TYPE_CERTIFIED")

    from ops.docsreg.pipelines.run_batch import _run_batch

    with patch("ops.docsreg.pipelines.run_batch.run_docsreg_cycle", return_value=mock_result):
        _run_batch(
            input_root=input_root,
            output_root=tmp_path / "output",
            evidence_root=tmp_path / "evidence",
        )

    ep_path = tmp_path / "output" / "extracted_processable_files.jsonl"
    assert ep_path.exists()
    rows = [json.loads(l) for l in ep_path.read_text().splitlines() if l.strip()]
    assert len(rows) == 1
    assert rows[0]["extension"] == ".pdf"
    assert rows[0]["status"] == "queued"


def test_summary_counts_match_reality(tmp_path, capsys):
    """Summary output numbers must be consistent with what was processed."""
    input_root = tmp_path / "input"
    input_root.mkdir()

    # 2 direct processable
    (input_root / "a.md").write_text("# A")
    (input_root / "b.txt").write_text("B")
    # 1 direct unsupported
    (input_root / "c.doc").write_bytes(b"\xd0\xcf\x11\xe0")
    # 1 archive with 1 processable + 1 unsupported
    _make_zip(input_root / "pack.zip", {
        "d.pdf": b"%PDF",
        "e.xls": b"\xd0\xcf",
    })

    mock_result = SimpleNamespace(passed=True, outcome="DOCUMENT_TYPE_CERTIFIED")

    from ops.docsreg.pipelines.run_batch import _run_batch

    with patch("ops.docsreg.pipelines.run_batch.run_docsreg_cycle", return_value=mock_result):
        _run_batch(
            input_root=input_root,
            output_root=tmp_path / "output",
            evidence_root=tmp_path / "evidence",
        )

    captured = capsys.readouterr().out

    assert "Direct processable:         2" in captured
    assert "Archives found:             1" in captured
    assert "Extracted processable:      1" in captured
    assert "Registered:                 3" in captured  # 2 direct + 1 extracted
    assert "Failed registration:        0" in captured
