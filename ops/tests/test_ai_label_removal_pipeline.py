from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from ailabel_helpers import build_docx, make_encrypted_office
from ops.pipelines.ai_label_removal import (
    AiLabelRemovalContext,
    remove_ai_labels_from_document,
)
from ops.pipelines.ai_label_removal import validators


def _ctx(name, fn):
    return AiLabelRemovalContext(request_id=name, source="test", original_filename=fn)


def test_success_returns_output_and_audit(tmp_path):
    src = build_docx(tmp_path / "r.docx")
    res = remove_ai_labels_from_document(src, tmp_path / "out", _ctx("ok", "r.docx"), audit_root=tmp_path / "a")
    assert res.status == "SUCCESS"
    assert res.output_path and res.output_path.exists()
    assert res.audit_path and res.audit_path.exists()
    manifest = json.loads(res.audit_path.read_text())
    assert manifest["status"] == "SUCCESS"
    assert manifest["input_sha256"] and manifest["output_sha256"]
    assert manifest["file_type"] == "docx"


def test_unsupported_format(tmp_path):
    src = tmp_path / "note.txt"
    src.write_text("just a text file, not an office document")
    res = remove_ai_labels_from_document(src, tmp_path / "out", _ctx("uns", "note.txt"), audit_root=tmp_path / "a")
    assert res.status == "UNSUPPORTED"
    assert res.output_path is None
    assert res.audit_path.exists()


def test_encrypted_office_blocked(tmp_path):
    src = make_encrypted_office(tmp_path / "secret.docx")
    res = remove_ai_labels_from_document(src, tmp_path / "out", _ctx("enc", "secret.docx"), audit_root=tmp_path / "a")
    assert res.status == "BLOCKED"
    assert res.output_path is None


def test_failed_output_integrity_returns_no_output(tmp_path, monkeypatch):
    src = build_docx(tmp_path / "r.docx")
    monkeypatch.setattr(validators, "validate_output_integrity", lambda p, t: (False, "forced failure"))
    res = remove_ai_labels_from_document(src, tmp_path / "out", _ctx("failint", "r.docx"), audit_root=tmp_path / "a")
    assert res.status == "FAILED"
    assert res.output_path is None
    # No leftover cleaned file in output dir.
    assert not list((tmp_path / "out").glob("*_clean.docx"))


def test_visible_content_change_returns_no_output(tmp_path, monkeypatch):
    src = build_docx(tmp_path / "r.docx")
    monkeypatch.setattr(validators, "compare_visible_content", lambda a, b, t: (False, "forced change"))
    res = remove_ai_labels_from_document(src, tmp_path / "out", _ctx("failvis", "r.docx"), audit_root=tmp_path / "a")
    assert res.status == "FAILED"
    assert res.output_path is None
    assert not list((tmp_path / "out").glob("*_clean.docx"))


def test_original_never_modified(tmp_path):
    src = build_docx(tmp_path / "r.docx")
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    remove_ai_labels_from_document(src, tmp_path / "out", _ctx("orig", "r.docx"), audit_root=tmp_path / "a")
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before


def test_audit_written_for_every_status(tmp_path):
    # SUCCESS
    s = build_docx(tmp_path / "a.docx")
    r1 = remove_ai_labels_from_document(s, tmp_path / "o1", _ctx("s1", "a.docx"), audit_root=tmp_path / "audit")
    # UNSUPPORTED
    u = tmp_path / "x.bin"
    u.write_bytes(b"\x00\x01\x02nope")
    r2 = remove_ai_labels_from_document(u, tmp_path / "o2", _ctx("s2", "x.bin"), audit_root=tmp_path / "audit")
    for r in (r1, r2):
        assert r.audit_path.exists()
        assert json.loads(r.audit_path.read_text())["request_id"]
