"""
logi_sprint_pipeline.py

Per-conversation sprint state tracker for Logi chief-engineer process.

Extends the pattern from ops/logi/strategic_planning.py but operates at
conversation granularity (single goal → phases → completion).

Sprint state is written to:
  aims_workspace/logi_sprints/<sprint_id>/state.json
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_SPRINTS_DIR = _ROOT / "aims_workspace" / "logi_sprints"

_PHASES = ["THINK", "PLAN", "BUILD", "REVIEW", "TEST", "SHIP", "REFLECT"]

_PHASE_SKILLS: dict[str, list[str]] = {
    "THINK": ["office_hours", "ceo_review", "capability_gap"],
    "PLAN": ["eng_review", "design_review", "devex_review", "autoplan", "investigate"],
    "BUILD": ["patch_prompt", "auditor_request", "queue_task", "schedule_task"],
    "REVIEW": ["review", "security_cso", "verify_agent_work"],
    "TEST": ["qa", "healthcheck_service", "read_logs_allowlisted", "diagnose_service_allowlisted"],
    "SHIP": ["release_ship"],
    "REFLECT": ["retro", "learn", "learning_registration", "skill_request"],
}


@dataclass
class SprintState:
    sprint_id: str
    goal: str
    current_phase: str
    phases_completed: list[str]
    skills_run: list[str]
    artifacts: list[str]
    created_at: str
    updated_at: str
    status: str   # ACTIVE | COMPLETED | BLOCKED | ABANDONED
    notes: list[str] = field(default_factory=list)


def _sprint_id(goal: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    h = hashlib.sha256(f"{goal}:{ts}".encode()).hexdigest()[:8]
    return f"sprint_{ts}_{h}"


def create_sprint_state(goal: str) -> SprintState:
    """Create a new sprint and persist it."""
    now = datetime.now(timezone.utc).isoformat()
    sid = _sprint_id(goal)
    state = SprintState(
        sprint_id=sid,
        goal=goal,
        current_phase="THINK",
        phases_completed=[],
        skills_run=[],
        artifacts=[],
        created_at=now,
        updated_at=now,
        status="ACTIVE",
    )
    _persist(state)
    return state


def advance_sprint_state(sprint_id: str, skill_result: dict) -> SprintState:
    """Record a skill result and advance phase if warranted."""
    state = load_sprint_state(sprint_id)
    if state is None:
        raise ValueError(f"Sprint not found: {sprint_id}")

    skill_id = skill_result.get("skill_id", "")
    artifact_id = skill_result.get("artifact_id", "")

    if skill_id and skill_id not in state.skills_run:
        state.skills_run.append(skill_id)
    if artifact_id:
        state.artifacts.append(artifact_id)

    # Advance phase if all key skills for current phase are done
    current_skills = _PHASE_SKILLS.get(state.current_phase, [])
    done = set(state.skills_run)
    if any(s in done for s in current_skills):
        if state.current_phase not in state.phases_completed:
            state.phases_completed.append(state.current_phase)
        # Move to next phase
        current_idx = _PHASES.index(state.current_phase)
        if current_idx + 1 < len(_PHASES):
            state.current_phase = _PHASES[current_idx + 1]
        else:
            state.status = "COMPLETED"

    state.updated_at = datetime.now(timezone.utc).isoformat()
    _persist(state)
    return state


def recommend_next_skill(sprint_id: str) -> list[str]:
    """Return recommended skills for the current phase."""
    state = load_sprint_state(sprint_id)
    if state is None:
        return ["office_hours"]
    done = set(state.skills_run)
    phase_skills = _PHASE_SKILLS.get(state.current_phase, [])
    remaining = [s for s in phase_skills if s not in done]
    return remaining[:3] if remaining else ["retro"]


def summarize_sprint_state(sprint_id: str) -> str:
    """Return a short human-readable sprint summary."""
    state = load_sprint_state(sprint_id)
    if state is None:
        return "Sprint not found."
    return (
        f"Sprint: {state.sprint_id}\n"
        f"Goal: {state.goal}\n"
        f"Phase: {state.current_phase}\n"
        f"Status: {state.status}\n"
        f"Skills run: {', '.join(state.skills_run) or 'none'}\n"
        f"Next: {', '.join(recommend_next_skill(sprint_id)) or 'complete'}"
    )


def load_sprint_state(sprint_id: str) -> SprintState | None:
    path = _SPRINTS_DIR / sprint_id / "state.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SprintState(**data)
    except Exception:
        return None


def _persist(state: SprintState) -> None:
    sprint_dir = _SPRINTS_DIR / state.sprint_id
    sprint_dir.mkdir(parents=True, exist_ok=True)
    (sprint_dir / "state.json").write_text(
        json.dumps(asdict(state), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
