"""Traini Claude review loop state persistence and iteration tracking."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "aims_workspace" / "traini_review_loop_state"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BaselineSnapshot:
    """Baseline model evaluation snapshot."""
    model_slot: str
    model_name: str
    eval_score: float
    eval_suite: str
    eval_timestamp: str
    eval_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateIteration:
    """Single review iteration for a candidate."""
    iteration_num: int
    candidate_id: str
    candidate_name: str
    review_mode: str  # sonnet_4_6 | opus_4_6
    reviewer_model: str
    review_id: str
    review_timestamp: str
    reviewer_verdict: str  # accept | accept_with_changes | reject | needs_context
    mistakes_found: list[str]
    corrections_applied: list[str]
    learning_materials_generated: list[str]
    repairman_tasks_created: list[str]
    review_confidence: float
    delta_score_expected: float
    delta_score_observed: Optional[float] = None
    iteration_complete: bool = False
    completion_timestamp: Optional[str] = None


@dataclass
class LoopRunState:
    """Complete state of one loop run (baseline → candidate → verdict)."""
    run_id: str
    run_started: str
    baseline: BaselineSnapshot
    candidate_id: str
    candidate_name: str
    iterations: list[CandidateIteration] = field(default_factory=list)
    current_iteration_num: int = 0
    loop_complete: bool = False
    final_verdict: Optional[str] = None
    final_recommendation: Optional[str] = None
    evidence_path: Optional[str] = None
    completion_timestamp: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["baseline"] = asdict(self.baseline)
        d["iterations"] = [asdict(it) for it in self.iterations]
        return d


class LoopStateManager:
    """Manage persistent loop state across restarts."""

    def __init__(self, state_dir: Path = STATE_DIR):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.current_state: Optional[LoopRunState] = None

    def _state_path(self, run_id: str) -> Path:
        return self.state_dir / f"{run_id}.json"

    def create_run(
        self,
        baseline: BaselineSnapshot,
        candidate_id: str,
        candidate_name: str,
    ) -> LoopRunState:
        """Create a new loop run state."""
        run_id = f"traini_loop_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')[:22]}"
        state = LoopRunState(
            run_id=run_id,
            run_started=_now(),
            baseline=baseline,
            candidate_id=candidate_id,
            candidate_name=candidate_name,
        )
        self.current_state = state
        self.save()
        return state

    def add_iteration(
        self,
        iteration_num: int,
        candidate_id: str,
        candidate_name: str,
        review_mode: str,
        reviewer_model: str,
        review_id: str,
        reviewer_verdict: str,
        mistakes_found: list[str],
        corrections_applied: list[str],
        learning_materials_generated: list[str],
        repairman_tasks_created: list[str],
        review_confidence: float,
        delta_score_expected: float,
    ) -> CandidateIteration:
        """Record a new iteration."""
        if not self.current_state:
            raise ValueError("No active run state")

        iteration = CandidateIteration(
            iteration_num=iteration_num,
            candidate_id=candidate_id,
            candidate_name=candidate_name,
            review_mode=review_mode,
            reviewer_model=reviewer_model,
            review_id=review_id,
            review_timestamp=_now(),
            reviewer_verdict=reviewer_verdict,
            mistakes_found=mistakes_found,
            corrections_applied=corrections_applied,
            learning_materials_generated=learning_materials_generated,
            repairman_tasks_created=repairman_tasks_created,
            review_confidence=review_confidence,
            delta_score_expected=delta_score_expected,
        )

        self.current_state.iterations.append(iteration)
        self.current_state.current_iteration_num = iteration_num
        self.save()
        return iteration

    def complete_iteration(
        self,
        iteration_num: int,
        delta_score_observed: Optional[float] = None,
    ) -> None:
        """Mark an iteration as complete."""
        if not self.current_state:
            raise ValueError("No active run state")

        for it in self.current_state.iterations:
            if it.iteration_num == iteration_num:
                it.iteration_complete = True
                it.completion_timestamp = _now()
                it.delta_score_observed = delta_score_observed
                break

        self.save()

    def complete_run(
        self,
        final_verdict: str,
        final_recommendation: str,
        evidence_path: str,
    ) -> LoopRunState:
        """Mark the entire loop run as complete."""
        if not self.current_state:
            raise ValueError("No active run state")

        self.current_state.loop_complete = True
        self.current_state.final_verdict = final_verdict
        self.current_state.final_recommendation = final_recommendation
        self.current_state.evidence_path = evidence_path
        self.current_state.completion_timestamp = _now()
        self.save()
        return self.current_state

    def save(self) -> None:
        """Persist current state to disk."""
        if not self.current_state:
            return
        path = self._state_path(self.current_state.run_id)
        path.write_text(json.dumps(self.current_state.to_dict(), indent=2))

    def load(self, run_id: str) -> Optional[LoopRunState]:
        """Load a previous run state."""
        path = self._state_path(run_id)
        if not path.exists():
            return None

        data = json.loads(path.read_text())
        baseline_data = data.pop("baseline")
        baseline = BaselineSnapshot(**baseline_data)

        iterations_data = data.pop("iterations", [])
        iterations = [CandidateIteration(**it) for it in iterations_data]

        state = LoopRunState(baseline=baseline, iterations=iterations, **data)
        self.current_state = state
        return state

    def list_runs(self, limit: int = 100) -> list[str]:
        """List all run IDs, newest first."""
        runs = sorted(self.state_dir.glob("traini_loop_*.json"), reverse=True)
        return [p.stem for p in runs[:limit]]
