"""Telegram launch helpers for DOCSREG runs from the Omi bot.

This module keeps the Telegram-facing parsing and execution logic separate
from ``omi_bot.py`` so it can be unit-tested without the full bot runtime.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import shlex
import secrets
import shutil
import re
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("docsreg_launch")

from aims_paths import workspace_root
from ops.docsreg.docsreg_attempt_capture import new_attempt_id, write_attempt_event
from ops.docsreg import DocsregCycleRunResult, run_docsreg_cycle
from ops.docsreg.docsreg_batch_semantics import classify_docsreg_attempt
from ops.docsreg.docsreg_document_type_registry import load_document_type_registry
from ops.docsreg.docsreg_production_auditor import build_structure_auditor_fn
from ops.docsreg.extraction.markitdown_adapter import MARKITDOWN_SUPPORTED_SUFFIXES


def _normalize_docsreg_teacher_mode(raw: str | None) -> str:
    text = (raw or "").strip().lower()
    if text in {"claude", "claude_code", "teacher", "auditor", "teacher_mode", "training", "teacher_training"}:
        return "claude_code"
    return "noop"


SUPPORTED_DRAFT_EXTENSIONS = frozenset({".rst", *MARKITDOWN_SUPPORTED_SUFFIXES})
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
    "claude_code",
)
DEFAULT_DOCSREG_TEACHER_MODE = _normalize_docsreg_teacher_mode(DEFAULT_DOCSREG_TEACHER_MODE)
DEFAULT_DOCSREG_EXTRACTOR_BACKEND = os.environ.get(
    "DOCSREG_EXTRACTOR_BACKEND",
    "markitdown",
).strip().lower() or "markitdown"
DEFAULT_DOCSREG_RUNTIME_MODE = os.environ.get(
    "DOCSREG_RUNTIME_MODE",
    "compose_network",
).strip().lower() or "compose_network"

_REPO_ROOT = workspace_root()

def _default_docsreg_compose_launcher() -> Path:
    env_launcher = os.environ.get("DOCSREG_COMPOSE_LAUNCHER", "").strip()
    if env_launcher:
        return Path(env_launcher)
    for candidate in (
        Path("/ops/scripts/run_docsreg_in_compose.sh"),
        Path("/workspace/ops/scripts/run_docsreg_in_compose.sh"),
        Path(__file__).resolve().parent.parent / "scripts" / "run_docsreg_in_compose.sh",
    ):
        if candidate.exists():
            return candidate
    return Path("/ops/scripts/run_docsreg_in_compose.sh")


DEFAULT_DOCSREG_COMPOSE_LAUNCHER = _default_docsreg_compose_launcher()
DEFAULT_DOCSREG_COMPOSE_DATA_ROOT = Path(
    os.environ.get("DOCSREG_COMPOSE_DATA_ROOT", "/data")
)

# Primary source directory for standards documents — used as fallback draft path
# when no explicit path is given in a /docsreg command.
DEFAULT_DOCSREG_STANDARDS_SOURCE = Path(
    os.environ.get(
        "DOCSREG_STANDARDS_SOURCE",
        "/media/axi_omi_sphere/FDF0-25E2/Documents/Standards",
    )
)


# Per-chat cancel events for running batches.  Key: Telegram chat_id.
_ACTIVE_BATCHES: dict[int, asyncio.Event] = {}

_STOP_TOKENS: frozenset[str] = frozenset({
    "stop", "стоп", "cancel", "отмена", "halt",
    "stop report", "стоп репорт", "прекрати", "стоп отчёт",
})


def _is_stop_command(text: str) -> bool:
    """Return True if *text* is a cancel/stop command for an active batch."""
    low = text.strip().lower()
    # Strip optional bot greeting prefix
    for prefix in ("omi,", "omi", "бот,", "бот"):
        if low.startswith(prefix):
            low = low[len(prefix):].strip()
            break
    return low in _STOP_TOKENS or any(low.startswith(t + " ") for t in _STOP_TOKENS)


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
    auto_repair_after_audit: bool = False
    auto_repair_dispatch_mode: str | None = None
    repair_training_memory_dir: Path | None = None


def _normalize_teacher_mode(raw: str | None) -> str:
    return _normalize_docsreg_teacher_mode(raw)


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
    auto_repair_after_audit = True
    auto_repair_dispatch_mode: str | None = None
    repair_training_memory_dir: Path | None = None

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
        if low in {"--auto-repair", "--auto-repair-after-audit"}:
            auto_repair_after_audit = True
            i += 1
            continue
        if low in {"--no-auto-repair", "--no-auto-repair-after-audit"}:
            auto_repair_after_audit = False
            i += 1
            continue
        if low.startswith("--auto-repair-dispatch-mode="):
            auto_repair_dispatch_mode = tok.split("=", 1)[1]
            i += 1
            continue
        if low == "--auto-repair-dispatch-mode" and next_tok:
            auto_repair_dispatch_mode = next_tok
            i += 2
            continue
        if low.startswith("--repair-training-memory-dir="):
            repair_training_memory_dir = Path(tok.split("=", 1)[1]).expanduser()
            i += 1
            continue
        if low == "--repair-training-memory-dir" and next_tok:
            repair_training_memory_dir = Path(next_tok).expanduser()
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
        auto_repair_after_audit=auto_repair_after_audit,
        auto_repair_dispatch_mode=auto_repair_dispatch_mode,
        repair_training_memory_dir=repair_training_memory_dir,
    )
    return request, None


def _format_launch_prompt() -> str:
    return (
        "Provide a draft file or folder path on DGX. "
        "Example: `/docsreg /mnt/dgx/project/draft.docx` "
        "or `DOCSREG audit_report /mnt/dgx/project/draft.md teacher`."
    )


def _load_certified_sources() -> frozenset[str]:
    """Return absolute source paths already certified in standards_index.

    Used to skip files that were successfully registered in a previous run.
    We only trust the certification marker when the registry also contains a
    real master/document entry for that source.  This avoids false skips when
    standards_index has a stale certified row but the master registry row was
    never written or was written to a different registry DB.
    """
    import sqlite3

    db_path = os.environ.get("OMI_DB_PATH", "data/aims_registry.db")
    try:
        con = sqlite3.connect(db_path)
        standards = con.execute(
            "SELECT source FROM standards_index WHERE status IN ('certified','active','approved')"
        ).fetchall()
        master_rows = con.execute(
            """
            SELECT file_path, stored_path, source_filename, file_name, source
            FROM documents
            WHERE
                lower(COALESCE(file_path, '')) LIKE '%/master/%'
                OR lower(COALESCE(stored_path, '')) LIKE '%/master/%'
                OR lower(COALESCE(source, '')) = 'docgen_bundle'
                OR COALESCE(master_doc_json, '') <> ''
            """
        ).fetchall()
        con.close()
        master_basenames = {
            Path(str(row[0] or "")).name
            for row in master_rows
            if str(row[0] or "").strip()
        } | {
            Path(str(row[1] or "")).name
            for row in master_rows
            if str(row[1] or "").strip()
        } | {
            str(row[2] or "").strip()
            for row in master_rows
            if str(row[2] or "").strip()
        } | {
            str(row[3] or "").strip()
            for row in master_rows
            if str(row[3] or "").strip()
        }
        certified: set[str] = set()
        for row in standards:
            source = str(row[0] or "").strip()
            if not source:
                continue
            src_name = Path(source).name
            if source in {str(Path(r[0] or "").resolve()) for r in master_rows if r[0]}:
                certified.add(str(Path(source).resolve()))
                continue
            if src_name in master_basenames:
                certified.add(str(Path(source).resolve()))
        return frozenset(certified)
    except Exception:
        return frozenset()


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


def _record_cycle_learning(
    result: Any,
    source_file: Path,
    evidence_root: Path,
    workspace_dir: Path | None = None,
) -> None:
    """Wrapper around record_knowledge_source() for completed DOCSREG cycles.

    Delegates all learning artifact writes to the canonical Knowledge Source
    Layer.  Non-fatal: any exception is caught and logged so registration is
    never blocked.
    """
    from ops.docsreg.docsreg_learning_capture import record_attempted_cycle_learning

    record_attempted_cycle_learning(
        result=result,
        source_file=source_file,
        evidence_root=evidence_root,
        workspace_dir=workspace_dir,
    )


def _docsreg_runtime_mode() -> str:
    mode = os.environ.get("DOCSREG_RUNTIME_MODE", DEFAULT_DOCSREG_RUNTIME_MODE)
    normalized = (mode or "").strip().lower()
    if normalized in {"compose", "compose_network", "compose-network"}:
        return "compose_network"
    if normalized in {"inproc", "local", "host"}:
        return "inproc"
    return DEFAULT_DOCSREG_RUNTIME_MODE


def _compose_launcher_path() -> Path:
    return Path(
        os.environ.get(
            "DOCSREG_COMPOSE_LAUNCHER",
            str(DEFAULT_DOCSREG_COMPOSE_LAUNCHER),
        )
    )


def _host_visible_path(container_path: Path) -> Path:
    """Map a container-visible workspace path to the host-visible path, if known."""
    host_workspace = Path(
        os.environ.get(
            "AIMS_WORKSPACE_HOST",
            "/home/axi_omi_sphere/aims-workspace/aims_workspace",
        )
    )
    container_workspace = Path(
        os.environ.get("AIMS_WORKSPACE", str(workspace_root()))
    )
    try:
        rel = Path(container_path).resolve().relative_to(container_workspace.resolve())
    except Exception:
        return Path(container_path)
    return host_workspace / rel


def _run_one_cycle_inproc(
    *,
    source_file: Path,
    request: DocsregLaunchRequest,
    evidence_root: Path,
) -> Any:
    # Use the production auditor so the batch path gets real COMPONENT_PASS /
    # COMPONENT_FAIL_REPAIRABLE statuses — the legacy build_docsreg_auditor
    # returns COMPONENT_BLOCKED which is not recognised by the gate and causes
    # every cycle to fail with the 0.60 quality floor.
    # Default threshold 0.80: lenient enough that well-formed docs can certify on
    # first cycle without a full evidence package; target_quality (0.98 cycle goal)
    # is a separate concept used to drive multi-cycle improvement.
    auditor_fn = build_structure_auditor_fn(
        threshold=request.target_quality if request.target_quality is not None else 0.80,
    )
    os.environ.setdefault("DOCSREG_EXTRACTOR_BACKEND", DEFAULT_DOCSREG_EXTRACTOR_BACKEND)
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
        auto_repair_after_audit=request.auto_repair_after_audit,
        auto_repair_dispatch_mode=request.auto_repair_dispatch_mode,
        repair_training_memory_dir=request.repair_training_memory_dir,
        auditor_fn=auditor_fn,
    )


def _run_one_cycle_via_compose(
    *,
    source_file: Path,
    request: DocsregLaunchRequest,
    evidence_root: Path,
) -> Any:
    launcher = _compose_launcher_path()
    if not launcher.exists():
        available = ""
        try:
            available = subprocess.run(
                ["docker", "compose", "config", "--services"],
                cwd=str(workspace_root()),
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip()
        except Exception:
            available = ""
        raise RuntimeError(
            f"DOCSREG compose launcher not found: {launcher}. "
            f"Available services: {available or 'unknown'}"
        )

    result_json = evidence_root / "docsreg_cycle_result.json"
    container_evidence_root = Path(
        os.environ.get("DOCSREG_COMPOSE_EVIDENCE_CONTAINER_ROOT", "/workspace-evidence")
    )
    container_result_json = container_evidence_root / "docsreg_cycle_result.json"
    payload = {
        "document_type": request.document_type,
        "source_path": str(source_file),
        "evidence_root": str(container_evidence_root),
        "redis_url": request.redis_url,
        "teacher_mode": request.teacher_mode,
        "target_quality": request.target_quality if request.target_quality is not None else 0.98,
        "max_cycles": request.max_cycles if request.max_cycles is not None else 7,
        "stall_window": request.stall_window if request.stall_window is not None else 3,
        "min_quality_delta": request.min_quality_delta if request.min_quality_delta is not None else 0.005,
        "auto_repair_after_audit": request.auto_repair_after_audit,
        "auto_repair_dispatch_mode": request.auto_repair_dispatch_mode,
        "repair_training_memory_dir": str(request.repair_training_memory_dir) if request.repair_training_memory_dir else "",
    }
    compose_script = r"""
import json
import os
import sys
from pathlib import Path

os.environ["DOCSREG_RUNTIME_MODE"] = "inproc"

payload = json.loads(sys.argv[1])
source_file = Path(sys.argv[2])
result_json = Path(sys.argv[3])
evidence_root = Path(payload["evidence_root"])

from ops.omi_telegram.docsreg_launch import DocsregLaunchRequest, _run_one_cycle

request = DocsregLaunchRequest(
    document_type=payload["document_type"],
    draft_path=Path(payload["source_path"]),
    draft_format=Path(payload["source_path"]).suffix.lower().lstrip(".") or "unknown",
    evidence_root=Path(payload["evidence_root"]),
    redis_url=payload["redis_url"],
    teacher_mode=payload["teacher_mode"],
    target_quality=payload["target_quality"],
    max_cycles=payload["max_cycles"],
    stall_window=payload["stall_window"],
    min_quality_delta=payload["min_quality_delta"],
    auto_repair_after_audit=bool(payload.get("auto_repair_after_audit", False)),
    auto_repair_dispatch_mode=payload.get("auto_repair_dispatch_mode") or None,
    repair_training_memory_dir=Path(payload["repair_training_memory_dir"]) if payload.get("repair_training_memory_dir") else None,
)
result = _run_one_cycle(
    source_file=source_file,
    request=request,
    evidence_root=evidence_root,
)
result_json.write_text(
    json.dumps(
        {
            "document_type": result.document_type,
            "draft_path": result.draft_path,
            "evidence_root": result.evidence_root,
            "outcome": result.outcome,
            "passed": result.passed,
            "cycles_run": result.cycles_run,
            "best_quality": result.best_quality,
            "notes": result.notes,
            "teacher_mode": result.teacher_mode,
            "run_id": getattr(result, "run_id", ""),
        },
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
    """
    prev_host_root = os.environ.get("DOCSREG_COMPOSE_EVIDENCE_HOST_ROOT")
    prev_container_root = os.environ.get("DOCSREG_COMPOSE_EVIDENCE_CONTAINER_ROOT")
    os.environ["DOCSREG_COMPOSE_EVIDENCE_HOST_ROOT"] = str(_host_visible_path(evidence_root))
    os.environ["DOCSREG_COMPOSE_EVIDENCE_CONTAINER_ROOT"] = str(container_evidence_root)
    try:
        proc = subprocess.run(
            [
                str(launcher),
                "python",
                "-c",
                compose_script,
                json.dumps(payload, ensure_ascii=False),
                str(source_file),
                str(container_result_json),
            ],
            cwd=str(_REPO_ROOT),
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        if prev_host_root is None:
            os.environ.pop("DOCSREG_COMPOSE_EVIDENCE_HOST_ROOT", None)
        else:
            os.environ["DOCSREG_COMPOSE_EVIDENCE_HOST_ROOT"] = prev_host_root
        if prev_container_root is None:
            os.environ.pop("DOCSREG_COMPOSE_EVIDENCE_CONTAINER_ROOT", None)
        else:
            os.environ["DOCSREG_COMPOSE_EVIDENCE_CONTAINER_ROOT"] = prev_container_root
    if proc.returncode != 0:
        raise RuntimeError(
            "DOCSREG compose cycle failed "
            f"(rc={proc.returncode}). stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    if not result_json.exists():
        raise RuntimeError(
            "DOCSREG compose cycle completed but did not write result JSON: "
            f"{result_json}. stdout={proc.stdout!r} stderr={proc.stderr!r}"
        )
    payload_out = json.loads(result_json.read_text(encoding="utf-8"))
    return DocsregCycleRunResult(**payload_out)


def _run_one_cycle(
    *,
    source_file: Path,
    request: DocsregLaunchRequest,
    evidence_root: Path,
) -> Any:
    runtime_mode = _docsreg_runtime_mode()
    if runtime_mode == "inproc":
        return _run_one_cycle_inproc(
            source_file=source_file,
            request=request,
            evidence_root=evidence_root,
        )
    if runtime_mode == "compose_network":
        return _run_one_cycle_via_compose(
            source_file=source_file,
            request=request,
            evidence_root=evidence_root,
        )
    raise RuntimeError(
        f"Unsupported DOCSREG_RUNTIME_MODE={runtime_mode!r}; use inproc or compose_network"
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


def _docsreg_auto_repair_default_for_update(update: Any) -> bool:
    """Return the default auto-repair policy for a Telegram update.

    Private chats start the cyclic improvement path. Group chats keep the
    single-run path unless the operator explicitly overrides it with flags.
    """
    try:
        chat = getattr(update, "effective_chat", None)
        chat_kind = (getattr(chat, "type", "") or "").lower()
        return chat_kind == "private"
    except Exception:
        return False


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
    request = replace(
        request,
        auto_repair_after_audit=_docsreg_auto_repair_default_for_update(update),
    )

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
    cancel_event = asyncio.Event()
    _ACTIVE_BATCHES[chat_id] = cancel_event

    processed = 0
    certified = 0
    registered = 0
    advisory = 0
    pending_needs_repair = 0
    failed = 0
    parse_rejected = 0
    unsupported = 0
    skipped = 0
    latest_quality: float | None = None
    latest_cycles_run: int | None = None
    best_quality_seen: float = 0.0
    repair_attempted = 0
    repair_applied = 0
    latest_repair_status = ""
    latest_repair_stop_reason = ""
    latest_repair_result_path = ""
    latest_repair_escalation_path = ""
    latest_repair_training_pair_path = ""
    latest_repair_lesson_path = ""
    latest_repair_skill_proposal_path = ""
    batch_results: list[str] = []

    certified_sources = _load_certified_sources()

    try:
        for idx, source_file in enumerate(inputs, start=1):
            # Yield to event loop so APScheduler / heartbeat jobs and incoming
            # "stop" messages can be processed between files.
            await asyncio.sleep(0)

            if cancel_event.is_set():
                break

            if str(source_file.resolve()) in certified_sources:
                skipped += 1
                continue

            processed += 1
            rel_path = _relative_artifact_path(request.draft_path, source_file)
            ext = source_file.suffix.lower()
            if source_file.is_dir() or (source_file.is_file() and ext not in SUPPORTED_DRAFT_EXTENSIONS):
                unsupported += 1
                _copy_for_review(source_file, request.draft_path, review_dir)
                batch_results.append(f"- `{rel_path}`: unsupported format")
                continue

            bot = getattr(ctx, "bot", None)
            await _send_chat_action_safe(bot, chat_id, "typing")

            file_evidence_root = session_root / rel_path.parent / f"{idx:03d}_{source_file.stem}"
            attempt_id = new_attempt_id("docsreg")
            source_sha = None
            try:
                from ops.docsreg.docsreg_knowledge_source import compute_file_sha256
                source_sha = compute_file_sha256(source_file)
            except Exception:
                pass
            write_attempt_event(
                attempt_id=attempt_id,
                stage="request_received",
                status="started",
                event_type="telegram_docsreg_request",
                message="Telegram DOCSREG request accepted.",
                source_path=str(source_file),
                source_sha256=source_sha,
                evidence_root=file_evidence_root,
                runtime={"entrypoint": "telegram", "runtime_mode": _docsreg_runtime_mode()},
            )
            write_attempt_event(
                attempt_id=attempt_id,
                stage="source_resolved",
                status="succeeded",
                event_type="source_resolved",
                message="Telegram DOCSREG source resolved.",
                source_path=str(source_file),
                source_sha256=source_sha,
                evidence_root=file_evidence_root,
            )
            write_attempt_event(
                attempt_id=attempt_id,
                stage="extraction",
                status="started",
                event_type="cycle_started",
                message="Telegram DOCSREG cycle started.",
                source_path=str(source_file),
                source_sha256=source_sha,
                evidence_root=file_evidence_root,
            )

            # Start a typing heartbeat so the event loop stays responsive
            stop_typing = asyncio.Event()
            heartbeat_task = asyncio.create_task(
                _typing_heartbeat(bot, chat_id, stop_typing)
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
                write_attempt_event(
                    attempt_id=attempt_id,
                    stage="extraction",
                    status="failed",
                    event_type="cycle_failed",
                    message="Telegram DOCSREG cycle failed before completion.",
                    source_path=str(source_file),
                    source_sha256=source_sha,
                    evidence_root=file_evidence_root,
                    error=exc,
                )
                write_attempt_event(
                    attempt_id=attempt_id,
                    stage="terminal",
                    status="failed",
                    event_type="terminal_failed",
                    message="Telegram DOCSREG attempt terminated with failure.",
                    source_path=str(source_file),
                    source_sha256=source_sha,
                    evidence_root=file_evidence_root,
                    error=exc,
                )
                continue
            finally:
                stop_typing.set()
                await heartbeat_task

            # Record learning data regardless of pass/fail — agents write their own data.
            try:
                _record_cycle_learning(
                    result,
                    source_file,
                    file_evidence_root,
                    workspace_dir=Path("aims_workspace"),
                )
            except Exception as _lerr:
                log.warning("docsreg_learning: record_cycle_learning raised: %s", _lerr)

            passed = getattr(result, "passed", False)
            classification = classify_docsreg_attempt(
                source_file=source_file,
                evidence_root=file_evidence_root,
                result=result,
            )
            cycle_quality = float(classification.get("quality", 0.0) or 0.0)
            cycles_run = int(getattr(result, "cycles_run", 0) or 0)
            best_quality = float(getattr(result, "best_quality", cycle_quality) or cycle_quality)
            latest_quality = cycle_quality
            latest_cycles_run = cycles_run
            best_quality_seen = max(best_quality_seen, best_quality, cycle_quality)
            if getattr(result, "repair_attempted", False):
                repair_attempted += 1
            if getattr(result, "repair_applied", False):
                repair_applied += 1
            latest_repair_status = str(getattr(result, "repair_status", "") or "")
            latest_repair_stop_reason = str(getattr(result, "repair_stop_reason", "") or "")
            latest_repair_result_path = str(getattr(result, "repair_result_path", "") or "")
            latest_repair_escalation_path = str(getattr(result, "repair_escalation_path", "") or "")
            latest_repair_training_pair_path = str(getattr(result, "repair_training_pair_path", "") or "")
            latest_repair_lesson_path = str(getattr(result, "repair_lesson_path", "") or "")
            latest_repair_skill_proposal_path = str(getattr(result, "repair_skill_proposal_path", "") or "")
            category = classification["category"]
            write_attempt_event(
                attempt_id=attempt_id,
                stage="quality_gate",
                status="succeeded" if classification.get("quality_report_found") else "blocked",
                event_type="quality_gate_evaluated",
                message=f"Telegram DOCSREG classified as {category}.",
                source_path=str(source_file),
                source_sha256=source_sha,
                evidence_root=file_evidence_root,
                artifacts={
                    "quality_report_found": classification.get("quality_report_found"),
                    "quality_report_path": classification.get("quality_report_path"),
                    "category": category,
                },
            )
            if category == "certified":
                certified += 1
                registered += 1
                # legacy label retained for source compatibility: : registered
                batch_results.append(
                    f"- `{rel_path}`: certified quality={cycle_quality:.4f} "
                    f"cycles={cycles_run} best={best_quality:.4f}"
                )
            elif category == "advisory":
                advisory += 1
                if classification.get("registered_to_db"):
                    registered += 1
                batch_results.append(
                    f"- `{rel_path}`: advisory quality={cycle_quality:.4f} "
                    f"cycles={cycles_run} best={best_quality:.4f}"
                )
            elif category == "pending_needs_repair":
                pending_needs_repair += 1
                if classification.get("registered_to_db"):
                    registered += 1
                _copy_for_review(source_file, request.draft_path, review_dir)
                batch_results.append(
                    f"- `{rel_path}`: pending / needs repair quality={cycle_quality:.4f} "
                    f"cycles={cycles_run} best={best_quality:.4f}"
                )
            elif category == "parse_rejected":
                parse_rejected += 1
                if classification.get("registered_to_db"):
                    registered += 1
                _copy_for_review(source_file, request.draft_path, review_dir)
                batch_results.append(
                    f"- `{rel_path}`: parse rejected quality={cycle_quality:.4f} "
                    f"cycles={cycles_run} best={best_quality:.4f}"
                )
            else:
                failed += 1
                if classification.get("registered_to_db"):
                    registered += 1
                _copy_for_review(source_file, request.draft_path, review_dir)
                batch_results.append(
                    f"- `{rel_path}`: failed ({getattr(result, 'outcome', 'FAILED')}) "
                    f"quality={cycle_quality:.4f} cycles={cycles_run} best={best_quality:.4f}"
                )
            write_attempt_event(
                attempt_id=attempt_id,
                stage="registration",
                status="succeeded" if classification.get("registered_to_db") else "skipped",
                event_type="registration_classified",
                message=f"Telegram DOCSREG registration classified as {category}.",
                source_path=str(source_file),
                source_sha256=source_sha,
                evidence_root=file_evidence_root,
                artifacts={
                    "registered_to_db": classification.get("registered_to_db"),
                    "registration_status": classification.get("registration_status"),
                },
            )
            write_attempt_event(
                attempt_id=attempt_id,
                stage="terminal",
                status="certified" if category == "certified" else (
                    "advisory" if category == "advisory" else "pending"
                    if category == "pending_needs_repair" else "rejected"
                    if category == "parse_rejected" else "failed"
                ),
                event_type="terminal_status",
                message=f"Telegram DOCSREG terminal category={category}.",
                source_path=str(source_file),
                source_sha256=source_sha,
                evidence_root=file_evidence_root,
                artifacts={"category": category},
            )

    finally:
        _ACTIVE_BATCHES.pop(chat_id, None)

    cancelled = cancel_event.is_set()
    status_line = "Batch cancelled.\n" if cancelled else "Batch complete.\n"
    review_needed = failed + pending_needs_repair + parse_rejected + unsupported
    review_note = f"\nFiles for review: `{review_dir}`" if review_needed else ""
    skip_note = f"Skipped (already certified): {skipped} files.\n" if skipped else ""
    latest_quality_text = f"{latest_quality:.4f}" if latest_quality is not None else "0.0000"
    latest_cycles_text = str(latest_cycles_run if latest_cycles_run is not None else 0)
    message_parts = [
        status_line,
        skip_note,
        f"Processed {processed} files.\n",
        f"Latest cycle quality: {latest_quality_text}\n",
        f"Latest cycle count: {latest_cycles_text}\n",
        f"Best quality seen: {best_quality_seen:.4f}\n",
        f"Repair attempted: {repair_attempted}\n",
        f"Repair applied: {repair_applied}\n",
        f"Repair status: {latest_repair_status or 'n/a'}\n",
        f"Repair stop reason: {latest_repair_stop_reason or 'n/a'}\n",
    ]
    if latest_repair_result_path:
        message_parts.append(f"Repair result: `{latest_repair_result_path}`\n")
    if latest_repair_escalation_path:
        message_parts.append(f"Repair escalation: `{latest_repair_escalation_path}`\n")
    if latest_repair_training_pair_path:
        message_parts.append(f"Repair training pair: `{latest_repair_training_pair_path}`\n")
    if latest_repair_lesson_path:
        message_parts.append(f"Repair lesson: `{latest_repair_lesson_path}`\n")
    if latest_repair_skill_proposal_path:
        message_parts.append(f"Repair skill proposal: `{latest_repair_skill_proposal_path}`\n")
    message_parts.extend(
        [
            f"Certified: {certified}\n",
            f"Advisory: {advisory}\n",
            f"Pending / needs repair: {pending_needs_repair}\n",
            f"Failed: {failed}\n",
            f"Unsupported / parse rejected: {unsupported + parse_rejected}\n",
            f"Registered {registered} files.\n",
            f"Failed registration {failed + parse_rejected} files.{review_note}",
        ]
    )
    await update.message.reply_text(
        "".join(message_parts),
        parse_mode="Markdown",
    )
    return True


async def maybe_handle_docsreg_message(update: Any, ctx: Any, text: str) -> bool:
    """Handle a free-text DOCSREG launch request or cancel command from the live chat."""
    # ── Cancel running batch ───────────────────────────────────────────────────
    if _is_stop_command(text or ""):
        chat_id = update.effective_chat.id if update.effective_chat else None
        cancel = _ACTIVE_BATCHES.get(chat_id) if chat_id is not None else None
        if cancel is not None:
            cancel.set()
            await update.message.reply_text("Stopping after current file...")
            return True
        # No active batch — don't consume the message
        return False

    # ── Launch batch via shared intent router ──────────────────────────────────
    try:
        from chat_intent_router import DOCUMENT_WORK_CMDS, classify  # noqa: PLC0415
    except Exception:
        return False

    routed = await asyncio.to_thread(classify, text or "", DOCUMENT_WORK_CMDS)
    if not routed or routed[0] != "docsreg":
        return False

    ctx.args = [text]
    return await cmd_docsreg(update, ctx)
