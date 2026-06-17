"""Regression tests for Axi AI-label-removal routing.

These tests ensure AI-label-removal requests are captured before generic
document-intake logic can claim the upload.
"""
from __future__ import annotations

import ast
import time
from pathlib import Path


def _load_helpers():
    src = Path(__file__).resolve().parents[1] / "axi_bot.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    wanted = {
        "_should_route_ai_label_removal_text",
        "_should_route_ai_label_removal_upload",
    }

    blocks: list[str] = ["import time\n\n"]
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            blocks.append(ast.get_source_segment(src.read_text(encoding="utf-8"), node) or "")
            blocks.append("\n\n")
    globs: dict[str, object] = {
        "_PENDING_AI_LABEL_REMOVAL": {},
        "_AXI_DIALOG": {},
        "_recent_ai_label_removal_context": lambda *args, **kwargs: False,
    }
    exec(compile("".join(blocks), "<axi_ai_label_removal_helpers>", "exec"), globs)  # noqa: S102
    return globs


_helpers = _load_helpers()
_should_route_ai_label_removal_text = _helpers["_should_route_ai_label_removal_text"]
_should_route_ai_label_removal_upload = _helpers["_should_route_ai_label_removal_upload"]


class _Msg:
    def __init__(self, text: str | None = None, caption: str | None = None):
        self.text = text
        self.caption = caption


def test_text_intent_is_detected() -> None:
    assert _should_route_ai_label_removal_text("remove AI labels from this document", 123)
    assert _should_route_ai_label_removal_text("удали метки ИИ", 123)


def test_upload_caption_intent_is_detected() -> None:
    _helpers["_PENDING_AI_LABEL_REMOVAL"].clear()
    msg = _Msg(caption="remove AI labels from this document")
    assert _should_route_ai_label_removal_upload(msg, 123)


def test_upload_pending_context_is_detected() -> None:
    _helpers["_PENDING_AI_LABEL_REMOVAL"].clear()
    _helpers["_PENDING_AI_LABEL_REMOVAL"][123] = {"prompt": "remove AI labels", "ts": time.time()}
    msg = _Msg()
    assert _should_route_ai_label_removal_upload(msg, 123)


def test_upload_irrelevant_message_is_not_routed() -> None:
    _helpers["_PENDING_AI_LABEL_REMOVAL"].clear()
    msg = _Msg(text="please summarize this report")
    assert not _should_route_ai_label_removal_upload(msg, 123)
