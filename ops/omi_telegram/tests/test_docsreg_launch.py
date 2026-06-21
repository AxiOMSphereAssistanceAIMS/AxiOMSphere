from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ops.chat_intent_router import OMI_CMDS, _keyword_classify
import ops.omi_telegram.docsreg_launch as docsreg_launch
from ops.omi_telegram.docsreg_launch import (
    cmd_docsreg,
    maybe_handle_docsreg_message,
    parse_docsreg_launch_spec,
)


class _FakeMessage:
    def __init__(self) -> None:
        self.replies: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **kwargs):
        self.replies.append((text, kwargs))
        return SimpleNamespace()


class _FakeUpdate:
    def __init__(self) -> None:
        self.effective_chat = SimpleNamespace(id=12345)
        self.message = _FakeMessage()


class _FakeContext:
    def __init__(self, args: list[str] | None = None) -> None:
        self.args = args or []


@pytest.fixture(autouse=True)
def _patch_docsreg_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(
        docsreg_launch,
        "DEFAULT_DOCSREG_EVIDENCE_ROOT",
        tmp_path / "docsreg_evidence",
        raising=False,
    )
    monkeypatch.setattr(
        docsreg_launch,
        "DEFAULT_DOCSREG_REDIS_URL",
        "redis://localhost:6379/0",
        raising=False,
    )
    monkeypatch.setattr(
        docsreg_launch,
        "DEFAULT_DOCSREG_TEACHER_MODE",
        "noop",
        raising=False,
    )


def _make_docx(path: Path, text: str = "Draft body") -> Path:
    from docx import Document

    doc = Document()
    doc.add_paragraph(text)
    doc.save(path)
    return path


def test_parse_docsreg_launch_spec_detects_format_first(tmp_path):
    draft = _make_docx(tmp_path / "draft.docx", "DOCSREG draft")

    request, err = parse_docsreg_launch_spec(f"run DOCSREG {draft}")

    assert err is None
    assert request is not None
    assert request.draft_path == draft
    assert request.draft_format == "docx"
    assert request.document_type == "procedure"


def test_parse_docsreg_launch_spec_accepts_explicit_teacher_and_type(tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text("# Draft", encoding="utf-8")

    request, err = parse_docsreg_launch_spec(f"DOCSREG audit_report {draft} teacher")

    assert err is None
    assert request is not None
    assert request.document_type == "audit_report"
    assert request.draft_path == draft
    assert request.draft_format == "md"
    assert request.teacher_mode == "claude_code"


def test_parse_docsreg_launch_spec_accepts_pdf(tmp_path):
    draft = tmp_path / "draft.pdf"
    draft.write_bytes(b"%PDF-1.4\n%%EOF\n")

    request, err = parse_docsreg_launch_spec(f"DOCSREG {draft}")

    assert err is None
    assert request is not None
    assert request.draft_path == draft
    assert request.draft_format == "pdf"


def test_docsreg_keyword_fallback_routes_command():
    routed = _keyword_classify("запусти DOCSREG /mnt/dgx/project/draft.md", OMI_CMDS)
    assert routed is not None
    assert routed[0] == "docsreg"


def test_parse_docsreg_slash_command_prefix_stripped(tmp_path):
    """Regression: 'Omi, /docsreg <path>' must not treat /docsreg as a path token.

    Root cause: parse_docsreg_launch_spec() skipped 'docsreg' but not '/docsreg'
    (with leading slash). _looks_like_path('/docsreg') returned True (has '/'),
    so the command token became a path_token and was joined with the real path,
    producing '/docsreg /media/...' → file not found.
    """
    std_root = tmp_path / "Standards"
    std_root.mkdir()
    (std_root / "doc.md").write_text("# Standard", encoding="utf-8")

    # Text-handler form: full message text including the command token
    request, err = parse_docsreg_launch_spec(f"Omi, /docsreg {std_root}")

    assert err is None, f"Parser error: {err}"
    assert request is not None
    assert request.draft_path == std_root


def test_parse_docsreg_slash_command_without_path_uses_default(tmp_path, monkeypatch):
    """'/docsreg' alone (no path) must fall back to DEFAULT_DOCSREG_STANDARDS_SOURCE."""
    import ops.omi_telegram.docsreg_launch as _m

    default_src = tmp_path / "DefaultStandards"
    default_src.mkdir()
    (default_src / "a.md").write_text("# A", encoding="utf-8")
    monkeypatch.setattr(_m, "DEFAULT_DOCSREG_STANDARDS_SOURCE", default_src)

    request, err = parse_docsreg_launch_spec("/docsreg")

    assert err is None, f"Parser error: {err}"
    assert request is not None
    assert request.draft_path == default_src


def test_parse_docsreg_slash_command_variants_stripped(tmp_path):
    """All command name variants with leading slash must be silently ignored."""
    std_root = tmp_path / "Stds"
    std_root.mkdir()

    for cmd in ("/docsreg", "/docsreg_start_media", "/gocsreg_start_media"):
        request, err = parse_docsreg_launch_spec(f"{cmd} {std_root}")
        assert err is None, f"Failed for {cmd!r}: {err}"
        assert request is not None and request.draft_path == std_root, (
            f"Wrong draft_path for {cmd!r}: {request}"
        )


def test_parse_docsreg_omi_greeting_stripped(tmp_path):
    """'Omi,' prefix must be stripped so it doesn't pollute the token list."""
    std_root = tmp_path / "Stds2"
    std_root.mkdir()

    request, err = parse_docsreg_launch_spec(f"Omi, /docsreg {std_root}")

    assert err is None, f"Parser error: {err}"
    assert request is not None
    assert request.draft_path == std_root


@pytest.mark.asyncio
async def test_cmd_docsreg_success_reports_result(tmp_path):
    draft = tmp_path / "draft.txt"
    draft.write_text("Draft body", encoding="utf-8")

    fake_result = SimpleNamespace(
        passed=True,
        document_type="procedure",
        cycles_run=1,
        best_quality=0.9557,
        evidence_root=str(tmp_path / "evidence"),
        outcome="DOCUMENT_TYPE_CERTIFIED",
        notes="",
    )

    update = _FakeUpdate()
    ctx = _FakeContext([str(draft)])

    with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle", return_value=fake_result):
        handled = await cmd_docsreg(update, ctx)

    assert handled is True
    assert any("task accepted" in text.lower() for text, _ in update.message.replies)
    assert any("processed 1 files" in text.lower() for text, _ in update.message.replies)


@pytest.mark.asyncio
async def test_maybe_handle_docsreg_message_routes_free_text(tmp_path):
    draft = tmp_path / "draft.txt"
    draft.write_text("Draft body", encoding="utf-8")

    fake_result = SimpleNamespace(
        passed=False,
        document_type="procedure",
        cycles_run=2,
        best_quality=0.62,
        evidence_root=str(tmp_path / "evidence"),
        outcome="DOCUMENT_TYPE_STALLED",
        notes="stalled",
    )

    update = _FakeUpdate()
    ctx = _FakeContext()

    with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle", return_value=fake_result):
        handled = await maybe_handle_docsreg_message(update, ctx, f"Omi, start DOCSREG {draft}")

    assert handled is True
    assert any("failed registration 1 files" in text.lower() for text, _ in update.message.replies)


@pytest.mark.asyncio
async def test_cmd_docsreg_directory_batch_stats(tmp_path):
    source_dir = tmp_path / "batch"
    source_dir.mkdir()
    (source_dir / "draft_a.md").write_text("# A", encoding="utf-8")
    (source_dir / "image.bin").write_bytes(b"\x00\x01")

    fake_result = SimpleNamespace(
        passed=True,
        document_type="procedure",
        cycles_run=1,
        best_quality=0.9557,
        evidence_root=str(tmp_path / "evidence"),
        outcome="DOCUMENT_TYPE_CERTIFIED",
        notes="",
    )

    update = _FakeUpdate()
    ctx = _FakeContext([str(source_dir)])

    with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle", return_value=fake_result):
        handled = await cmd_docsreg(update, ctx)

    assert handled is True
    final_reply = update.message.replies[-1][0]
    assert "processed 2 files" in final_reply.lower()
    assert "registered 1 files" in final_reply.lower()
    assert "failed registration 1 files" in final_reply.lower()


@pytest.mark.asyncio
async def test_cmd_docsreg_directory_walks_subfolders(tmp_path):
    source_dir = tmp_path / "batch"
    nested = source_dir / "sub" / "nested"
    nested.mkdir(parents=True)
    (source_dir / "draft_a.md").write_text("# A", encoding="utf-8")
    (nested / "draft_b.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
    (nested / "image.bin").write_bytes(b"\x00\x01")

    fake_result = SimpleNamespace(
        passed=True,
        document_type="procedure",
        cycles_run=1,
        best_quality=0.9557,
        evidence_root=str(tmp_path / "evidence"),
        outcome="DOCUMENT_TYPE_CERTIFIED",
        notes="",
    )

    update = _FakeUpdate()
    ctx = _FakeContext([str(source_dir)])

    with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle", return_value=fake_result):
        handled = await cmd_docsreg(update, ctx)

    assert handled is True
    final_reply = update.message.replies[-1][0]
    assert "processed 3 files" in final_reply.lower()
    assert "registered 2 files" in final_reply.lower()
    assert "failed registration 1 files" in final_reply.lower()
    review_dir_line = final_reply.split("Files for review: `", 1)[1].split("`", 1)[0]
    review_dir = Path(review_dir_line)
    assert (review_dir / "sub" / "nested" / "image.bin").exists()
