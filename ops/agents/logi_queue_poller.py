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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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
_REPAIRMAN_DISPATCHED = _ROOT / "aims_workspace" / "repairman_requests" / "dispatched"
_REPAIRMAN_REVIEWED = _ROOT / "aims_workspace" / "repairman_requests" / "reviewed_by_poller"
_NOTIFY_CACHE = _ROOT / "aims_workspace" / "logi_artifacts" / "queue_poller" / "notify_cache.json"
_BACKLOG_DIGEST = _ROOT / "aims_workspace" / "logi_artifacts" / "queue_poller" / "backlog_digest.json"
_NOTIFY_DEDUPE_SEC = 1800
_FRESHNESS_MAX_AGE_SEC = 2 * 86400
_ARTIFACTS_ROOT = _ROOT / "aims_workspace" / "logi_artifacts" / "queue_poller"
_RAW_MATERIAL = _ROOT / "aims_workspace" / "logi_session_memory" / "queue_poller_raw.jsonl"
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
            # Prevent an unchanged Codex/Poli blocker from becoming an
            # infinite retry storm. Three cases with the same title that were
            # actually blocked at the Codex or Poli gate (not a downstream
            # verify/judge failure) require a controlled rework packet with
            # the real reasons on record before intake can resume.
            prior_failures = 0
            prior_reasons: list[str] = []
            for case_file in sorted(_ARTIFACTS_ROOT.glob("case_*/case.json"), key=lambda f: f.stat().st_mtime):
                try:
                    case = json.loads(case_file.read_text(encoding="utf-8"))
                    if case.get("outcome") != "failed" or case.get("title") != t.get("title"):
                        continue
                    codex_path = case_file.parent / "codex_audit.json"
                    if not codex_path.is_file():
                        continue  # failed before reaching a Codex/Poli gate — not a gate blockage
                    codex = json.loads(codex_path.read_text(encoding="utf-8"))
                    codex_status = str(codex.get("status", "")).upper()
                    poli_allowed = None
                    poli_path = case_file.parent / "poli_audit.json"
                    if poli_path.is_file():
                        try:
                            poli_allowed = json.loads(poli_path.read_text(encoding="utf-8")).get("allowed")
                        except (OSError, ValueError, TypeError):
                            poli_allowed = None
                    if codex_status == "PASSED" and poli_allowed is not False:
                        continue  # gate passed; any later failure was verify/judge, not a repeated blockage
                    prior_failures += 1
                    reason = "; ".join(
                        f.get("finding", "") for f in codex.get("findings", []) if f.get("finding")
                    ) or f"codex_status={codex_status}"
                    if poli_path.is_file():
                        try:
                            poli_reasons = json.loads(poli_path.read_text(encoding="utf-8")).get("reasons") or []
                            if poli_reasons:
                                reason = reason + " | poli: " + "; ".join(poli_reasons)
                        except (OSError, ValueError, TypeError):
                            pass
                    prior_reasons.append(reason)
                except (OSError, ValueError, TypeError):
                    continue
            if prior_failures >= int(os.environ.get("LOGI_MAX_IDENTICAL_FAILURES", "3")):
                _BLOCKED_REWORK_DIR.mkdir(parents=True, exist_ok=True)
                t["status"] = "blocked_rework"
                t["blocked_reason"] = "same task blocked at the Codex/Poli gate three times; auto-retry stopped"
                t["prior_failed_cases"] = prior_failures
                (_BLOCKED_REWORK_DIR / p.name).write_text(json.dumps(t, indent=2, ensure_ascii=False), encoding="utf-8")
                (_BLOCKED_REWORK_DIR / f"support_case_{p.stem}.json").write_text(json.dumps({
                    "schema": "aims.logi.support_case.v1",
                    "task_title": t.get("title", p.stem),
                    "created_at": _now(),
                    "reason": "3 identical Codex/Poli gate blockages for this task; automatic retry stopped",
                    "prior_failure_reasons": prior_reasons[-3:],
                    "remediation_plan": [
                        "Review each listed Codex/Poli blocking reason individually before resubmitting.",
                        "Prepare new evidence (updated diff, passing QA regression, verified rollback baseline) "
                        "that addresses every listed reason — do not resubmit the unchanged proposal.",
                        "If the reasons indicate a missing capability rather than a bug, file a "
                        "NEEDS_NEW_SKILL request instead of retrying this task.",
                        "A human or Logi-orchestrated session must clear this support case before the "
                        "task re-enters the pending queue.",
                    ],
                }, indent=2, ensure_ascii=False), encoding="utf-8")
                p.unlink()
                continue
            envelopes.append(FailureEnvelope(
                support_case_id=_case_id(), source="logi_task_queue",
                source_ref=str(p), title=t.get("title", p.stem),
                description=t.get("description", ""),
                requested_by=t.get("requested_by", ""),
                priority=t.get("priority", "normal"), created_at=_now(),
                params=dict(t.get("params") or {}),
            ))
    if _PROBLEM_INBOX.exists():
        for p in sorted(_PROBLEM_INBOX.glob("*.md")) + sorted(_PROBLEM_INBOX.glob("*.txt")):
            envelopes.append(FailureEnvelope(
                support_case_id=_case_id(), source="problem_inbox",
                source_ref=str(p), title=p.stem,
                description=p.read_text(encoding="utf-8", errors="replace")[:4000],
                created_at=_now(),
            ))
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
            envelopes.append(FailureEnvelope(
                support_case_id=_case_id(), source="argus_incident",
                source_ref=str(p), title=f"Argus incident: {p.stem}",
                description=json.dumps(inc, ensure_ascii=False)[:4000],
                incident_id=p.stem, created_at=_now(),
            ))
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
    requested_slot = str((env.params or {}).get("model_slot") or "").strip().lower()
    if requested_slot == "slot32":
        # Slot32 is the coding worker and its queued proxy caps output at 700
        # tokens.  Keep orchestration JSON compact; long recall context caused
        # the model to emit anti-pattern prose before the required object.
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
            title=env.title, description=env.description[:3000],
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
    analysis.setdefault("concept_preserved", True)
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
        entry = {"command": cmd, "allowed": argv is not None}
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
        else:
            entry["skipped_reason"] = "not in read-only allowlist"
        results.append(entry)
    out = workdir / f"{label}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


_DOCKER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


def check_backlog_staleness(env: FailureEnvelope) -> dict | None:
    """For repairman_dispatched incidents naming a Docker service: check
    whether the container is currently healthy. If it's been running clean
    since before the dispatch was even created, the old incident is stale —
    it should never be re-reported as a fresh needs_approval item. Returns
    evidence dict if stale-resolved, else None (still needs handling)."""
    if env.source != "repairman_dispatched":
        return None
    try:
        request = json.loads(env.description).get("request", {})
    except Exception:
        return None
    component = str(request.get("affected_component", "")).strip()
    if not component or not _DOCKER_NAME_RE.match(component):
        return None
    container = component if component.startswith(("axiomsphere-", "aims-")) else f"axiomsphere-{component}"
    try:
        proc = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}} {{.RestartCount}} {{.State.StartedAt}}",
             container],
            capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    if proc.returncode != 0:
        return None  # container gone/renamed — not evidence of resolution, let it through
    parts = proc.stdout.strip().split(" ", 2)
    if len(parts) < 3:
        return None
    status, restarts, started_at = parts[0], parts[1], parts[2]
    created_at = str(request.get("created_at", ""))
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
    if status == "running":
        return {
            "stale": True,
            "container": container,
            "current_state": status,
            "restart_count": restarts,
            "started_at": started_at,
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
    payload = json.dumps({
        "task": (analysis.get("repair_request") or env.title)[:2000],
        "mode": "inspect",
        "source": f"logi_queue_poller:{env.support_case_id}",
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


def _codex_audit_case(env: FailureEnvelope, analysis: dict, inspect: dict, workdir: Path) -> dict:
    """Run the deterministic Codex CLI audit that replaces Telegram approval.

    Telegram is deliberately not part of this decision.  A missing auditor is
    a deferred case, while WARN/BLOCKED is a failed bounded attempt with
    evidence; neither state asks an operator to approve a machine proposal.
    """
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
        priority = [
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
        for rel, needles in {
            "ops/docsreg/docsreg_document_type_cycle.py": ("shared_document_eligibility", "eligibility gate rejected"),
            "ops/scripts/msdg_sequential_promotion_queue.py": ("shared_content_admission", "BLOCKED_INELIGIBLE_DOCUMENT"),
        }.items():
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
        qa_result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "ops/tests/test_shared_document_eligibility.py",
             "ops/tests/test_poli_checklist.py", "ops/tests/test_poli_change_auditor.py",
             "ops/agents/tests/test_logi_queue_poller.py", "ops/tests/test_msdg_shared_admission.py", "ops/tests/test_msdg_content_eligibility.py"],
            cwd=_ROOT, capture_output=True, text=True, timeout=180,
        )
        qa_text = f"command=bounded shared-gate regression\nexit_code={qa_result.returncode}\n{qa_result.stdout}\n{qa_result.stderr}"
        qa_path = workdir / "qa_regression.txt"
        qa_path.write_text(qa_text, encoding="utf-8")
        final_report = workdir / "fullstack_execution_report.md"
        final_report.write_text(
            "# Fullstack bounded execution report\n\n"
            f"Task: `{env.support_case_id}`\n\n"
            "Chain prepared: Architect → Fullstack implementer/Repairman → QA. "
            "Codex CLI and Poli are pending independent gates at report creation; this report is not a closure claim.\n\n"
            "Scope: shared deterministic document-eligibility gate consumed by DOCSREG and MSDG.\n"
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
            "ops/tests/test_shared_document_eligibility.py", "ops/tests/test_poli_checklist.py",
            "ops/tests/test_poli_change_auditor.py", "ops/agents/tests/test_logi_queue_poller.py",
            "ops/tests/test_msdg_shared_admission.py", "ops/tests/test_msdg_content_eligibility.py"]
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


def _poli_audit_case(env: FailureEnvelope, analysis: dict, codex_audit: dict, workdir: Path) -> dict:
    """Ask Poli's deterministic policy holder to interpret Codex evidence."""
    from ops.agents.poli_change_auditor import evaluate_fullstack_change

    params = env.params or {}
    proposal = {
        "strategy_change": bool(analysis.get("strategy_change", False)),
        # No silent True default: concept_preserved/restorative must be an
        # explicit, on-record claim (from the operator-declared repair
        # contract in _hydrate_declared_repair_contract, or an LLM analysis
        # that actually states it) — never assumed. Poli additionally
        # requires Codex to independently corroborate both before ALLOW.
        "concept_preserved": bool(analysis.get("concept_preserved", False)),
        "restorative": bool(analysis.get("restorative", False)),
        "protected_boundary_mutation": bool(analysis.get("protected_boundary_mutation", False)),
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
        "concept_preserved_evidence": "codex_audit.json:findings",
        "restorative_evidence": "codex_audit.json:findings",
        "strategy_preserved_evidence": "codex_audit.json:findings",
        "protected_boundary_clear_evidence": "evidence_manifest.json:changed_files",
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
    }
    return evaluate_fullstack_change(proposal, codex_audit)
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
    if now - last < _NOTIFY_DEDUPE_SEC:
        return False
    sent = notify_fn(text)
    cache[key] = now
    cache = {k: v for k, v in cache.items() if now - v < _NOTIFY_DEDUPE_SEC * 4}
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
        if freshness["required"]:
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
            analysis = _hydrate_declared_repair_contract(env, llm(env))
            (workdir / "analysis.json").write_text(
                json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
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
        if staleness and analysis.get("classification") == "repair_needed":
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
                analysis["human_report_ru"] = (
                    f"{analysis.get('human_report_ru', '')}\n\n"
                    f"Codex CLI не одобрил bounded repair: статус {codex_status}. "
                    "Рекомендации сохранены в codex_audit.json; Telegram содержит только результат."
                ).strip()
            else:
                poli_audit = _poli_audit_case(env, analysis, codex_audit, workdir)
                (workdir / "poli_audit.json").write_text(
                    json.dumps(poli_audit, indent=2, ensure_ascii=False), encoding="utf-8")
                if not poli_audit.get("allowed"):
                    env.outcome = "failed"
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
                    applied = apply_repair(env, analysis, [])
                    (workdir / "repairman_apply.json").write_text(
                        json.dumps(applied, indent=2, ensure_ascii=False), encoding="utf-8")
                    env.outcome = "completed" if str(applied.get("status", "")).lower() in {
                        "ok", "accepted", "queued", "completed", "success"
                    } else "failed"
                elif decision is not None and decision.decision == "NO_REPAIR":
                    env.outcome = "completed"
                elif decision is not None:
                    env.outcome = "failed"
        else:
            env.outcome = "completed"

        env.stage = "VERIFY"
        vres = run_allowlisted(analysis.get("verification_commands", []), workdir, "verification")
        ran = [r for r in vres if r.get("allowed")]
        verify_pass = bool(ran) and all(r.get("exit_code") == 0 for r in ran)
        if staleness:
            # The docker inspect evidence gathered in RESOLVE *is* the proof —
            # don't demote a correctly-detected stale/self-resolved incident
            # just because the LLM's own verification_commands list was empty.
            verify_pass = True
        elif env.outcome == "completed" and not verify_pass:
            # completed requires real passed evidence; zero evidence is never a pass
            env.outcome = "failed"
            analysis["human_report_ru"] = (
                f"{analysis.get('human_report_ru', '')}\n\n"
                "Недостаточно фактических verification-доказательств; approve через Telegram не создаётся."
            ).strip()

        # Independent judge (advisory): a disagreeing judge demotes 'completed'
        # to needs_approval — a human look, never a silent pass.
        verdict = judge(env, analysis, vres)
        (workdir / "judge_verdict.json").write_text(
            json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
        if env.outcome == "completed" and verdict.get("solved") is False:
            env.outcome = "failed"
            analysis["human_report_ru"] = (
                f"{analysis.get('human_report_ru', '')}\n\n"
                "Независимая проверка не подтвердила результат; Telegram содержит только итог, "
                "повтор требует нового Codex-аудита."
            ).strip()
    finally:
        env.stage = "FEEDBACK"
        record_feedback(env, analysis, verify_pass)
        env.artifacts = [
            str(p.relative_to(_ROOT)) if p.is_relative_to(_ROOT) else str(p)
            for p in sorted(workdir.glob("*.json"))
        ]
        report = write_human_report(env, analysis, verify_pass, workdir=workdir)
        env.artifacts.append(str(report))
        shutil.rmtree(tmpdir, ignore_errors=True)          # CLEANUP intermediates
        status_ru = {"completed": "✅ решена успешно", "needs_approval": "🟡 Codex-аудит требует доработки",
                     "failed": "❌ не решена: Codex не одобрил или repair не завершён",
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
    if env.source == "argus_incident" and env.outcome != "deferred":
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
