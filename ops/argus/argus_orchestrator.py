"""
argus_orchestrator.py
─────────────────────
Plan-driven task orchestrator for Argus.

Reads YAML plan files from ARGUS_PLANS_DIR and executes steps on schedule.
- Scheduled steps run automatically (no human approval)
- Destructive steps (requires_approval=true) send Telegram inline buttons
- Missed steps are detected and run as catch-up (with notification)
- Morning digest summarises overnight activity + execution status

Claude Code prepares plans; Argus executes them.

Env vars:
  ARGUS_PLANS_DIR         — directory with *.yaml plan files (default: /workspace/ops/argus/plans)
  ARGUS_DIGEST_HOUR       — hour (local time) to send morning digest (default: 7)
  ARGUS_ORCHESTRATOR_SEC  — plan loop interval in seconds (default: 60)
  ARGUS_CATCH_UP_HOURS    — look-back window for missed steps, hours (default: 20)
  TASK_REGISTRY_URL       — task registry API (default: http://localhost:8765)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
import sys
import os

# Ensure /ops is in path so we can import orchestrator_planning
sys.path.insert(0, '/ops')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from argus_code_agent import RepairAgent
try:
    from orchestrator_planning.argus_digest_remediation_policy import (
        auto_healing_summary,
        normalize_problem_name,
        recommended_user_steps,
    )
except ModuleNotFoundError:
    # Fallback: provide stub implementations if orchestrator_planning is not available
    def auto_healing_summary(msg: str) -> str:
        return msg

    def normalize_problem_name(name: str) -> str:
        return name.lower().replace(" ", "_")

    def recommended_user_steps(context: str) -> list:
        return ["Check logs", "Restart service"]

# Import more orchestrator_planning modules with fallback
try:
    from orchestrator_planning.argus_repairman_followup_contract import build_repairman_followup_contract
    from orchestrator_planning.argus_repairman_followup_contract import build_repairman_followup_task_payload
    from orchestrator_planning.argus_repairman_followup_contract import build_followup_plain_english_notice
    from orchestrator_planning.night_digest_evidence_checker import collect_night_digest_evidence
except ModuleNotFoundError:
    # Stub implementations
    def build_repairman_followup_contract(**kwargs) -> dict:
        return {"status": "pending"}

    def build_repairman_followup_task_payload(contract: dict) -> dict:
        return contract

    def build_followup_plain_english_notice(payload: dict) -> str:
        return "Repair task pending"

    def collect_night_digest_evidence(date: str) -> dict:
        return {"collected_at": date}

log = logging.getLogger("argus.orchestrator")

# ── Config ─────────────────────────────────────────────────────────────────────
PLANS_DIR = Path(os.environ.get("ARGUS_PLANS_DIR", "/workspace/ops/argus/plans"))
DIGEST_HOUR = int(os.environ.get("ARGUS_DIGEST_HOUR", "7"))
LOOP_INTERVAL = int(os.environ.get("ARGUS_ORCHESTRATOR_SEC", "60"))
TASK_REGISTRY_URL = os.environ.get("TASK_REGISTRY_URL", "http://localhost:8765")
STATE_FILE = Path(os.environ.get("ARGUS_ORCHESTRATOR_STATE", "/data/argus_orch_state.json"))
CATCH_UP_HOURS = int(os.environ.get("ARGUS_CATCH_UP_HOURS", "20"))
# Anti-storm guards for catch-up mode
CATCH_UP_MAX_PER_TICK = max(1, int(os.environ.get("ARGUS_CATCH_UP_MAX_PER_TICK", "3")))
CATCH_UP_STARTUP_GRACE_SEC = max(0, int(os.environ.get("ARGUS_CATCH_UP_STARTUP_GRACE_SEC", "300")))

# ── Cron helpers ───────────────────────────────────────────────────────────────
def _cron_field_matches(field: str, value: int) -> bool:
    if field == "*":
        return True
    if "," in field:
        return any(_cron_field_matches(f.strip(), value) for f in field.split(","))
    if field.startswith("*/"):
        try:
            return value % int(field[2:]) == 0
        except:
            return False
    if "-" in field:
        a, b = field.split("-", 1)
        try:
            return int(a) <= value <= int(b)
        except:
            return False
    try:
        return int(field) == value
    except:
        return False


def cron_matches(expr: str, dt: datetime) -> bool:
    parts = expr.split()
    if len(parts) != 5:
        return False
    m, h, d, mo, w = parts
    return (
        _cron_field_matches(m, dt.minute)
        and _cron_field_matches(h, dt.hour)
        and _cron_field_matches(d, dt.day)
        and _cron_field_matches(mo, dt.month)
        and _cron_field_matches(w, dt.weekday())
    )


def _last_expected_firing(expr, since, before):
    t = before.replace(second=0, microsecond=0) - timedelta(minutes=1)
    floor = since.replace(second=0, microsecond=0)
    while t >= floor:
        if cron_matches(expr, t):
            return t
        t -= timedelta(minutes=1)
    return None


def _next_expected_firing(expr, after):
    t = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 14):
        if cron_matches(expr, t):
            return t
        t += timedelta(minutes=1)
    return None


def _should_defer_catchup(step: "PlanStep", expected: datetime, now: datetime) -> bool:
    if step.catch_up_policy != "next_window_only":
        return False
    if step.max_catch_up_lateness_minutes is None:
        return now > expected
    return (now - expected) > timedelta(minutes=step.max_catch_up_lateness_minutes)


# ── Data structures ────────────────────────────────────────────────────────────
@dataclass
class PlanStep:
    id: str
    description: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    cron: str | None = None
    trigger: str | None = None
    requires_approval: bool = False
    approval_reason: str | None = None
    include_in_digest: bool = True
    plan_name: str = ""
    enabled_from: str | None = None
    catch_up_policy: str = "default"
    max_catch_up_lateness_minutes: int | None = None


@dataclass
class DigestEntry:
    ts: datetime
    step_id: str
    description: str
    status: str
    detail: str = ""
    is_catchup: bool = False


# ── State persistence ──────────────────────────────────────────────────────────

class OrchestratorState:
    """JSON-file-backed state: last run times, last status, overnight digest buffer."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text())
        except Exception as e:
            log.warning("state load failed: %s", e)
            self._data = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2, default=str))
        except Exception as e:
            log.warning("state save failed: %s", e)

    def last_run(self, step_id: str) -> datetime | None:
        with self._lock:
            ts = self._data.get(f"last_run:{step_id}")
            if ts:
                try:
                    return datetime.fromisoformat(ts)
                except Exception:
                    return None
            return None

    def mark_run(self, step_id: str, dt: datetime, status: str = "ok", detail: str = "") -> None:
        with self._lock:
            self._data[f"last_run:{step_id}"] = dt.isoformat()
            self._data[f"last_status:{step_id}"] = {
                "status": status,
                "detail": detail[:300],
                "ts": dt.isoformat(),
            }
            self._save()

    def last_status(self, step_id: str) -> dict | None:
        """Returns {"status": "ok"|"failed"|..., "detail": "...", "ts": "..."} or None."""
        with self._lock:
            return self._data.get(f"last_status:{step_id}")

    def push_digest(self, entry: DigestEntry) -> None:
        with self._lock:
            buf = self._data.setdefault("digest_buffer", [])
            buf.append({
                "ts": entry.ts.isoformat(),
                "step_id": entry.step_id,
                "description": entry.description,
                "status": entry.status,
                "detail": entry.detail,
                "is_catchup": entry.is_catchup,
            })
            self._save()

    def pop_digest(self) -> list[DigestEntry]:
        with self._lock:
            buf = self._data.pop("digest_buffer", [])
            self._save()
        result = []
        for b in buf:
            try:
                result.append(DigestEntry(
                    ts=datetime.fromisoformat(b["ts"]),
                    step_id=b["step_id"],
                    description=b["description"],
                    status=b["status"],
                    detail=b.get("detail", ""),
                    is_catchup=b.get("is_catchup", False),
                ))
            except Exception:
                pass
        return result

    def set_pending_approval(self, step_id: str, step_data: dict) -> None:
        with self._lock:
            self._data[f"pending:{step_id}"] = step_data
            self._save()

    def get_pending_approval(self, step_id: str) -> dict | None:
        with self._lock:
            return self._data.get(f"pending:{step_id}")

    def clear_pending_approval(self, step_id: str) -> None:
        with self._lock:
            self._data.pop(f"pending:{step_id}", None)
            self._save()

    def get_meta(self, key: str) -> Any:
        with self._lock:
            return self._data.get(f"meta:{key}")

    def set_meta(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[f"meta:{key}"] = value
            self._save()


# ── Plan loader ────────────────────────────────────────────────────────────────

def _load_plans(plans_dir: Path) -> list[PlanStep]:
    def _to_bool(val: object, default: bool = False) -> bool:
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            norm = val.strip().lower()
            if norm in {"1", "true", "yes", "y", "on"}:
                return True
            if norm in {"0", "false", "no", "n", "off", ""}:
                return False
            return default
        return bool(val)

    steps: list[PlanStep] = []
    if not plans_dir.exists():
        log.info("plans dir not found: %s", plans_dir)
        return steps

    try:
        import yaml  # type: ignore
    except ImportError:
        log.error("PyYAML not installed — orchestrator disabled. pip install pyyaml")
        return steps

    for yf in sorted(plans_dir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(yf.read_text())
            plan_name = doc.get("name", yf.stem)
            for s in doc.get("steps", []):
                step = PlanStep(
                    id=s["id"],
                    description=s.get("description", s["id"]),
                    action=s.get("action", "notify"),
                    params=s.get("params", {}),
                    cron=s.get("cron"),
                    trigger=s.get("trigger"),
                    requires_approval=_to_bool(s.get("requires_approval", False), default=False),
                    approval_reason=s.get("approval_reason"),
                    include_in_digest=_to_bool(s.get("include_in_digest", True), default=True),
                    plan_name=plan_name,
                    enabled_from=s.get("enabled_from"),
                    catch_up_policy=s.get("catch_up_policy", "default"),
                    max_catch_up_lateness_minutes=(
                        int(s["max_catch_up_lateness_minutes"])
                        if s.get("max_catch_up_lateness_minutes") is not None
                        else None
                    ),
                )
                steps.append(step)
            log.info("loaded plan %r: %d steps", plan_name, len(doc.get("steps", [])))
        except Exception as e:
            log.error("failed to load plan %s: %s", yf, e)

    return steps


# ── Action executors ───────────────────────────────────────────────────────────

def _exec_create_task(params: dict) -> tuple[bool, str]:
    """POST /tasks to Task Registry."""
    import urllib.request
    payload = {
        "title": params.get("title", "Argus scheduled task"),
        "source": params.get("source", "argus"),
        "chat_id": params.get("chat_id", "argus"),
        "description": params.get("description", ""),
        "agent": params.get("agent", ""),
    }
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{TASK_REGISTRY_URL}/tasks",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            tid = body.get("task_id", "?")
            return True, f"task_id={tid}"
    except Exception as e:
        return False, str(e)


def _exec_run_script(params: dict) -> tuple[bool, str]:
    """Run a shell command/script. 'script' can be path or full command."""
    script = str(params.get("script", "")).strip()
    if not script:
        return False, "no script specified"
    workspace = os.environ.get("AIMS_WORKSPACE", "/workspace")
    try:
        # Backward-compatible mode:
        # - if `script` points to an existing file:
        #     *.py -> run with python3
        #     else -> run with bash
        # - otherwise treat it as a shell command line (supports args)
        full = Path(workspace) / script
        if full.exists():
            cmd = ["python3", str(full)] if full.suffix == ".py" else ["bash", str(full)]
        else:
            cmd = ["bash", "-lc", script]
        result = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True, text=True, timeout=300,
        )
        ok = result.returncode == 0
        out = (result.stdout + result.stderr)[:400]
        return ok, out.strip()
    except subprocess.TimeoutExpired:
        return False, "script timed out (300s)"
    except Exception as e:
        return False, str(e)


def _exec_notify(params: dict) -> tuple[bool, str]:
    """No-op executor — message is sent by the orchestrator loop itself."""
    return True, params.get("message", "")


# ── Main orchestrator class ────────────────────────────────────────────────────

from argus_code_agent import RepairAgent

class ArgusOrchestrator:
    """
    Runs a background thread that checks plan steps every LOOP_INTERVAL seconds.
    - Fires steps whose cron expression matches the current time (once per minute).
    - Detects missed steps (cron expected to fire but didn't, within CATCH_UP_HOURS)
      and runs them as catch-ups with a Telegram notification.
    - Calls on_event(step, status, detail) to send Telegram messages via argus_bot.
    """

    def __init__(
        self,
        on_notify: Callable[[str], None] | None = None,
        on_approval_request: Callable[[PlanStep], None] | None = None,
        storage: "ArgusStorage | None" = None,
    ) -> None:
        self._on_notify = on_notify or (lambda _msg: None)
        self._on_approval_request = on_approval_request or (lambda _step: None)
        self._storage = storage
        self._state = OrchestratorState(STATE_FILE)
        self._steps: list[PlanStep] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._digest_sent_today: set[str] = set()

        # 🔧 ВАЖНО: инициализация RepairAgent
        self._repair = RepairAgent()

        # Pending approval
        self._pending: dict[str, PlanStep] = {}
        self._pending_lock = threading.Lock()

        # Catch-up dedup
        self._catchup_attempted: dict[str, datetime] = {}
        self._catchup_lock = threading.Lock()
        self._started_at: datetime | None = None

    def reload_plans(self) -> int:
        self._steps = _load_plans(PLANS_DIR)
        return len(self._steps)

    def start(self) -> None:
        self.reload_plans()
        self._started_at = datetime.now()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="argus-orchestrator"
        )
        self._thread.start()
        log.info("ArgusOrchestrator started: %d steps loaded", len(self._steps))

    def stop(self) -> None:
        self._stop.set()

    # ── MAIN LOOP ─────────────────────────────────────────────

    def _loop(self) -> None:
        last_minute = -1
        while not self._stop.wait(timeout=15):
            now = datetime.now()

            if now.minute == last_minute:
                continue

            last_minute = now.minute
            self._tick(now)

    def _tick(self, now: datetime) -> None:
        # 1. обычные шаги
        for step in self._steps:
            if not step.cron:
                continue

            if step.enabled_from and now.date() < datetime.strptime(
                step.enabled_from, "%Y-%m-%d"
            ).date():
                continue

            if not cron_matches(step.cron, now):
                continue

            last = self._state.last_run(step.id)
            if last and (now - last).total_seconds() < 50:
                continue

            log.info("plan step fired: %s", step.id)
            self._state.mark_run(step.id, now)
            self._fire(step, now, is_catchup=False)

        # 2. catch-up
        self._run_catchups(now)

    def _execute_action(self, step: PlanStep) -> tuple[bool, str]:
        action = step.action
        if action == "create_task":
            return _exec_create_task(step.params)
        if action == "run_script":
            return _exec_run_script(step.params)
        if action == "notify":
            return _exec_notify(step.params)
        if action == "send_digest":
            return True, "digest"
        log.warning("unknown action: %s", action)
        return False, f"unknown action: {action}"

    # ── EXECUTION ─────────────────────────────────────────────

    def _fire(self, step: PlanStep, now: datetime, is_catchup: bool = False) -> None:
        if step.requires_approval:
            self._request_approval(step)
            return

        if step.action == "send_digest":
            self._send_morning_digest(now)
            return

        ok, detail = self._execute_action(step)

        status_key = (
            "catchup_ok" if ok else "catchup_fail"
        ) if is_catchup else (
            "ok" if ok else "failed"
        )

        # 🔧 AUTO-REPAIR
        if not ok:
            try:
                repair_result = self._repair.fix_from_context({
                    "error": detail,
                    "context": {
                        "step_id": step.id,
                        "plan": step.plan_name,
                        "action": step.action,
                        "params": step.params,
                    },
                    "output": detail,
                })

                self._on_notify(
                    f"Auto-repair applied.\n"
                    f"Issue: {step.description}.\n"
                    f"Status: not critical yet.\n"
                    f"Repair summary: {repair_result[:300]}"
                )

            except Exception as e:
                self._on_notify(
                    f"Repair attempt failed.\n"
                    f"Issue: {step.description}.\n"
                    f"Status: still unresolved.\n"
                    f"Reason: {str(e)[:240]}"
                )
            self._maybe_prepare_repairman_followup(step, detail, now)

        # state
        self._state.mark_run(step.id, now, status=status_key, detail=detail)

        if step.include_in_digest:
            self._state.push_digest(DigestEntry(
                ts=now,
                step_id=step.id,
                description=step.description,
                status=status_key,
                detail=detail[:200],
                is_catchup=is_catchup,
            ))

        # notify
        if not ok:
            self._on_notify(
                f"❌ Step failed\n"
                f"{step.id}\n"
                f"<pre>{detail[:200]}</pre>"
            )
        elif is_catchup:
            self._on_notify(
                f"↩️ Catch-up done\n{step.id}"
            )

    def _maybe_prepare_repairman_followup(self, step: PlanStep, detail: str, now: datetime) -> None:
        if step.params.get("agent") == "repairman" or "repairman" in step.id.lower():
            return

        contract = build_repairman_followup_contract(
            step_id=step.id,
            description=step.description,
            status="failed",
            evidence_inputs=[detail[:300]] if detail else [],
        )
        if contract["problem_type"] == "night-window":
            return
        if not contract.get("safe_to_auto_prepare", False):
            return

        meta_key = f"repairman_followup:{step.id}"
        last_created = self._state.get_meta(meta_key)
        if last_created:
            try:
                last_dt = datetime.fromisoformat(last_created)
                if (now - last_dt).total_seconds() < 6 * 3600:
                    return
            except Exception:
                pass

        payload = build_repairman_followup_task_payload(contract)
        ok, task_detail = _exec_create_task(payload)
        if ok:
            self._state.set_meta(meta_key, now.isoformat())
            self._on_notify(build_followup_plain_english_notice(contract, task_detail))

    # ── Catch-up logic ─────────────────────────────────────────────────────────

    def _run_catchups(self, now: datetime) -> None:
        """
        For each scheduled step: if there was an expected cron firing in the last
        CATCH_UP_HOURS that was not covered by last_run → fire as catch-up.

        Steps with requires_approval=True are NOT auto-run; instead, a missed-step
        alert is sent to the owner.
        """
        # Startup grace: avoid firing a large backlog immediately after restart.
        if self._started_at is not None and (now - self._started_at).total_seconds() < CATCH_UP_STARTUP_GRACE_SEC:
            return

        since = now - timedelta(hours=CATCH_UP_HOURS)
        launched_this_tick = 0

        for step in self._steps:
            if not step.cron:
                continue
            # Don't catch-up the digest step itself
            if step.action == "send_digest":
                continue
            # Skip steps not yet enabled
            if step.enabled_from and now.date() < datetime.strptime(step.enabled_from, "%Y-%m-%d").date():
                continue

            expected = _last_expected_firing(step.cron, since, now)
            if expected is None:
                continue  # no firing expected in window

            last = self._state.last_run(step.id)
            if last and last >= expected:
                continue  # already ran at or after the expected time

            # Check catch-up dedup: don't retry within 10 min of last attempt
            with self._catchup_lock:
                last_attempt = self._catchup_attempted.get(step.id)
                if last_attempt and (now - last_attempt).total_seconds() < 600:
                    continue
                self._catchup_attempted[step.id] = now

            missed_str = expected.strftime("%d.%m %H:%M")
            log.warning("catch-up: step %s missed at %s", step.id, missed_str)

            if _should_defer_catchup(step, expected, now):
                detail = f"ожидался {missed_str}, перенесён на следующее ночное окно"
                log.info("catch-up deferred: step %s policy=%s", step.id, step.catch_up_policy)
                if step.include_in_digest:
                    self._state.push_digest(DigestEntry(
                        ts=now,
                        step_id=step.id,
                        description=step.description,
                        status="deferred",
                        detail=detail,
                        is_catchup=True,
                    ))
                continue

            if step.requires_approval:
                # Alert only — don't auto-run approval-guarded steps
                self._on_notify(
                    f"⚠️ <b>Пропущен шаг (требует одобрения)</b>\n"
                    f"Step: <code>{step.id}</code>\n"
                    f"Ожидался: {missed_str}\n"
                    f"Используй /plan run {step.id} для ручного запуска."
                )
                if step.include_in_digest:
                    self._state.push_digest(DigestEntry(
                        ts=now, step_id=step.id,
                        description=step.description,
                        status="missed",
                        detail=f"ожидался {missed_str}, требует одобрения",
                        is_catchup=True,
                    ))
            else:
                # Auto catch-up
                self._on_notify(
                    f"↩️ <b>Catch-up запущен</b>: <code>{step.id}</code>\n"
                    f"Ожидался: {missed_str}, запускаю сейчас."
                )
                self._state.mark_run(step.id, now)
                self._fire(step, now, is_catchup=True)
                launched_this_tick += 1
                if launched_this_tick >= CATCH_UP_MAX_PER_TICK:
                    log.info(
                        "catch-up throttle reached: launched=%s max_per_tick=%s",
                        launched_this_tick,
                        CATCH_UP_MAX_PER_TICK,
                    )
                    break


# ── Step execution ─────────────────────────────────────────────────────────
def _fire(self, step: PlanStep, now: datetime, is_catchup: bool = False) -> None:
    if step.requires_approval:
        self._request_approval(step)
        return

    if step.action == "send_digest":
        self._send_morning_digest(now)
        return

    ok, detail = self._execute_action(step)

    status_key = ("catchup_ok" if ok else "catchup_fail") if is_catchup else ("ok" if ok else "failed")
    icon = "✅" if ok else "❌"
    catchup_tag = " (catch-up)" if is_catchup else ""

    # 🔧 AUTO-REPAIR
    if not ok:
        try:
            log.warning("triggering repair agent for step: %s", step.id)

            repair_result = self._repair.fix_from_context({
                "error": detail,
                "context": {
                    "step_id": step.id,
                    "plan": step.plan_name,
                    "action": step.action,
                    "params": step.params,
                },
                "output": detail,
            })

            self._on_notify(
                f"🛠 <b>Auto-repair выполнен</b>\n"
                f"Step: <code>{step.id}</code>\n"
                f"<pre>{repair_result[:500]}</pre>"
            )

        except Exception as repair_error:
            self._on_notify(
                f"❌ <b>Repair failed</b>\n"
                f"Step: <code>{step.id}</code>\n"
                f"<pre>{str(repair_error)[:300]}</pre>"
            )

    # запись состояния
    self._state.mark_run(step.id, now, status=status_key, detail=detail)

    if step.include_in_digest:
        self._state.push_digest(DigestEntry(
            ts=now,
            step_id=step.id,
            description=step.description,
            status=status_key,
            detail=detail[:200],
            is_catchup=is_catchup,
        ))

    # уведомления
    if not ok:
        self._on_notify(
            f"{icon} <b>Step failed{catchup_tag}</b>\n"
            f"Step: <code>{step.id}</code>\n"
            f"Plan: {step.plan_name}\n"
            f"Error: <pre>{detail[:300]}</pre>"
        )
    elif is_catchup:
        self._on_notify(
            f"↩️ {icon} <b>Catch-up выполнен</b>: <code>{step.id}</code>\n"
            f"{detail[:200]}"
        )


    # ── ACTION EXECUTION ─────────────────────────────────────

    def _execute_action(self, step: PlanStep) -> tuple[bool, str]:
        action = step.action

        if action == "create_task":
            return _exec_create_task(step.params)

        elif action == "run_script":
            return _exec_run_script(step.params)

        elif action == "notify":
            msg = step.params.get("message", step.description)
            self._on_notify(msg)
            return True, "notified"

        elif action == "send_digest":
            return True, "digest"

        else:
            log.warning("unknown action: %s", action)
            return False, f"unknown action: {action}"

    # ── APPROVAL FLOW ───────────────────────────────────────

    def _request_approval(self, step: PlanStep) -> None:
        with self._pending_lock:
            self._pending[step.id] = step

        self._state.set_pending_approval(step.id, {
            "id": step.id,
            "description": step.description,
            "action": step.action,
            "params": step.params,
        })

        self._on_approval_request(step)

    def approve(self, step_id: str) -> str:
        with self._pending_lock:
            step = self._pending.pop(step_id, None)

        self._state.clear_pending_approval(step_id)

        if step is None:
            return "⚠️ Шаг не найден или уже выполнен"

        ok, detail = self._execute_action(step)

        status = "approved+ok" if ok else "approved+fail"
        icon = "✅" if ok else "❌"

        self._state.mark_run(step_id, datetime.now(), status=status, detail=detail)

        if step.include_in_digest:
            self._state.push_digest(DigestEntry(
                ts=datetime.now(),
                step_id=step.id,
                description=step.description,
                status=status,
                detail=detail[:200],
            ))

        return f"{icon} <b>{step.description}</b>\n<pre>{detail[:300]}</pre>"

    def defer(self, step_id: str, hours: int = 12) -> str:
        with self._pending_lock:
            step = self._pending.pop(step_id, None)

        self._state.clear_pending_approval(step_id)

        if step is None:
            return "⚠️ Шаг не найден"

        fake_ts = datetime.now() - timedelta(seconds=LOOP_INTERVAL) + timedelta(hours=hours)

        self._state.mark_run(
            step.id,
            fake_ts,
            status="deferred",
            detail=f"отложено на {hours}ч"
        )

        if step.include_in_digest:
            self._state.push_digest(DigestEntry(
                ts=datetime.now(),
                step_id=step.id,
                description=step.description,
                status="deferred",
                detail=f"отложено на {hours}ч",
            ))

        return f"⏸ <b>{step.description}</b> отложено на {hours} ч"

    def cancel(self, step_id: str) -> str:
        with self._pending_lock:
            step = self._pending.pop(step_id, None)

        self._state.clear_pending_approval(step_id)

        if step is None:
            return "⚠️ Шаг не найден"

        self._state.mark_run(step.id, datetime.now(), status="cancelled")

        if step.include_in_digest:
            self._state.push_digest(DigestEntry(
                ts=datetime.now(),
                step_id=step.id,
                description=step.description,
                status="cancelled",
            ))

        return f"❌ <b>{step.description}</b> отменено"

    # ── Manual trigger (for /plan run <id>) ────────────────────────────────────

    def run_step_now(self, step_id: str) -> str:
        step = next((s for s in self._steps if s.id == step_id), None)
        if step is None:
            return f"⚠️ Шаг <code>{step_id}</code> не найден в планах."
        now = datetime.now()
        if step.requires_approval:
            self._request_approval(step)
            return f"🔐 <b>{step.description}</b>\nОтправлен запрос на одобрение."
        if step.action == "send_digest":
            return self.send_digest_now()
        ok, detail = self._execute_action(step)
        self._state.mark_run(step.id, now, status="ok" if ok else "failed", detail=detail)
        icon = "✅" if ok else "❌"
        return f"{icon} <b>{step.description}</b>\n<pre>{detail[:400]}</pre>"

    # ── Morning digest ─────────────────────────────────────────────────────────

    def _send_morning_digest(self, now: datetime) -> None:
        today = now.strftime("%Y-%m-%d")
        if today in self._digest_sent_today:
            return
        self._digest_sent_today.add(today)
        entries = self._state.pop_digest()
        text = self._format_digest(entries, now)
        self._on_notify(text)
        log.info("morning digest sent: %d entries", len(entries))

    def send_digest_now(self) -> str:
        entries = self._state.pop_digest()
        return self._format_digest(entries, datetime.now())

    def _problem_name(self, step_id: str, description: str) -> str:
        text = (description or step_id).strip()
        text = text.replace("Argus morning digest for ", "")
        text = text.replace("Morning digest delivery for ", "")
        return text[:1].upper() + text[1:] if text else step_id

    def _problem_recommendation(self, step_id: str, description: str) -> str:
        key = f"{step_id} {description}".lower()
        if "traini" in key:
            return (
                "проверить последний artifact в aims_workspace/audit/traini_monitoring/, "
                "сверить health/status Traini и при повторе подготовить новый skill или передать кейс в Repairman"
            )
        if "qwen32" in key:
            return (
                "проверить latest qwen3_32b_coding_night result/logs, "
                "сверить gate/training/eval status и при повторе подготовить новый repair skill"
            )
        if "ft_" in key or "nightly" in key:
            return (
                "проверить последний nightly audit и scheduler logs, "
                "уточнить failing stage и определить, нужен ли новый skill или ручной runtime fix"
            )
        if "docbench" in key:
            return "проверить последний docbench artifact и повторить stage в следующее ночное окно"
        return "проверить последний artifact и scheduler logs, затем решить: новый skill, repair packet или ручной follow-up"

    def _evaluated_problem_lines(self, entries: list[DigestEntry], evidence: dict[str, Any] | None) -> list[str]:
        grouped: dict[str, list[DigestEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.step_id, []).append(entry)

        healed: list[str] = []
        unresolved: list[str] = []

        if evidence is not None:
            if evidence.get("digest_evidence_ready"):
                healed.append("Night evidence completeness — автоисцеление: scheduler-owned artifacts собраны и подтверждены")
            else:
                missing = ", ".join(evidence.get("required_evidence_missing") or []) or "нет данных"
                stale = ", ".join(evidence.get("required_evidence_stale") or []) or "нет"
                unresolved.append(
                    "Night evidence completeness — шаги: проверить missing/stale artifacts "
                    f"({missing}; stale: {stale}) и дождаться следующего ночного окна или вручную добрать evidence"
                )

        for step_id, history in sorted(grouped.items(), key=lambda item: max(e.ts for e in item[1])):
            history = sorted(history, key=lambda e: e.ts)
            latest = history[-1]
            statuses = {entry.status for entry in history}
            name = self._problem_name(step_id, latest.description)

            if latest.status == "deferred":
                healed.append(f"{name} — автоисцеление: ночной запуск перенесен на следующее штатное окно")
                continue

            if latest.status in {"ok", "catchup_ok", "approved+ok"} and statuses & {"failed", "catchup_fail", "missed"}:
                healed.append(f"{name} — автоисцеление: повторный прогон или follow-up завершился успешно")
                continue

            if latest.status in {"failed", "catchup_fail", "missed", "cancelled", "approved+fail"}:
                unresolved.append(f"{name} — шаги: {self._problem_recommendation(step_id, latest.description)}")

        lines: list[str] = []
        if healed:
            lines.append("<b>Исцелено автоматически:</b>")
            for line in healed[:8]:
                lines.append(f"  ✅ {line}")
        if unresolved:
            if lines:
                lines.append("")
            lines.append("<b>Требует вашего решения:</b>")
            for line in unresolved[:8]:
                lines.append(f"  ⚠️ {line}")
        if not lines:
            lines.append("<b>Результат:</b>")
            lines.append("  ✅ Ночных проблем, требующих действий, не выявлено")
        return lines

    def _format_digest(self, entries: list[DigestEntry], now: datetime) -> str:
        date_str = now.strftime("%d %b %Y")
        lines = [f"☀️ <b>Ночной отчёт Argus — {date_str}</b>\n"]

        evidence: dict[str, Any] | None = None
        try:
            evidence = collect_night_digest_evidence(now=now)
            if evidence.get("digest_evidence_ready"):
                lines.append("🧾 Evidence: complete (scheduler-owned night artifacts present)")
            else:
                missing = ", ".join(evidence.get("required_evidence_missing") or [])
                stale = ", ".join(evidence.get("required_evidence_stale") or [])
                detail_parts = []
                if missing:
                    detail_parts.append(f"missing: {missing}")
                if stale:
                    detail_parts.append(f"stale: {stale}")
                detail = " | ".join(detail_parts) if detail_parts else "missing or stale night evidence"
                lines.append(f"⚠️ Evidence: incomplete ({detail})")
            lines.append("ℹ️ Digest basis: scheduler night artifacts, not argus-bot liveness\n")
        except Exception as exc:
            lines.append(f"⚠️ Evidence check unavailable: {exc}")
            lines.append("ℹ️ Digest basis should be scheduler night artifacts\n")

        lines.append("")
        lines.extend(self._evaluated_problem_lines(entries, evidence))

        lines.append("")
        lines.append(self._system_snapshot())
        return "\n".join(lines)

    def _system_snapshot(self) -> str:
        parts = []

        try:
            import shutil
            usage = shutil.disk_usage("/")
            free_gb = usage.free // (1024 ** 3)
            parts.append(f"💾 Диск: {free_gb} GB свободно")
        except Exception:
            pass

        try:
            import urllib.request
            ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
            with urllib.request.urlopen(f"{ollama_url}/api/ps", timeout=3) as r:
                data = json.loads(r.read())
            names = [m.get("name", "?") for m in (data.get("models") or [])]
            parts.append(f"🤖 VRAM: {', '.join(names) if names else 'пусто'}")
        except Exception:
            pass

        try:
            import urllib.request
            url = f"{TASK_REGISTRY_URL}/metrics?hours=12"
            with urllib.request.urlopen(url, timeout=5) as r:
                m = json.loads(r.read())
            done  = m.get("done", 0)
            stuck = m.get("stuck", 0) + m.get("failed", 0)
            parts.append(f"📋 Задачи 12ч: {done} выполнено, {stuck} проблем")
        except Exception:
            pass

        return "\n".join(parts) if parts else ""

    # ── Status for /plan command ───────────────────────────────────────────────

    def status_text(self) -> str:
        if not self._steps:
            return "⚠️ Планов не загружено. Проверьте ARGUS_PLANS_DIR."

        now = datetime.now()
        since = now - timedelta(hours=CATCH_UP_HOURS)

        lines = [f"📅 <b>Планировщик Argus</b> — {len(self._steps)} шагов\n"]

        status_icons = {
            "ok":           "✅",
            "failed":       "❌",
            "catchup_ok":   "↩️✅",
            "catchup_fail": "↩️❌",
            "missed":       "⚠️",
            "deferred":     "⏸",
            "cancelled":    "✖️",
            "approved+ok":  "✅",
            "approved+fail":"❌",
        }
        # ETA for long-running launched steps (minutes). Override via env:
        # ARGUS_STEP_ETA_MIN="ft_prepare_chain_run=240,ft_v7_routing=120"
        eta_by_step: dict[str, int] = {
            "ft_prepare_chain_run": 240,
            "ft_v7_routing": 120,
            "ft_14_nightly": 120,
            "ft_70_nightly": 180,
            "ft_72_nightly": 180,
        }
        raw_eta = os.environ.get("ARGUS_STEP_ETA_MIN", "").strip()
        if raw_eta:
            for part in raw_eta.split(","):
                p = part.strip()
                if "=" not in p:
                    continue
                k, v = p.split("=", 1)
                k = k.strip()
                try:
                    eta_by_step[k] = max(1, int(v.strip()))
                except ValueError:
                    continue

        upcoming: list[tuple[datetime, str, str]] = []

        for step in self._steps:
            last = self._state.last_run(step.id)
            last_status = self._state.last_status(step.id)
            last_str = last.strftime("%d.%m %H:%M") if last else "—"

            with self._pending_lock:
                is_pending = step.id in self._pending
            pending_mark   = " ⏳<i>ждёт одобрения</i>" if is_pending else ""
            approval_mark  = " 🔐" if step.requires_approval else ""

            # Determine health indicator
            if last_status:
                s = last_status.get("status", "")
                health = status_icons.get(s, "•")
            elif step.cron:
                # Check if overdue
                expected = _last_expected_firing(step.cron, since, now)
                health = "⚠️" if expected else "⏳"
            else:
                health = "—"

            # Missed indicator: expected but no last_run or last_run < expected
            missed_mark = ""
            if step.cron and not is_pending:
                expected = _last_expected_firing(step.cron, since, now)
                if expected and (last is None or last < expected):
                    missed_mark = " 🔴<i>пропущен</i>"

            detail_str = ""
            if last_status and last_status.get("detail"):
                detail_str = f"\n  └ {last_status['detail'][:80]}"

            # For launchers that return immediately (nohup/remote pid), show running + ETA.
            running_mark = ""
            if last and last_status:
                detail = str(last_status.get("detail", ""))
                status = str(last_status.get("status", ""))
                launched = ("remote_pid=" in detail) or ("local_nohup pid=" in detail)
                if launched and status in {"ok", "approved+ok", "catchup_ok"}:
                    eta_min = eta_by_step.get(step.id, 120)
                    eta_at = last + timedelta(minutes=eta_min)
                    if now <= eta_at:
                        running_mark = f" 🟡<i>in progress, ETA ~{eta_at.strftime('%H:%M')}</i>"
                    else:
                        running_mark = " ⌛<i>launched, ETA passed</i>"

            next_str = "—"
            if step.cron:
                nxt = _next_expected_firing(step.cron, now)
                if nxt is not None:
                    next_str = nxt.strftime("%d.%m %H:%M")
                    upcoming.append((nxt, step.id, step.description))

            lines.append(
                f"{health} <b>{step.id}</b>{approval_mark}{pending_mark}{missed_mark}{running_mark}\n"
                f"  {step.description}\n"
                f"  cron: <code>{step.cron or step.trigger or '—'}</code>"
                f"  | last: {last_str} | next: {next_str}{detail_str}"
            )

        if upcoming:
            lines.append("\n<b>Дальше по расписанию:</b>")
            for dt, sid, desc in sorted(upcoming, key=lambda x: x[0])[:5]:
                lines.append(f"  • <b>{dt.strftime('%d.%m %H:%M')}</b> — <code>{sid}</code> ({desc[:60]})")

        return "\n".join(lines)
        
        # 🔧 AUTO-REPAIR PIPELINE ───────────────────────────────────────────────

        if not ok:
            try:
                log.warning("triggering repair agent for step: %s", step.id)

                repair_result = self._repair.fix_from_context({
                    "error": detail,
                    "context": {
                        "step_id": step.id,
                        "plan": step.plan_name,
                        "action": step.action,
                        "params": step.params,
                    },
                    "output": detail,
                })

                self._on_notify(
                    f"🛠 <b>Auto-repair выполнен</b>\n"
                    f"Step: <code>{step.id}</code>\n"
                    f"<pre>{repair_result[:500]}</pre>"
                )

            except Exception as repair_error:
                self._on_notify(
                    f"❌ <b>Repair failed</b>\n"
                    f"Step: <code>{step.id}</code>\n"
                    f"<pre>{str(repair_error)[:300]}</pre>"
                )
                
        return "\n".join(lines)


# ── Utility: restore pending approvals on restart ───────────────────────────
    def restore_pending(self) -> None:
        """
        Restore pending approvals from persisted state (after restart).
        """
        restored = 0
        for step in self._steps:
            data = self._state.get_pending_approval(step.id)
            if not data:
                continue

            with self._pending_lock:
                self._pending[step.id] = step
                restored += 1

        if restored:
            log.info("restored %d pending approvals from state", restored)


# ── Debug helper ────────────────────────────────────────────────────────────
    def debug_dump(self) -> dict:
        """
        Returns internal state snapshot for debugging.
        """
        with self._pending_lock:
            pending_ids = list(self._pending.keys())

        return {
            "steps_loaded": len(self._steps),
            "pending": pending_ids,
            "last_runs": {
                step.id: (
                    self._state.last_run(step.id).isoformat()
                    if self._state.last_run(step.id)
                    else None
                )
                for step in self._steps
            },
        }


# ── Optional: manual reload + restart ───────────────────────────────────────
    def restart(self) -> None:
        """
        Reload plans and reset loop thread.
        """
        self.stop()
        time.sleep(1)

        self._stop = threading.Event()
        self.reload_plans()

        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="argus-orchestrator",
        )
        self._thread.start()

        log.info("ArgusOrchestrator restarted")


# ── Entry point helper ──────────────────────────────────────────────────────
def create_orchestrator(
    on_notify: Callable[[str], None],
    on_approval_request: Callable[[PlanStep], None],
    storage: "ArgusStorage | None" = None,
) -> ArgusOrchestrator:
    """
    Factory helper (чтобы удобно подключать в argus_bot).
    """
    orch = ArgusOrchestrator(
        on_notify=on_notify,
        on_approval_request=on_approval_request,
        storage=storage,
    )

    orch.reload_plans()
    orch.restore_pending()

    return orch


def _argus_problem_name(self, step_id: str, description: str) -> str:
    return normalize_problem_name(step_id, description)


def _argus_problem_recommendation(self, step_id: str, description: str) -> str:
    contract = build_repairman_followup_contract(
        step_id=step_id,
        description=description,
        status="failed",
    )
    return contract["recommended_user_steps"]


def _argus_evaluated_problem_lines(self, entries: list[DigestEntry], evidence: dict[str, Any] | None) -> list[str]:
    grouped: dict[str, list[DigestEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.step_id, []).append(entry)

    healed: list[str] = []
    unresolved: list[str] = []

    if evidence is not None:
        if evidence.get("digest_evidence_ready"):
            healed.append(f"Night evidence completeness — автоисцеление: {auto_healing_summary('evidence_complete')}")
        else:
            missing = ", ".join(evidence.get("required_evidence_missing") or []) or "нет данных"
            stale = ", ".join(evidence.get("required_evidence_stale") or []) or "нет"
            unresolved.append(
                "Night evidence completeness — шаги: проверить missing/stale artifacts "
                f"({missing}; stale: {stale}) и дождаться следующего ночного окна или вручную добрать evidence"
            )

    for step_id, history in sorted(grouped.items(), key=lambda item: max(e.ts for e in item[1])):
        history = sorted(history, key=lambda e: e.ts)
        latest = history[-1]
        statuses = {entry.status for entry in history}
        name = self._problem_name(step_id, latest.description)

        if latest.status == "deferred":
            healed.append(f"{name} — автоисцеление: {auto_healing_summary('deferred_to_next_window')}")
            continue

        if latest.status in {"ok", "catchup_ok", "approved+ok"} and statuses & {"failed", "catchup_fail", "missed"}:
            healed.append(f"{name} — автоисцеление: {auto_healing_summary('rerun_succeeded')}")
            continue

        if latest.status in {"failed", "catchup_fail", "missed", "cancelled", "approved+fail"}:
            unresolved.append(f"{name} — шаги: {self._problem_recommendation(step_id, latest.description)}")

    lines: list[str] = []
    if healed:
        lines.append("<b>Исцелено автоматически:</b>")
        for line in healed[:8]:
            lines.append(f"  ✅ {line}")
    if unresolved:
        if lines:
            lines.append("")
        lines.append("<b>Требует вашего решения:</b>")
        for line in unresolved[:8]:
            lines.append(f"  ⚠️ {line}")
    if not lines:
        lines.append("<b>Результат:</b>")
        lines.append("  ✅ Ночных проблем, требующих действий, не выявлено")
    return lines


def _argus_format_digest(self, entries: list[DigestEntry], now: datetime) -> str:
    date_str = now.strftime("%d %b %Y")
    lines = [f"☀️ <b>Ночной отчёт Argus — {date_str}</b>\n"]

    evidence: dict[str, Any] | None = None
    try:
        evidence = collect_night_digest_evidence(now=now)
        if evidence.get("digest_evidence_ready"):
            lines.append("🧾 Evidence: complete (scheduler-owned night artifacts present)")
        else:
            missing = ", ".join(evidence.get("required_evidence_missing") or [])
            stale = ", ".join(evidence.get("required_evidence_stale") or [])
            detail_parts = []
            if missing:
                detail_parts.append(f"missing: {missing}")
            if stale:
                detail_parts.append(f"stale: {stale}")
            detail = " | ".join(detail_parts) if detail_parts else "missing or stale night evidence"
            lines.append(f"⚠️ Evidence: incomplete ({detail})")
        lines.append("ℹ️ Digest basis: scheduler night artifacts, not argus-bot liveness\n")
    except Exception as exc:
        lines.append(f"⚠️ Evidence check unavailable: {exc}")
        lines.append("ℹ️ Digest basis should be scheduler night artifacts\n")

    lines.append("")
    lines.extend(self._evaluated_problem_lines(entries, evidence))

    if hasattr(self, "_system_snapshot"):
        lines.append("")
        snapshot = self._system_snapshot()
        if snapshot:
            lines.append(snapshot)
    return "\n".join(lines)


ArgusOrchestrator._problem_name = _argus_problem_name
ArgusOrchestrator._problem_recommendation = _argus_problem_recommendation
ArgusOrchestrator._evaluated_problem_lines = _argus_evaluated_problem_lines
ArgusOrchestrator._format_digest = _argus_format_digest
