"""
verified_learning_event_recorder.py

Write verified learning events to aims_workspace/self_learning/inbox/.

Rules:
  - training_eligible=True only when verifier_result is present
    with status VERIFIED_PASS, VERIFIED_FAIL, or PARTIAL
  - Never write fake command outputs as real evidence
  - Initial (bad) output and corrected output stored separately
  - JSONL format, one event per line
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_INBOX = Path("aims_workspace/self_learning/inbox")
_EVENTS_FILE = _INBOX / "audited_correction_events.jsonl"

_TRAINING_ELIGIBLE_VERIFIER_STATUSES = {
    "VERIFIED_PASS",
    "VERIFIED_FAIL",
    "PARTIAL",
}

_ALLOWED_EVENT_TYPES = {
    "VERIFIED_MODEL_MISTAKE",
    "VERIFIED_SELF_CORRECTION",
    "VERIFIED_CODEX_FINDING",
    "VERIFIED_POLICY_VIOLATION_AVOIDED",
    "VERIFIED_TOOL_SELECTION_ERROR",
    "VERIFIED_CONTEXT_MERGE_ERROR",
}

_MISTAKE_CLASS_TO_EVENT_TYPE = {
    "FAKE_OUTPUT": "VERIFIED_MODEL_MISTAKE",
    "STATIC_ONLY_OPERATIONAL": "VERIFIED_CONTEXT_MERGE_ERROR",
    "PASS_WITHOUT_EVIDENCE": "VERIFIED_MODEL_MISTAKE",
    "DESTRUCTIVE_UNCONFIRMED": "VERIFIED_POLICY_VIOLATION_AVOIDED",
    "MISMATCH": "VERIFIED_MODEL_MISTAKE",
}


@dataclass
class LearningEventInput:
    task_id: str
    user_request: str
    actor_initial_output: str
    actor_final_output: str
    self_check_result: dict
    codex_audit_result: dict
    verifier_result: dict
    correction_summary: str
    mistake_class: str | None
    evidence_dir: str
    source: str = "audited_correction_loop"
    extra: dict = field(default_factory=dict)


def record_learning_event(event_input: LearningEventInput) -> dict:
    """
    Write a single learning event to the inbox JSONL file.

    Returns the event dict that was written.
    training_eligible is set only when verifier_result has an accepted status.
    """
    _INBOX.mkdir(parents=True, exist_ok=True)

    verifier_status = event_input.verifier_result.get("status", "")
    training_eligible = verifier_status in _TRAINING_ELIGIBLE_VERIFIER_STATUSES

    event_type = _MISTAKE_CLASS_TO_EVENT_TYPE.get(
        event_input.mistake_class or "",
        "VERIFIED_MODEL_MISTAKE",
    )

    event = {
        "event_id": str(uuid.uuid4()),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "task_id": event_input.task_id,
        "user_request": event_input.user_request,
        "actor_initial_output": event_input.actor_initial_output,
        "actor_final_output": event_input.actor_final_output,
        "self_check_result": event_input.self_check_result,
        "codex_audit_result": event_input.codex_audit_result,
        "verifier_result": event_input.verifier_result,
        "correction_summary": event_input.correction_summary,
        "mistake_class": event_input.mistake_class,
        "training_eligible": training_eligible,
        "evidence_dir": event_input.evidence_dir,
        "source": event_input.source,
    }
    if event_input.extra:
        event["extra"] = event_input.extra

    with open(_EVENTS_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    return event


def load_recent_events(max_events: int = 50) -> list[dict]:
    """Return the most recent learning events from the inbox."""
    if not _EVENTS_FILE.exists():
        return []
    lines = _EVENTS_FILE.read_text(encoding="utf-8").splitlines()
    events = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(events) >= max_events:
            break
    return list(reversed(events))
