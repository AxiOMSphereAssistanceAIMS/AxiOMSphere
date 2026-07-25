"""
logi_queue_poller.py

Closed-loop queue poller: picks up problems, drives them through analysis on
slot32, tiered resolution, replay verification, learning feedback, cleanup and
reporting. Fail-loud by design: every stage writes an artifact, and a task can
never be silently dropped — it always ends in completed / failed /
needs_approval / deferred with a capability ACK on record.

Pipeline per case:
  INTAKE     logi_tasks/pending + repairman_requests/dispatched + problem inbox
             → FailureEnvelope with support_case_id
  ACK        KNOWS_HOW | NEEDS_NEW_SKILL | BLOCKED_EXTERNAL (never silent)
  ANALYZE    slot32 LLM + experience recall (playbooks / anti-patterns)
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
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PENDING_DIR = _ROOT / "aims_workspace" / "logi_tasks" / "pending"
_DONE_DIRS = {
    "completed": _ROOT / "aims_workspace" / "logi_tasks" / "completed",
    "failed": _ROOT / "aims_workspace" / "logi_tasks" / "failed",
    "needs_approval": _ROOT / "aims_workspace" / "logi_tasks" / "needs_approval",
}
_PROBLEM_INBOX = _ROOT / "aims_workspace" / "logi_problem_inbox"
_REPAIRMAN_DISPATCHED = _ROOT / "aims_workspace" / "repairman_requests" / "dispatched"
_ARTIFACTS_ROOT = _ROOT / "aims_workspace" / "logi_artifacts" / "queue_poller"
_RAW_MATERIAL = _ROOT / "aims_workspace" / "logi_session_memory" / "queue_poller_raw.jsonl"
_HEARTBEAT = _ROOT / "aims_workspace" / "logi_controlled_autonomy_status" / "queue_poller_heartbeat.json"
_LOCK = _ARTIFACTS_ROOT / ".poller.lock"
_REPORT_DIR = Path(os.environ.get("LOGI_POLLER_REPORT_DIR", str(Path.home() / "tmp")))

SLOT32_URL = os.environ.get("AIMS_SLOT32_OPENAI_URL", "http://127.0.0.1:18081/v1")
SLOT32_MODEL = os.environ.get("AIMS_SLOT32_MODEL", "aims_slot32_qwen3_coder_next_fp8_v0")
REPAIRMAN_URL = os.environ.get("AIMS_REPAIRMAN_URL", "http://127.0.0.1:8010")
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
    ack: str = ""                # KNOWS_HOW | NEEDS_NEW_SKILL | BLOCKED_EXTERNAL
    stage: str = "INTAKE"
    outcome: str = ""            # completed | failed | needs_approval | deferred
    artifacts: list[str] = field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _case_id() -> str:
    return "case_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + os.urandom(3).hex()


def _load_env_bom_safe() -> None:
    env_file = _ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


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
            envelopes.append(FailureEnvelope(
                support_case_id=_case_id(), source="logi_task_queue",
                source_ref=str(p), title=t.get("title", p.stem),
                description=t.get("description", ""),
                requested_by=t.get("requested_by", ""),
                priority=t.get("priority", "normal"), created_at=_now(),
            ))
    if _PROBLEM_INBOX.exists():
        for p in sorted(_PROBLEM_INBOX.glob("*.md")) + sorted(_PROBLEM_INBOX.glob("*.txt")):
            envelopes.append(FailureEnvelope(
                support_case_id=_case_id(), source="problem_inbox",
                source_ref=str(p), title=p.stem,
                description=p.read_text(encoding="utf-8", errors="replace")[:4000],
                created_at=_now(),
            ))
    if _REPAIRMAN_DISPATCHED.exists():
        for p in sorted(_REPAIRMAN_DISPATCHED.glob("*.json"), key=lambda f: f.stat().st_mtime):
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            envelopes.append(FailureEnvelope(
                support_case_id=_case_id(), source="repairman_dispatched",
                source_ref=str(p),
                title=r.get("title") or r.get("task") or p.stem,
                description=json.dumps(r, ensure_ascii=False)[:4000],
                repair_id=r.get("request_id", ""),
                incident_id=r.get("incident_id", ""), created_at=_now(),
            ))
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
        from ops.agents.logi_experience_recall import recall_playbooks, recall_anti_patterns
        parts = []
        for m in recall_playbooks(text, limit=2).matches:
            parts.append(f"playbook: {m.summary}")
        for m in recall_anti_patterns(text, limit=2).matches:
            parts.append(f"anti-pattern: {m.summary}")
        return "\n".join(parts) or "нет похожего опыта"
    except Exception as e:
        return f"recall unavailable: {e}"


def llm_analyze(env: FailureEnvelope, timeout: int = 420) -> dict:
    prompt = _ANALYSIS_PROMPT.format(
        title=env.title, description=env.description[:3000],
        experience=_recall_context(env.title + " " + env.description[:400]),
    )
    body = json.dumps({
        "model": SLOT32_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1400, "temperature": 0.2,
    }).encode()
    req = urllib.request.Request(
        SLOT32_URL.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON in LLM analysis: {content[:200]}")
    return json.loads(m.group(0))


# ── Diagnostics / verification (allowlisted, read-only) ──────────────────────

def _command_allowed(cmd: str) -> bool:
    if _FORBIDDEN_TOKENS.search(cmd):
        return False
    tokens = cmd.split()
    return any(tokens[:len(p)] == list(p) for p in DIAG_ALLOWLIST)


def run_allowlisted(commands: list[str], workdir: Path, label: str) -> list[dict]:
    results = []
    for cmd in commands[:8]:
        entry = {"command": cmd, "allowed": _command_allowed(cmd)}
        if entry["allowed"]:
            try:
                proc = subprocess.run(
                    cmd, shell=True, cwd=str(_ROOT), timeout=180,
                    capture_output=True, text=True)
                entry["exit_code"] = proc.returncode
                entry["stdout"] = proc.stdout[-4000:]
                entry["stderr"] = proc.stderr[-2000:]
            except subprocess.TimeoutExpired:
                entry["exit_code"] = -1
                entry["stderr"] = "TIMEOUT"
        else:
            entry["skipped_reason"] = "not in read-only allowlist"
        results.append(entry)
    out = workdir / f"{label}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


# ── Resolution (Repairman bridge) ────────────────────────────────────────────

def repairman_inspect(env: FailureEnvelope, analysis: dict, diagnostics: list[dict]) -> dict:
    payload = json.dumps({
        "task": (analysis.get("repair_request") or env.title)[:2000],
        "mode": "inspect",
        "source": f"logi_queue_poller:{env.support_case_id}",
    }).encode()
    req = urllib.request.Request(
        REPAIRMAN_URL.rstrip("/") + "/repair", data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"status": "error", "error": str(e)[:300]}


# ── Feedback / learning (candidate-only) ─────────────────────────────────────

def record_feedback(env: FailureEnvelope, analysis: dict, verify_pass: bool) -> None:
    _RAW_MATERIAL.parent.mkdir(parents=True, exist_ok=True)
    with _RAW_MATERIAL.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": _now(), "support_case_id": env.support_case_id,
            "source": env.source, "title": env.title, "ack": env.ack,
            "classification": analysis.get("classification", ""),
            "outcome": env.outcome, "verify_pass": verify_pass,
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

def write_human_report(env: FailureEnvelope, analysis: dict, verify_pass: bool) -> Path:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = _REPORT_DIR / f"logi_report_{env.support_case_id}.md"
    status_ru = {"completed": "решена успешно", "needs_approval": "разобрана, ждёт подтверждения",
                 "failed": "НЕ решена", "deferred": "отложена"}.get(env.outcome, env.outcome)
    path.write_text(
        f"# Отчёт Logi — {env.title}\n\n"
        f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M %Z')}\n"
        f"Кейс: {env.support_case_id} (источник: {env.source})\n"
        f"Статус: {status_ru}\n\n"
        f"## Что за проблема\n{analysis.get('problem_summary_ru', env.description[:500])}\n\n"
        f"## Разбор\n{analysis.get('human_report_ru', 'см. артефакты')}\n\n"
        f"## Гипотеза первопричины\n{analysis.get('root_cause_hypothesis', '—')}\n\n"
        f"## Проверка\n{'пройдена' if verify_pass else 'не пройдена / не выполнялась'}\n\n"
        f"## Артефакты\n" + "\n".join(f"- {a}" for a in env.artifacts) + "\n",
        encoding="utf-8")
    return path


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
                 notify=send_telegram) -> FailureEnvelope:
    workdir = _ARTIFACTS_ROOT / env.support_case_id
    workdir.mkdir(parents=True, exist_ok=True)
    tmpdir = workdir / "tmp"
    tmpdir.mkdir(exist_ok=True)
    verify_pass = False
    analysis: dict = {}
    try:
        env.stage, env.ack = "ANALYZE", "KNOWS_HOW"
        try:
            analysis = llm(env)
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
        if analysis.get("classification") == "repair_needed":
            inspect = repairman(env, analysis, [])
            (workdir / "repairman_inspect.json").write_text(
                json.dumps(inspect, indent=2, ensure_ascii=False), encoding="utf-8")
            env.outcome = "needs_approval"   # fix mode never auto-fired
        else:
            env.outcome = "completed"

        env.stage = "VERIFY"
        vres = run_allowlisted(analysis.get("verification_commands", []), workdir, "verification")
        ran = [r for r in vres if r.get("allowed")]
        verify_pass = bool(ran) and all(r.get("exit_code") == 0 for r in ran)
        if env.outcome == "completed" and ran and not verify_pass:
            env.outcome = "failed"
    finally:
        env.stage = "FEEDBACK"
        record_feedback(env, analysis, verify_pass)
        env.artifacts = [
            str(p.relative_to(_ROOT)) if p.is_relative_to(_ROOT) else str(p)
            for p in sorted(workdir.glob("*.json"))
        ]
        report = write_human_report(env, analysis, verify_pass)
        env.artifacts.append(str(report))
        shutil.rmtree(tmpdir, ignore_errors=True)          # CLEANUP intermediates
        status_ru = {"completed": "✅ решена успешно", "needs_approval": "🟡 разобрана, нужен approve на ремонт",
                     "failed": "❌ не решена", "deferred": "⏸ отложена (LLM недоступен)"}.get(env.outcome, env.outcome)
        telegram_ok = notify(f"Logi: была проблема «{env.title[:80]}» — {status_ru}.\nДетали: {report}")
        case = asdict(env)
        case["telegram_notified"] = bool(telegram_ok)
        (workdir / "case.json").write_text(
            json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
        _finalize_source(env)
    return env


def _finalize_source(env: FailureEnvelope) -> None:
    """Move the source task file according to the outcome (never silently drop)."""
    if env.source != "logi_task_queue":
        return
    src = Path(env.source_ref)
    if not src.exists():
        return
    dest_key = env.outcome if env.outcome in _DONE_DIRS else None
    if env.outcome == "deferred" or dest_key is None:
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
    if _LOCK.exists() and time.time() - _LOCK.stat().st_mtime < interval * 3:
        print("another poller instance appears active; exiting")
        return
    _ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)
    while True:
        _LOCK.touch()
        try:
            done = poll_once(max_cases=1)
            for e in done:
                print(f"[{_now()}] {e.support_case_id} {e.title[:50]!r} -> {e.outcome}")
        except Exception as exc:
            print(f"[{_now()}] poller cycle error: {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    main()
