"""
job_filter_change_request.py

Governance queue for JobLocator (job-filter-bot) search-filter change
requests raised via Telegram chat.

Mirrors the existing logi_skill_request.py pattern: JobLocator never edits
its own filter code directly from a chat message. A confirmed request is a
task for a Logi-orchestrated fullstack session to implement; JobLocator only
reports the change as done once mark_completed() has been called with
evidence, never on its own say-so (no hallucinated "done").

Lifecycle:
  pending    -> write_change_request()   (LLM-parsed proposal, awaiting the
                                           requester's explicit confirmation)
  confirmed  -> mark_confirmed()         (requester replied CONFIRM <id>;
                                           now a real task for fullstack)
  completed  -> mark_completed()         (fullstack/Logi implemented it and
                                           supplied evidence — only after
                                           this does JobLocator report success)
  rejected   -> mark_rejected()          (requester replied CANCEL <id>, or
                                           the request expired unconfirmed)

Requests:
  aims_workspace/job_filter/joblocator_requests/pending/
  aims_workspace/job_filter/joblocator_requests/confirmed/
  aims_workspace/job_filter/joblocator_requests/completed/
  aims_workspace/job_filter/joblocator_requests/rejected/
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_BASE_DIR = _ROOT / "aims_workspace" / "job_filter" / "joblocator_requests"
_PENDING_DIR = _BASE_DIR / "pending"
_CONFIRMED_DIR = _BASE_DIR / "confirmed"
_COMPLETED_DIR = _BASE_DIR / "completed"
_REJECTED_DIR = _BASE_DIR / "rejected"

_ALL_DIRS = (_PENDING_DIR, _CONFIRMED_DIR, _COMPLETED_DIR, _REJECTED_DIR)

_CONFIRMATION_TTL_SECONDS = 600  # 10 minutes, matches logi_confirmation_flow.py


@dataclass
class JobFilterChangeRequest:
    request_id: str
    created_at: str
    requested_by: str  # telegram chat_id
    raw_request_text: str  # exactly what the user typed
    understood_summary: str  # plain-language restatement shown back to the user for confirmation
    proposed_change: dict  # structured: {"action": ..., "target": ..., "value": ..., "reason": ...}
    status: str = "pending"
    confirmed_at: str = ""
    completed_at: str = ""
    completed_by: str = ""
    evidence: str = ""
    rejected_reason: str = ""
    fullstack_review_required: bool = True


def _request_id(requested_by: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    h = hashlib.sha256(f"{requested_by}:{ts}".encode()).hexdigest()[:8]
    return f"jf_change_{ts}_{h}"


def _dir_for_status(status: str) -> Path:
    return {
        "pending": _PENDING_DIR,
        "confirmed": _CONFIRMED_DIR,
        "completed": _COMPLETED_DIR,
        "rejected": _REJECTED_DIR,
    }[status]


def _path_for(record: JobFilterChangeRequest) -> Path:
    return _dir_for_status(record.status) / f"{record.request_id}.json"


def _write(record: JobFilterChangeRequest) -> None:
    path = _path_for(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(record), indent=2, ensure_ascii=False), encoding="utf-8")


def write_change_request(
    requested_by: str,
    raw_request_text: str,
    understood_summary: str,
    proposed_change: dict,
) -> JobFilterChangeRequest:
    """Write a pending change request. Never executes anything by itself."""
    record = JobFilterChangeRequest(
        request_id=_request_id(requested_by),
        created_at=datetime.now(timezone.utc).isoformat(),
        requested_by=requested_by,
        raw_request_text=raw_request_text,
        understood_summary=understood_summary,
        proposed_change=proposed_change,
    )
    _write(record)
    return record


def _find(request_id: str) -> tuple[JobFilterChangeRequest, Path] | None:
    for d in _ALL_DIRS:
        path = d / f"{request_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return JobFilterChangeRequest(**data), path
            except Exception:
                return None
    return None


def load_change_request(request_id: str) -> JobFilterChangeRequest | None:
    found = _find(request_id)
    return found[0] if found else None


def _list_status(status: str) -> list[JobFilterChangeRequest]:
    out: list[JobFilterChangeRequest] = []
    d = _dir_for_status(status)
    if not d.exists():
        return out
    for path in sorted(d.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append(JobFilterChangeRequest(**data))
        except Exception:
            continue
    return out


def list_pending() -> list[JobFilterChangeRequest]:
    return _list_status("pending")


def list_confirmed() -> list[JobFilterChangeRequest]:
    """Confirmed-but-not-yet-implemented — the queue fullstack works from."""
    return _list_status("confirmed")


def list_completed() -> list[JobFilterChangeRequest]:
    return _list_status("completed")


def is_expired(record: JobFilterChangeRequest) -> bool:
    try:
        created = datetime.fromisoformat(record.created_at)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - created > timedelta(seconds=_CONFIRMATION_TTL_SECONDS)


def mark_confirmed(request_id: str, *, requested_by: str) -> JobFilterChangeRequest | None:
    """Move a pending request to confirmed. Only the original requester may confirm."""
    found = _find(request_id)
    if not found:
        return None
    record, old_path = found
    if record.status != "pending":
        return None
    if str(record.requested_by) != str(requested_by):
        return None
    record.status = "confirmed"
    record.confirmed_at = datetime.now(timezone.utc).isoformat()
    old_path.unlink(missing_ok=True)
    _write(record)
    return record


def mark_rejected(request_id: str, *, reason: str) -> JobFilterChangeRequest | None:
    found = _find(request_id)
    if not found:
        return None
    record, old_path = found
    if record.status in ("completed", "rejected"):
        return None
    record.status = "rejected"
    record.rejected_reason = reason
    old_path.unlink(missing_ok=True)
    _write(record)
    return record


def mark_completed(request_id: str, *, completed_by: str, evidence: str) -> JobFilterChangeRequest | None:
    """Record that fullstack/Logi actually implemented and verified the
    change. JobLocator must never report success without calling this
    first — evidence is required, not optional.
    """
    if not evidence.strip():
        raise ValueError("evidence is required to mark a change request completed")
    found = _find(request_id)
    if not found:
        return None
    record, old_path = found
    if record.status != "confirmed":
        return None
    record.status = "completed"
    record.completed_at = datetime.now(timezone.utc).isoformat()
    record.completed_by = completed_by
    record.evidence = evidence
    old_path.unlink(missing_ok=True)
    _write(record)
    return record
