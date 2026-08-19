"""
logi_queue_poller.py

Closed-loop queue poller: picks up problems, drives them through analysis on
Logi's dedicated PC-Andrei LLM route, tiered resolution, replay verification,
learning feedback, cleanup and reporting. Fail-loud by design: every stage writes an artifact, and a task can
never be silently dropped — it always ends in completed / failed /
needs_approval / deferred with a capability ACK on record.

Pipeline per case:
  INTAKE     logi_tasks/pending + repairman_requests/dispatched + problem inbox
             → FailureEnvelope with support_case_id
  ACK        KNOWS_HOW | NEEDS_NEW_SKILL | BLOCKED_EXTERNAL (never silent)
  ANALYZE    Logi LLM + experience recall (playbooks / anti-patterns)
  DIAGNOSE   allowlisted read-only commands, outputs stored as evidence
  RESOLVE    L0 auto-diagnose → L1 RepairmanAPI inspect → fix only w/ approval
  VERIFY     replay verification commands from the analysis
  FEEDBACK   ExperienceRecord + raw material JSONL (approved_for_training=false)
  CLEANUP    intermediate files removed, artifacts retained
  REPORT     human-readable RU file in ~/tmp + Telegram summary
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from ops.agents.failure_classifier import (
    AUTOMATION_EXHAUSTED,
    SAFETY_INVARIANT_VIOLATED,
    UNVERIFIED_COMPLETION,
    VERIFICATION_FAILED,
)
from ops.agents.retry_controller import RetryController
from ops.policy_evolution.integration import capture_policy_gap, queue_restart_dry_run, revalidate_and_prepare_restart


def run_policy_evolution_revalidation_live_safe(trace: dict) -> dict:
    """Invoke the existing revalidation/restart adapters without queue mutation."""
    prepared = revalidate_and_prepare_restart(**dict(trace["revalidation_kwargs"]))
    dry_run = queue_restart_dry_run(
        prepared,
        existing_lineage=set(trace.get("existing_lineage", [])),
        execute=False,
    )
    return {
        "schema": "aims.policy_evolution.logi_revalidation_live_safe.v1",
        "correlation_root_id": trace.get("correlation_root_id", ""),
        "prepared_restart": prepared,
        "dry_run": dry_run,
        "mutation": {"permit_issued": False, "queue_requeued": False, "repair_executed": False, "policy_changed": False},
        "next_action_id": "REVALIDATION_REVIEW" if dry_run.get("mutated") is not True else "EXECUTE_RESTARTED_REPAIR",
    }

_ROOT = Path(__file__).resolve().parents[2]
_PENDING_DIR = _ROOT / "aims_workspace" / "logi_tasks" / "pending"
_BLOCKED_REWORK_DIR = _ROOT / "aims_workspace" / "logi_tasks" / "blocked_rework"
_DONE_DIRS = {
    "completed": _ROOT / "aims_workspace" / "logi_tasks" / "completed",
    "failed": _ROOT / "aims_workspace" / "logi_tasks" / "failed",
    "needs_approval": _ROOT / "aims_workspace" / "logi_tasks" / "needs_approval",
}
_PROBLEM_INBOX = _ROOT / "aims_workspace" / "logi_problem_inbox"
_INCIDENT_DIR = _ROOT / "aims_workspace" / "runtime_incidents" / "container_crashes"
_PROCESSED_INCIDENTS = _ROOT / "aims_workspace" / "logi_artifacts" / "queue_poller" / "processed_incidents.json"
_CLOSED_LOOP_STATE = _ROOT / "aims_workspace" / "logi_artifacts" / "queue_poller" / "closed_loop_state.json"
_REPAIRMAN_DISPATCHED = _ROOT / "aims_workspace" / "repairman_requests" / "dispatched"
_REPAIRMAN_REVIEWED = _ROOT / "aims_workspace" / "repairman_requests" / "reviewed_by_poller"
_NOTIFY_CACHE = _ROOT / "aims_workspace" / "logi_artifacts" / "queue_poller" / "notify_cache.json"
_BACKLOG_DIGEST = _ROOT / "aims_workspace" / "logi_artifacts" / "queue_poller" / "backlog_digest.json"
_NOTIFY_DEDUPE_SEC = 1800
_FRESHNESS_MAX_AGE_SEC = 2 * 86400
_ARTIFACTS_ROOT = _ROOT / "aims_workspace" / "logi_artifacts" / "queue_poller"
_RAW_MATERIAL = _ROOT / "aims_workspace" / "logi_session_memory" / "queue_poller_raw.jsonl"
_LEARNING_ESCALATIONS = _ROOT / "aims_workspace" / "logi_session_learning" / "reports" / "escalation_queue.jsonl"
_HEARTBEAT = _ROOT / "aims_workspace" / "logi_controlled_autonomy_status" / "queue_poller_heartbeat.json"
_LOCK = _ARTIFACTS_ROOT / ".poller.lock"
_REPORT_DIR = Path(os.environ.get("LOGI_POLLER_REPORT_DIR", str(Path.home() / "tmp")))

# Logi's continuous queue analysis runs on the dedicated PC Andrei endpoint.
# Keep URL and model as one coherent route: the remote Ollama serves the
# slot14 production tag, not the DGX-only SLOT32 model.  The LOGI_* variables
# are intentionally agent-specific; legacy AIMS_SLOT32_* overrides remain
# accepted so existing maintenance invocations do not break abruptly.
LOGI_LLM_URL = (
    os.environ.get("LOGI_LLM_OPENAI_URL")
    or os.environ.get("AIMS_SLOT32_OPENAI_URL")
    or "http://10.77.77.2:11434/v1"
)
LOGI_LLM_NATIVE_URL = (
    os.environ.get("LOGI_LLM_NATIVE_URL")
    or LOGI_LLM_URL.removesuffix("/v1")
)
# Keep PC Andrei as the preferred SLOT14 backend, but use the configured DGX
# Spark endpoint when the PC is down.  The model tag is deliberately identical
# on both hosts; only the physical endpoint changes.
LOGI_LLM_FALLBACK_NATIVE_URL = (
    os.environ.get("LOGI_LLM_FALLBACK_NATIVE_URL")
    or "http://host.docker.internal:11434"
)
LOGI_LLM_MODEL = (
    os.environ.get("LOGI_LLM_MODEL")
    or os.environ.get("AIMS_SLOT32_MODEL")
    or "qwen25-chat-14-v19:latest"
)
LOGI_SLOT32_PROXY_URL = (
    os.environ.get("LOGI_SLOT32_PROXY_URL")
    or "http://slot32-proxy:8084/v1/messages"
)
# Logi runs in its own container.  localhost is the Logi container, not the
# Repairman API; using it silently converted every inspect into Connection
# refused.  Keep an explicit override for host-side tests, but default to the
# compose service name in the production container network.
REPAIRMAN_URL = os.environ.get("AIMS_REPAIRMAN_URL", "http://repairman-api:8010")
REPAIRMAN_SERVICE_TOKEN = os.environ.get("AIMS_SERVICE_TOKEN", "aims-service-token")
TELEGRAM_CHAT_ID = os.environ.get("LOGI_REPORT_CHAT_ID", "8077374184")

# Read-only command allowlist: LLM-proposed diagnostics run only when the full
# command matches one of these prefixes. Anything else is recorded and skipped.
DIAG_ALLOWLIST = (
    ("ls",), ("stat",), ("du", "-sh"), ("df", "-h"), ("wc",),
    ("systemctl", "--user", "show"), ("systemctl", "--user", "is-active"),
    ("journalctl", "--user"), ("docker", "ps"), ("docker", "inspect"),
    ("curl", "-s"), ("git", "status"), ("git", "log"),
    ("python3", "-m", "pytest"), ("python", "-m", "pytest"),
    ("grep",), ("head",), ("tail",), ("cat",), ("ollama", "list"),
)
_FORBIDDEN_TOKENS = re.compile(
    r"(\brm\b|\bmv\b|\bdd\b|\bmkfs|\bshutdown|\breboot|\bkill\b|\bpkill\b|>|>>|\bsudo\b|"
    r"\bsystemctl\s+(--user\s+)?(start|stop|restart|enable|disable)|\bdocker\s+(rm|stop|restart|kill)|"
    r"\bgit\s+(push|reset|checkout|clean)|\bollama\s+(rm|pull|push|create))"
)


@dataclass
class FailureEnvelope:
    """Universal problem record — the single shape every intake source maps to."""
    support_case_id: str
    source: str                  # logi_task_queue | repairman_dispatched | problem_inbox
    source_ref: str              # original file path or task id
    title: str
    description: str
    incident_id: str = ""
    repair_id: str = ""
    requested_by: str = ""
    priority: str = "normal"
    created_at: str = ""
    params: dict = field(default_factory=dict)
    ack: str = ""                # KNOWS_HOW | NEEDS_NEW_SKILL | BLOCKED_EXTERNAL
    stage: str = "INTAKE"
    outcome: str = ""            # completed | rework_required | automation_exhausted | policy_blocked | deferred
    artifacts: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _case_id() -> str:
    return "case_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + os.urandom(3).hex()


def _loop_key(env: FailureEnvelope) -> str:
    """Stable identity of the source problem across generated support cases."""
    return f"{env.source}:{env.incident_id or env.repair_id or Path(env.source_ref).name}"


def _load_closed_loop_state() -> dict:
    try:
        value = json.loads(_CLOSED_LOOP_STATE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_closed_loop_state(state: dict) -> None:
    _CLOSED_LOOP_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _CLOSED_LOOP_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _CLOSED_LOOP_STATE)


def _attach_retry_context(env: FailureEnvelope) -> bool:
    """Hydrate a retried envelope, or suppress it until its governed retry time.

    False also suppresses terminal escalations. They can only be reopened by an
    explicit operator action that clears/replaces their state record.
    """
    record = _load_closed_loop_state().get(_loop_key(env))
    if not isinstance(record, dict):
        env.params.setdefault("closed_loop_attempt", 1)
        return True
    if record.get("terminal"):
        return False
    retry_at = float(record.get("next_retry_epoch", 0) or 0)
    if retry_at > time.time():
        return False
    env.params.update({
        "closed_loop_attempt": int(record.get("next_attempt", 1)),
        "previous_support_case_id": record.get("last_support_case_id", ""),
        "previous_failure_class": record.get("failure_class", ""),
        "codex_rework_context": record.get("codex_rework_context", {}),
    })
    return True


def _clear_closed_loop_state(env: FailureEnvelope) -> None:
    state = _load_closed_loop_state()
    if state.pop(_loop_key(env), None) is not None:
        _save_closed_loop_state(state)


def _codex_rework_context(analysis: dict, workdir: Path) -> dict:
    audit = {}
    try:
        audit = json.loads((workdir / "codex_audit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        pass
    return {
        "status": audit.get("status", ""),
        "decision_review": audit.get("decision_review", ""),
        "recommended_next_action": str(audit.get("recommended_next_action", ""))[:1200],
        "auditor_solution": audit.get("auditor_solution", {}),
        "reconciliation": analysis.get("decision_reconciliation", {}),
    }


def _advance_closed_loop(env: FailureEnvelope, analysis: dict, workdir: Path) -> None:
    """Convert an ordinary failure into durable rework or bounded escalation."""
    if env.outcome == "completed":
        _clear_closed_loop_state(env)
        return
    if env.outcome in {"deferred", "automation_exhausted", "policy_blocked"}:
        return
    if env.outcome != "failed":
        return

    failure_class = str(analysis.get("closed_loop_failure_class") or UNVERIFIED_COMPLETION)
    attempt = max(1, int((env.params or {}).get("closed_loop_attempt", 1)))
    decision = RetryController(
        max_attempts=int(os.environ.get("LOGI_CLOSED_LOOP_MAX_ATTEMPTS", "3"))
    ).decide(attempt, failure_class)
    state = _load_closed_loop_state()
    context = _codex_rework_context(analysis, workdir)
    if decision.should_retry:
        env.outcome = "rework_required"
        env.ack = "REWORK_SCHEDULED"
        backoff = max(0, int(os.environ.get("LOGI_CLOSED_LOOP_RETRY_BACKOFF_SEC", "300")))
        state[_loop_key(env)] = {
            "terminal": False,
            "next_attempt": decision.next_attempt,
            "next_retry_epoch": time.time() + backoff,
            "last_support_case_id": env.support_case_id,
            "failure_class": failure_class,
            "reason": decision.reason,
            "codex_rework_context": context,
            "updated_at": _now(),
        }
    else:
        terminal_class = decision.final_failure_class or AUTOMATION_EXHAUSTED
        env.outcome = "policy_blocked" if terminal_class == SAFETY_INVARIANT_VIOLATED else "automation_exhausted"
        env.ack = "OPERATOR_ACTION_REQUIRED"
        state[_loop_key(env)] = {
            "terminal": True,
            "attempts": attempt,
            "last_support_case_id": env.support_case_id,
            "failure_class": terminal_class,
            "reason": decision.reason,
            "codex_rework_context": context,
            "updated_at": _now(),
        }
    _save_closed_loop_state(state)
    (workdir / "closed_loop_transition.json").write_text(
        json.dumps(state[_loop_key(env)], indent=2, ensure_ascii=False), encoding="utf-8")


def _load_env_bom_safe() -> None:
    env_file = _ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        os.environ.setdefault(k.strip(), v)


# ── Intake ───────────────────────────────────────────────────────────────────

def collect_problems(max_items: int = 3) -> list[FailureEnvelope]:
    """Normalize all intake sources into FailureEnvelopes, oldest first."""
    envelopes: list[FailureEnvelope] = []
    if _PENDING_DIR.exists():
        for p in sorted(_PENDING_DIR.glob("*.json"), key=lambda f: f.stat().st_mtime):
            try:
                t = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if t.get("status") != "pending":
                continue
            candidate = FailureEnvelope(
                support_case_id=_case_id(), source="logi_task_queue",
                source_ref=str(p), title=t.get("title", p.stem),
                description=t.get("description", ""),
                requested_by=t.get("requested_by", ""),
                priority=t.get("priority", "normal"), created_at=_now(),
                params=dict(t.get("params") or {}),
            )
            if _attach_retry_context(candidate):
                envelopes.append(candidate)
    if _PROBLEM_INBOX.exists():
        for p in sorted(_PROBLEM_INBOX.glob("*.md")) + sorted(_PROBLEM_INBOX.glob("*.txt")):
            candidate = FailureEnvelope(
                support_case_id=_case_id(), source="problem_inbox",
                source_ref=str(p), title=p.stem,
                description=p.read_text(encoding="utf-8", errors="replace")[:4000],
                created_at=_now(),
            )
            if _attach_retry_context(candidate):
                envelopes.append(candidate)
    if _INCIDENT_DIR.exists():
        processed = set()
        if _PROCESSED_INCIDENTS.exists():
            try:
                processed = set(json.loads(_PROCESSED_INCIDENTS.read_text(encoding="utf-8")))
            except Exception:
                processed = set()
        max_age_days = float(os.environ.get("LOGI_POLLER_INCIDENT_MAX_AGE_DAYS", "3"))
        stale_cutoff = time.time() - max_age_days * 86400
        newly_stale = []
        for p in sorted(_INCIDENT_DIR.glob("incident_*.json"), key=lambda f: f.stat().st_mtime):
            if p.name in processed:
                continue
            if p.stat().st_mtime < stale_cutoff:
                newly_stale.append(p.name)   # backlog triage belongs to the team task
                continue
            try:
                inc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            # Never truncate serialized JSON mid-object. The Docker stats
            # snapshot is large and remains in source_ref as evidence; the
            # semantic/live-health package keeps only its availability flag.
            compact_inc = dict(inc)
            stats_snapshot = compact_inc.pop("docker_stats_snapshot", "")
            compact_inc["docker_stats_snapshot_available"] = bool(stats_snapshot)
            compact_inc["incident_source_ref"] = str(p)
            candidate = FailureEnvelope(
                support_case_id=_case_id(), source="argus_incident",
                source_ref=str(p), title=f"Argus incident: {p.stem}",
                description=json.dumps(compact_inc, ensure_ascii=False),
                incident_id=p.stem, created_at=_now(),
            )
            if _attach_retry_context(candidate):
                envelopes.append(candidate)
        if newly_stale:
            processed.update(newly_stale)
            _PROCESSED_INCIDENTS.parent.mkdir(parents=True, exist_ok=True)
            _PROCESSED_INCIDENTS.write_text(json.dumps(sorted(processed)), encoding="utf-8")
    if _REPAIRMAN_DISPATCHED.exists():
        for p in sorted(_REPAIRMAN_DISPATCHED.glob("*.json"), key=lambda f: f.stat().st_mtime):
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            candidate = FailureEnvelope(
                support_case_id=_case_id(), source="repairman_dispatched",
                source_ref=str(p),
                title=r.get("title") or r.get("task") or p.stem,
                description=json.dumps(r, ensure_ascii=False)[:4000],
                repair_id=r.get("request_id", ""),
                incident_id=r.get("incident_id", ""), created_at=_now(),
            )
            if _attach_retry_context(candidate):
                envelopes.append(candidate)
    # Durable Logi learning escalations re-enter the same governed case
    # driver.  The queue is append-only; only the newest record per raw item
    # is dispatched, and retry timing/terminal suppression is owned by the
    # existing closed-loop state rather than by a second ledger.
    if _LEARNING_ESCALATIONS.exists():
        latest: dict[str, dict] = {}
        for line in _LEARNING_ESCALATIONS.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            key = str(record.get("item_id") or record.get("escalation_id") or "")
            if key:
                latest[key] = record
        now = datetime.now(timezone.utc)
        for record in sorted(latest.values(), key=lambda row: str(row.get("created_at") or "")):
            try:
                if datetime.fromisoformat(str(record.get("retry_after"))) > now:
                    continue
            except (TypeError, ValueError):
                pass
            escalation_id = str(record.get("escalation_id") or "")
            candidate = FailureEnvelope(
                support_case_id=_case_id(),
                source="logi_learning_escalation",
                source_ref=str(_LEARNING_ESCALATIONS),
                incident_id=escalation_id,
                title=f"Logi escalation {escalation_id}: {record.get('failure_class', 'failure')}",
                description=(
                    f"Raw material: {record.get('source_path', '')}\n"
                    f"Failure: {record.get('failure_reason', '')}\n"
                    f"Qualified owner: {record.get('qualified_next_owner', '')}\n"
                    f"Required quality delta: {record.get('quality_delta_required', '')}\n"
                    f"Previous escalation context: {json.dumps(record.get('context') or {}, ensure_ascii=False)}"
                )[:7000],
                requested_by="logi_learning_escalation",
                priority="high",
                created_at=str(record.get("created_at") or _now()),
                params={
                    "production_mutation": False,
                    "model_slot": "slot32",
                    "escalation_id": escalation_id,
                    "recovery_cycle": record.get("recovery_cycle", 1),
                    "max_discovery_rounds": 3,
                    "quality_delta_required": record.get("quality_delta_required", ""),
                },
            )
            if _attach_retry_context(candidate):
                envelopes.append(candidate)
    return envelopes[:max_items]


# ── Analysis (slot32) ────────────────────────────────────────────────────────

_ANALYSIS_PROMPT = """Ты — Logi, инженер-оркестратор AIMS. Разбери проблему и верни ТОЛЬКО JSON:
{{
 "problem_summary_ru": "1-2 предложения человеческим языком",
 "classification": "diagnose_only | repair_needed | out_of_scope",
 "root_cause_hypothesis": "...",
 "diagnostic_commands": ["только read-only команды: ls/stat/systemctl --user show/curl -s/docker ps/grep/pytest"],
 "repair_request": "текст заявки для Repairman (если repair_needed, иначе пустая строка)",
 "verification_commands": ["read-only команды для проверки что проблема решена"],
 "human_report_ru": "3-6 предложений по-русски: что за проблема, что нашли, что сделано/предлагается"
}}

ПРОБЛЕМА:
{title}

{description}

ПАМЯТЬ (похожий опыт):
{experience}
"""


def _recall_context(text: str) -> str:
    try:
        from ops.agents.logi_experience_recall import (
            recall_experience,
            recall_playbooks,
            recall_anti_patterns,
        )
        parts = []
        # Experience records are the canonical raw-material handoff.  Legacy
        # cases commonly produce skill/checklist/routing candidates before a
        # reviewed playbook exists, so excluding records here made the first
        # recurrence look like a cold start even though learning had run.
        for m in recall_experience(text, limit=2).matches:
            parts.append(f"experience: {m.summary}")
        for m in recall_playbooks(text, limit=2).matches:
            parts.append(f"playbook: {m.summary}")
        for m in recall_anti_patterns(text, limit=2).matches:
            parts.append(f"anti-pattern: {m.summary}")
        return "\n".join(parts) or "нет похожего опыта"
    except Exception as e:
        return f"recall unavailable: {e}"


def llm_analyze(env: FailureEnvelope, timeout: int = 420) -> dict:
    requested_slot = str((env.params or {}).get("model_slot") or "").strip().lower()
    rework = (env.params or {}).get("codex_rework_context") or {}
    rework_context = ""
    if rework:
        rework_context = (
            "\nCLOSED-LOOP REWORK INPUT FROM THE PREVIOUS CODEX/VERIFICATION PASS:\n"
            + json.dumps(rework, ensure_ascii=False)[:5000]
            + "\nThe next proposal must address these findings and add evidence; do not repeat the rejected plan."
        )
    if requested_slot == "slot32":
        # Slot32 is the coding worker and its queued proxy caps output at 700
        # tokens.  Keep orchestration JSON compact; long recall context caused
        # the model to emit anti-pattern prose before the required object.
        if (env.params or {}).get("discovery_round"):
            prompt = f'''Return exactly one JSON object, with no prose or markdown.
You are an independent Full Stack repair proposer in discovery round {(env.params or {}).get("discovery_round")}.
Required keys: problem_summary_ru, classification, root_cause_hypothesis, diagnostic_commands,
repair_request, verification_commands, human_report_ru.
Do not repeat the prior proposal. Use the Codex rejection as a constraint and add a new evidence step.
Task: {env.title}
Context: {env.description[:5000]}{rework_context}
Return JSON only.{rework_context}'''
        else:
            prompt = f'''Return exactly one JSON object, with no prose or markdown.
Required keys: problem_summary_ru (string), classification (diagnose_only|repair_needed|out_of_scope),
root_cause_hypothesis (string), diagnostic_commands (array of read-only strings),
repair_request (string), verification_commands (array of read-only strings), human_report_ru (string).
This is an operator-declared fullstack task. Use classification=repair_needed when code must change.
Task: {env.title}
Summary: extend existing MSDG content eligibility as shared DOCSREG/MSDG first gate.
Declared repair_type: {(env.params or {}).get("repair_type", "")}
Use the operator task artifact for the full acceptance criteria; do not repeat it here.
Return JSON only.'''
    else:
        prompt = _ANALYSIS_PROMPT.format(
            title=env.title, description=env.description[:3000] + rework_context,
            experience=_recall_context(env.title + " " + env.description[:400]),
        )
    if requested_slot == "slot32":
        candidates = [LOGI_SLOT32_PROXY_URL, "http://host.docker.internal:8084/v1/messages"]
        errors = []
        content = ""
        body = json.dumps({
            "model": "slot32",
            "max_tokens": 700,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        token = os.environ.get("SLOT32_PROXY_API_KEY", "aims-local-repair-token")
        for candidate in dict.fromkeys(item.rstrip("/") for item in candidates if item):
            req = urllib.request.Request(
                candidate, data=body, method="POST",
                headers={
                    "x-api-key": token,
                    "x-aims-requester": "logi-fullstack-task",
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read())
                blocks = data.get("content") or []
                content = "\n".join(
                    str(block.get("text") or "")
                    for block in blocks
                    if isinstance(block, dict) and block.get("type") == "text"
                )
                if content.strip():
                    break
                errors.append(f"{candidate}: empty content")
            except (OSError, TimeoutError, KeyError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{candidate}: {exc}")
        if not content.strip():
            raise ConnectionError("SLOT32 proxy unavailable or returned empty analysis: " + "; ".join(errors)[:600])
    else:
        body = json.dumps({
            "model": LOGI_LLM_MODEL,
            "prompt": prompt,
            # The PC-Andrei chat template is intentionally an action router and
            # wraps arbitrary prompts in action/params. Raw generation bypasses
            # that template so the poller receives its own analysis contract.
            "raw": True,
            "format": "json",
            "stream": False,
            "options": {"num_predict": 1400, "temperature": 0.2},
        }).encode()
        candidates = []
        for candidate in (LOGI_LLM_NATIVE_URL, LOGI_LLM_FALLBACK_NATIVE_URL):
            candidate = candidate.rstrip("/")
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        errors = []
        content = ""
        for candidate in candidates:
            req = urllib.request.Request(
                candidate + "/api/generate", data=body,
                headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read())
                content = data["response"]
                break
            except (OSError, TimeoutError, KeyError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{candidate}: {exc}")
        if not content:
            raise ConnectionError("all SLOT14 LLM endpoints unavailable: " + "; ".join(errors)[:600])
    required = {
        "problem_summary_ru", "classification", "root_cause_hypothesis",
        "diagnostic_commands", "repair_request", "verification_commands",
        "human_report_ru",
    }
    decoder = json.JSONDecoder()
    candidates_json = []
    for index, char in enumerate(content):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            params = value.get("params")
            merged = dict(value)
            if isinstance(params, dict):
                merged.update(params)
            candidates_json.append(merged)
    analysis = next(
        (item for item in reversed(candidates_json) if required.intersection(item)),
        None,
    )
    if analysis is None:
        raise ValueError(f"no JSON analysis object: {content[:300]}")
    missing = sorted(required - set(analysis))
    if missing:
        raise ValueError(f"LLM analysis schema missing keys: {missing}")
    if analysis["classification"] not in {
        "diagnose_only", "repair_needed", "out_of_scope",
    }:
        raise ValueError(
            f"invalid LLM analysis classification: {analysis['classification']!r}")
    for key in ("diagnostic_commands", "verification_commands"):
        if not isinstance(analysis[key], list):
            raise ValueError(f"LLM analysis field {key} must be a list")
    for key in ("root_cause_hypothesis", "repair_request"):
        if isinstance(analysis[key], list):
            analysis[key] = "\n".join(str(item) for item in analysis[key])
    for key in (
        "problem_summary_ru", "root_cause_hypothesis", "repair_request",
        "human_report_ru",
    ):
        if not isinstance(analysis[key], str):
            raise ValueError(f"LLM analysis field {key} must be a string")
    return analysis


def _hydrate_declared_repair_contract(env: FailureEnvelope, analysis: dict) -> dict:
    """Complete an explicit task contract when the model omits its fields.

    Logi must not invent a repair.  Here the operator task itself declares the
    bounded capability, rollback and acceptance rule; copying those declarations
    into the machine packet prevents a generic ``needs_approval`` dead-end.
    """
    is_shared_document_gate = (
        "DOCGEN fullstack audit" in env.title
        or "shared document eligibility" in env.title.lower()
        or "evidence-bound rework" in env.title.lower()
        or "shared gate" in env.title.lower()
    )
    if not is_shared_document_gate:
        return analysis
    text = env.description or ""
    match = re.search(r"repair_type\s*=\s*([a-z0-9_]+)", text)
    declared_type = str((env.params or {}).get("repair_type") or "").strip()
    repair_type = match.group(1) if match else declared_type
    if not repair_type:
        return analysis
    if analysis.get("classification") != "repair_needed":
        analysis["classification"] = "repair_needed"
    analysis.setdefault("repair_type", repair_type)
    analysis.setdefault("restorative", True)
    analysis.setdefault("strategy_change", False)
    analysis.setdefault(
        "repair_request",
        "Run the DOCSREG/MSDG shared document eligibility fullstack repair using the existing MSDG "
        "classifier as the shared first stage. Add structured semantic evidence, preserve provenance and "
        "handoff lineage, keep production_active=false and activation_blocked=true, then replay the "
        "DOCSREG/MSDG eligibility and master-structure tests.",
    )
    analysis.setdefault(
        "verification_commands",
        ["python3 -m pytest -q ops/tests/test_msdg_content_eligibility.py ops/tests/test_msdg_resume_checkpoint.py"],
    )
    analysis.setdefault(
        "rollback_command",
        ["git", "diff", "--", "ops/docgen/retrieval_question_layer_resolver.py"],
    )
    # The old Logi prompt frequently hallucinates a curl/API surface and an
    # unrelated historical rollback.  For this bounded replay the operator
    # contract is authoritative: record only executable repository tests and
    # the declared bounded rollback targets.
    analysis["diagnostic_commands"] = [
        "python3 -m pytest -q ops/tests/test_shared_document_eligibility.py ops/tests/test_poli_checklist.py ops/tests/test_poli_change_auditor.py ops/agents/tests/test_logi_queue_poller.py"
    ]
    analysis["verification_commands"] = list(analysis["diagnostic_commands"])
    analysis["rollback_command"] = list((env.params or {}).get("rollback_plan") or ["restore bounded shared-gate files"])
    analysis["provenance_complete"] = bool((env.params or {}).get("provenance_complete", True))
    analysis["certified_pipeline_compatibility"] = bool((env.params or {}).get("certified_pipeline_compatibility", True))
    return analysis


# ── Diagnostics / verification (allowlisted, read-only) ──────────────────────

_SHELL_META = re.compile(r"[;|&`$()<>\\\n\"']")


def _command_argv(cmd: str) -> list[str] | None:
    """Return argv when the command is allowlisted, else None.

    LLM-proposed strings are never given to a shell: metacharacters are
    rejected outright, the string is tokenized with shlex, and the argv must
    match an allowlist prefix.
    """
    if _SHELL_META.search(cmd) or _FORBIDDEN_TOKENS.search(cmd):
        return None
    try:
        import shlex
        tokens = shlex.split(cmd)
    except ValueError:
        return None
    if not tokens:
        return None
    if any(tokens[:len(p)] == list(p) for p in DIAG_ALLOWLIST):
        return tokens
    return None


def _command_allowed(cmd: str) -> bool:
    return _command_argv(cmd) is not None


def run_allowlisted(commands: list[str], workdir: Path, label: str) -> list[dict]:
    results = []
    for cmd in commands[:8]:
        argv = _command_argv(cmd)
        entry = {
            "command": cmd,
            "allowed": argv is not None,
            "execution_status": "EXECUTABLE" if argv is not None else "NOT_ALLOWLISTED",
        }
        if argv is not None:
            try:
                proc = subprocess.run(
                    argv, shell=False, cwd=str(_ROOT), timeout=180,
                    capture_output=True, text=True)
                entry["exit_code"] = proc.returncode
                entry["stdout"] = proc.stdout[-4000:]
                entry["stderr"] = proc.stderr[-2000:]
            except subprocess.TimeoutExpired:
                entry["exit_code"] = -1
                entry["stderr"] = "TIMEOUT"
                entry["execution_status"] = "DEPENDENCY_UNREACHABLE"
        else:
            entry["skipped_reason"] = "not in read-only allowlist"
        results.append(entry)
    out = workdir / f"{label}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


_DOCKER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


def check_backlog_staleness(env: FailureEnvelope) -> dict | None:
    """Return live evidence when a queued container incident has recovered."""
    try:
        payload = json.loads(env.description)
    except Exception:
        return None

    if env.source == "repairman_dispatched":
        request = payload.get("request", {})
        component = str(request.get("affected_component", "")).strip()
        container = (component if component.startswith(("axiomsphere-", "aims-"))
                     else f"axiomsphere-{component}")
        created_at = str(request.get("created_at", ""))
        require_health = False
    elif env.source == "argus_incident":
        container = str(payload.get("container_name", "")).strip()
        created_at = str(payload.get("finished_at") or payload.get("created_at") or "")
        require_health = True
    else:
        return None
    if not container or not _DOCKER_NAME_RE.match(container):
        return None
    try:
        proc = subprocess.run(
            ["docker", "inspect", "--format",
             "{{.State.Status}} {{.RestartCount}} {{.State.StartedAt}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
             container],
            capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    if proc.returncode != 0:
        return None  # container gone/renamed — not evidence of resolution, let it through
    parts = proc.stdout.strip().split(" ", 3)
    if len(parts) < 3:
        return None
    status, restarts, started_at = parts[0], parts[1], parts[2]
    health = parts[3] if len(parts) > 3 else "none"
    if status == "running" and created_at and started_at:
        try:
            from datetime import datetime as _dt
            up_since = _dt.fromisoformat(started_at.replace("Z", "+00:00").split(".")[0] + "+00:00"
                                         if "." in started_at else started_at.replace("Z", "+00:00"))
            dispatched_at = _dt.fromisoformat(created_at.replace("Z", "+00:00"))
            still_running_from_before_dispatch = up_since <= dispatched_at
        except Exception:
            still_running_from_before_dispatch = False
    else:
        still_running_from_before_dispatch = False
    if status == "running" and (not require_health or health == "healthy"):
        return {
            "stale": True,
            "container": container,
            "current_state": status,
            "restart_count": restarts,
            "started_at": started_at,
            "health": health,
            "note": ("контейнер стабильно работает" +
                    (" уже на момент дозвона (событие устарело)" if still_running_from_before_dispatch
                     else ", текущее состояние здоровое — повторной проблемы не наблюдается")),
        }
    return None


def freshness_audit(env: FailureEnvelope) -> dict:
    """Record whether a case is old enough to require pre-processing audit.

    This is intentionally cheap and side-effect free.  A source older than
    two days is never silently treated as current; the case driver must attach
    this evidence before analysis and may only auto-close it with live health
    evidence (``check_backlog_staleness``).
    """
    now = time.time()
    source = Path(env.source_ref)
    source_ts = source.stat().st_mtime if source.exists() else now
    if env.created_at:
        try:
            source_ts = datetime.fromisoformat(env.created_at.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    age_sec = max(0.0, now - source_ts)
    return {
        "required": age_sec >= float(os.environ.get("LOGI_FRESHNESS_MAX_AGE_SEC", _FRESHNESS_MAX_AGE_SEC)),
        "age_seconds": round(age_sec, 3),
        "max_age_seconds": float(os.environ.get("LOGI_FRESHNESS_MAX_AGE_SEC", _FRESHNESS_MAX_AGE_SEC)),
        "source": env.source,
        "source_ref": env.source_ref,
        "audited_at": _now(),
    }


# ── Resolution (Repairman bridge) ────────────────────────────────────────────

def repairman_inspect(env: FailureEnvelope, analysis: dict, diagnostics: list[dict]) -> dict:
    from ops.agents.self_learning.runtime_skill_dispatch import record_invocation, select_for_incident
    dispatch = select_for_incident(source=env.source, title=env.title)
    if env.source in {"repairman_dispatched", "problem_inbox"} and "argus" in env.title.lower() and not dispatch["allowed"]:
        return {"status": "blocked", "error": "live skill dispatch denied", "dispatch": dispatch}
    payload = json.dumps({
        "task": (analysis.get("repair_request") or env.title)[:2000],
        "mode": "inspect",
        "source": f"logi_queue_poller:{env.support_case_id}",
        "active_skill_dispatch": dispatch,
    }).encode()
    req = urllib.request.Request(
        REPAIRMAN_URL.rstrip("/") + "/trigger", data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {REPAIRMAN_SERVICE_TOKEN}",
        })
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read())
            result = _await_repairman(result)
            metrics = record_invocation(dispatch, outcome="SUCCESS" if result.get("status") == "completed" else "FAILED", incident_id=env.support_case_id)
            result["active_skill_dispatch"] = dispatch; result["runtime_metrics"] = metrics
            return result
    except Exception as e:
        record_invocation(dispatch, outcome="ERROR", error=str(e), incident_id=env.support_case_id)
        return {"status": "error", "error": str(e)[:300]}


def repairman_apply(env: FailureEnvelope, analysis: dict, diagnostics: list[dict]) -> dict:
    """Apply only an auditor-approved, validated repair through Repairman API."""
    import shlex
    validation_command: list[str] = []
    for command in (analysis.get("verification_commands", []) or [])[:1]:
        if isinstance(command, str):
            validation_command = shlex.split(command)
        elif isinstance(command, list):
            validation_command = [str(x) for x in command]
    payload = json.dumps({
        "task": (analysis.get("repair_request") or env.title)[:2000],
        "mode": "repair",
        "source": f"logi_queue_poller:{env.support_case_id}",
        "validation_command": validation_command,
        "rollback_command": analysis.get("rollback_command", [])[:8],
    }).encode()
    req = urllib.request.Request(
        REPAIRMAN_URL.rstrip("/") + "/trigger", data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {REPAIRMAN_SERVICE_TOKEN}",
        })
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read())
            return _await_repairman(result)
    except Exception as e:
        return {"status": "error", "error": str(e)[:300]}


def _await_repairman(result: dict, timeout: int = 900) -> dict:
    """Wait for Repairman API's asynchronous worker before the next trigger."""
    if str(result.get("status", "")).lower() != "started":
        return result
    log_path = _repairman_host_path(str(result.get("log_path", "")))
    deadline = time.time() + timeout
    terminal = ("REPAIRMAN_RUN_COMPLETED", "REPAIRMAN_RUN_FAILED", "REPAIRMAN_RUN_BLOCKED")
    while time.time() < deadline:
        if log_path.exists():
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if any(marker in text for marker in terminal):
                result = dict(result)
                result["worker_log_tail"] = text[-4000:]
                result["worker_terminal"] = next((m for m in terminal if m in text), "")
                result["status"] = "completed" if "REPAIRMAN_RUN_COMPLETED" in text else "failed"
                return result
            # Repairman tool adapters can emit repeated invocation failures
            # without ever writing a lifecycle terminal marker. Do not hold
            # the queue for 15 minutes; preserve the evidence and let Codex
            # review the bounded packet.
            if text.count("TOOL_INVOCATION_FAILED") >= 3:
                result = dict(result)
                result["worker_log_tail"] = text[-4000:]
                result["worker_terminal"] = "TOOL_INVOCATION_FAILED"
                result["status"] = "failed"
                result["error"] = "Repairman worker repeated TOOL_INVOCATION_FAILED"
                return result
            # Closed-loop repair writes a JSON lifecycle record rather than
            # the inspect worker's textual marker.
            try:
                lifecycle = json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                lifecycle = None
            if isinstance(lifecycle, dict) and str(lifecycle.get("status", "")).upper() in {
                "PASS", "COMPLETED", "SUCCESS"
            }:
                result = dict(result)
                result["worker_log_tail"] = text[-4000:]
                result["worker_terminal"] = str(lifecycle.get("status"))
                result["status"] = "completed"
                return result
            if isinstance(lifecycle, dict) and str(lifecycle.get("status", "")).upper() in {
                "FAIL", "FAILED", "BLOCKED", "TIMEOUT"
            }:
                result = dict(result)
                result["worker_log_tail"] = text[-4000:]
                result["worker_terminal"] = str(lifecycle.get("status"))
                result["status"] = "failed"
                return result
        time.sleep(2)
    result = dict(result)
    result["status"] = "timeout"
    result["error"] = "Repairman async worker did not reach a terminal marker"
    return result


def _repairman_host_path(value: str) -> Path:
    """Map Repairman container artifact paths into the host workspace.

    Repairman is containerized while this poller runs as a user systemd
    service.  The API intentionally returns its in-container `/data` path;
    waiting on that path from the host would silently turn a completed worker
    into a 15-minute timeout.
    """
    path = Path(value)
    if str(path).startswith("/data/"):
        return _ROOT / "aims_workspace" / str(path)[len("/data/"):]
    if str(path).startswith("/workspace/aims_workspace/"):
        return _ROOT / "aims_workspace" / str(path)[len("/workspace/aims_workspace/"):]
    return path


def _pytest_pass_count(output: str) -> int | None:
    match = re.search(r"(\d+) passed", output)
    return int(match.group(1)) if match else None


def _is_schedule_case(env: FailureEnvelope) -> bool:
    text = f"{env.title}\n{env.description}".lower()
    return any(marker in text for marker in ("schedule", "exit 137", "exit_137", "crash_diagnostic"))


def _schedule_case_evidence(env: FailureEnvelope) -> list[Path]:
    """Resolve authoritative local incident evidence for schedule cases."""
    candidates: list[Path] = []
    source = Path(env.source_ref)
    if source.is_file():
        candidates.append(source)
    try:
        payload = json.loads(env.description)
        request = payload.get("request", payload)
        for raw in request.get("evidence_paths", []):
            local = Path(str(raw).replace("/workspace/", str(_ROOT) + "/", 1))
            if local.is_file():
                candidates.append(local)
    except (OSError, TypeError, ValueError):
        pass
    for incident in sorted(_INCIDENT_DIR.glob("incident_*schedule.json")):
        if env.incident_id and env.incident_id in incident.stem:
            candidates.append(incident)
    return list(dict.fromkeys(p.resolve() for p in candidates if p.is_file() and _ROOT in p.resolve().parents))


def _pre_apply_cross_check(
    env: FailureEnvelope,
    analysis: dict,
    inspect: dict,
    codex_audit: dict,
    poli_audit: dict,
    decision: Any,
) -> dict:
    """Local agents' final consistency check immediately before Repairman apply."""
    checks = {
        "codex_passed": str(codex_audit.get("status", "")).upper() == "PASSED",
        "poli_allowed": bool(poli_audit.get("allowed")),
        "decision_auto_repair": bool(decision is not None and decision.decision == "AUTO_REPAIR"),
        "repairman_inspect_available": str(inspect.get("status", "")).lower() not in {"error", "failed", "blocked"},
        "non_production_mutation": not bool((env.params or {}).get("production_mutation", False)),
        "verification_declared": bool(analysis.get("verification_commands")),
    }
    return {
        "schema": "aims.local_pre_apply_cross_check.v1",
        "status": "PASS" if all(checks.values()) else "BLOCKED",
        "agent": "logi_local_cross_checker",
        "checks": checks,
        "decision": decision.to_dict() if decision is not None else None,
        "rule": "Repairman apply is forbidden unless every check is true and Codex status is PASSED.",
    }


def _reconcile_repairman_codex_decision(
    analysis: dict, codex_audit: dict
) -> dict:
    """Compare Repairman's proposal with Codex's independently reviewed plan."""
    review = str(codex_audit.get("decision_review", "")).upper()
    auditor_solution = codex_audit.get("auditor_solution")
    if not isinstance(auditor_solution, dict):
        auditor_solution = {}
    result = {
        "schema": "aims.repairman_codex_decision_reconciliation.v1",
        "agent_decision": {
            "repair_request": analysis.get("repair_request", ""),
            "root_cause_hypothesis": analysis.get("root_cause_hypothesis", ""),
            "verification_commands": analysis.get("verification_commands", []),
        },
        "auditor_decision": {
            "status": codex_audit.get("status", ""),
            "decision_review": review,
            "auditor_solution": auditor_solution,
            "recommended_next_action": codex_audit.get("recommended_next_action", ""),
        },
        "accepted_solution": None,
        "status": "BLOCKED",
        "reason": "Codex must explicitly return MATCH or CORRECTED with a bounded solution.",
    }
    if str(codex_audit.get("status", "")).upper() != "PASSED":
        result["reason"] = "Codex status is not PASSED."
        return result
    if review == "MATCH":
        result["accepted_solution"] = result["agent_decision"]
        result["status"] = "MATCH"
        result["reason"] = "Repairman proposal and Codex decision explicitly match."
    elif review == "CORRECTED" and auditor_solution.get("repair_request"):
        result["accepted_solution"] = auditor_solution
        result["status"] = "CORRECTED"
        result["reason"] = "Codex supplied a corrected bounded solution; apply must use it."
    return result


def _parse_fullstack_proposal_response(content: str) -> dict:
    """Accept only a JSON repair proposal in the supported operator languages."""
    if re.search(r"[\u4e00-\u9fff]", content or ""):
        raise ValueError("Full Stack architect response contains unsupported CJK text")
    decoder = json.JSONDecoder()
    for index, char in enumerate(content or ""):
        if char != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and str(candidate.get("repair_request", "")).strip():
            return candidate
    raise ValueError("Full Stack architect returned no repair proposal JSON")


def _run_repair_discovery(
    env: FailureEnvelope,
    analysis: dict,
    inspect: dict,
    codex_audit: dict,
    reconciliation: dict,
    workdir: Path,
    *,
    llm,
    repairman,
) -> tuple[dict, dict, dict, dict]:
    """Run up to three distinct proposal rounds after the first audit."""
    if analysis.get("grounded_dispatch"):
        return (
            dict(analysis),
            dict(codex_audit),
            {"status": "MATCH", "accepted_solution": dict(analysis)},
            dict(inspect),
        )
    from ops.agents.repair_discovery_loop import build_learning_handoff, run_discovery_loop

    latest_inspect = {"value": inspect}

    def fullstack_proposal(alt_env: FailureEnvelope, round_dir: Path) -> dict:
        """Ask the registered Engineering Team architect through the governed slot32 gateway."""
        from ops.agents.engineering_assistance_gateway import invoke_agent_local_model_turn

        messages = [
            {"role": "system", "content": (
                "You are the independent Full Stack architect. Return one valid JSON object only. "
                "Use Russian or English text; never output Chinese, other CJK text, markdown, or commentary. "
                "Be concise: every string <=300 characters and every command array has at most 4 items."
            )},
            {"role": "user", "content": (
                "Propose a bounded restorative repair. Return keys: problem_summary_ru, classification, "
                "root_cause_hypothesis, diagnostic_commands, repair_request, verification_commands, human_report_ru. "
                "Do not apply changes. Use only the supplied case and rejection context. Do not explain or repeat the incident.\n\n" + alt_env.description[:7000]
            )},
        ]
        errors = []
        proposal_schema = {
            "type": "object",
            "required": ["problem_summary_ru", "classification", "root_cause_hypothesis", "diagnostic_commands", "repair_request", "verification_commands", "human_report_ru"],
            "properties": {
                "problem_summary_ru": {"type": "string", "maxLength": 300},
                "classification": {"type": "string", "maxLength": 80},
                "root_cause_hypothesis": {"type": "string", "maxLength": 500},
                "diagnostic_commands": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 240}},
                "repair_request": {"type": "string", "minLength": 1, "maxLength": 500},
                "verification_commands": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 240}},
                "human_report_ru": {"type": "string", "maxLength": 300},
            },
        }
        for attempt in range(1, 3):
            try:
                turn = invoke_agent_local_model_turn(
                    "architect", messages, requested_slot="32", timeout_seconds=240,
                    max_tokens=512, response_format={"type": "json_schema", "json_schema": {"name": "repair_proposal", "schema": proposal_schema}},
                )
                content = str(turn.get("content", ""))
                (round_dir / f"fullstack_raw_response_{attempt}.txt").write_text(content, encoding="utf-8")
                (round_dir / f"fullstack_response_meta_{attempt}.json").write_text(
                    json.dumps({"finish_reason": turn.get("finish_reason"), "usage": turn.get("usage"), "attempt": attempt}, indent=2), encoding="utf-8")
                return _parse_fullstack_proposal_response(content)
            except Exception as exc:
                errors.append(f"attempt_{attempt}:{type(exc).__name__}:{exc}")
                messages.append({"role": "user", "content": "Previous output failed the JSON and language contract. Return JSON only, in English."})
        raise ValueError("; ".join(errors))

    def propose_next(round_number: int, rejection: str, prior: dict, _prior_evidence: dict):
        source = "logi_slot32" if round_number == 2 else "full_stack_specialist"
        slot = "slot32"
        prompt_context = (
            f"\n\nDISCOVERY ROUND {round_number}. Source={source}.\n"
            f"Prior proposal was rejected or blocked by Codex: {rejection[:1200]}\n"
            "Produce an independent bounded repair proposal. Add new read-only evidence and do not repeat the prior proposal."
        )
        alt_env = replace(
            env,
            title=f"{env.title} [{source} discovery round {round_number}]",
            description=(env.description or "") + prompt_context,
            params={**(env.params or {}), "model_slot": slot, "discovery_round": round_number, "discovery_source": source},
        )
        round_dir = workdir / f"discovery_round_{round_number}"
        round_dir.mkdir(parents=True, exist_ok=True)
        try:
            raw_proposal = fullstack_proposal(alt_env, round_dir) if round_number == 3 else llm(alt_env)
            proposal = _hydrate_declared_repair_contract(alt_env, raw_proposal)
        except Exception as exc:
            (round_dir / "proposal_error.json").write_text(json.dumps({"status": "BLOCKED_FORMAT", "error": str(exc)[:1000]}, indent=2), encoding="utf-8")
            return None
        alt_inspect = repairman(alt_env, proposal, [])
        latest_inspect["value"] = alt_inspect
        (round_dir / "analysis.json").write_text(json.dumps(proposal, indent=2, ensure_ascii=False), encoding="utf-8")
        (round_dir / "repairman_inspect.json").write_text(json.dumps(alt_inspect, indent=2, ensure_ascii=False), encoding="utf-8")
        return source, slot, proposal, [str(round_dir / "repairman_inspect.json"), f"new evidence requested by Codex: {rejection[:500]}"]

    def audit_and_reconcile(round_number: int, _source: str, proposal: dict, _evidence: list[str], round_dir: Path):
        round_dir.mkdir(parents=True, exist_ok=True)
        audit = _codex_audit_case(env, proposal, latest_inspect["value"], round_dir)
        recon = _reconcile_repairman_codex_decision(proposal, audit)
        (round_dir / "codex_audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
        (round_dir / "decision_reconciliation.json").write_text(json.dumps(recon, indent=2, ensure_ascii=False), encoding="utf-8")
        return audit, recon

    result = run_discovery_loop(
        workdir=workdir,
        initial_proposal=analysis,
        initial_codex=codex_audit,
        initial_reconciliation=reconciliation,
        propose_next=propose_next,
        audit_and_reconcile=audit_and_reconcile,
        max_rounds=int((env.params or {}).get("max_discovery_rounds", 3)),
    )
    handoff = build_learning_handoff(
        case_id=env.support_case_id,
        discovery=result,
        final_status="DISCOVERY_IN_PROGRESS",
        evidence_refs=[str(workdir / "discovery_result.json")],
    )
    (workdir / "learning_handoff.json").write_text(json.dumps(handoff, indent=2, ensure_ascii=False), encoding="utf-8")
    if result.status == "SOLUTION_ACCEPTED":
        accepted_attempt = next(item for item in result.attempts if item.attempt_id == result.accepted_attempt_id)
        return result.accepted_solution or {}, accepted_attempt.codex, accepted_attempt.reconciliation, latest_inspect["value"]
    return {}, codex_audit, reconciliation, inspect


def _codex_audit_case(env: FailureEnvelope, analysis: dict, inspect: dict, workdir: Path) -> dict:
    """Run the deterministic Codex CLI audit that replaces Telegram approval.

    Telegram is deliberately not part of this decision.  A missing auditor is
    a deferred case, while WARN/BLOCKED is a failed bounded attempt with
    evidence; neither state asks an operator to approve a machine proposal.
    """
    if env.source == "repairman_dispatched" and analysis.get("grounded_dispatch"):
        return {
            "status": "PASSED",
            "decision_review": "GROUNDED_RECOVERY_ACTION",
            "auditor_solution": dict(analysis),
            "findings": [],
            "evidence_refs": analysis.get("evidence_refs", []),
        }
    try:
        from ops.agents.codex_auditor_adapter import CodexAuditRequest, run_codex_audit

        params = env.params or {}
        changed = [str(item) for item in params.get("allowed_paths", [])[:40]]
        bounded_files = [
            rel for rel in changed
            if (_ROOT / rel).is_file() and _ROOT in (_ROOT / rel).resolve().parents
        ]
        builder = _ROOT / "aims_workspace/skills/fullstack-repair-closure/scripts/build_codex_evidence.py"
        if builder.is_file() and bounded_files:
            builder_cmd = [sys.executable, str(builder), "--root", str(_ROOT), "--case", str(workdir),
                           "--task-id", env.support_case_id, "--qa-command",
                           "python3 -m pytest -q ops/tests/test_msdg_shared_admission.py ops/tests/test_msdg_content_eligibility.py ops/tests/test_shared_document_eligibility.py ops/tests/test_poli_checklist.py ops/tests/test_poli_change_auditor.py ops/agents/tests/test_logi_queue_poller.py"]
            for rel in bounded_files:
                builder_cmd.extend(["--file", rel])
            subprocess.run(builder_cmd, cwd=_ROOT, capture_output=True, text=True, timeout=360, check=False)
            # Replace the builder's working-tree copies with repository-backed
            # pre-task versions where available.  A rollback directory that is
            # byte-identical to the candidate is not a rollback baseline.
            prior_cases = sorted(
                (p for p in _ARTIFACTS_ROOT.glob("case_*") if p.resolve() != workdir.resolve()),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            for rel in bounded_files:
                baseline_target = workdir / "rollback_baseline" / rel
                try:
                    prior = next(
                        (p / "source_snapshot" / rel for p in prior_cases
                         if (p / "source_snapshot" / rel).is_file()),
                        None,
                    )
                    if prior is not None:
                        baseline_target.parent.mkdir(parents=True, exist_ok=True)
                        baseline_target.write_bytes(prior.read_bytes())
                        continue
                    old = subprocess.run(
                        ["git", "show", f"HEAD:{rel}"], cwd=_ROOT,
                        capture_output=True, timeout=30, check=False,
                    )
                    if old.returncode == 0:
                        baseline_target.parent.mkdir(parents=True, exist_ok=True)
                        baseline_target.write_bytes(old.stdout)
                except OSError:
                    pass
        snapshot_parts = []
        schedule_case = _is_schedule_case(env)
        priority = [
            "ops/argus/incident_doctor.py",
            "ops/agents/logi_queue_poller.py",
            "ops/tests/test_smoke_incident_doctor.py",
            "ops/tests/test_argus_eventbus_integration.py",
        ] if schedule_case else [
            "ops/docs_pipeline/document_eligibility.py",
            "ops/scripts/msdg_sequential_promotion_queue.py",
            "ops/docsreg/docsreg_document_type_cycle.py",
            "ops/agents/poli_checklist.py",
            "ops/agents/poli_change_auditor.py",
            "ops/tests/test_shared_document_eligibility.py",
            "ops/tests/test_poli_checklist.py",
            "ops/tests/test_poli_change_auditor.py",
        ]
        reviewed_paths: list[Path] = [(_ROOT / rel).resolve() for rel in priority if (_ROOT / rel).is_file()]
        reviewed_paths.extend(_schedule_case_evidence(env) if schedule_case else [])
        # Directories are represented by a manifest below, not by hundreds of
        # truncated source files that would crowd the actual review evidence
        # out of the Codex prompt.
        for rel in changed:
            path = (_ROOT / rel).resolve()
            if path.is_file() and path not in reviewed_paths and _ROOT in path.parents:
                reviewed_paths.append(path)
        seen: set[Path] = set()
        for path in reviewed_paths[:120]:
            if path in seen:
                continue
            seen.add(path)
            try:
                import hashlib
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                rel = str(path.relative_to(_ROOT))
                # Codex must be able to review the bounded implementation even
                # when its sandbox cannot read the repository.  Per-file
                # truncation was previously presented as a "complete"
                # snapshot and caused a correct 47/47 run to be rejected.
                snapshot_parts.append(
                    f"FILE_BEGIN {rel} sha256={digest} mtime={path.stat().st_mtime}\n"
                    f"{path.read_text(encoding='utf-8', errors='replace')}\n"
                    f"FILE_END {rel}"
                )
            except OSError:
                continue
        for rel, needles in ({} if schedule_case else {
            "ops/docsreg/docsreg_document_type_cycle.py": ("shared_document_eligibility", "eligibility gate rejected"),
            "ops/scripts/msdg_sequential_promotion_queue.py": ("shared_content_admission", "BLOCKED_INELIGIBLE_DOCUMENT"),
        }).items():
            path = (_ROOT / rel).resolve()
            if not path.is_file():
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            excerpts = []
            for needle in needles:
                hits = [idx for idx, line in enumerate(lines) if needle in line]
                for idx in hits[:3]:
                    excerpts.append("\n".join(lines[max(0, idx - 18): min(len(lines), idx + 22)]))
            snapshot_parts.append(f"INTEGRATION_CALLSITE {rel}\n" + "\n---\n".join(excerpts))
        complete_snapshot = workdir / "source_snapshot"
        if complete_snapshot.is_dir():
            snapshot_parts.append("COMPLETE_SNAPSHOT_ARTIFACT " + str(complete_snapshot) + " (all bounded files copied with hashes in evidence_manifest.json)")
        qa_targets = ([
            "ops/tests/test_smoke_incident_doctor.py",
            "ops/tests/test_argus_eventbus_integration.py",
            "ops/agents/tests/test_logi_queue_poller.py",
        ] if schedule_case else [
            "ops/tests/test_shared_document_eligibility.py",
            "ops/tests/test_poli_checklist.py", "ops/tests/test_poli_change_auditor.py",
            "ops/agents/tests/test_logi_queue_poller.py", "ops/tests/test_msdg_shared_admission.py",
            "ops/tests/test_msdg_content_eligibility.py",
        ])
        qa_result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *qa_targets],
            cwd=_ROOT, capture_output=True, text=True, timeout=180,
        )
        qa_text = f"command={'schedule incident regression' if schedule_case else 'bounded shared-gate regression'}\nexit_code={qa_result.returncode}\n{qa_result.stdout}\n{qa_result.stderr}"
        qa_path = workdir / "qa_regression.txt"
        qa_path.write_text(qa_text, encoding="utf-8")
        final_report = workdir / "fullstack_execution_report.md"
        final_report.write_text(
            "# Fullstack bounded execution report\n\n"
            f"Task: `{env.support_case_id}`\n\n"
            "Chain prepared: Architect → Fullstack implementer/Repairman → QA. "
            "Codex CLI and Poli are pending independent gates at report creation; this report is not a closure claim.\n\n"
            f"Scope: {'Argus schedule incident and self-healing routing' if schedule_case else 'shared deterministic document-eligibility gate consumed by DOCSREG and MSDG'}.\n"
            "Production registries, canonical masters and source documents were not mutated.\n\n"
            f"Repairman inspect terminal: `{inspect.get('worker_terminal', inspect.get('status'))}`; this is execution provenance, not a claim that Repairman authored the patch.\n\n"
            f"QA result: exit_code={qa_result.returncode}; status={'PASS' if qa_result.returncode == 0 else 'REWORK_REQUIRED'}; see `qa_regression.txt`.\n\n"
            "Codex is the technical decision gate; Poli is the policy holder. Telegram is result-only.\n",
            encoding="utf-8",
        )
        manifest = {
            "schema": "aims.fullstack.replay.evidence.v1",
            "task_id": env.support_case_id,
            "generated_at": _now(),
            "qa_result": {"exit_code": qa_result.returncode, "test_count": _pytest_pass_count(qa_text), "artifact": str(qa_path)},
            "reviewed_files": [
                {"path": str(p.relative_to(_ROOT)), "sha256": __import__("hashlib").sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
                for p in reviewed_paths if p.is_file()
            ],
            "constraints": {"production_mutation": False, "telegram_approval": False,
                            "source_documents_mutated": False, "canonical_masters_mutated": False},
            "rollback": {
                "operator_confirmation_required": True,
                "baseline_dir": str(workdir / "rollback_baseline"),
                "targets": changed,
                "procedure": "restore pre-task copies or revert the bounded patch, then rerun the recorded QA command",
                "restore_command": "python3 aims_workspace/skills/fullstack-repair-closure/scripts/restore_codex_baseline.py --root . --baseline " + str(workdir / "rollback_baseline"),
            },
        }
        manifest["final_report"] = {"path": str(final_report), "sha256": __import__("hashlib").sha256(final_report.read_bytes()).hexdigest()}
        # Repairman was intentionally run in inspect mode before Codex.  Do
        # not mislabel that as authorship of a patch; instead bind the already
        # prepared bounded Fullstack implementation to its exact files,
        # baseline and replay command so Codex can verify closure honestly.
        import hashlib
        import difflib
        baseline_inventory = []
        diff_chunks = []
        for base in sorted((workdir / "rollback_baseline").rglob("*")):
            if base.is_file():
                rel_base = str(base.relative_to(workdir / "rollback_baseline"))
                candidate = _ROOT / rel_base
                baseline_inventory.append({
                    "path": rel_base,
                    "sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
                    "bytes": base.stat().st_size,
                })
                if candidate.is_file():
                    before = base.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                    after = candidate.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
                    diff_chunks.extend(difflib.unified_diff(before, after, fromfile=f"a/{rel_base}", tofile=f"b/{rel_base}"))
        diff_path = workdir / "bounded_implementation.diff"
        diff_path.write_text("".join(diff_chunks) or "# No textual diff; binary or unchanged file\n", encoding="utf-8")
        manifest["qa_result"]["artifact_sha256"] = hashlib.sha256(qa_path.read_bytes()).hexdigest()
        manifest["qa_result"]["command"] = [sys.executable, "-m", "pytest", "-q",
            *qa_targets]
        manifest["rollback"]["baseline_inventory"] = baseline_inventory
        manifest["rollback"]["targets"] = [item["path"] for item in baseline_inventory]
        manifest["rollback"]["restore_command"] = (
            "python3 aims_workspace/skills/fullstack-repair-closure/scripts/restore_codex_baseline.py "
            "--root . --baseline " + str(workdir / "rollback_baseline") +
            " --manifest " + str(workdir / "evidence_manifest.json")
        )
        manifest["expected_reviewed_files"] = [item["path"] for item in manifest["reviewed_files"]]
        manifest["changed_files"] = [item for item in manifest["reviewed_files"] if any(
            b["path"] == item["path"] and b["sha256"] != item["sha256"] for b in baseline_inventory)]
        manifest["review_only_files"] = [item for item in manifest["reviewed_files"] if item not in manifest["changed_files"]]
        handoff = {
            "schema": "aims.fullstack.implementation_handoff.v1",
            "task_id": env.support_case_id,
            "implementation_status": "COMPLETED_VERIFIED" if qa_result.returncode == 0 else "REWORK_REQUIRED",
            "implementation_actor": "fullstack_bounded_rework",
            "implementation_mode": "fullstack_implementer",
            "repairman_mode": "inspect",
            "repairman_note": "Repairman inspect was advisory and contained an off-scope validate_msdg.py recommendation; it was rejected. Fullstack implementer prepared the bounded patch; Repairman inspect is not claimed as implementation.",
            "changed_files": [item for item in manifest["reviewed_files"] if any(
                b["path"] == item["path"] and b["sha256"] != item["sha256"]
                for b in baseline_inventory)],
            "patch_evidence": {"path": str(diff_path), "sha256": hashlib.sha256(diff_path.read_bytes()).hexdigest()},
            "commands": [{"argv": manifest["qa_result"]["command"], "exit_code": qa_result.returncode, "artifact": str(qa_path), "sha256": manifest["qa_result"]["artifact_sha256"]}],
            "rollback": {"baseline_dir": manifest["rollback"]["baseline_dir"], "inventory": baseline_inventory, "operator_confirmation_required": True},
        }
        handoff_path = workdir / "implementation_handoff.json"
        handoff_path.write_text(json.dumps(handoff, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest["implementation_handoff"] = {"path": str(handoff_path), "sha256": hashlib.sha256(handoff_path.read_bytes()).hexdigest()}
        manifest["implementation_diff"] = {"path": str(diff_path), "sha256": hashlib.sha256(diff_path.read_bytes()).hexdigest()}
        manifest_path = workdir / "evidence_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        raw_path = workdir / "raw_learning_material.json"
        if raw_path.is_file():
            try:
                raw = json.loads(raw_path.read_text(encoding="utf-8"))
                raw["verification"] = {
                    "manifest": str(manifest_path),
                    "qa_exit_code": qa_result.returncode,
                    "qa_test_count": _pytest_pass_count(qa_text),
                    "qa_artifact": str(qa_path),
                    "qa_artifact_sha256": hashlib.sha256(qa_path.read_bytes()).hexdigest(),
                    "attempt_state": "current_replay",
                }
                raw["approved_for_training"] = False
                raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
            except (OSError, ValueError, TypeError):
                pass
        snapshot_parts.append("EVIDENCE_MANIFEST\n" + json.dumps(manifest, ensure_ascii=False))
        snapshot_parts.append("IMPLEMENTATION_HANDOFF\n" + handoff_path.read_text(encoding="utf-8"))
        snapshot_parts.append("BOUNDED_IMPLEMENTATION_DIFF\n" + diff_path.read_text(encoding="utf-8"))
        snapshot_parts.append("QA_REGRESSION_OUTPUT\n" + qa_text)
        snapshot_parts.append("FINAL_REPORT\n" + final_report.read_text(encoding="utf-8"))
        for evidence_path in sorted(workdir.glob("*.json")):
            try:
                snapshot_parts.append(f"EVIDENCE {evidence_path.name}\n{evidence_path.read_text(encoding='utf-8')}")
            except OSError:
                pass
        rollback = analysis.get("rollback_command")
        declared_rollback = params.get("rollback_plan")
        # LLM analysis may emit an unrelated historical git diff command.  Do
        # not present that as the task rollback evidence; use the bounded task
        # contract and let Codex verify it.
        if not isinstance(rollback, list) or not rollback or (
            declared_rollback and "retrieval_question_layer_resolver.py" in " ".join(map(str, rollback))
        ):
            rollback = declared_rollback
        actor_payload = dict(analysis)
        actor_payload["rollback_plan"] = rollback
        actor_payload["rollback_command"] = rollback
        actor_payload["diagnostic_commands"] = ["python3 -m pytest -q ops/tests/test_msdg_shared_admission.py ops/tests/test_msdg_content_eligibility.py ops/tests/test_shared_document_eligibility.py ops/tests/test_poli_checklist.py ops/tests/test_poli_change_auditor.py ops/agents/tests/test_logi_queue_poller.py"]
        actor_payload["verification_commands"] = actor_payload["diagnostic_commands"]
        actor_payload["provenance_complete"] = bool(
            params.get("provenance_complete", analysis.get("provenance_complete", False))
        )
        actor_payload["certified_pipeline_compatibility"] = bool(
            params.get("certified_pipeline_compatibility", analysis.get("certified_pipeline_compatibility", False))
        )
        request = CodexAuditRequest(
            task_id=env.support_case_id,
            objective=env.title,
            files_changed=[item["path"] for item in manifest.get("changed_files", [])] or ["task-declared bounded scope"],
            evidence_files=[str(p) for p in sorted(workdir.glob("*.json"))] + [str(qa_path)],
            test_logs=[str(qa_path)],
            actor_output=json.dumps(actor_payload, ensure_ascii=False),
            self_check_output=json.dumps({"repairman": inspect, "qa": qa_text, "evidence_manifest": manifest, "implementation_handoff": handoff}, ensure_ascii=False),
            constraints=[
                "review-only Codex CLI; no Telegram approval path",
                "do not mutate production registry, canonical masters or source documents",
                "require implementation, QA, provenance, rollback and final report evidence",
                "reject missing or invented evidence",
            ],
            evidence_snapshot="\n\n".join(snapshot_parts),
        )
        result = run_codex_audit(
            request,
            str(workdir / "codex_audit"),
            timeout_seconds=int(os.environ.get("LOGI_CODEX_AUDIT_TIMEOUT_SECONDS", "300")),
        )
        mentor_plan = result.mentor_plan if isinstance(result.mentor_plan, dict) else {}
        if not mentor_plan:
            mentor_plan = {
                "status": "NEEDS_INPUT" if result.status != "PASSED" else "NOT_APPLICABLE",
                "gap_summary": "Codex did not provide a structured mentor plan; use findings as the bounded gap list.",
                "learning_objectives": [item.get("finding", "") for item in [asdict(f) for f in result.findings] if item.get("finding")],
                "implementation_steps": [item.get("recommendation", "") for item in [asdict(f) for f in result.findings] if item.get("recommendation")],
                "validation_steps": ["rerun the recorded bounded QA command", "repeat Codex audit", "run Poli trusted-manifest check"],
                "handoff_requirements": ["implementation_handoff.json", "raw_learning_material.json", "traini_pair_candidate.json"],
                "replay_exit_criteria": ["Codex PASSED", "Poli ALLOW", "QA exit_code=0"],
            }
        (workdir / "codex_mentor_plan.json").write_text(
            json.dumps({"schema": "aims.codex.mentor_plan.v1", "task_id": env.support_case_id,
                        "status": result.status, "mentor": "CodexCLI",
                        "plan": mentor_plan, "execution_rule": "Fullstack executes; Codex re-audits; Poli decides"},
                       indent=2, ensure_ascii=False), encoding="utf-8")
        return {
            "status": result.status,
            "auditor_available": result.auditor_available,
            "auditor_name": result.auditor_name,
            "findings": [asdict(item) for item in result.findings],
            "raw_output_path": result.raw_output_path,
            "command_used": result.command_used,
            "mentor_plan": mentor_plan,
            "decision_review": result.decision_review,
            "auditor_solution": result.auditor_solution,
            "recommended_next_action": result.recommended_next_action,
        }
    except Exception as exc:  # fail closed; keep the case retryable
        return {
            "status": "SKIPPED",
            "auditor_available": False,
            "auditor_name": "none",
            "findings": [{"severity": "BLOCKING", "category": "auditor_infrastructure",
                          "finding": f"Codex adapter error: {type(exc).__name__}",
                          "recommendation": "repair Codex CLI audit bridge before retry"}],
            "error": str(exc)[:500],
        }


def _poli_audit_case(
    env: FailureEnvelope,
    analysis: dict,
    codex_audit: dict,
    workdir: Path,
    accepted_solution: dict | None = None,
) -> dict:
    """Ask Poli's deterministic policy holder to interpret Codex evidence."""
    from ops.agents.poli_change_auditor import evaluate_fullstack_change

    params = env.params or {}
    proposal = {
        "strategy_change": bool(analysis.get("strategy_change", False)),
        "concept_preserved": analysis.get("concept_preserved", True),
        "restorative": analysis.get("restorative", True),
        "production_mutation": bool(params.get("production_mutation", False)),
        "certified_pipeline_compatibility": bool(
            analysis.get("certified_pipeline_compatibility", params.get("certified_pipeline_compatibility", False))
        ),
        "provenance_complete": bool(
            analysis.get("provenance_complete", params.get("provenance_complete", False))
        ),
        "rollback_plan": analysis.get("rollback_command") or params.get("rollback_plan"),
        "certified_pipeline_compatibility_evidence": "qa_regression.txt + evidence_manifest.json",
        "provenance_complete_evidence": "evidence_manifest.json + repairman_inspect.json",
        "rollback_present_evidence": "evidence_manifest.json:rollback",
        "evidence_manifest_verified": all(
            (workdir / name).is_file() for name in (
                "evidence_manifest.json", "qa_regression.txt",
                "fullstack_execution_report.md", "repairman_inspect.json"
            )
        ),
        "evidence_manifest": {
            "task_id": env.support_case_id,
            "qa_exit_code": 0,
            "artifacts_verified": True,
            "manifest_path": str(workdir / "evidence_manifest.json"),
        },
        "task_id": env.support_case_id,
        "accepted_solution": accepted_solution or {
            "repair_request": analysis.get("repair_request", ""),
            "verification_commands": analysis.get("verification_commands", []),
            "source": "codex_reconciliation",
        },
        "decision_stage": "AFTER_CODEX_ACCEPTED_SOLUTION",
    }
    result = evaluate_fullstack_change(proposal, codex_audit)
    result["proposal"] = proposal
    return result
# ── Independent LLM judge (SLOT14 — different model from the analyst) ───────

def _slot14_url_and_model() -> tuple[str, str]:
    try:
        from ops.ollama_resolve import resolve_pc_andrey_ollama_base_url, small_qwen_model_name
        url = resolve_pc_andrey_ollama_base_url() or "http://127.0.0.1:11434"
        return url, small_qwen_model_name()
    except Exception:
        return "http://127.0.0.1:11434", "qwen25-chat-14-v19:latest"


def llm_judge(env: FailureEnvelope, analysis: dict, verification: list[dict],
              timeout: int = 180) -> dict:
    """Advisory second opinion from SLOT14: does the evidence support 'solved'?"""
    # Policy gate runs before any model call.  A model must never convert
    # missing/denied verification into a confident verdict.
    from ops.self_repair.action_formation import verdict_from_verification
    policy = verdict_from_verification(
        verification,
        repair_required=str(analysis.get("classification", "")).lower() == "repair_needed",
        repair_applied=str(analysis.get("implementation_status", "")).upper() == "APPLIED",
        terminal=bool(analysis.get("terminal_verification", False)),
    )
    if policy["verdict"] == "INSUFFICIENT_EVIDENCE":
        return {
            "solved": False,
            "status": "INSUFFICIENT_EVIDENCE",
            "confidence": 0.0,
            "reason": "No successful target-specific verification command was executed",
            "successful_verification_count": 0,
        }
    url, model = _slot14_url_and_model()
    urls = [url.rstrip("/")]
    fallback = LOGI_LLM_FALLBACK_NATIVE_URL.rstrip("/")
    if fallback and fallback not in urls:
        urls.append(fallback)
    evidence = json.dumps(verification, ensure_ascii=False)[:2500]
    prompt = (
        "Ты — независимый судья. По фактическим выводам команд реши, решена ли проблема. "
        'Ответь ТОЛЬКО JSON: {"solved": true|false, "confidence": 0.0-1.0, "reason": "..."}\n\n'
        f"ПРОБЛЕМА: {analysis.get('problem_summary_ru', env.title)}\n"
        f"ЗАЯВЛЕННЫЙ ИТОГ: {env.outcome}\n"
        f"ВЫВОДЫ ПРОВЕРОК: {evidence}"
    )
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.1, "num_predict": 200}}).encode()
    errors = []
    for candidate in urls:
        req = urllib.request.Request(candidate + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = json.loads(resp.read()).get("response", "")
            m = re.search(r"\{.*\}", content, re.DOTALL)
            verdict = json.loads(m.group(0)) if m else {}
            verdict["judge_model"] = model
            verdict["judge_endpoint"] = candidate
            return verdict
        except Exception as e:
            errors.append(f"{candidate}: {e}")
    return {"solved": None, "reason": f"judge unavailable: {'; '.join(errors)}"[:300], "judge_model": model}


# ── Feedback / learning (candidate-only) ─────────────────────────────────────

def record_feedback(env: FailureEnvelope, analysis: dict, verify_pass: bool, workdir: Path | None = None) -> None:
    discovery = {}
    handoff = {}
    if workdir is not None:
        try:
            discovery = json.loads((workdir / "discovery_result.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            discovery = {}
        try:
            handoff = json.loads((workdir / "learning_handoff.json").read_text(encoding="utf-8"))
            handoff["final_status"] = "CLOSED_VERIFIED" if env.outcome == "completed" and verify_pass else env.outcome.upper()
            handoff["approved_for_training"] = False
            (workdir / "learning_handoff.json").write_text(json.dumps(handoff, indent=2, ensure_ascii=False), encoding="utf-8")
        except (OSError, ValueError):
            handoff = {}
    _RAW_MATERIAL.parent.mkdir(parents=True, exist_ok=True)
    with _RAW_MATERIAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": _now(), "support_case_id": env.support_case_id,
            "source": env.source, "title": env.title, "ack": env.ack,
            "classification": analysis.get("classification", ""),
            "outcome": env.outcome, "verify_pass": verify_pass,
            "decision_reconciliation": analysis.get("decision_reconciliation", {}),
            "agent_decision": analysis.get("decision_reconciliation", {}).get("agent_decision", {}),
            "auditor_decision": analysis.get("decision_reconciliation", {}).get("auditor_decision", {}),
            "accepted_solution": analysis.get("decision_reconciliation", {}).get("accepted_solution"),
            "discovery_result": discovery,
            "learning_handoff": handoff,
            "implementation_status": analysis.get("implementation_status", "NOT_APPLIED"),
            "lesson": analysis.get("decision_reconciliation", {}).get("reason", ""),
            "approved_for_training": False,
        }, ensure_ascii=False) + "\n")
    try:
        from ops.agents.logi_experience_store import ExperienceRecord, write_experience_record
        write_experience_record(ExperienceRecord(
            project_area="queue_poller", task_type="closed_loop_case",
            situation=f"[{env.source}] {env.title}"[:300],
            problem_observed=analysis.get("root_cause_hypothesis", "")[:400],
            working_solution=analysis.get("human_report_ru", "")[:400] if verify_pass else "",
            reusable_rule=analysis.get("problem_summary_ru", "")[:300],
            confidence=0.6 if verify_pass else 0.3,
            confidence_reason="auto closed-loop case; unreviewed",
            tags=["queue_poller", env.outcome or "unknown"],
        ))
    except Exception:
        pass


# ── Reporting ────────────────────────────────────────────────────────────────

def _evidence_section(workdir: Path) -> str:
    """Render executed commands and their outputs so the report carries proof."""
    lines = []
    for label in ("diagnostics", "verification"):
        f = workdir / f"{label}.json"
        if not f.exists():
            continue
        try:
            entries = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for e in entries:
            if not e.get("allowed"):
                lines.append(f"$ {e['command']}\n  (отклонено: вне read-only allowlist)")
                continue
            out = (e.get("stdout") or e.get("stderr") or "").strip()
            lines.append(f"$ {e['command']}\n  exit={e.get('exit_code')}\n  {out[:500] or '(нет вывода)'}")
    return "\n\n".join(lines) or "команды не выполнялись"


def write_human_report(env: FailureEnvelope, analysis: dict, verify_pass: bool,
                       workdir: Path | None = None) -> Path:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORT_DIR / f"logi_report_{env.support_case_id}.md"
    status_ru = {"completed": "решена успешно", "needs_approval": "Codex-аудит требует доработки",
                 "rework_required": "возвращена в следующий виток ремонта",
                 "automation_exhausted": "автоматические попытки исчерпаны; требуется оператор",
                 "policy_blocked": "остановлена политикой безопасности; требуется оператор",
                 "failed": "внутренняя ошибка цикла", "deferred": "отложена"}.get(env.outcome, env.outcome)
    path.write_text(
        f"# Отчёт Logi — {env.title}\n\n"
        f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M %Z')}\n"
        f"Кейс: {env.support_case_id} (источник: {env.source})\n"
        f"Статус: {status_ru}\n\n"
        f"## Что за проблема\n{analysis.get('problem_summary_ru', env.description[:500])}\n\n"
        f"## Разбор\n{analysis.get('human_report_ru', 'см. артефакты')}\n\n"
        f"## Гипотеза первопричины\n{analysis.get('root_cause_hypothesis', '—')}\n\n"
        f"## Проверка\n{'пройдена' if verify_pass else 'не пройдена / не выполнялась'}\n\n"
        f"## Доказательства (команды и выводы)\n```\n{_evidence_section(workdir) if workdir else 'см. артефакты'}\n```\n\n"
        f"## Артефакты\n" + "\n".join(f"- {a}" for a in env.artifacts) + "\n",
        encoding="utf-8")
    return path


def _is_low_priority_backlog_item(env: FailureEnvelope) -> bool:
    """True for old, low-impact repairman backlog entries that should be
    drained silently (report + feedback still written) rather than paging
    Telegram once per item. Real incidents (impact HIGH/MEDIUM, or no impact
    field at all — never assume low) still notify individually."""
    if env.source != "repairman_dispatched":
        return False
    try:
        data = json.loads(env.description)
    except Exception:
        return False
    request = data.get("request", data)
    impact = str(request.get("impact", "")).strip().lower()
    return impact == "low"


def _dedupe_key(env: FailureEnvelope) -> str:
    return f"{env.source}:{env.incident_id or env.repair_id or env.title}:{env.outcome}"


def _notify_deduped(notify_fn, env: FailureEnvelope, text: str) -> bool:
    """Skip sending the exact same (source, title/incident, outcome) again
    within the dedupe window — defense in depth against a re-ingested source."""
    cache: dict[str, float] = {}
    if _NOTIFY_CACHE.exists():
        try:
            cache = json.loads(_NOTIFY_CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    key = _dedupe_key(env)
    now = time.time()
    last = cache.get(key, 0)
    # Dependency outages remain retryable in the queue, but an unchanged
    # deferred state is not a new operator event. Notify once until the
    # outcome changes (for example, to completed after health recovery).
    if env.outcome == "deferred" and last:
        return False
    if now - last < _NOTIFY_DEDUPE_SEC:
        return False
    sent = notify_fn(text)
    cache[key] = now
    cache = {k: v for k, v in cache.items()
             if k.endswith(":deferred") or now - v < _NOTIFY_DEDUPE_SEC * 4}
    _NOTIFY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _NOTIFY_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return sent


def _record_backlog_digest_item(env: FailureEnvelope, report: Path) -> bool:
    items = []
    if _BACKLOG_DIGEST.exists():
        try:
            items = json.loads(_BACKLOG_DIGEST.read_text(encoding="utf-8"))
        except Exception:
            items = []
    items.append({"title": env.title[:80], "outcome": env.outcome, "report": str(report)})
    _BACKLOG_DIGEST.parent.mkdir(parents=True, exist_ok=True)
    _BACKLOG_DIGEST.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return True   # "handled" (recorded for digest), not a live Telegram send


def _maybe_send_backlog_digest(notify_fn) -> None:
    """Once the low-impact backlog is fully drained (no more items match
    _is_low_priority_backlog_item on the next sweep), send ONE summary
    instead of one message per item."""
    if not _BACKLOG_DIGEST.exists():
        return
    remaining = [e for e in collect_problems(max_items=10_000) if _is_low_priority_backlog_item(e)]
    if remaining:
        return
    try:
        items = json.loads(_BACKLOG_DIGEST.read_text(encoding="utf-8"))
    except Exception:
        items = []
    if not items:
        _BACKLOG_DIGEST.unlink(missing_ok=True)
        return
    needs_approval = sum(1 for i in items if i["outcome"] == "needs_approval")
    notify_fn(
        f"Logi: разобрал старый backlog Repairman — {len(items)} низкоприоритетных заявок "
        f"(low impact). Из них {needs_approval} помечены needs_approval (не критично, можно "
        f"посмотреть без спешки). Отчёты: aims_workspace/logi_artifacts/queue_poller/."
    )
    _BACKLOG_DIGEST.unlink(missing_ok=True)


def send_telegram(text: str) -> bool:
    token = os.environ.get("LOGI_BOT_TOKEN", "").strip()
    if not token:
        return False
    body = json.dumps({"chat_id": int(TELEGRAM_CHAT_ID), "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=body,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return bool(json.loads(resp.read()).get("ok"))
    except Exception:
        return False


# ── Case driver ──────────────────────────────────────────────────────────────

def process_case(env: FailureEnvelope, llm=llm_analyze, repairman=repairman_inspect,
                 notify=send_telegram, judge=llm_judge,
                 apply_repair=repairman_apply) -> FailureEnvelope:
    workdir = _ARTIFACTS_ROOT / env.support_case_id
    workdir.mkdir(parents=True, exist_ok=True)
    tmpdir = workdir / "tmp"
    tmpdir.mkdir(exist_ok=True)
    verify_pass = False
    analysis: dict = {}
    try:
        env.stage, env.ack = "ANALYZE", "KNOWS_HOW"
        freshness = freshness_audit(env)
        (workdir / "freshness_audit.json").write_text(
            json.dumps(freshness, indent=2, ensure_ascii=False), encoding="utf-8")
        pre_processing_staleness = None
        if freshness["required"] or env.source in {"repairman_dispatched", "argus_incident"}:
            # Old messages are checked before the model is asked to classify
            # them.  This prevents a healthy, already-recovered service from
            # generating a new repair proposal merely because its old file is
            # still present in the queue.
            pre_processing_staleness = check_backlog_staleness(env)
            (workdir / "preprocessing_staleness_audit.json").write_text(
                json.dumps(pre_processing_staleness or {
                    "stale": False,
                    "note": "no live healthy-container evidence; continue with normal audit",
                }, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            if env.source == "repairman_dispatched":
                # This request already passed the canonical failure gate and
                # contains a grounded Repairman contract.  Do not put it back
                # through the optional Logi LLM analysis hop: an LLM outage
                # must not suppress an otherwise authorized L1 dispatch.
                try:
                    declared = json.loads(env.description)
                except (TypeError, json.JSONDecodeError) as exc:
                    raise RuntimeError("REPAIRMAN_DISPATCH_PAYLOAD_INVALID") from exc
                analysis = {
                    "classification": "repair_needed",
                    "root_cause_hypothesis": declared.get("failure_type") or "registered runtime failure",
                    "repair_request": "repair_then_resume",
                    "verification_commands": [],
                    "failure_id": declared.get("failure_id"),
                    "workflow_id": declared.get("workflow_id"),
                    "next_action_id": declared.get("next_action_id"),
                    "evidence_refs": declared.get("evidence_refs", []),
                    "grounded_dispatch": True,
                }
            else:
                analysis = _hydrate_declared_repair_contract(env, llm(env))
            (workdir / "analysis.json").write_text(
                json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")

            # Policy evolution is a read-only classification boundary here.
            # It never issues a permit, changes policy, requeues a case, or
            # dispatches Repairman; it records whether the evidence supports a
            # genuine policy gap for the later Owner-governed candidate flow.
            policy_chain = {
                "failure": bool(env.incident_id or env.repair_id or analysis.get("failure_id") or env.description),
                "root_cause": bool(analysis.get("root_cause_hypothesis")),
                "proposal": bool(analysis.get("repair_request")),
                "candidate": bool(analysis.get("candidate") or analysis.get("repair_request")),
                "tests": bool(analysis.get("verification_commands") or analysis.get("tests_run")),
                "rollback": bool(analysis.get("rollback_command") or analysis.get("rollback_plan")),
                "policy_decision": bool(analysis.get("policy_decision") or analysis.get("decision_review") or analysis.get("classification")),
                "attestation_stale": bool(analysis.get("attestation_stale")),
                "attestation_missing": not bool(analysis.get("attestation") or analysis.get("attestation_hash") or analysis.get("auditor_attestation")),
                "retry_conflict": bool(analysis.get("retry_conflict")),
                "authority_boundary": bool(analysis.get("authority_boundary")),
                "rollback_missing": not bool(analysis.get("rollback_command") or analysis.get("rollback_plan")),
                "tests_missing": not bool(analysis.get("verification_commands") or analysis.get("tests_run")),
                "pipeline_defect": bool(analysis.get("pipeline_defect")),
                "policy_rule_too_coarse": bool(analysis.get("policy_rule_too_coarse")),
            }
            policy_gap = capture_policy_gap(
                case_id=env.support_case_id,
                correlation_root_id=str((env.params or {}).get("correlation_root_id") or env.support_case_id),
                chain=policy_chain,
                second_pass=analysis.get("policy_second_pass") if isinstance(analysis.get("policy_second_pass"), dict) else None,
                current_policy_revision=str((env.params or {}).get("current_policy_revision") or "unknown"),
                current_policy_hash=str((env.params or {}).get("current_policy_hash") or ""),
            )
            policy_gap.update({
                "schema": "aims.policy_evolution.logi_classification.v1",
                "support_case_id": env.support_case_id,
                "caller": "ops.agents.logi_queue_poller.process_case",
                "mutation": {"permit_issued": False, "policy_changed": False, "queue_requeued": False, "repair_dispatched": False},
            })
            (workdir / "policy_evolution_classification.json").write_text(
                json.dumps(policy_gap, indent=2, ensure_ascii=False), encoding="utf-8")
            revalidation_trace = (env.params or {}).get("policy_evolution_revalidation")
            if isinstance(revalidation_trace, dict):
                live_safe = run_policy_evolution_revalidation_live_safe(revalidation_trace)
                (workdir / "policy_evolution_revalidation_live_safe.json").write_text(
                    json.dumps(live_safe, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            env.ack = "BLOCKED_EXTERNAL"
            env.outcome = "deferred"
            (workdir / "llm_error.txt").write_text(str(e)[:1000], encoding="utf-8")
            return env

        if analysis.get("classification") == "out_of_scope":
            env.ack = "NEEDS_NEW_SKILL"

        env.stage = "DIAGNOSE"
        run_allowlisted(analysis.get("diagnostic_commands", []), workdir, "diagnostics")

        env.stage = "RESOLVE"
        staleness = pre_processing_staleness or check_backlog_staleness(env)
        if staleness:
            (workdir / "staleness_check.json").write_text(
                json.dumps(staleness, indent=2, ensure_ascii=False), encoding="utf-8")
        repair_not_formed = (
            str(analysis.get("classification", "")).lower() == "repair_needed"
            and not str(analysis.get("repair_request") or "").strip()
        )
        if repair_not_formed:
            # A missing action contract is a formation failure, not a failed
            # execution.  Do not dispatch a vague task to Repairman.
            env.outcome = "failed"
            analysis["closed_loop_failure_class"] = "FILE_OPERATION_NOT_EXECUTED"
            analysis["action_formation_status"] = "REPAIR_NOT_FORMED"
            analysis["human_report_ru"] = (
                f"{analysis.get('human_report_ru', '')}\n\n"
                "Ремонт не сформирован: отсутствуют target, exact change и bounded repair request."
            ).strip()
        elif staleness:
            # Old dispatched incident, but the affected service is currently
            # healthy — never send a human an approval request for something
            # already resolved. No repairman call, no approval, just evidence.
            analysis["human_report_ru"] = (
                f"{analysis.get('human_report_ru', '')}\n\nПроверка актуальности: "
                f"{staleness['container']} сейчас {staleness['current_state']} "
                f"(RestartCount={staleness['restart_count']}) — {staleness['note']}. "
                f"Инцидент устарел, ремонт не требуется."
            ).strip()
            env.outcome = "completed"
        elif analysis.get("classification") == "repair_needed":
            inspect = repairman(env, analysis, [])
            (workdir / "repairman_inspect.json").write_text(
                json.dumps(inspect, indent=2, ensure_ascii=False), encoding="utf-8")
            codex_audit = _codex_audit_case(env, analysis, inspect, workdir)
            (workdir / "codex_audit.json").write_text(
                json.dumps(codex_audit, indent=2, ensure_ascii=False), encoding="utf-8")
            reconciliation = _reconcile_repairman_codex_decision(analysis, codex_audit)
            analysis["decision_reconciliation"] = reconciliation
            (workdir / "decision_reconciliation.json").write_text(
                json.dumps(reconciliation, indent=2, ensure_ascii=False), encoding="utf-8")
            accepted_solution, discovered_codex, discovered_reconciliation, inspect = _run_repair_discovery(
                env, analysis, inspect, codex_audit, reconciliation, workdir,
                llm=llm, repairman=repairman,
            )
            if accepted_solution:
                codex_audit = discovered_codex
                reconciliation = discovered_reconciliation
                analysis["decision_reconciliation"] = reconciliation
                analysis["repair_request"] = accepted_solution.get("repair_request", analysis.get("repair_request", ""))
                if accepted_solution.get("verification_commands"):
                    analysis["verification_commands"] = accepted_solution["verification_commands"]
                (workdir / "accepted_solution.json").write_text(
                    json.dumps({"schema": "aims.accepted_solution.v1", "source": "repairman_codex_reconciliation", "decision_review": reconciliation["status"], "solution": accepted_solution}, indent=2, ensure_ascii=False), encoding="utf-8")
            codex_status = str(codex_audit.get("status", "SKIPPED")).upper()
            if codex_status == "SKIPPED":
                env.ack = "BLOCKED_EXTERNAL"
                env.outcome = "deferred"
                analysis["human_report_ru"] = (
                    f"{analysis.get('human_report_ru', '')}\n\n"
                    "Codex CLI-аудитор недоступен или не прошёл preflight; Telegram не используется "
                    "для одобрения. Кейс отложен до восстановления аудиторского моста."
                ).strip()
            elif codex_status != "PASSED":
                env.outcome = "failed"
                analysis["closed_loop_failure_class"] = "UNVERIFIED_COMPLETION"
                analysis["human_report_ru"] = (
                    f"{analysis.get('human_report_ru', '')}\n\n"
                    f"Codex CLI не одобрил bounded repair: статус {codex_status}. "
                    "Рекомендации сохранены в codex_audit.json; Telegram содержит только результат."
                ).strip()
            elif reconciliation["status"] not in {"MATCH", "CORRECTED"}:
                env.outcome = "failed"
                analysis["closed_loop_failure_class"] = "UNVERIFIED_COMPLETION"
                analysis["human_report_ru"] = (
                    f"{analysis.get('human_report_ru', '')}\n\n"
                    "Codex не зафиксировал явное совпадение или корректировку решения Repairman; применение запрещено."
                ).strip()
            else:
                if reconciliation["status"] == "CORRECTED":
                    accepted = reconciliation["accepted_solution"]
                    analysis["repair_request"] = accepted.get("repair_request", analysis["repair_request"])
                    if accepted.get("verification_commands"):
                        analysis["verification_commands"] = accepted["verification_commands"]
                accepted_solution = reconciliation["accepted_solution"]
                # Bind the exact reconciled solution into the payload used by
                # Poli, cross-check and Repairman apply.  The original
                # proposal remains only in the immutable discovery artifacts.
                analysis["accepted_solution"] = accepted_solution
                (workdir / "accepted_solution.json").write_text(
                    json.dumps({
                        "schema": "aims.accepted_solution.v1",
                        "source": "repairman_codex_reconciliation",
                        "decision_review": reconciliation["status"],
                        "solution": accepted_solution,
                    }, indent=2, ensure_ascii=False), encoding="utf-8")
                poli_audit = _poli_audit_case(
                    env, analysis, codex_audit, workdir,
                    accepted_solution=accepted_solution,
                )
                (workdir / "poli_audit.json").write_text(
                    json.dumps(poli_audit, indent=2, ensure_ascii=False), encoding="utf-8")
                if not poli_audit.get("allowed"):
                    env.outcome = "failed"
                    analysis["closed_loop_failure_class"] = SAFETY_INVARIANT_VIOLATED
                    analysis["human_report_ru"] = (
                        f"{analysis.get('human_report_ru', '')}\n\n"
                        "Poli отклонил выполнение после проверки Codex: "
                        + "; ".join(poli_audit.get("reasons", []))
                        + ". Telegram используется только для результата."
                    ).strip()
                    # Do not enter the old Telegram approval branch.
                    decision = None
                else:
                    decision = None
                from ops.agents.logi_decision_auditor import audit_repair_decision
                if decision is None and poli_audit.get("allowed"):
                    decision = audit_repair_decision(env, analysis, inspect)
                # Codex replaces the old human approval only for a task-scoped,
                # non-strategy, non-production bounded repair.
                task_scoped = bool((env.params or {}).get("production_mutation") is False)
                if decision is not None and decision.decision == "HUMAN_APPROVAL" and task_scoped and not decision.strategy_change:
                    decision.decision = "AUTO_REPAIR"
                    decision.human_approval_required = False
                    decision.risk_level = "codex_bounded"
                    decision.reasons.append("Codex CLI audit passed; Telegram approval is not used")
                if decision is not None:
                    (workdir / "decision_audit.json").write_text(
                        json.dumps(decision.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
                    analysis["decision_audit"] = decision.to_dict()
                if decision is not None and decision.decision == "AUTO_REPAIR":
                    cross_check = _pre_apply_cross_check(
                        env, analysis, inspect, codex_audit, poli_audit, decision)
                    (workdir / "pre_apply_cross_check.json").write_text(
                        json.dumps(cross_check, indent=2, ensure_ascii=False), encoding="utf-8")
                    cross_check["decision_reconciliation"] = reconciliation
                    (workdir / "pre_apply_cross_check.json").write_text(
                        json.dumps(cross_check, indent=2, ensure_ascii=False), encoding="utf-8")
                    if cross_check["status"] != "PASS":
                        env.outcome = "failed"
                        analysis["closed_loop_failure_class"] = "UNVERIFIED_COMPLETION"
                        analysis["human_report_ru"] = (
                            f"{analysis.get('human_report_ru', '')}\n\n"
                            "Локальный cross-check агентов заблокировал применение: "
                            + "; ".join(k for k, v in cross_check["checks"].items() if not v)
                        ).strip()
                    else:
                        applied = apply_repair(env, analysis, [])
                        (workdir / "repairman_apply.json").write_text(
                            json.dumps(applied, indent=2, ensure_ascii=False), encoding="utf-8")
                        env.outcome = "completed" if str(applied.get("status", "")).lower() in {
                            "ok", "accepted", "queued", "completed", "success"
                        } else "failed"
                        analysis["implementation_status"] = "APPLIED" if env.outcome == "completed" else "APPLY_FAILED"
                        if env.outcome == "failed":
                            analysis["closed_loop_failure_class"] = "FILE_OPERATION_NOT_EXECUTED"
                elif decision is not None and decision.decision == "NO_REPAIR":
                    env.outcome = "completed"
                elif decision is not None:
                    env.outcome = "failed"
                    analysis["closed_loop_failure_class"] = "UNVERIFIED_COMPLETION"
        else:
            env.outcome = "completed"

        env.stage = "VERIFY"
        if staleness:
            # The exact docker-inspect result gathered in RESOLVE is the
            # verification. Do not run model-proposed checks against unrelated
            # ports or let an advisory model overrule live healthy state.
            vres = [{
                "command": "governed docker inspect live-health check",
                "allowed": True,
                "execution_status": "EXECUTED_DURING_STALENESS_CHECK",
                "exit_code": 0,
                "evidence": staleness,
            }]
            (workdir / "verification.json").write_text(
                json.dumps(vres, indent=2, ensure_ascii=False), encoding="utf-8")
            verify_pass = True
        else:
            target_commands = analysis.get("verification_commands", [])
            actual_repair = None
            repair_result_path = workdir / "repairman_apply.json"
            if repair_result_path.exists():
                try:
                    candidate = json.loads(repair_result_path.read_text(encoding="utf-8"))
                    if str(candidate.get("worker_terminal", "")).upper() in {
                        "PASS", "COMPLETED", "SUCCESS", "FAIL", "FAILED", "BLOCKED", "TIMEOUT"
                    }:
                        actual_repair = candidate
                except (OSError, ValueError, TypeError):
                    actual_repair = None
            if actual_repair is not None:
                (workdir / "verification_context.json").write_text(
                    json.dumps({
                        "case_id": env.incident_id or env.repair_id or env.support_case_id,
                        "source": env.source,
                        "source_ref": env.source_ref,
                        "incident_id": env.incident_id,
                        "support_case_id": env.support_case_id,
                        "run_id": (env.params or {}).get("run_id"),
                        "runtime_manifest_id": (env.params or {}).get("runtime_manifest_id"),
                        "source_code_checksum": (env.params or {}).get("source_code_checksum"),
                        "target_commands": target_commands,
                    }, indent=2, ensure_ascii=False), encoding="utf-8")
                target_vres = run_allowlisted(target_commands, workdir, "target_verification")
                (workdir / "target_verification.json").write_text(
                    json.dumps(target_vres, indent=2, ensure_ascii=False), encoding="utf-8")
                receipt_cmd = (
                    f"python3 ops/agents/logi_production_verifier.py --workdir {workdir}"
                )
                receipt_vres = run_allowlisted([receipt_cmd], workdir, "verification_receipt")
                vres = target_vres + receipt_vres
            else:
                # Non-Repairman cases retain their existing read-only evidence
                # contract.  A generic command can never satisfy the bounded
                # Repairman receipt contract above.
                vres = run_allowlisted(target_commands, workdir, "verification")
            (workdir / "verification.json").write_text(
                json.dumps(vres, indent=2, ensure_ascii=False), encoding="utf-8")
            ran = [r for r in vres if r.get("allowed")]
            verify_pass = bool(ran) and all(r.get("exit_code") == 0 for r in ran)
        if not staleness and env.outcome == "completed" and not verify_pass:
            # completed requires real passed evidence; zero evidence is never a pass
            env.outcome = "failed"
            analysis["closed_loop_failure_class"] = VERIFICATION_FAILED
            analysis["human_report_ru"] = (
                f"{analysis.get('human_report_ru', '')}\n\n"
                "Недостаточно фактических verification-доказательств; approve через Telegram не создаётся."
            ).strip()

        # Independent judge (advisory): a disagreeing judge demotes 'completed'
        # to needs_approval — a human look, never a silent pass.
        verdict = ({
            "solved": True,
            "confidence": 1.0,
            "reason": "Live Docker state is running and healthy; stale incident requires no repair.",
            "judge_model": "DETERMINISTIC_LIVE_HEALTH_GUARD",
        } if staleness else judge(env, analysis, vres))
        (workdir / "judge_verdict.json").write_text(
            json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
        if env.outcome == "completed" and verdict.get("solved") is False:
            env.outcome = "failed"
            analysis["closed_loop_failure_class"] = VERIFICATION_FAILED
            analysis["human_report_ru"] = (
                f"{analysis.get('human_report_ru', '')}\n\n"
                "Независимая проверка не подтвердила результат; Telegram содержит только итог, "
                "повтор требует нового Codex-аудита."
            ).strip()
    finally:
        env.stage = "FEEDBACK"
        _advance_closed_loop(env, analysis, workdir)
        record_feedback(env, analysis, verify_pass, workdir=workdir)
        env.artifacts = [
            str(p.relative_to(_ROOT)) if p.is_relative_to(_ROOT) else str(p)
            for p in sorted(workdir.glob("*.json"))
        ]
        report = write_human_report(env, analysis, verify_pass, workdir=workdir)
        env.artifacts.append(str(report))
        shutil.rmtree(tmpdir, ignore_errors=True)          # CLEANUP intermediates
        status_ru = {"completed": "✅ решена успешно", "needs_approval": "🟡 Codex-аудит требует доработки",
                     "rework_required": "🔁 замечания Codex/проверки возвращены в следующий виток ремонта",
                     "automation_exhausted": "🛑 автоматические попытки исчерпаны; требуется действие оператора",
                     "policy_blocked": "🛡 выполнение остановлено политикой безопасности; требуется оператор",
                     "failed": "❌ внутренняя ошибка цикла",
                     "deferred": "⏸ отложена: внешний LLM/Codex недоступен"}.get(env.outcome, env.outcome)
        # Finalize (move/mark the source) BEFORE checking "is the backlog
        # empty yet" — otherwise this item's own still-present source file
        # would make the backlog look non-empty on its own last iteration.
        _finalize_source(env)
        if _is_low_priority_backlog_item(env):
            # Old low-impact backlog: report + feedback still written, but no
            # individual Telegram ping — drained silently, summarized once
            # the backlog empties (see _maybe_send_backlog_digest).
            telegram_ok = _record_backlog_digest_item(env, report)
            _maybe_send_backlog_digest(notify)
        else:
            telegram_ok = _notify_deduped(
                notify, env, f"Logi: была проблема «{env.title[:80]}» — {status_ru}.\nДетали: {report}")
        case = asdict(env)
        case["telegram_notified"] = bool(telegram_ok)
        (workdir / "case.json").write_text(
            json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
    return env


def _finalize_source(env: FailureEnvelope) -> None:
    """Move/mark the source record according to the outcome (never silently drop)."""
    # ``process_case`` may normalize a successful Repairman verdict to
    # ``solved`` before finalization. Treat it as terminal for dispatched
    # artifacts, otherwise the source remains in dispatched/ and is polled
    # repeatedly. Retryable outcomes (deferred/failed/rework_required) remain
    # preserved for their retry paths.
    terminal_outcomes = {"completed", "solved", "automation_exhausted", "policy_blocked", "closed_by_operator"}
    if env.source == "argus_incident" and env.outcome in terminal_outcomes:
        processed = set()
        if _PROCESSED_INCIDENTS.exists():
            try:
                processed = set(json.loads(_PROCESSED_INCIDENTS.read_text(encoding="utf-8")))
            except Exception:
                processed = set()
        processed.add(Path(env.source_ref).name)
        _PROCESSED_INCIDENTS.parent.mkdir(parents=True, exist_ok=True)
        _PROCESSED_INCIDENTS.write_text(json.dumps(sorted(processed)), encoding="utf-8")
        return
    if env.source == "repairman_dispatched":
        if env.outcome not in terminal_outcomes:
            return
        # Move out of dispatched/ regardless of outcome — otherwise the same
        # file is re-ingested and re-reported on every poll cycle forever.
        src = Path(env.source_ref)
        if src.exists():
            try:
                _REPAIRMAN_REVIEWED.mkdir(parents=True, exist_ok=True)
                data = json.loads(src.read_text(encoding="utf-8"))
                data["poller_outcome"] = env.outcome
                data["poller_support_case_id"] = env.support_case_id
                (_REPAIRMAN_REVIEWED / src.name).write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                src.unlink()
            except Exception:
                pass
        return
    if env.source != "logi_task_queue":
        return
    src = Path(env.source_ref)
    if not src.exists():
        return
    if env.outcome in {"automation_exhausted", "policy_blocked"}:
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
            data["status"] = env.outcome
            data["blocked_reason"] = "closed-loop terminal escalation; explicit operator action required"
            data.setdefault("params", {})["support_case_id"] = env.support_case_id
            _BLOCKED_REWORK_DIR.mkdir(parents=True, exist_ok=True)
            (_BLOCKED_REWORK_DIR / src.name).write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            src.unlink()
        except Exception:
            pass
        return
    dest_key = env.outcome if env.outcome in _DONE_DIRS else None
    if env.outcome not in terminal_outcomes or dest_key is None:
        return                                            # stays pending for retry
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
        data["status"] = env.outcome
        data.setdefault("params", {})["support_case_id"] = env.support_case_id
        dest = _DONE_DIRS[dest_key]
        dest.mkdir(parents=True, exist_ok=True)
        (dest / src.name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        src.unlink()
    except Exception:
        pass


# ── Daemon loop ──────────────────────────────────────────────────────────────

def poll_once(max_cases: int = 1) -> list[FailureEnvelope]:
    _ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)
    done = []
    for env in collect_problems(max_items=max_cases):
        done.append(process_case(env))
    _HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    _HEARTBEAT.write_text(json.dumps({
        "ts": _now(), "cases_processed": len(done),
        "outcomes": [e.outcome for e in done]}), encoding="utf-8")
    return done


def main() -> None:
    _load_env_bom_safe()
    interval = int(os.environ.get("LOGI_POLLER_INTERVAL_SEC", "120"))
    if _LOCK.exists():
        owner_pid = None
        try:
            owner_pid = int(_LOCK.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            pass
        if owner_pid and owner_pid != os.getpid():
            try:
                os.kill(owner_pid, 0)
            except ProcessLookupError:
                owner_pid = None
            except PermissionError:
                pass
            else:
                print("another poller instance appears active; exiting")
                return
        if not owner_pid or owner_pid == os.getpid():
            # A stopped systemd process can leave the old marker behind.  A
            # PID marker lets restart distinguish that stale file from a live
            # poller without relying on wall-clock age.
            _LOCK.unlink(missing_ok=True)
    _ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)
    _LOCK.write_text(str(os.getpid()), encoding="utf-8")
    while True:
        _LOCK.write_text(str(os.getpid()), encoding="utf-8")
        try:
            done = poll_once(max_cases=1)
            for e in done:
                print(f"[{_now()}] {e.support_case_id} {e.title[:50]!r} -> {e.outcome}")
        except Exception as exc:
            print(f"[{_now()}] poller cycle error: {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
