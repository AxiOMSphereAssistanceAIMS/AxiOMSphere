"""Logi — Scheduled Execution Watchdog.

Monitors every cycle and Traini block execution:
- writes and reads heartbeat files
- detects MISSED_START / STALE / HUNG states
- creates problems and corrective actions on failure
- implements the full watchdog state machine

State machine:
    PLANNED → SCHEDULED → START_REQUESTED → STARTED → RUNNING
    → HEARTBEAT_OK → COMPLETED → VALIDATING → VALIDATED
    → CLOSED_PASS | CLOSED_WARN | CLOSED_PARTIAL | CLOSED_FAIL

Failure paths:
    any state → MISSED_START | STALE | HUNG | FAILED
    → PROBLEM_CREATED → CORRECTIVE_ACTION_CREATED
    → RECOVERY_ATTEMPTED → ESCALATED
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
WATCHDOG_DIR = ROOT / "aims_workspace" / "model_improvement_loop" / "watchdog"
LESSONS_FILE = ROOT / "aims_workspace" / "repairman_memory" / "lessons.jsonl"

HEARTBEAT_STALE_SECONDS = 300   # 5 min without heartbeat → STALE
MISSED_START_GRACE_SECONDS = 60  # 1 min late → MISSED_START
HUNG_SECONDS = 3600              # 1 hour without completion → HUNG


# ── State constants ───────────────────────────────────────────────────────────

class WatchdogState:
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    START_REQUESTED = "START_REQUESTED"
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    HEARTBEAT_OK = "HEARTBEAT_OK"
    COMPLETED = "COMPLETED"
    VALIDATING = "VALIDATING"
    VALIDATED = "VALIDATED"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_WARN = "CLOSED_WARN"
    CLOSED_PARTIAL = "CLOSED_PARTIAL"
    CLOSED_FAIL = "CLOSED_FAIL"
    MISSED_START = "MISSED_START"
    STALE = "STALE"
    HUNG = "HUNG"
    FAILED = "FAILED"
    PROBLEM_CREATED = "PROBLEM_CREATED"
    CORRECTIVE_ACTION_CREATED = "CORRECTIVE_ACTION_CREATED"
    RECOVERY_ATTEMPTED = "RECOVERY_ATTEMPTED"
    ESCALATED = "ESCALATED"


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class MonitoredRun:
    monitored_run_id: str
    action_id: str              # cycle_id or block_id or planned action ID
    action_type: str            # CYCLE / TRAINI_BLOCK / PLANNED_ACTION
    slot_id: str
    status: str                 # WatchdogState
    planned_start_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    heartbeat_required: bool
    heartbeat_file: str         # path relative to ROOT
    last_heartbeat_at: Optional[str]
    heartbeat_interval_seconds: int
    expected_artifacts: list[str]
    produced_artifacts: list[str]
    validation_result: Optional[str]
    final_closure_result: Optional[str]
    problem_id: Optional[str]
    corrective_action_id: Optional[str]
    corrective_action_description: Optional[str]
    lessons_learned_ref: Optional[str]
    created_by: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WatchdogProblem:
    problem_id: str
    monitored_run_id: str
    action_id: str
    detected_state: str
    description: str
    severity: str               # LOW / MEDIUM / HIGH / CRITICAL
    created_at: str
    corrective_action_id: Optional[str] = None
    resolution: Optional[str] = None
    resolved_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Watchdog ──────────────────────────────────────────────────────────────────

class ScheduledExecutionWatchdog:
    """Monitors runs and enforces the watchdog state machine."""

    def __init__(self, run_dir: Optional[Path] = None) -> None:
        self._dir = run_dir or WATCHDOG_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, MonitoredRun] = {}
        self._problems: dict[str, WatchdogProblem] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        action_id: str,
        action_type: str,
        slot_id: str,
        planned_start_at: Optional[str] = None,
        heartbeat_required: bool = True,
        expected_artifacts: Optional[list[str]] = None,
        created_by: str = "logi",
    ) -> MonitoredRun:
        run_id = f"wr_{action_id[:20]}_{uuid.uuid4().hex[:6]}"
        hb_file = f"aims_workspace/model_improvement_loop/watchdog/{run_id}.heartbeat.json"
        run = MonitoredRun(
            monitored_run_id=run_id,
            action_id=action_id,
            action_type=action_type,
            slot_id=slot_id,
            status=WatchdogState.PLANNED,
            planned_start_at=planned_start_at,
            started_at=None,
            completed_at=None,
            heartbeat_required=heartbeat_required,
            heartbeat_file=hb_file,
            last_heartbeat_at=None,
            heartbeat_interval_seconds=60,
            expected_artifacts=expected_artifacts or [],
            produced_artifacts=[],
            validation_result=None,
            final_closure_result=None,
            problem_id=None,
            corrective_action_id=None,
            corrective_action_description=None,
            lessons_learned_ref=None,
            created_by=created_by,
        )
        self._runs[run_id] = run
        self._save_run(run)
        return run

    # ── State transitions ──────────────────────────────────────────────────────

    def transition(
        self,
        run: MonitoredRun,
        new_state: str,
        notes: str = "",
        extra: Optional[dict[str, Any]] = None,
    ) -> MonitoredRun:
        now = datetime.now(timezone.utc).isoformat()
        run.status = new_state
        if new_state in (WatchdogState.STARTED, WatchdogState.RUNNING):
            if run.started_at is None:
                run.started_at = now
        if new_state in (WatchdogState.COMPLETED, WatchdogState.FAILED):
            run.completed_at = now
        if notes:
            run.notes = (run.notes + " | " + notes).strip(" |")
        if extra:
            for k, v in extra.items():
                if hasattr(run, k):
                    setattr(run, k, v)
        self._save_run(run)
        return run

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    def write_heartbeat(self, run: MonitoredRun, extra: Optional[dict] = None) -> Path:
        """Write a heartbeat file for this run."""
        now = datetime.now(timezone.utc).isoformat()
        run.last_heartbeat_at = now
        hb_path = ROOT / run.heartbeat_file
        hb_path.parent.mkdir(parents=True, exist_ok=True)
        hb = {
            "monitored_run_id": run.monitored_run_id,
            "action_id": run.action_id,
            "status": run.status,
            "last_heartbeat_at": now,
            "slot_id": run.slot_id,
        }
        if extra:
            hb.update(extra)
        hb_path.write_text(json.dumps(hb, indent=2, ensure_ascii=False), encoding="utf-8")
        run.status = WatchdogState.HEARTBEAT_OK
        self._save_run(run)
        return hb_path

    def read_heartbeat(self, run: MonitoredRun) -> Optional[dict[str, Any]]:
        """Read a heartbeat file for this run."""
        hb_path = ROOT / run.heartbeat_file
        if not hb_path.exists():
            return None
        try:
            return json.loads(hb_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    # ── Staleness / hung detection ─────────────────────────────────────────────

    def check_staleness(self, run: MonitoredRun) -> str:
        """Return current health state: HEARTBEAT_OK / STALE / HUNG / MISSED_START / OK."""
        now = datetime.now(timezone.utc)

        if run.status in (
            WatchdogState.CLOSED_PASS, WatchdogState.CLOSED_WARN,
            WatchdogState.CLOSED_PARTIAL, WatchdogState.CLOSED_FAIL,
            WatchdogState.ESCALATED,
        ):
            return "CLOSED"

        # Missed start check
        if run.planned_start_at and run.started_at is None:
            try:
                planned = datetime.fromisoformat(run.planned_start_at)
                if (now - planned).total_seconds() > MISSED_START_GRACE_SECONDS:
                    return WatchdogState.MISSED_START
            except Exception:
                pass

        # Running but heartbeat stale
        if run.started_at and run.heartbeat_required:
            ref = run.last_heartbeat_at or run.started_at
            try:
                ref_dt = datetime.fromisoformat(ref)
                elapsed = (now - ref_dt).total_seconds()
                if elapsed > HUNG_SECONDS:
                    return WatchdogState.HUNG
                if elapsed > HEARTBEAT_STALE_SECONDS:
                    return WatchdogState.STALE
            except Exception:
                pass

        return "OK"

    # ── Problem & corrective action ────────────────────────────────────────────

    def create_problem(
        self,
        run: MonitoredRun,
        detected_state: str,
        description: str,
        severity: str = "MEDIUM",
    ) -> WatchdogProblem:
        problem_id = f"prob_{run.monitored_run_id[:16]}_{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc).isoformat()
        problem = WatchdogProblem(
            problem_id=problem_id,
            monitored_run_id=run.monitored_run_id,
            action_id=run.action_id,
            detected_state=detected_state,
            description=description,
            severity=severity,
            created_at=now,
        )
        self._problems[problem_id] = problem
        run.problem_id = problem_id
        run.status = WatchdogState.PROBLEM_CREATED
        self._save_run(run)
        self._save_problem(problem)
        return problem

    def create_corrective_action(
        self,
        run: MonitoredRun,
        problem: WatchdogProblem,
        action_description: str,
    ) -> str:
        ca_id = f"ca_{problem.problem_id[:20]}_{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc).isoformat()
        problem.corrective_action_id = ca_id
        run.corrective_action_id = ca_id
        run.corrective_action_description = action_description
        run.status = WatchdogState.CORRECTIVE_ACTION_CREATED
        ca = {
            "corrective_action_id": ca_id,
            "problem_id": problem.problem_id,
            "monitored_run_id": run.monitored_run_id,
            "action_id": run.action_id,
            "description": action_description,
            "created_at": now,
            "status": "CREATED",
        }
        ca_path = self._dir / f"{ca_id}.json"
        ca_path.write_text(json.dumps(ca, indent=2, ensure_ascii=False), encoding="utf-8")
        self._save_run(run)
        self._save_problem(problem)
        return ca_id

    def validate_and_close(
        self,
        run: MonitoredRun,
        validation_result: str,
        produced_artifacts: Optional[list[str]] = None,
        lessons_ref: Optional[str] = None,
    ) -> str:
        run.validation_result = validation_result
        run.produced_artifacts = produced_artifacts or []
        run.lessons_learned_ref = lessons_ref
        if validation_result == "PASS":
            closure = WatchdogState.CLOSED_PASS
        elif validation_result == "PARTIAL":
            closure = WatchdogState.CLOSED_PARTIAL
        elif validation_result == "WARN":
            closure = WatchdogState.CLOSED_WARN
        else:
            closure = WatchdogState.CLOSED_FAIL
        run.final_closure_result = closure
        run.status = closure
        self._save_run(run)
        return closure

    def write_lesson(
        self,
        run: MonitoredRun,
        lesson: dict[str, Any],
    ) -> None:
        try:
            LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with LESSONS_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(lesson, ensure_ascii=False) + "\n")
            run.lessons_learned_ref = str(LESSONS_FILE.relative_to(ROOT))
            self._save_run(run)
        except Exception:
            pass

    # ── Index ──────────────────────────────────────────────────────────────────

    def write_index(self, output_dir: Optional[Path] = None) -> Path:
        out = output_dir or self._dir
        index = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "runs": [r.to_dict() for r in self._runs.values()],
            "problems": [p.to_dict() for p in self._problems.values()],
        }
        path = out / "monitored_runs_index.json"
        path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save_run(self, run: MonitoredRun) -> None:
        path = self._dir / f"{run.monitored_run_id}.json"
        path.write_text(json.dumps(run.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _save_problem(self, problem: WatchdogProblem) -> None:
        path = self._dir / f"{problem.problem_id}.json"
        path.write_text(json.dumps(problem.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def all_runs(self) -> list[MonitoredRun]:
        return list(self._runs.values())

    def get_run(self, run_id: str) -> Optional[MonitoredRun]:
        return self._runs.get(run_id)
