from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ailabel_helpers import build_docx
from ops.pipelines.ai_label_removal.telegram_handler import (
    build_user_message,
    detect_ai_label_removal_intent,
    handle_ai_label_removal,
    run_request,
)
from ops.pipelines.ai_label_removal.pipeline import AiLabelRemovalResult


def test_run_request_success(tmp_path):
    src = build_docx(tmp_path / "r.docx")
    res = run_request(
        src, tmp_path / "out", chat_id=123, user_id=456,
        original_filename="r.docx", request_id="rr1", audit_root=tmp_path / "a",
    )
    assert res.status == "SUCCESS"
    assert res.output_path.exists()


def test_build_user_message_variants():
    base = dict(input_path=Path("x"), output_path=None, file_type="docx")
    assert "✅" in build_user_message(AiLabelRemovalResult(status="SUCCESS", **base))
    assert "⚠️" in build_user_message(AiLabelRemovalResult(status="UNSUPPORTED", **base))
    assert "⛔" in build_user_message(AiLabelRemovalResult(status="BLOCKED", **base))
    msg = build_user_message(AiLabelRemovalResult(status="FAILED", error_message="boom", **base))
    assert "❌" in msg and "boom" in msg


# --- Fakes for the async handler ---

class _FakeFile:
    def __init__(self, src: Path):
        self._src = src

    async def download_to_drive(self, dest: str):
        Path(dest).write_bytes(self._src.read_bytes())


class _FakeBot:
    def __init__(self, src: Path):
        self._src = src

    async def get_file(self, file_id):
        return _FakeFile(self._src)


class _FakeDoc:
    def __init__(self, file_name):
        self.file_id = "fid"
        self.file_name = file_name


class _FakeChat:
    id = 999


class _FakeUser:
    id = 777


class _FakeMessage:
    def __init__(self, text, document=None):
        self.text = text
        self.caption = None
        self.document = document
        self.chat = _FakeChat()
        self.from_user = _FakeUser()
        self.sent_documents = []
        self.sent_texts = []

    async def reply_document(self, document=None, filename=None, caption=None):
        data = document.read() if hasattr(document, "read") else document
        self.sent_documents.append((filename, caption, data))

    async def reply_text(self, text):
        self.sent_texts.append(text)


class _FakeUpdate:
    def __init__(self, message):
        self.message = message


class _FakeCtx:
    def __init__(self, bot):
        self.bot = bot


def test_handler_ignores_non_intent_message():
    msg = _FakeMessage("just a normal message")
    handled = asyncio.run(handle_ai_label_removal(_FakeUpdate(msg), _FakeCtx(_FakeBot(Path()))))
    assert handled is False


def test_handler_asks_for_file_when_missing():
    msg = _FakeMessage("удали метки ИИ", document=None)
    handled = asyncio.run(handle_ai_label_removal(_FakeUpdate(msg), _FakeCtx(_FakeBot(Path()))))
    assert handled is True
    assert msg.sent_texts and "Прикрепите" in msg.sent_texts[0]


def test_handler_cleans_and_sends_document(tmp_path):
    src = build_docx(tmp_path / "r.docx")
    msg = _FakeMessage("remove AI labels", document=_FakeDoc("r.docx"))
    handled = asyncio.run(handle_ai_label_removal(_FakeUpdate(msg), _FakeCtx(_FakeBot(src))))
    assert handled is True
    assert msg.sent_documents, "expected a cleaned document to be sent"
    filename, caption, data = msg.sent_documents[0]
    assert filename.endswith(".docx")
    assert "✅" in caption
    assert data and len(data) > 0


def test_handler_sends_error_for_unsupported(tmp_path):
    bad = tmp_path / "note.txt"
    bad.write_text("not an office file")
    msg = _FakeMessage("очисти AI metadata", document=_FakeDoc("note.txt"))
    handled = asyncio.run(handle_ai_label_removal(_FakeUpdate(msg), _FakeCtx(_FakeBot(bad))))
    assert handled is True
    assert msg.sent_texts and "⚠️" in msg.sent_texts[0]
