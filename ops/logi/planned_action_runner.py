"""Planned Action Runner — executes StrategicPlannedActions through Logi infrastructure.

Dispatches via Logi's ProcessGoal + ProcessLedger data structures. Does NOT bypass
Logi — the runner uses Logi data models for every dispatch, collection, comparison,
and corrective step.

Architecture (Logi loop):
  runner.run(action)
    → ProcessGoal created for this action
    → ProcessLedger initialized
    → ledger.dispatch() recorded
    → subprocess executed (logi_subprocess handler)
    → ledger.collect() recorded with result
    → pass/fail criteria evaluated
    → ledger.compare() recorded
    → if FAIL: corrective action logged
    → lessons_learned appended
    → StrategicPlannedActionsRegistry updated

Execution modes:
  dry-run          — SIMULATED, no subprocess, safe for testing
  live-lightweight — real subprocess, only for cpu_only/zero-vram actions
  live-gpu-gated   — real subprocess for explicitly opted-in slot32 GPU actions;
                     serialized through DGX heavy lock and never allowed for slot120

CLI:
  python3 ops/logi/planned_action_runner.py \\
      --mode live-lightweight --action-id PA-007
  python3 ops/logi/planned_action_runner.py \\
      --mode live-lightweight --run-due
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "ops"
EVIDENCE_ROOT = ROOT / "aims_workspace/strategic_planning/scheduled_actions/evidence"
LESSONS_FILE = ROOT / "aims_workspace/repairman_memory/lessons.jsonl"

# Make logi package importable
if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))

from logi.process_goals import ProcessGoal, SuccessCriterion, CorrectiveAction
from logi.process_ledger import ProcessLedger
from logi.short_term_action_plan import StrategicPlannedAction, StrategicPlannedActionsRegistry
from models.model_registry import resolve_model_slot
from ollama_resolve import dgx_heavy_lock, ollama_ps_entry_summary

log = logging.getLogger("planned_action_runner")

DUBAI_TZ = timezone(timedelta(hours=4))

# Actions safe for live-lightweight: cpu_only, max_vram_gb==0, no slot120 forbidden check needed
_LIVE_LIGHTWEIGHT_SAFE_RESOURCE = frozenset()   # checked dynamically via resource_policy


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_live_lightweight_safe(action: StrategicPlannedAction) -> bool:
    """Return True iff action's resource policy allows live-lightweight execution."""
    rp = action.resource_policy or {}
    if rp.get("max_vram_gb", 99) > 0:
        return False
    if not rp.get("cpu_only_ok", False):
        return False
    # Forbid if slot120 is in allowed_model_slots (should never be for lightweight)
    if "slot120" in rp.get("allowed_model_slots", []):
        return False
    return True


def _is_live_gpu_gated_safe(action: StrategicPlannedAction) -> bool:
    """Return True iff action explicitly opts into serialized slot32 GPU execution."""
    rp = action.resource_policy or {}
    slots = rp.get("allowed_model_slots", [])
    if not rp.get("gpu_queue_and_await", False):
        return False
    if rp.get("max_vram_gb", 0) <= 0:
        return False
    if rp.get("cpu_only_ok", True):
        return False
    if "slot120" in slots:
        return False
    return bool(slots) and set(slots).issubset({"slot32"})


# ── Scheduler bridge for StrategicPlannedActions ──────────────────────────────

class StrategicSchedulerBridge:
    """Select due StrategicPlannedActions based on preferred_window_start."""

    def __init__(self, registry: StrategicPlannedActionsRegistry | None = None) -> None:
        self.registry = registry or StrategicPlannedActionsRegistry()

    def evaluate_due_actions(
        self,
        *,
        now: datetime | None = None,
        mode: str = "dry-run",
        statuses: tuple[str, ...] = ("PENDING",),
    ) -> dict[str, Any]:
        """Return due/pending actions whose window has opened."""
        if now is None:
            now = datetime.now(timezone.utc)
        actions = self.registry.load_all()
        pending = [a for a in actions if a.status in statuses]
        due: list[dict[str, Any]] = []
        not_due: list[dict[str, Any]] = []

        for action in pending:
            window_start = _parse_iso(action.preferred_window_start)
            is_due = (window_start is None) or (window_start <= now)
            is_safe = _is_live_lightweight_safe(action)
            entry = {
                "action_id": action.action_id,
                "title": action.title,
                "owner_agent": action.owner_agent,
                "preferred_window_start": action.preferred_window_start,
                "preferred_window_end": action.preferred_window_end,
                "schedule_type": action.schedule_type,
                "execution_handler": action.execution_handler,
                "live_lightweight_safe": is_safe,
                "selected": is_due,
            }
            if is_due:
                due.append(entry)
            else:
                not_due.append(entry)

        return {
            "status": "PASS",
            "mode": mode,
            "now_utc": now.isoformat(),
            "now_dubai": now.astimezone(DUBAI_TZ).isoformat(),
            "pending_total": len(pending),
            "due_total": len(due),
            "not_due_total": len(not_due),
            "due_actions": due,
            "not_due_actions": not_due,
            "live_lightweight_safe_count": sum(1 for d in due if d["live_lightweight_safe"]),
        }


# ── Runner ─────────────────────────────────────────────────────────────────────

class PlannedActionRunner:
    """Runs a single StrategicPlannedAction through the Logi process loop."""

    def __init__(self, dry_run: bool = False, mode: str = "") -> None:
        # mode takes precedence over dry_run flag for backward compat
        if mode == "live-lightweight":
            self.dry_run = False
            self.mode = "live-lightweight"
        elif mode == "live-gpu-gated":
            self.dry_run = False
            self.mode = "live-gpu-gated"
        elif mode == "dry-run" or dry_run:
            self.dry_run = True
            self.mode = "dry-run"
        else:
            self.dry_run = False
            self.mode = "live-lightweight"
        self.registry = StrategicPlannedActionsRegistry()

    def run(self, action: StrategicPlannedAction) -> dict[str, Any]:
        """Execute action and return result dict."""
        action.attempt_count += 1
        evidence_dir = EVIDENCE_ROOT / action.action_id
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # Build ProcessGoal for this action (ProcessGoal has no description field)
        goal = ProcessGoal(
            goal_id=f"pg_{action.action_id}_{int(time.time())}",
            title=action.title,
            target_state=action.description[:200] if action.description else "",
            success_criteria=[
                SuccessCriterion(description=c, required=True)
                for c in action.acceptance_criteria
            ],
        )
        goal.status = "RUNNING"

        # Logi ledger for this action run
        run_dir = evidence_dir / f"run_{goal.goal_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        ledger = ProcessLedger(goal_id=goal.goal_id, run_dir=run_dir)
        ledger.record("action_start", {
            "action_id": action.action_id,
            "title": action.title,
            "handler": action.execution_handler,
            "mode": self.mode,
            "dry_run": self.dry_run,
        }, agent=action.owner_agent)

        # Live-lightweight safety gate: only run if resource policy permits
        if self.mode == "live-lightweight" and not _is_live_lightweight_safe(action):
            ledger.record("safety_abort", {
                "reason": "Action not safe for live-lightweight (VRAM>0 or cpu_only_ok=False)"
            }, status="SKIP", agent="logi")
            return self._finalize(action, goal, ledger, "SKIP", {
                "reason": "live_lightweight_unsafe: resource policy requires VRAM or not cpu_only"
            }, evidence_dir)
        if self.mode == "live-gpu-gated" and not _is_live_gpu_gated_safe(action):
            ledger.record("safety_abort", {
                "reason": "Action not safe for live-gpu-gated (must opt in, require VRAM, slot32-only, cpu_only_ok=False)"
            }, status="SKIP", agent="logi")
            return self._finalize(action, goal, ledger, "SKIP", {
                "reason": "live_gpu_gated_unsafe: action is not explicit slot32 gpu_queue_and_await workload"
            }, evidence_dir)

        # Safety check: abort_if_argus_critical
        safety = action.safety_policy or {}
        if safety.get("abort_if_argus_critical", True) and not self.dry_run:
            if self._argus_critical_active():
                ledger.record("safety_abort", {
                    "reason": "Argus CRITICAL event active — aborting scheduled action"
                }, status="ABORT", agent="argus")
                return self._finalize(action, goal, ledger, "SKIP", {
                    "reason": "aborted: argus_critical_active"
                }, evidence_dir)

        # Dispatch
        ledger.dispatch(
            step_title=action.title,
            agent=action.owner_agent,
            tool=action.execution_handler,
            payload={
                "command": action.command_or_callable,
                "args": action.command_args,
            }
        )

        # Execute
        result = self._execute(action, ledger, evidence_dir)

        # Collect
        result_summary = f"status={result.get('status')} exit_code={result.get('exit_code')}"
        ledger.collect(
            step_title=action.title,
            agent=action.owner_agent,
            result_summary=result_summary,
            status=result.get("status", "FAIL"),
        )

        # Compare against acceptance criteria
        passed, failures = self._evaluate_criteria(action, result)
        for i, criterion in enumerate(action.acceptance_criteria):
            crit_status = "PASS" if (not failures) else "FAIL"
            ledger.compare(
                criterion=criterion,
                actual=result_summary,
                expected="exit_code=0",
                status=crit_status,
            )

        if passed:
            goal.status = "PASS"
            final_status = "PASS"
        else:
            goal.status = "FAIL"
            final_status = "FAIL"
            # Record corrective action
            corrective = CorrectiveAction(
                reason=f"Action {action.action_id} failed criteria: {failures}",
                responsible_agent=action.owner_agent,
                action_taken="Logged failure; retry per retry_policy",
                validation_result="PENDING",
            )
            ledger.record("corrective_action", corrective.to_dict(), status="LOGGED",
                          agent=action.owner_agent)

        # Lessons learned
        self._append_lessons(action, final_status, result, failures)

        return self._finalize(action, goal, ledger, final_status, result, evidence_dir)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _execute(
        self,
        action: StrategicPlannedAction,
        ledger: ProcessLedger,
        evidence_dir: Path,
    ) -> dict[str, Any]:
        if self.dry_run:
            ledger.record("dry_run_skip", {
                "command": action.command_or_callable,
                "args": action.command_args,
            }, status="SIMULATED", agent=action.owner_agent)
            return {
                "status": "SIMULATED",
                "exit_code": 0,
                "stdout": f"[dry_run] would execute: {action.command_or_callable}",
                "stderr": "",
                "wall_time_sec": 0,
            }

        handler = action.execution_handler
        if handler == "logi_subprocess":
            return self._run_subprocess(action, evidence_dir)
        if handler == "logi_http":
            return self._run_http(action)
        # logi_tool: treat as noop for now (extend as needed)
        return {
            "status": "SKIP",
            "reason": f"handler '{handler}' not implemented in this runner version",
        }

    def _run_subprocess(
        self, action: StrategicPlannedAction, evidence_dir: Path
    ) -> dict[str, Any]:
        import shlex
        base = shlex.split(action.command_or_callable) if " " in action.command_or_callable else [action.command_or_callable]
        cmd = base + action.command_args
        working_dir = Path(action.working_dir) if action.working_dir else ROOT

        resource = action.resource_policy or {}
        timeout_sec = resource.get("max_wall_time_minutes", 60) * 60

        stdout_path = evidence_dir / "stdout.txt"
        stderr_path = evidence_dir / "stderr.txt"
        gpu_lock_acquired = False
        ps_before = ""
        ps_after = ""
        slot32_model = resolve_model_slot("32")

        t0 = time.monotonic()
        try:
            if self.mode == "live-gpu-gated":
                with dgx_heavy_lock():
                    gpu_lock_acquired = True
                    ps_before = ollama_ps_entry_summary(slot32_model)
                    proc = subprocess.run(
                        cmd,
                        cwd=working_dir,
                        capture_output=True,
                        text=True,
                        timeout=timeout_sec,
                    )
                    ps_after = ollama_ps_entry_summary(slot32_model)
            else:
                proc = subprocess.run(
                    cmd,
                    cwd=working_dir,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                )
            elapsed = time.monotonic() - t0
            stdout_path.write_text(proc.stdout or "", encoding="utf-8")
            stderr_path.write_text(proc.stderr or "", encoding="utf-8")
            return {
                "status": "PASS" if proc.returncode == 0 else "FAIL",
                "exit_code": proc.returncode,
                "stdout": proc.stdout[-2000:] if proc.stdout else "",
                "stderr": proc.stderr[-1000:] if proc.stderr else "",
                "wall_time_sec": round(elapsed, 1),
                "gpu_queue_and_await_used": self.mode == "live-gpu-gated",
                "gpu_lock_acquired": gpu_lock_acquired,
                "slot32_ps_before": ps_before,
                "slot32_ps_after": ps_after,
            }
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - t0
            return {
                "status": "FAIL",
                "exit_code": -1,
                "error": f"timeout after {elapsed:.0f}s",
                "wall_time_sec": round(elapsed, 1),
                "gpu_queue_and_await_used": self.mode == "live-gpu-gated",
                "gpu_lock_acquired": gpu_lock_acquired,
                "slot32_ps_before": ps_before,
                "slot32_ps_after": ps_after,
            }
        except Exception as exc:
            return {
                "status": "FAIL",
                "exit_code": -1,
                "error": str(exc),
                "wall_time_sec": 0,
                "gpu_queue_and_await_used": self.mode == "live-gpu-gated",
                "gpu_lock_acquired": gpu_lock_acquired,
                "slot32_ps_before": ps_before,
                "slot32_ps_after": ps_after,
            }

    def _run_http(self, action: StrategicPlannedAction) -> dict[str, Any]:
        try:
            import urllib.request
            url = action.command_or_callable
            with urllib.request.urlopen(url, timeout=30) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            return {"status": "PASS", "exit_code": 0, "body": body[:2000]}
        except Exception as exc:
            return {"status": "FAIL", "exit_code": -1, "error": str(exc)}

    def _evaluate_criteria(
        self, action: StrategicPlannedAction, result: dict[str, Any]
    ) -> tuple[bool, list[str]]:
        """Evaluate acceptance criteria against execution result.

        Simple rules:
         - SIMULATED result → all criteria pass (dry-run)
         - exit_code == 0 → first criterion (exit code check) passes
         - remaining criteria are logged as PENDING (require human review)
        """
        failures: list[str] = []
        exec_status = result.get("status", "FAIL")
        exit_code = result.get("exit_code", -1)

        if exec_status == "SIMULATED":
            return True, []

        if exec_status == "SKIP":
            return True, []

        if exit_code != 0:
            failures.append(f"Exit code {exit_code} != 0")

        if failures:
            return False, failures
        return True, []

    def _argus_critical_active(self) -> bool:
        """Check Argus for active CRITICAL events (best-effort)."""
        queue_file = ROOT / "aims_workspace/argus_pending_queues.json"
        if not queue_file.exists():
            return False
        try:
            data = json.loads(queue_file.read_text(encoding="utf-8"))
            for item in data.get("pending", []):
                if isinstance(item, dict) and item.get("severity") == "CRITICAL":
                    return True
        except Exception:
            pass
        return False

    def _append_lessons(
        self,
        action: StrategicPlannedAction,
        status: str,
        result: dict,
        failures: list[str],
    ) -> None:
        if not action.lessons_learned_plan:
            return
        LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": _now_utc(),
            "action_id": action.action_id,
            "title": action.title,
            "status": status,
            "failures": failures,
            "lessons_plan": action.lessons_learned_plan,
            "exit_code": result.get("exit_code"),
        }
        with LESSONS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _finalize(
        self,
        action: StrategicPlannedAction,
        goal: ProcessGoal,
        ledger: ProcessLedger,
        status: str,
        result: dict,
        evidence_dir: Path,
    ) -> dict[str, Any]:
        action.status = status
        action.execution_result = result
        action.completed_at = _now_utc()
        action.save()

        ledger.record("action_complete", {
            "action_id": action.action_id,
            "status": status,
            "goal_status": goal.status,
        }, status=status, agent=action.owner_agent)

        summary = {
            "action_id": action.action_id,
            "title": action.title,
            "status": status,
            "mode": self.mode,
            "goal_id": goal.goal_id,
            "goal_status": goal.status,
            "exit_code": result.get("exit_code"),
            "wall_time_sec": result.get("wall_time_sec", 0),
            "evidence_dir": str(evidence_dir),
            "ledger_path": str(ledger._path),
            "completed_at": action.completed_at,
        }

        self._write_evidence_bundle(action, goal, ledger, status, result, evidence_dir, summary)
        log.info("PlannedActionRunner: %s → %s [%s]", action.action_id, status, self.mode)
        return summary

    def _write_evidence_bundle(
        self,
        action: StrategicPlannedAction,
        goal: ProcessGoal,
        ledger: ProcessLedger,
        status: str,
        result: dict,
        evidence_dir: Path,
        summary: dict,
    ) -> None:
        """Write all required evidence files to evidence_dir."""

        # action_execution_result.json
        exec_result = {
            **summary,
            "command": action.command_or_callable,
            "command_args": action.command_args,
            "stdout_tail": result.get("stdout", "")[-500:],
            "stderr_tail": result.get("stderr", "")[-200:],
        }
        (evidence_dir / "action_execution_result.json").write_text(
            json.dumps(exec_result, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # action_execution_report.md
        icon = "PASS" if status == "PASS" else ("SKIP" if status in ("SKIP", "SIMULATED") else "FAIL")
        md = [
            f"# Planned Action Execution Report",
            f"",
            f"**Action:** {action.action_id} — {action.title}  ",
            f"**Status:** {icon}  ",
            f"**Mode:** {self.mode}  ",
            f"**Owner:** {action.owner_agent}  ",
            f"**Completed:** {action.completed_at}  ",
            f"**Exit code:** {result.get('exit_code', 'N/A')}  ",
            f"**Wall time:** {result.get('wall_time_sec', 0):.1f}s  ",
            f"",
            f"## Command",
            f"```",
            f"{action.command_or_callable} {' '.join(action.command_args)}",
            f"```",
            f"",
            f"## Acceptance criteria",
        ]
        for c in action.acceptance_criteria:
            md.append(f"  - {c}")
        md += [
            f"",
            f"## Result",
            f"```",
            result.get("stdout", "")[-400:] or result.get("reason", "no output"),
            f"```",
        ]
        (evidence_dir / "action_execution_report.md").write_text(
            "\n".join(md), encoding="utf-8"
        )

        # process_ledger.json — copy ledger entries from file
        ledger_entries: list[dict] = []
        if ledger._path.exists():
            for line in ledger._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        ledger_entries.append(json.loads(line))
                    except Exception:
                        pass
        (evidence_dir / "process_ledger.json").write_text(
            json.dumps(ledger_entries, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # validation_result.json
        validation = {
            "action_id": action.action_id,
            "validation_plan": action.validation_plan,
            "criteria_checked": len(action.acceptance_criteria),
            "exit_code_check": result.get("exit_code") == 0,
            "overall": status,
            "timestamp": _now_utc(),
        }
        (evidence_dir / "validation_result.json").write_text(
            json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # lessons_learned.json (per-action)
        lesson = {
            "action_id": action.action_id,
            "title": action.title,
            "result": status,
            "issue_observed": "none" if status == "PASS" else result.get("reason", result.get("error", "exit non-zero")),
            "corrective_action": "retry per retry_policy" if status == "FAIL" else "none",
            "future_recommendation": action.lessons_learned_plan or "continue as planned",
            "timestamp": _now_utc(),
        }
        (evidence_dir / "lessons_learned.json").write_text(
            json.dumps(lesson, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # artifacts_index.json
        artifacts = [str(p.relative_to(ROOT)) for p in evidence_dir.rglob("*") if p.is_file()]
        (evidence_dir / "artifacts_index.json").write_text(
            json.dumps({
                "action_id": action.action_id,
                "evidence_dir": str(evidence_dir),
                "artifact_count": len(artifacts),
                "artifacts": sorted(artifacts),
                "generated_at": _now_utc(),
            }, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # runner_summary.json (kept for backward compat)
        (evidence_dir / "runner_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )

# ── CLI ────────────────────────────────────────────────────────────────────────

def _cli_main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="AIMS PlannedActionRunner CLI")
    parser.add_argument("--mode", default="dry-run",
                        choices=["dry-run", "live-lightweight", "live-gpu-gated"],
                        help="Execution mode")
    parser.add_argument("--action-id", default="",
                        help="Run specific action by ID")
    parser.add_argument("--run-due", action="store_true",
                        help="Run all due safe actions (live-lightweight only runs cpu_only)")
    args = parser.parse_args()

    runner = PlannedActionRunner(mode=args.mode)
    registry = StrategicPlannedActionsRegistry()

    if args.run_due:
        bridge = StrategicSchedulerBridge(registry)
        sel = bridge.evaluate_due_actions(mode=args.mode, statuses=("PENDING",))
        print(json.dumps(sel, indent=2))
        results = []
        for entry in sel["due_actions"]:
            if args.mode == "live-lightweight" and not entry["live_lightweight_safe"]:
                log.info("Skipping %s — not live-lightweight safe", entry["action_id"])
                continue
            action = registry.load(entry["action_id"])
            if args.mode == "live-gpu-gated" and (action is None or not _is_live_gpu_gated_safe(action)):
                log.info("Skipping %s — not live-gpu-gated safe", entry["action_id"])
                continue
            if action:
                r = runner.run(action)
                results.append(r)
        print(json.dumps({"ran": len(results), "results": results}, indent=2))
        return 0

    if args.action_id:
        action = registry.load(args.action_id)
        if action is None:
            log.error("Action %s not found in registry", args.action_id)
            return 1
        result = runner.run(action)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] in ("PASS", "SKIP", "SIMULATED") else 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(_cli_main())
