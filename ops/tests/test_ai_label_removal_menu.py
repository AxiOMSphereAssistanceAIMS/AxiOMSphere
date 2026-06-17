from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ailabel_helpers import build_docx
from ops.pipelines.ai_label_removal import telegram_intent_menu as menu
from ops.pipelines.ai_label_removal import telegram_handler as th


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
    def __init__(self, name):
        self.file_id = "fid"
        self.file_name = name


class _FakeChat:
    id = 555


class _FakeUser:
    id = 222


class _FakeMessage:
    def __init__(self, text="", document=None):
        self.text = text
        self.caption = None
        self.document = document
        self.chat = _FakeChat()
        self.from_user = _FakeUser()
        self.sent_texts = []
        self.sent_markups = []
        self.sent_documents = []

    async def reply_text(self, text, reply_markup=None):
        self.sent_texts.append(text)
        self.sent_markups.append(reply_markup)

    async def reply_document(self, document=None, filename=None, caption=None):
        data = document.read() if hasattr(document, "read") else document
        self.sent_documents.append((filename, caption, data))


class _FakeQuery:
    def __init__(self, data, message):
        self.data = data
        self.message = message
        self.answered = False

    async def answer(self):
        self.answered = True


class _FakeUpdate:
    def __init__(self, message=None, callback_query=None):
        self.message = message
        self.callback_query = callback_query


class _FakeCtx:
    def __init__(self, bot=None):
        self.bot = bot


class TestPureHelpers:
    def test_five_options_in_order(self):
        keys = [k for k, _ in menu.INTENT_OPTIONS]
        assert keys == ["docgen", "training_pair", "standard_revision", "docsreg", "ai_cleanup"]

    def test_callback_round_trip(self):
        data = menu.make_callback_data("ai_cleanup", "abcd1234")
        assert menu.parse_callback_data(data) == ("ai_cleanup", "abcd1234")

    def test_callback_rejects_foreign_and_invalid(self):
        assert menu.parse_callback_data("dt_something") is None
        assert menu.parse_callback_data("axi_intent:bogus:tok") is None
        assert menu.parse_callback_data("") is None

    def test_keyboard_rows(self):
        rows = menu.build_keyboard_rows("tok")
        assert len(rows) == 5
        assert all(len(r) == 1 for r in rows)
        # each callback_data parses back to a valid key
        for row in rows:
            label, data = row[0]
            assert menu.parse_callback_data(data)[1] == "tok"

    def test_stash_and_pop(self, tmp_path):
        f = tmp_path / "d.docx"
        f.write_text("x")
        req = menu.stash_pending(chat_id=1, user_id=2, file_path=f, original_filename="d.docx")
        assert menu.pop_pending(req.token).original_filename == "d.docx"
        assert menu.pop_pending(req.token) is None  # popped once


class TestMenuFlow:
    def test_present_menu_downloads_and_shows_five_buttons(self, tmp_path):
        src = build_docx(tmp_path / "r.docx")
        msg = _FakeMessage(text="обработай документ", document=_FakeDoc("r.docx"))
        shown = asyncio.run(th.present_clarification_menu(_FakeUpdate(message=msg), _FakeCtx(_FakeBot(src))))
        assert shown is True
        assert msg.sent_markups[-1] is not None
        kb = msg.sent_markups[-1].inline_keyboard
        assert len(kb) == 5

    def test_ai_cleanup_callback_runs_pipeline_and_sends_file(self, tmp_path):
        src = build_docx(tmp_path / "r.docx")
        # Stash a pending request as if the menu was shown.
        req = menu.stash_pending(
            chat_id=10, user_id=20, file_path=src, original_filename="r.docx"
        )
        msg = _FakeMessage()
        query = _FakeQuery(menu.make_callback_data("ai_cleanup", req.token), msg)
        handled = asyncio.run(th.handle_intent_menu_callback(_FakeUpdate(callback_query=query), _FakeCtx()))
        assert handled is True
        assert query.answered
        assert msg.sent_documents, "cleaned document should be sent"
        filename, caption, data = msg.sent_documents[0]
        assert filename.endswith(".docx") and "✅" in caption

    def test_expired_token_message(self):
        msg = _FakeMessage()
        query = _FakeQuery(menu.make_callback_data("ai_cleanup", "deadbeef"), msg)
        handled = asyncio.run(th.handle_intent_menu_callback(_FakeUpdate(callback_query=query), _FakeCtx()))
        assert handled is True
        assert any("истекло" in t for t in msg.sent_texts)

    def test_foreign_callback_not_handled(self):
        msg = _FakeMessage()
        query = _FakeQuery("dt_approve", msg)
        handled = asyncio.run(th.handle_intent_menu_callback(_FakeUpdate(callback_query=query), _FakeCtx()))
        assert handled is False

    def test_registered_route_is_invoked(self, tmp_path):
        called = {}

        async def fake_route(req, update, ctx):
            called["key"] = req.original_filename

        menu.register_route("docgen", fake_route)
        try:
            f = tmp_path / "z.docx"
            f.write_text("x")
            req = menu.stash_pending(chat_id=1, user_id=2, file_path=f, original_filename="z.docx")
            msg = _FakeMessage()
            query = _FakeQuery(menu.make_callback_data("docgen", req.token), msg)
            asyncio.run(th.handle_intent_menu_callback(_FakeUpdate(callback_query=query), _FakeCtx()))
            assert called.get("key") == "z.docx"
        finally:
            # restore: remove the fake docgen route so other tests aren't affected
            menu._ROUTES.pop("docgen", None)
