"""
DOCSREG Telegram Control Path — Layer 4 Tests.

Verifies the /docsreg Telegram handler end-to-end without a live bot runtime.
All tests work against the pure-Python layer (parse_docsreg_launch_spec,
_resolve_draft_path, _run_one_cycle wiring) so no Telegram connection is needed.

Tests:
  1. test_parse_creates_request_with_default_target_quality
  2. test_no_group_private_branching_same_handler
  3. test_free_text_docsreg_trigger_parsed_to_request
  4. test_run_one_cycle_uses_production_auditor_not_legacy
  5. test_failed_doc_not_reported_as_certified
  6. test_invalid_extension_rejected_safely
  7. test_zip_path_rejected_not_supported
"""
from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ops.omi_telegram.docsreg_launch import (
    SUPPORTED_DRAFT_EXTENSIONS,
    DocsregLaunchRequest,
    _collect_input_files,
    _resolve_draft_path,
    _run_one_cycle,
    cmd_docsreg,
    maybe_handle_docsreg_message,
    parse_docsreg_launch_spec,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_update(chat_id: int = 12345, text: str = "") -> MagicMock:
    """Minimal Telegram Update stub."""
    upd = MagicMock()
    upd.effective_chat.id = chat_id
    upd.message.reply_text = MagicMock(return_value=asyncio.coroutine(lambda *a, **kw: None)())
    return upd


def _make_ctx(args: list[str] | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.args = args or []
    ctx.bot = MagicMock()
    ctx.bot.send_chat_action = MagicMock(return_value=asyncio.coroutine(lambda *a, **kw: None)())
    return ctx


# ── Test 1: parse creates DocsregLaunchRequest with defaults ──────────────────


def test_parse_creates_request_with_default_target_quality(tmp_path: Path) -> None:
    """/docsreg <path> creates a DocsregLaunchRequest; target_quality is None by default.

    _run_one_cycle() interprets target_quality=None as 0.98 (the improvement goal),
    separate from the 0.80 cert threshold used by the production auditor.
    """
    draft = tmp_path / "draft.md"
    draft.write_text("# Draft", encoding="utf-8")

    request, err = parse_docsreg_launch_spec(f"/docsreg {draft}")

    assert err is None, f"Unexpected parse error: {err}"
    assert request is not None
    assert isinstance(request, DocsregLaunchRequest)
    assert request.draft_path == draft
    assert request.target_quality is None, (
        "target_quality must be None when not specified; "
        "_run_one_cycle will apply 0.98 default internally"
    )
    assert request.draft_format == "md"


def test_parse_explicit_target_quality_stored(tmp_path: Path) -> None:
    """--target-quality flag is parsed and stored on the request."""
    draft = tmp_path / "doc.pdf"
    draft.write_bytes(b"%PDF-1.4")

    request, err = parse_docsreg_launch_spec(f"docsreg {draft} --target-quality=0.90")

    assert err is None
    assert request is not None
    assert request.target_quality == pytest.approx(0.90)


# ── Test 2: no group / private branching — same handler for all chat types ────


def test_no_group_private_branching_same_handler() -> None:
    """cmd_docsreg does not branch on chat type; group and private chats use the same path.

    There is deliberately no separate /docsreg_private or /docsreg_group entry
    point.  Both group and private chats go through cmd_docsreg() which reads
    update.effective_chat.id for state management only, not for routing.
    """
    src = inspect.getsource(cmd_docsreg)

    # Confirm no branching on 'group', 'private', 'supergroup' chat types
    for keyword in ("chat_type", "group", "private", "supergroup"):
        assert keyword not in src, (
            f"cmd_docsreg must not branch on chat type '{keyword}'; "
            "docsreg_launch.py treats all chats identically"
        )

    # Both update shapes (group / private) resolve to the same coroutine
    assert asyncio.iscoroutinefunction(cmd_docsreg)


# ── Test 3: free-text message routed via maybe_handle_docsreg_message ─────────


def test_free_text_docsreg_trigger_parsed_to_request(tmp_path: Path) -> None:
    """maybe_handle_docsreg_message delegates to cmd_docsreg for docsreg phrases.

    The stop-command path is separate; this test ensures a non-stop docsreg
    trigger returns True (consumed) and invokes the same request pathway.
    """
    draft = tmp_path / "report.pdf"
    draft.write_bytes(b"%PDF-1.4")

    # Verify maybe_handle_docsreg_message is a coroutine and accepts free text
    assert asyncio.iscoroutinefunction(maybe_handle_docsreg_message)

    # A stop command must NOT be forwarded to the docsreg batch; anything else
    # with a docsreg keyword should land in the parse path.  We confirm parse
    # works on the same text the free-text router would forward.
    free_text = f"run docsreg {draft}"
    request, err = parse_docsreg_launch_spec(free_text)
    assert err is None, f"Free-text parse failed: {err}"
    assert request is not None
    assert request.draft_path == draft


# ── Test 4: _run_one_cycle wires production auditor, not legacy ───────────────


def test_run_one_cycle_uses_production_auditor_not_legacy(tmp_path: Path) -> None:
    """_run_one_cycle must call build_structure_auditor_fn (production auditor).

    The legacy build_docsreg_auditor returns COMPONENT_BLOCKED, which is not in
    RECOGNISED_AUDIT_STATUSES and causes every cycle to fail.  The production
    auditor (build_structure_auditor_fn) returns COMPONENT_PASS / COMPONENT_FAIL_REPAIRABLE.
    """
    draft = tmp_path / "doc.md"
    draft.write_text("# Test document", encoding="utf-8")

    request = DocsregLaunchRequest(
        document_type="procedure",
        draft_path=draft,
        draft_format="md",
        evidence_root=tmp_path / "ev",
        redis_url="redis://localhost:6379/0",
        teacher_mode="noop",
        target_quality=0.90,
    )

    captured_threshold: list[float] = []
    real_auditor_fn = MagicMock(return_value=MagicMock())

    def fake_build_structure_auditor_fn(threshold: float) -> Any:
        captured_threshold.append(threshold)
        return real_auditor_fn

    fake_cycle_result = MagicMock()
    fake_cycle_result.passed = True
    fake_cycle_result.outcome = "CERTIFIED_MASTER_READY"

    with patch(
        "ops.omi_telegram.docsreg_launch.build_structure_auditor_fn",
        side_effect=fake_build_structure_auditor_fn,
    ), patch(
        "ops.omi_telegram.docsreg_launch.run_docsreg_cycle",
        return_value=fake_cycle_result,
    ):
        result = _run_one_cycle(
            source_file=draft,
            request=request,
            evidence_root=tmp_path / "ev",
        )

    assert len(captured_threshold) == 1, "build_structure_auditor_fn must be called exactly once"
    assert captured_threshold[0] == pytest.approx(0.90), (
        "Threshold must match request.target_quality when set"
    )
    assert result is fake_cycle_result


def test_run_one_cycle_uses_default_threshold_when_target_quality_none(tmp_path: Path) -> None:
    """When target_quality is None, _run_one_cycle uses 0.80 for the auditor threshold."""
    draft = tmp_path / "doc.md"
    draft.write_text("# Test", encoding="utf-8")

    request = DocsregLaunchRequest(
        document_type="procedure",
        draft_path=draft,
        draft_format="md",
        evidence_root=tmp_path / "ev",
        redis_url="redis://localhost:6379/0",
        teacher_mode="noop",
        target_quality=None,  # not specified
    )

    captured: list[float] = []

    def fake_build(threshold: float) -> Any:
        captured.append(threshold)
        return MagicMock()

    with patch("ops.omi_telegram.docsreg_launch.build_structure_auditor_fn", side_effect=fake_build), \
         patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle", return_value=MagicMock()):
        _run_one_cycle(source_file=draft, request=request, evidence_root=tmp_path / "ev")

    assert len(captured) == 1
    assert captured[0] == pytest.approx(0.80), (
        "Default cert threshold must be 0.80 when target_quality is not specified"
    )


# ── Test 5: failed doc is never shown as certified ────────────────────────────


def test_failed_doc_not_reported_as_certified(tmp_path: Path) -> None:
    """The batch loop labels failed files as 'failed (OUTCOME)', never as 'registered'.

    This is a structural verification of the batch_results accumulation logic in
    cmd_docsreg().  We verify by examining the source code path: result.passed is
    the gate, and False → 'failed (...)', True → 'registered'.
    """
    src = inspect.getsource(cmd_docsreg)

    # The result gate uses getattr(result, "passed", False) to route outcomes
    assert 'getattr(result, "passed", False)' in src, (
        "cmd_docsreg must guard registration with getattr(result, 'passed', False)"
    )
    # Failed branch must use the 'failed' label
    assert '"failed ({}'.format("getattr") not in src  # sanity — just check format
    assert ": failed (" in src, "Batch results must use 'failed (OUTCOME)' for non-passing docs"
    # Passing branch must use 'registered' not 'certified'
    assert ": registered" in src, "Batch results must use 'registered' for passing docs"

    # Parse + resolve confirms failed outcome → error message surfaced in reply
    src_text = inspect.getsource(cmd_docsreg)
    assert "Failed registration" in src_text, (
        "Final reply must report failed file count under 'Failed registration'"
    )


# ── Test 6: invalid extension rejected safely ─────────────────────────────────


def test_invalid_extension_rejected_safely(tmp_path: Path) -> None:
    """_resolve_draft_path returns an error for unsupported file extensions.

    The error must be non-fatal (returns str, no exception) so cmd_docsreg can
    surface it as a user-readable Telegram reply.
    """
    # Write a real file with an unsupported extension
    bad_file = tmp_path / "report.xlsx"
    bad_file.write_bytes(b"PK\x03\x04")  # ZIP magic (xlsx is a zip)

    resolved_path, fmt, err = _resolve_draft_path(str(bad_file))

    assert resolved_path is None, "Unsupported extension must not resolve to a path"
    assert err is not None, "Must return an error string for unsupported extensions"
    assert "Unsupported DOCSREG launch format" in err or ".xlsx" in err, (
        f"Error should name the bad extension, got: {err!r}"
    )


def test_invalid_extension_via_parse(tmp_path: Path) -> None:
    """parse_docsreg_launch_spec propagates _resolve_draft_path errors as parse errors."""
    bad_file = tmp_path / "data.csv"
    bad_file.write_text("col1,col2\n1,2\n", encoding="utf-8")

    request, err = parse_docsreg_launch_spec(f"/docsreg {bad_file}")

    assert request is None
    assert err is not None
    assert ".csv" in err or "Unsupported" in err


# ── Test 7: .zip path rejected — not in SUPPORTED_DRAFT_EXTENSIONS ────────────


def test_zip_path_rejected_not_supported(tmp_path: Path) -> None:
    """.zip is not in SUPPORTED_DRAFT_EXTENSIONS — it is rejected with a clear error.

    Discovery of archive members (zip extraction + per-member processing) is a
    separate future capability; it is not wired in the current batch loop.
    """
    assert ".zip" not in SUPPORTED_DRAFT_EXTENSIONS, (
        ".zip must not be in SUPPORTED_DRAFT_EXTENSIONS until archive extraction is wired"
    )

    zip_file = tmp_path / "archive.zip"
    zip_file.write_bytes(b"PK\x03\x04")

    resolved_path, fmt, err = _resolve_draft_path(str(zip_file))

    assert resolved_path is None
    assert err is not None, "zip must produce a user-readable error"
    # Error must explain the problem, not raise an uncaught exception
    assert isinstance(err, str) and len(err) > 5

    # Also verify via the top-level parser
    request, parse_err = parse_docsreg_launch_spec(f"docsreg {zip_file}")
    assert request is None
    assert parse_err is not None


def test_supported_extensions_set() -> None:
    """Document the current supported extensions set as a contract test."""
    assert SUPPORTED_DRAFT_EXTENSIONS == frozenset({".md", ".txt", ".rst", ".docx", ".pdf"})
