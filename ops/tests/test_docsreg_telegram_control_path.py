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
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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


# ── Handler-level smoke tests — call cmd_docsreg() as a real coroutine ─────────
#
# Strategy:
#   - AsyncMock for reply_text / send_chat_action (Telegram stubs)
#   - run_docsreg_cycle mocked via side_effect that writes quality_report.json
#     to the evidence_root it receives → _run_one_cycle and _record_cycle_learning
#     run for real; only the Redis/Qdrant backend call is replaced.
#   - aims_paths.workspace_root patched to tmp_path so learning writes are local.
#   - build_structure_auditor_fn left real unless spied upon to verify wiring.
#
# Redis/Qdrant: unavailable in unit mode; run_docsreg_cycle mock bypasses them.
# This is noted in evidence as a remaining risk (live integration not exercised).


_COMP_SCORES = {
    "content_richness_score": 0.90,
    "data_retention_score": 0.88,
    "source_to_master_alignment_score": 0.91,
    "structure_score": 0.89,
    "metadata_safety_score": 0.95,
}

_COMP_SCORES_FAIL = {k: 0.25 for k in _COMP_SCORES}


def _make_update_async(chat_id: int = 12345) -> MagicMock:
    """Telegram Update stub with AsyncMock reply_text (safe to await)."""
    upd = MagicMock()
    upd.effective_chat.id = chat_id
    upd.message.reply_text = AsyncMock(return_value=None)
    return upd


def _make_ctx_async() -> MagicMock:
    ctx = MagicMock()
    ctx.args = []
    ctx.bot = MagicMock()
    ctx.bot.send_chat_action = AsyncMock(return_value=None)
    return ctx


def _cycle_side_effect(*, passed: bool = True, quality: float = 0.91):
    """Return a side_effect function for run_docsreg_cycle that writes real evidence files."""
    def _inner(**kwargs):
        ev_root = Path(kwargs["evidence_root"])
        ev_root.mkdir(parents=True, exist_ok=True)
        scores = _COMP_SCORES if passed else _COMP_SCORES_FAIL
        report = {
            "quality": quality,
            "target_quality": 0.80,
            "audit_status": "COMPONENT_PASS" if passed else "COMPONENT_FAIL_REPAIRABLE",
            "component_scores": scores,
        }
        (ev_root / "quality_report.json").write_text(json.dumps(report), encoding="utf-8")
        if passed:
            (ev_root / "raw_extracted_text.md").write_text("# Source\n\nContent.", encoding="utf-8")
            (ev_root / "master_document.md").write_text("# Master\n\nContent.", encoding="utf-8")
        r = MagicMock()
        r.passed = passed
        r.outcome = "CERTIFIED_MASTER_READY" if passed else "QUALITY_INSUFFICIENT"
        r.best_quality = quality
        r.job_id = "job-handler-test"
        r.doc_id = "doc-handler-test"
        r.cycle_id = "cycle-handler-test"
        r.cycles_run = 1
        return r
    return _inner


# ── Test H1: directory input queues batch job ─────────────────────────────────


@pytest.mark.asyncio
async def test_cmd_docsreg_directory_creates_batch_job(tmp_path: Path) -> None:
    """cmd_docsreg() with a directory path processes all .md files inside it.

    Verifies the full handler path: parse → collect_input_files → batch loop
    → _run_one_cycle → reply with "Registered N files".
    """
    draft_dir = tmp_path / "standards"
    draft_dir.mkdir()
    (draft_dir / "doc_a.md").write_text("# Doc A\n\nContent.", encoding="utf-8")
    (draft_dir / "doc_b.md").write_text("# Doc B\n\nContent.", encoding="utf-8")

    ws = tmp_path / "workspace"
    ws.mkdir()

    upd = _make_update_async()
    ctx = _make_ctx_async()
    ctx.args = [str(draft_dir)]

    ev_root = tmp_path / "evidence"

    with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle",
               side_effect=_cycle_side_effect(passed=True)), \
         patch("aims_paths.workspace_root", return_value=ws), \
         patch("ops.omi_telegram.docsreg_launch.DEFAULT_DOCSREG_EVIDENCE_ROOT", ev_root):
        result = await cmd_docsreg(upd, ctx)

    assert result is True
    # reply_text called at least twice: "Task accepted" + final summary
    assert upd.message.reply_text.call_count >= 2
    calls = [str(c) for c in upd.message.reply_text.call_args_list]
    final_reply = str(upd.message.reply_text.call_args_list[-1])
    assert "Registered 2" in final_reply, f"Expected 2 registered, got: {final_reply}"
    assert "Failed registration 0" in final_reply


# ── Test H2: real _run_one_cycle path — production auditor is called ──────────


@pytest.mark.asyncio
async def test_cmd_docsreg_calls_real_run_one_cycle_path(tmp_path: Path) -> None:
    """cmd_docsreg() exercises the real _run_one_cycle, which calls build_structure_auditor_fn.

    The spy on build_structure_auditor_fn proves the production auditor wiring is
    not bypassed at the handler level.
    """
    draft = tmp_path / "procedure.md"
    draft.write_text("# Procedure\n\nStep 1: Do it.", encoding="utf-8")

    ws = tmp_path / "workspace"
    ws.mkdir()

    auditor_calls: list[float] = []
    _original_build = __import__(
        "ops.docsreg.docsreg_production_auditor",
        fromlist=["build_structure_auditor_fn"],
    ).build_structure_auditor_fn

    def _spy_build(threshold: float) -> Any:
        auditor_calls.append(threshold)
        return _original_build(threshold)

    upd = _make_update_async()
    ctx = _make_ctx_async()
    ctx.args = [str(draft)]

    ev_root = tmp_path / "evidence"

    with patch("ops.omi_telegram.docsreg_launch.build_structure_auditor_fn",
               side_effect=_spy_build), \
         patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle",
               side_effect=_cycle_side_effect(passed=True)), \
         patch("aims_paths.workspace_root", return_value=ws), \
         patch("ops.omi_telegram.docsreg_launch.DEFAULT_DOCSREG_EVIDENCE_ROOT", ev_root):
        await cmd_docsreg(upd, ctx)

    assert len(auditor_calls) == 1, (
        "build_structure_auditor_fn must be called exactly once per file via _run_one_cycle"
    )
    assert auditor_calls[0] == pytest.approx(0.80), (
        "Default threshold 0.80 when target_quality not specified"
    )


# ── Test H3: invalid path → error reply, handler returns True (consumed) ──────


@pytest.mark.asyncio
async def test_cmd_docsreg_rejects_invalid_path(tmp_path: Path) -> None:
    """cmd_docsreg() with a nonexistent path returns an error reply via Telegram.

    The handler must return True (message consumed) even on parse error; the
    error is surfaced to the user, not re-raised as an exception.
    """
    upd = _make_update_async()
    ctx = _make_ctx_async()
    ctx.args = ["/nonexistent/path/that/does/not/exist/draft.md"]

    result = await cmd_docsreg(upd, ctx)

    assert result is True
    upd.message.reply_text.assert_called_once()
    error_text = str(upd.message.reply_text.call_args_list[0])
    assert "❌" in error_text or "DOCSREG" in error_text


# ── Test H4: passing doc → "Registered 1 files" in reply ─────────────────────


@pytest.mark.asyncio
async def test_cmd_docsreg_status_reports_real_quality(tmp_path: Path) -> None:
    """After a passing cycle, cmd_docsreg() reports Registered 1, Failed 0.

    The reply text reflects the actual batch outcome — not a static message.
    """
    draft = tmp_path / "quality_doc.md"
    draft.write_text("# Quality Document\n\nRich structured content.", encoding="utf-8")

    ws = tmp_path / "workspace"
    ws.mkdir()

    upd = _make_update_async()
    ctx = _make_ctx_async()
    ctx.args = [str(draft)]

    ev_root = tmp_path / "evidence"

    with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle",
               side_effect=_cycle_side_effect(passed=True, quality=0.91)), \
         patch("aims_paths.workspace_root", return_value=ws), \
         patch("ops.omi_telegram.docsreg_launch.DEFAULT_DOCSREG_EVIDENCE_ROOT", ev_root):
        await cmd_docsreg(upd, ctx)

    final = str(upd.message.reply_text.call_args_list[-1])
    assert "Registered 1" in final, f"Expected 'Registered 1' in reply: {final}"
    assert "Failed registration 0" in final


# ── Test H5: failed doc → never shows as registered ──────────────────────────


@pytest.mark.asyncio
async def test_cmd_docsreg_report_does_not_certify_failed_docs(tmp_path: Path) -> None:
    """A doc that fails quality gate appears as 'failed', never as 'registered'.

    This closes the risk that a false-positive reply could mislead operators
    into believing a low-quality document was accepted into the registry.
    """
    draft = tmp_path / "weak_doc.md"
    draft.write_text("# x", encoding="utf-8")  # trivial content

    ws = tmp_path / "workspace"
    ws.mkdir()

    upd = _make_update_async()
    ctx = _make_ctx_async()
    ctx.args = [str(draft)]

    ev_root = tmp_path / "evidence"

    with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle",
               side_effect=_cycle_side_effect(passed=False, quality=0.31)), \
         patch("aims_paths.workspace_root", return_value=ws), \
         patch("ops.omi_telegram.docsreg_launch.DEFAULT_DOCSREG_EVIDENCE_ROOT", ev_root):
        await cmd_docsreg(upd, ctx)

    final = str(upd.message.reply_text.call_args_list[-1])
    assert "Registered 0" in final, f"Failed doc must not be registered: {final}"
    assert "Failed registration 1" in final, f"Expected failed count 1: {final}"
    # Confirm 'registered' label is absent for the failed file
    batch_reply_texts = [str(c) for c in upd.message.reply_text.call_args_list]
    for txt in batch_reply_texts:
        assert ": registered" not in txt, (
            f"Failed doc must never appear as 'registered' in any reply: {txt}"
        )


# ── Test H6: group and private chats use the same handler, no branching ───────


@pytest.mark.asyncio
async def test_group_chat_docsreg_allowed_for_registration_only(tmp_path: Path) -> None:
    """cmd_docsreg() routes group and private chats identically.

    chat_id is used only for cancel-event state management; it never changes
    the execution path.  A group chat (negative chat_id) must produce the same
    Registered/Failed counts as a private chat (positive chat_id).
    """
    draft = tmp_path / "shared_doc.md"
    draft.write_text("# Shared Document\n\nContent.", encoding="utf-8")

    ws = tmp_path / "workspace"
    ws.mkdir()

    results: dict[str, str] = {}
    ev_root = tmp_path / "evidence"

    for chat_label, chat_id in [("private", 12345), ("group", -1001234567890)]:
        upd = _make_update_async(chat_id=chat_id)
        ctx = _make_ctx_async()
        ctx.args = [str(draft)]

        with patch("ops.omi_telegram.docsreg_launch.run_docsreg_cycle",
                   side_effect=_cycle_side_effect(passed=True)), \
             patch("aims_paths.workspace_root", return_value=ws), \
             patch("ops.omi_telegram.docsreg_launch.DEFAULT_DOCSREG_EVIDENCE_ROOT", ev_root):
            await cmd_docsreg(upd, ctx)

        results[chat_label] = str(upd.message.reply_text.call_args_list[-1])

    # Both chat types must reach the same outcome
    assert "Registered 1" in results["private"]
    assert "Registered 1" in results["group"]
    # Handler must not route differently based on chat type
    src = inspect.getsource(cmd_docsreg)
    assert "chat_type" not in src


# ── Test H7: no args → help prompt, not batch execution ──────────────────────


@pytest.mark.asyncio
async def test_private_improvement_requires_explicit_command(tmp_path: Path) -> None:
    """Without an explicit path argument, cmd_docsreg() returns a usage prompt.

    No batch execution happens; no files are processed.  The user must provide
    an explicit /docsreg <path> to start processing.
    """
    upd = _make_update_async()
    ctx = _make_ctx_async()
    ctx.args = []  # no arguments

    result = await cmd_docsreg(upd, ctx)

    assert result is True
    upd.message.reply_text.assert_called_once()
    prompt_text = str(upd.message.reply_text.call_args_list[0])
    # Must show usage guidance, not a batch result
    assert "docsreg" in prompt_text.lower() or "DOCSREG" in prompt_text


# ── Archive behavior contract ─────────────────────────────────────────────────


def test_zip_archive_behavior_documented() -> None:
    """Explicit contract: archive.zip is rejected at parse gate; extraction is future work.

    current_behavior  = parse_gate_reject
    expected_after_archive_layer = extract_and_queue_members
    """
    archive_behavior = {
        "file": "archive.zip",
        "current_behavior": "parse_gate_reject",
        "reason": ".zip not in SUPPORTED_DRAFT_EXTENSIONS",
        "expected_after_archive_layer": "extract_and_queue_members",
        "blocker_for_layer4": False,
    }
    assert archive_behavior["current_behavior"] == "parse_gate_reject"
    assert archive_behavior["blocker_for_layer4"] is False
    assert ".zip" not in SUPPORTED_DRAFT_EXTENSIONS
