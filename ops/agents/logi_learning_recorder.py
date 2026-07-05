"""
logi_learning_recorder.py

Thin wrapper over verified_learning_event_recorder.py with confirmation flow.

Routes to existing learning pipeline:
  aims_workspace/self_learning/inbox/audited_correction_events.jsonl

Also writes pending learning event candidates:
  aims_workspace/logi_learning_events/pending/

Does NOT run training. training_eligible=False until verifier confirms.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PENDING_DIR = _ROOT / "aims_workspace" / "logi_learning_events" / "pending"
_COMPLETED_DIR = _ROOT / "aims_workspace" / "logi_learning_events" / "completed"
_TRAINING_CANDIDATES_DIR = _ROOT / "aims_workspace" / "logi_training_pair_candidates"


@dataclass
class LearningEventCandidate:
    event_id: str
    created_at: str
    requested_by: str
    source_message: str
    task_type: str
    failure_class: str
    user_intent: str
    expected_behavior: str
    actual_behavior: str
    missing_capability: str
    existing_analogs_checked: list[str]
    proposed_fix: str
    training_event_candidate: bool
    patch_prompt_candidate: str
    auditor_help_recommended: bool
    lesson: str
    proposed_training_pair: dict
    training_eligible: bool = False   # always False until verifier present
    original_message: str = ""
    status: str = "pending"


def _event_id(source: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    h = hashlib.sha256(f"{source}:{ts}".encode()).hexdigest()[:8]
    return f"learn_ev_{ts}_{h}"


def write_learning_event_candidate(
    source_message: str,
    user_intent: str,
    expected_behavior: str,
    actual_behavior: str,
    failure_class: str = "CAPABILITY_GAP",
    missing_capability: str = "",
    existing_analogs_checked: list[str] | None = None,
    proposed_fix: str = "",
    lesson: str = "",
    proposed_training_pair: dict | None = None,
    patch_prompt_candidate: str = "",
    auditor_help_recommended: bool = False,
    requested_by: str = "0",
    task_type: str = "general",
) -> LearningEventCandidate:
    """
    Write a pending learning event candidate.
    training_eligible is always False at creation — requires verifier.
    """
    now = datetime.now(timezone.utc).isoformat()
    event = LearningEventCandidate(
        event_id=_event_id(source_message),
        created_at=now,
        requested_by=requested_by,
        source_message=source_message,
        task_type=task_type,
        failure_class=failure_class,
        user_intent=user_intent,
        expected_behavior=expected_behavior,
        actual_behavior=actual_behavior,
        missing_capability=missing_capability,
        existing_analogs_checked=existing_analogs_checked or [],
        proposed_fix=proposed_fix,
        training_event_candidate=True,
        patch_prompt_candidate=patch_prompt_candidate,
        auditor_help_recommended=auditor_help_recommended,
        lesson=lesson,
        proposed_training_pair=proposed_training_pair or {
            "instruction": user_intent,
            "expected": expected_behavior,
            "actual": actual_behavior,
        },
        training_eligible=False,
        original_message=source_message,
    )
    _PENDING_DIR.mkdir(parents=True, exist_ok=True)
    path = _PENDING_DIR / f"{event.event_id}.json"
    path.write_text(json.dumps(asdict(event), indent=2, ensure_ascii=False), encoding="utf-8")

    # Also write a training pair candidate (separate from the event)
    _TRAINING_CANDIDATES_DIR.mkdir(parents=True, exist_ok=True)
    pair_path = _TRAINING_CANDIDATES_DIR / f"{event.event_id}_pair_candidate.json"
    pair_path.write_text(json.dumps({
        "event_id": event.event_id,
        "created_at": now,
        "training_eligible": False,
        "note": "Pending auditor/verifier review before promotion to training set.",
        "pair": event.proposed_training_pair,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    return event


def load_learning_event(event_id: str) -> dict | None:
    for d in (_PENDING_DIR, _COMPLETED_DIR):
        path = d / f"{event_id}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
    return None
