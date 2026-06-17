"""Regression tests for Axi DOCSREG delegation semantics.

These tests ensure DOCSREG launch text is treated as Omi-owned context and does
not fall through into Axi's docx/standards generation heuristics.
"""
from __future__ import annotations

import ast
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _load_helpers():
    src = Path(__file__).resolve().parents[1] / "axi_bot.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    wanted = {
        "_is_docsreg_launch_text",
        "_is_omi_owned_intent",
        "_wants_docx",
        "_wants_standards_docx_result",
    }

    blocks: list[str] = ["import asyncio\nimport re\n\n"]
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            blocks.append(ast.get_source_segment(src.read_text(encoding="utf-8"), node) or "")
            blocks.append("\n\n")
    globs: dict[str, object] = {}
    exec(compile("".join(blocks), "<axi_docsreg_helpers>", "exec"), globs)  # noqa: S102
    return globs


_helpers = _load_helpers()
_is_docsreg_launch_text = _helpers["_is_docsreg_launch_text"]
_is_omi_owned_intent = _helpers["_is_omi_owned_intent"]
_wants_docx = _helpers["_wants_docx"]
_wants_standards_docx_result = _helpers["_wants_standards_docx_result"]


def test_docsreg_launch_text_is_recognized_as_foreign_intent() -> None:
    assert _is_docsreg_launch_text("/docsreg_start_media /media/axi_omi_sphere/FDF0-25E2/Documents/Standards")
    assert _is_docsreg_launch_text("DOCSREG audit_report /mnt/dgx/project/draft.md teacher")


def test_docsreg_semantics_do_not_trigger_docx_generation() -> None:
    text = "/docsreg_start_media /media/axi_omi_sphere/FDF0-25E2/Documents/Standards"
    assert not _wants_docx(text)
    assert not _wants_standards_docx_result(text)


@pytest.mark.asyncio
async def test_omi_owned_intent_detects_docsreg_semantics(monkeypatch) -> None:
    fake_router = SimpleNamespace(
        OMI_CMDS={"docsreg": "run DOCSREG certification cycle"},
        classify=lambda text, cmd_map, **kwargs: ("docsreg", []) if "docsreg" in (text or "").lower() else None,
    )
    monkeypatch.setitem(sys.modules, "chat_intent_router", fake_router)

    assert await _is_omi_owned_intent("/docsreg_start_media /media/axi_omi_sphere/FDF0-25E2/Documents/Standards")
    assert await _is_omi_owned_intent("DOCSREG audit_report /mnt/dgx/project/draft.md teacher")


def test_regular_docx_requests_still_match() -> None:
    assert _wants_docx("Please generate a Word report from this analysis")
    assert _wants_standards_docx_result("Please update the Word document with the fixes")
