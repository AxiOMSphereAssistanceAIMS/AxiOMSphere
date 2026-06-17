from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace


def _load_cmd():
    src = Path(__file__).resolve().parents[1] / "axi_bot.py"
    text = src.read_text(encoding="utf-8")
    tree = ast.parse(text)

    blocks: list[str] = ["import time\n\n"]
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "cmd_aimarks_delete":
            blocks.append(ast.get_source_segment(text, node) or "")
            blocks.append("\n\n")

    globs: dict[str, object] = {
        "_chat_allowed": lambda update: True,
        "_seed_ai_label_removal_pending": lambda chat_id, prompt: None,
    }
    exec(compile("".join(blocks), "<axi_cmd_aimarks_delete>", "exec"), globs)  # noqa: S102
    return globs["cmd_aimarks_delete"]


cmd_aimarks_delete = _load_cmd()


class _FakeDoc:
    file_id = "fid"
    file_name = "r.docx"


class _FakeChat:
    id = 123


class _FakeMessage:
    def __init__(self, text="/aimarks_delete", document=None):
        self.text = text
        self.caption = None
        self.document = document
        self.chat = _FakeChat()
        self.sent_texts = []

    async def reply_text(self, text, reply_markup=None):
        self.sent_texts.append(text)


class _FakeUpdate:
    def __init__(self, message):
        self.message = message
        self.effective_chat = _FakeChat()


class _FakeCtx:
    pass


def test_aimarks_delete_seeds_pending_when_no_document(monkeypatch):
    captured = {}
    cmd_aimarks_delete.__globals__["_seed_ai_label_removal_pending"] = lambda chat_id, prompt: captured.update(chat_id=chat_id, prompt=prompt)

    msg = _FakeMessage("/aimarks_delete")
    asyncio.run(cmd_aimarks_delete(_FakeUpdate(msg), _FakeCtx()))

    assert captured["chat_id"] == 123
    assert captured["prompt"] == "/aimarks_delete"
    assert msg.sent_texts and "Прикрепите документ" in msg.sent_texts[0]


def test_aimarks_delete_uses_pipeline_when_document_present(monkeypatch):
    captured = {}

    async def fake_handle(update, ctx):
        captured["called"] = True
        return True

    monkeypatch.setitem(
        sys.modules,
        "ops.pipelines.ai_label_removal.telegram_handler",
        SimpleNamespace(handle_ai_label_removal=fake_handle),
    )
    cmd_aimarks_delete.__globals__["_seed_ai_label_removal_pending"] = lambda chat_id, prompt: captured.update(chat_id=chat_id, prompt=prompt)

    msg = _FakeMessage("/aimarks_delete", document=_FakeDoc())
    asyncio.run(cmd_aimarks_delete(_FakeUpdate(msg), _FakeCtx()))

    assert captured["called"] is True
    assert captured["chat_id"] == 123
