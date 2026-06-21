"""Telegram launch helpers for DOCSREG runs from the Omi bot.

This module keeps the Telegram-facing parsing and execution logic separate
from ``omi_bot.py`` so it can be unit-tested without the full bot runtime.
"""
from __future__ import annotations

import asyncio
import os
import shlex
import secrets
import shutil
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aims_paths import workspace_root
from ops.docsreg import run_docsreg_cycle
from ops.docsreg.docsreg_document_type_registry import load_document_type_registry


SUPPORTED_DRAFT_EXTENSIONS = frozenset({".md", ".txt", ".rst", ".docx", ".pdf"})
DEFAULT_DOCSREG_EVIDENCE_ROOT = Path(
    os.environ.get(
        "DOCSREG_EVIDENCE_ROOT",
        str(workspace_root() / "docsreg_evidence"),
    )
)
DEFAULT_DOCSREG_REDIS_URL = os.environ.get(
    "DOCSREG_REDIS_URL",
    "redis://aims-redis:6379/0",
)
DEFAULT_DOCSREG_TEACHER_MODE = os.environ.get(
    "DOCSREG_TEACHER_MODE",
    "noop",
).strip().lower() or "noop"

# Primary source directory for standards documents — used as fallback draft path
# when no explicit path is given in a /docsreg command.
DEFAULT_DOCSREG_STANDARDS_SOURCE = Path(
    os.environ.get(
        "DOCSREG_STANDARDS_SOURCE",
        "/media/axi_omi_sphere/FDF0-25E2/Documents/Standards",
    )
)


async def _send_chat_action_safe(bot: Any, chat_id: int, action: str) -> None:
    """Best-effort Telegram chat action heartbeat.

    We keep DOCSREG text output minimal, but still signal that the bot is
    actively working so long-running batches do not look dead in chat.
    """
    try:
        sender = getattr(bot, "send_chat_action", None)
        if sender is None:
            return
        await sender(chat_id=chat_id, action=action)
    except Exception:
        return


@dataclass(frozen=True)
class DocsregLaunchRequest:
    """Parsed Telegram request for a DOCSREG run."""

    document_type: str
    draft_path: Path
    draft_format: str
    evidence_root: Path
    redis_url: str
    teacher_mode: str
    target_quality: float | None = None
    max_cycles: int | None = None
    stall_window: int | None = None
    min_quality_delta: float | None = None


def _normalize_teacher_mode(raw: str | None) -> str:
    text = (raw or "").strip().lower()
    if text in {"claude", "claude_code", "teacher", "auditor", "teacher_mode"}:
        return "claude_code"
    return "noop"


def _known_document_type_ids() -> set[str]:
    try:
        return {cfg.id.strip().lower() for cfg in load_document_type_registry()}
    except Exception:
        return set()


def _infer_document_type(tokens: list[str]) -> str:
    known = _known_document_type_ids()
    if not tokens:
        return "procedure"

    aliases = {
        "procedure": {"procedure", "proc", "sop", "standard operating procedure"},
        "work_instruction": {"work_instruction", "work instruction", "instruction"},
        "maintenance_plan": {"maintenance_plan", "maintenance plan", "plan"},
        "inspection_report": {"inspection_report", "inspection report", "inspection"},
        "risk_assessment": {"risk_assessment", "risk assessment", "risk"},
        "technical_specification": {"technical_specification", "technical specification", "specification", "spec"},
        "change_request": {"change_request", "change request", "moc"},
        "audit_report": {"audit_report", "audit report", "audit"},
    }

    token_blob = " ".join(tokens).strip().lower()
    for doc_id, variants in aliases.items():
        if doc_id not in known:
            continue
        for variant in variants:
            pattern = r"\b" + re.escape(variant.lower()) + r"\b"
            if re.search(pattern, token_blob):
                return doc_id

    for token in tokens:
        tok = token.strip().lower()
        if tok in known:
            return tok

    return "procedure"


def _looks_like_path(token: str) -> bool:
    t = (token or "").strip()
    if not t:
        return False
    if t.startswith("~"):
        return True
    if os.sep in t:
        return True
    if "/" in t or "\\" in t:
        return True
    return Path(t).suffix.lower() in SUPPORTED_DRAFT_EXTENSIONS


def _detect_file_format(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def _candidate_alias_paths(raw_path: str) -> list[Path]:
    path = Path(raw_path).expanduser()
    candidates = [path]
    raw = str(path)
    if raw.startswith("/axi_omi_sphere/"):
        candidates.append(Path("/media") / raw.lstrip("/"))
        candidates.append(Path("/home") / raw.lstrip("/"))
    elif raw.startswith("/media/axi_omi_sphere/"):
        candidates.append(Path("/axi_omi_sphere") / raw.split("/media/axi_omi_sphere/", 1)[1])
    elif raw.startswith("/home/axi_omi_sphere/"):
        candidates.append(Path("/media/axi_omi_sphere") / raw.split("/home/axi_omi_sphere/", 1)[1])
    return candidates


def _resolve_draft_path(raw_path: str) -> tuple[Path | None, str | None, str | None]:
    for path in _candidate_alias_paths(raw_path):
        if not path.exists():
            continue

        if path.is_file():
            if path.suffix.lower() not in SUPPORTED_DRAFT_EXTENSIONS:
                return None, None, (
                    f"Unsupported DOCSREG launch format: `{path.suffix.lower()}`. "
                    f"Supported: {', '.join(sorted(SUPPORTED_DRAFT_EXTENSIONS))}"
                )
            return path, _detect_file_format(path), None

        if not path.is_dir():
            return None, None, f"Path is neither a file nor a folder: `{raw_path}`"

        return path, "directory", None

    return None, None, f"File or folder not found: `{raw_path}`"


def parse_docsreg_launch_spec(text: str) -> tuple[DocsregLaunchRequest | None, str | None]:
    """Parse free-form Telegram text into a DOCSREG launch request.

    Returns ``(request, error_message)``.  On success ``error_message`` is ``None``.
    The parser accepts flexible phrases such as:

    - ``run DOCSREG /dgx/path/draft.md``
    - ``docsreg audit_report /dgx/path/doc.docx teacher``
    - ``/docsreg --teacher-mode=claude_code /dgx/path/draft.txt``
    """
    raw = (text or "").strip()
    if not raw:
        return None, "Empty DOCSREG request."

    try:
        tokens = shlex.split(raw)
    except ValueError:
        tokens = raw.split()

    cleaned: list[str] = []
    teacher_mode = DEFAULT_DOCSREG_TEACHER_MODE
    evidence_root = DEFAULT_DOCSREG_EVIDENCE_ROOT
    redis_url = DEFAULT_DOCSREG_REDIS_URL
    target_quality: float | None = None
    max_cycles: int | None = None
    stall_window: int | None = None
    min_quality_delta: float | None = None
    explicit_doc_type: str | None = None

    i = 0
    while i < len(tokens):
        tok = tokens[i].strip()
        low = tok.lower()
        next_tok = tokens[i + 1].strip() if i + 1 < len(tokens) else ""

        if low.lstrip("/") in {"docsreg", "docreg", "docsreg_start_media",
                               "gocsreg_start_media", "run", "start", "launch"} \
                or low.rstrip(",") in {"omi", "бот", "bot"}:
            i += 1
            continue
        if low in {"teacher", "auditor", "claude", "claude_code"}:
            teacher_mode = _normalize_teacher_mode(low)
            i += 1
            continue
        if low.startswith("--teacher-mode="):
            teacher_mode = _normalize_teacher_mode(tok.split("=", 1)[1])
            i += 1
            continue
        if low == "--teacher-mode" and next_tok:
            teacher_mode = _normalize_teacher_mode(next_tok)
            i += 2
            continue
        if low.startswith("--evidence-root="):
            evidence_root = Path(tok.split("=", 1)[1]).expanduser()
            i += 1
            continue
        if low == "--evidence-root" and next_tok:
            evidence_root = Path(next_tok).expanduser()
            i += 2
            continue
        if low.startswith("--redis-url="):
            redis_url = tok.split("=", 1)[1]
            i += 1
            continue
        if low == "--redis-url" and next_tok:
            redis_url = next_tok
            i += 2
            continue
        if low.startswith("--target-quality="):
            try:
                target_quality = float(tok.split("=", 1)[1])
            except ValueError:
                return None, f"Invalid target_quality: `{tok}`"
            i += 1
            continue
        if low == "--target-quality" and next_tok:
            try:
                target_quality = float(next_tok)
            except ValueError:
                return None, f"Invalid target_quality: `{next_tok}`"
            i += 2
            continue
        if low.startswith("--max-cycles="):
            try:
                max_cycles = int(tok.split("=", 1)[1])
            except ValueError:
                return None, f"Invalid max_cycles: `{tok}`"
            i += 1
            continue
        if low == "--max-cycles" and next_tok:
            try:
                max_cycles = int(next_tok)
            except ValueError:
                return None, f"Invalid max_cycles: `{next_tok}`"
            i += 2
            continue
        if low.startswith("--stall-window="):
            try:
                stall_window = int(tok.split("=", 1)[1])
            except ValueError:
                return None, f"Invalid stall_window: `{tok}`"
            i += 1
            continue
        if low == "--stall-window" and next_tok:
            try:
                stall_window = int(next_tok)
            except ValueError:
                return None, f"Invalid stall_window: `{next_tok}`"
            i += 2
            continue
        if low.startswith("--min-quality-delta="):
            try:
                min_quality_delta = float(tok.split("=", 1)[1])
            except ValueError:
                return None, f"Invalid min_quality_delta: `{tok}`"
            i += 1
            continue
        if low == "--min-quality-delta" and next_tok:
            try:
                min_quality_delta = float(next_tok)
            except ValueError:
                return None, f"Invalid min_quality_delta: `{next_tok}`"
            i += 2
            continue
        if low.startswith("--document-type=") or low.startswith("--doc-type=") or low.startswith("type="):
            explicit_doc_type = tok.split("=", 1)[1]
            i += 1
            continue
        if low in {"--document-type", "--doc-type"} and next_tok:
            explicit_doc_type = next_tok
            i += 2
            continue

        cleaned.append(tok)
        i += 1

    if not cleaned:
        # No path given — use the configured Standards source directory.
        if DEFAULT_DOCSREG_STANDARDS_SOURCE.exists():
            cleaned = [str(DEFAULT_DOCSREG_STANDARDS_SOURCE)]
        else:
            return None, (
                f"Provide a draft file or folder path, or mount the Standards drive at "
                f"`{DEFAULT_DOCSREG_STANDARDS_SOURCE}`."
            )

    path_tokens = [tok for tok in cleaned if _looks_like_path(tok)]
    if not path_tokens and cleaned:
        path_tokens = [cleaned[-1]]

    raw_path = " ".join(path_tokens).strip()
    draft_path, draft_format, err = _resolve_draft_path(raw_path)
    if err:
        return None, err
    assert draft_path is not None
    assert draft_format is not None

    doc_type_tokens = [tok for tok in cleaned if tok not in path_tokens]
    doc_type = explicit_doc_type or _infer_document_type(doc_type_tokens or cleaned[:2])

    request = DocsregLaunchRequest(
        document_type=doc_type,
        draft_path=draft_path,
        draft_format=draft_format,
        evidence_root=evidence_root,
        redis_url=redis_url,
        teacher_mode=teacher_mode,
        target_quality=target_quality,
        max_cycles=max_cycles,
        stall_window=stall_window,
        min_quality_delta=min_quality_delta,
    )
    return request, None


def _format_launch_prompt() -> str:
    return (
        "Provide a draft file or folder path on DGX. "
        "Example: `/docsreg /mnt/dgx/project/draft.docx` "
        "or `DOCSREG audit_report /mnt/dgx/project/draft.md teacher`."
    )


def _collect_input_files(source_path: Path) -> list[Path]:
    if source_path.is_file():
        return [source_path]
    if not source_path.is_dir():
        return []
    return sorted(
        [p for p in source_path.rglob("*") if p.is_file()],
        key=lambda p: str(p.relative_to(source_path)).lower(),
    )


def _relative_artifact_path(source_root: Path, source_file: Path) -> Path:
    try:
        return source_file.relative_to(source_root)
    except ValueError:
        return Path(source_file.name)


def _copy_for_review(source_file: Path, source_root: Path, review_dir: Path) -> None:
    rel_path = _relative_artifact_path(source_root, source_file)
    target = review_dir / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source_file, target)
    except Exception:
        pass


def _run_one_cycle(
    *,
    source_file: Path,
    request: DocsregLaunchRequest,
    evidence_root: Path,
) -> Any:
    return run_docsreg_cycle(
        document_type=request.document_type,
        draft_path=source_file,
        evidence_root=evidence_root,
        redis_url=request.redis_url,
        teacher_mode=request.teacher_mode,  # type: ignore[arg-type]
        target_quality=request.target_quality if request.target_quality is not None else 0.98,
        max_cycles=request.max_cycles if request.max_cycles is not None else 7,
        stall_window=request.stall_window if request.stall_window is not None else 3,
        min_quality_delta=request.min_quality_delta if request.min_quality_delta is not None else 0.005,
    )


async def _typing_heartbeat(bot: Any, chat_id: int, stop_event: asyncio.Event) -> None:
    """Send 'typing' action every 4 seconds while a long task is running.

    This keeps the Telegram UI showing "typing..." and, more importantly,
    gives the asyncio event loop regular wake-ups so APScheduler jobs
    (heartbeat, task-registry polling) are not starved.
    """
    while not stop_event.is_set():
        await _send_chat_action_safe(bot, chat_id, "typing")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=4.0)
        except asyncio.TimeoutError:
            pass


async def cmd_docsreg(update: Any, ctx: Any) -> bool:
    """Telegram command handler for DOCSREG launches."""
    if update.effective_chat is None or update.message is None:
        return False

    request_id = secrets.token_hex(6)
    text = " ".join(getattr(ctx, "args", []) or []).strip()
    if not text:
        await update.message.reply_text(_format_launch_prompt(), parse_mode="Markdown")
        return True

    request, err = parse_docsreg_launch_spec(text)
    if err:
        await update.message.reply_text(f"❌ DOCSREG: {err}\n\n{_format_launch_prompt()}", parse_mode="Markdown")
        return True
    assert request is not None

    loop = asyncio.get_running_loop()

    inputs = _collect_input_files(request.draft_path)
    if not inputs:
        session_root = request.evidence_root / request_id
        review_dir = session_root / "for_checking"
        review_dir.mkdir(parents=True, exist_ok=True)
        await update.message.reply_text(
            "Task accepted.\n"
            "Processed 0 files.\n"
            "Registered 0 files.\n"
            f"Failed registration 0 files.\n"
            f"Files for review: `{review_dir}`",
            parse_mode="Markdown",
        )
        return True

    session_root = request.evidence_root / request_id
    review_dir = session_root / "for_checking"
    review_dir.mkdir(parents=True, exist_ok=True)

    total = len(inputs)
    await update.message.reply_text(
        f"Task accepted — {total} file(s) queued for processing.",
        parse_mode="Markdown",
    )

    chat_id = update.effective_chat.id
    processed = 0
    registered = 0
    failed = 0
    batch_results: list[str] = []

    for idx, source_file in enumerate(inputs, start=1):
        # Yield to event loop so APScheduler / heartbeat jobs can run
        await asyncio.sleep(0)

        processed += 1
        rel_path = _relative_artifact_path(request.draft_path, source_file)
        ext = source_file.suffix.lower()
        if source_file.is_dir() or (source_file.is_file() and ext not in SUPPORTED_DRAFT_EXTENSIONS):
            failed += 1
            _copy_for_review(source_file, request.draft_path, review_dir)
            batch_results.append(f"- `{rel_path}`: failed (unsupported format)")
            continue

        # Per-file progress message
        await _send_chat_action_safe(ctx.bot, chat_id, "typing")
        await update.message.reply_text(
            f"[{idx}/{total}] Processing `{rel_path}`...",
            parse_mode="Markdown",
        )

        file_evidence_root = session_root / rel_path.parent / f"{idx:03d}_{source_file.stem}"

        # Start a typing heartbeat so the event loop stays responsive
        stop_typing = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            _typing_heartbeat(ctx.bot, chat_id, stop_typing)
        )

        try:
            result = await loop.run_in_executor(
                None,
                lambda sf=source_file, fr=file_evidence_root: _run_one_cycle(
                    source_file=sf,
                    request=request,
                    evidence_root=fr,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            failed += 1
            _copy_for_review(source_file, request.draft_path, review_dir)
            batch_results.append(f"- `{rel_path}`: failed ({type(exc).__name__})")
            continue
        finally:
            stop_typing.set()
            await heartbeat_task

        if getattr(result, "passed", False):
            registered += 1
            batch_results.append(f"- `{rel_path}`: registered")
        else:
            failed += 1
            _copy_for_review(source_file, request.draft_path, review_dir)
            batch_results.append(f"- `{rel_path}`: failed ({getattr(result, 'outcome', 'FAILED')})")

    review_note = f"\nFiles for review: `{review_dir}`" if failed else ""
    await update.message.reply_text(
        f"Batch complete.\n"
        f"Processed {processed} files.\n"
        f"Registered {registered} files.\n"
        f"Failed registration {failed} files.{review_note}",
        parse_mode="Markdown",
    )
    return True


async def maybe_handle_docsreg_message(update: Any, ctx: Any, text: str) -> bool:
    """Handle a free-text DOCSREG launch request from the live chat."""
    low = (text or "").lower()
    if "docsreg" not in low and "start_media" not in low:
        return False
    ctx.args = [text]
    return await cmd_docsreg(update, ctx)
