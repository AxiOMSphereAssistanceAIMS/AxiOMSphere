"""
codex_auditor_adapter.py

External code review channel via a three-tier auditor chain:

  1. AIMS_CODEX_AUDITOR_CMD         (primary Codex launcher)
  2. AIMS_CODEX_AUDITOR_FALLBACK_CMD (secondary Codex launcher)
  3. AIMS_CLAUDE_BEDROCK_AUDITOR_CMD (Claude Code via AWS Bedrock)
  4. SKIPPED — no usable auditor found

Each launcher implements:
  --preflight   → exit 0 if available, non-zero otherwise
  --audit <file> → run audit, print JSON or text to stdout

Exit code semantics from launchers:
  0  available / success
  10 AUTH_REQUIRED
  11 WRONG_BINARY
  12 RATE_LIMITED
  13 NOT_CONFIGURED
  14 TIMEOUT
  15 AUDIT_FAILED
  16 INVALID_USAGE

The adapter never calls raw `codex` from PATH — only configured launchers.
The adapter never initiates login. Never hangs on browser/device prompts.
Returns SKIPPED if all launchers fail/unavailable — deterministic flow continues.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CodexAuditRequest:
    task_id: str
    objective: str
    files_changed: list[str]
    evidence_files: list[str]
    test_logs: list[str]
    actor_output: str
    self_check_output: str
    constraints: list[str]


@dataclass
class CodexAuditFinding:
    severity: str          # INFO | WARN | BLOCKING
    category: str          # evidence | tests | policy | implementation | safety | learning
    finding: str
    recommendation: str
    evidence_reference: str | None = None


@dataclass
class CodexAuditResult:
    status: str                           # PASSED | WARN | BLOCKED | ERROR | SKIPPED
    findings: list[CodexAuditFinding] = field(default_factory=list)
    raw_output_path: str | None = None
    command_used: list[str] = field(default_factory=list)
    auditor_available: bool = False
    auditor_name: str = "none"            # primary_codex | secondary_codex | claude_bedrock | none


_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "ops" / "scripts"

# Launcher exit codes
_EXIT_AUTH_REQUIRED = 10
_EXIT_WRONG_BINARY = 11
_EXIT_RATE_LIMITED = 12
_EXIT_NOT_CONFIGURED = 13
_EXIT_TIMEOUT = 14
_EXIT_AUDIT_FAILED = 15
_EXIT_INVALID_USAGE = 16

# Exit codes where we should try the next auditor
_SKIP_TO_NEXT_CODES = {
    _EXIT_AUTH_REQUIRED, _EXIT_WRONG_BINARY,
    _EXIT_NOT_CONFIGURED, _EXIT_TIMEOUT,
    _EXIT_AUDIT_FAILED,
}


def _auditor_chain() -> list[tuple[str, str]]:
    """
    Return ordered list of (auditor_name, launcher_script_path).
    Only includes auditors whose launcher script exists on disk.
    Never falls back to raw PATH `codex`.
    """
    candidates = [
        ("primary_codex",    os.environ.get("AIMS_CODEX_AUDITOR_CMD",
                             str(_SCRIPTS_DIR / "codex_auditor_primary.sh"))),
        ("secondary_codex",  os.environ.get("AIMS_CODEX_AUDITOR_FALLBACK_CMD",
                             str(_SCRIPTS_DIR / "codex_auditor_secondary.sh"))),
        ("claude_bedrock",   os.environ.get("AIMS_CLAUDE_BEDROCK_AUDITOR_CMD",
                             str(_SCRIPTS_DIR / "claude_bedrock_auditor.sh"))),
    ]
    return [(name, path) for name, path in candidates if Path(path).exists()]


def _run_preflight(launcher: str, preflight_timeout: int = 30) -> tuple[bool, str]:
    """
    Run --preflight on a launcher. Returns (available, status_string).
    Never raises.
    """
    try:
        result = subprocess.run(
            [launcher, "--preflight"],
            capture_output=True,
            text=True,
            timeout=preflight_timeout,
        )
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode == 0:
            return True, "AVAILABLE"
        # Parse status from JSON output if possible
        try:
            data = json.loads(output)
            status = data.get("status", f"FAILED_RC_{result.returncode}")
        except (json.JSONDecodeError, ValueError):
            status = f"FAILED_RC_{result.returncode}"
        return False, status
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, f"ERROR_{type(exc).__name__}"


def _run_audit(
    launcher: str,
    prompt_file: str,
    timeout_seconds: int,
) -> tuple[int, str]:
    """
    Run --audit <prompt_file> on a launcher.
    Returns (returncode, raw_output_text).
    Never raises.
    """
    try:
        result = subprocess.run(
            [launcher, "--audit", prompt_file],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        raw = result.stdout or result.stderr or ""
        return result.returncode, raw
    except subprocess.TimeoutExpired:
        return _EXIT_TIMEOUT, f"TIMEOUT after {timeout_seconds}s"
    except Exception as exc:
        return _EXIT_AUDIT_FAILED, f"EXCEPTION: {exc}"


def _build_audit_prompt(request: CodexAuditRequest) -> str:
    constraints_str = "\n".join(f"- {c}" for c in request.constraints)
    changed_str = "\n".join(f"- {f}" for f in request.files_changed)
    evidence_str = "\n".join(f"- {f}" for f in request.evidence_files)
    test_str = "\n".join(f"- {f}" for f in request.test_logs)
    return f"""You are an external code auditor. Review the following task and output ONLY valid JSON.

TASK ID: {request.task_id}
OBJECTIVE: {request.objective}

CONSTRAINTS:
{constraints_str}

FILES CHANGED:
{changed_str}

EVIDENCE FILES:
{evidence_str}

TEST LOGS:
{test_str}

ACTOR OUTPUT:
{request.actor_output[:3000]}

SELF-CHECK OUTPUT:
{request.self_check_output[:2000]}

Output schema (JSON only, no markdown):
{{
  "status": "PASSED | WARN | BLOCKED",
  "findings": [
    {{
      "severity": "INFO | WARN | BLOCKING",
      "category": "evidence | tests | policy | implementation | safety | learning",
      "finding": "...",
      "recommendation": "...",
      "evidence_reference": "..."
    }}
  ],
  "recommended_next_action": "..."
}}
"""


def _parse_findings(raw: str) -> tuple[str, list[CodexAuditFinding]]:
    """Parse JSON output from auditor. Returns (status, findings)."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()
    try:
        data = json.loads(text)
        status = data.get("status", "WARN")
        if status not in ("PASSED", "WARN", "BLOCKED"):
            status = "WARN"
        findings = []
        for f in data.get("findings", []):
            findings.append(CodexAuditFinding(
                severity=f.get("severity", "WARN"),
                category=f.get("category", "implementation"),
                finding=f.get("finding", ""),
                recommendation=f.get("recommendation", ""),
                evidence_reference=f.get("evidence_reference"),
            ))
        return status, findings
    except (json.JSONDecodeError, KeyError, ValueError):
        return "WARN", [CodexAuditFinding(
            severity="WARN",
            category="auditor_format",
            finding="Auditor output was not valid JSON",
            recommendation="Review raw output manually or improve audit prompt",
            evidence_reference="codex_audit_raw.txt",
        )]


def run_codex_audit(
    request: CodexAuditRequest,
    evidence_dir: str,
    timeout_seconds: int = 300,
) -> CodexAuditResult:
    """
    Run audit through the three-tier auditor chain.

    Tries each launcher in priority order:
      1. primary_codex (AIMS_CODEX_AUDITOR_CMD)
      2. secondary_codex (AIMS_CODEX_AUDITOR_FALLBACK_CMD)
      3. claude_bedrock (AIMS_CLAUDE_BEDROCK_AUDITOR_CMD)

    Returns SKIPPED if all launchers are unavailable/fail.
    Never fabricates auditor output. Never initiates login.
    """
    ev = Path(evidence_dir)
    ev.mkdir(parents=True, exist_ok=True)

    # Write audit prompt to a temp file (launchers read it as a file)
    prompt_text = _build_audit_prompt(request)
    prompt_path = ev / "codex_audit_prompt.txt"
    prompt_path.write_text(prompt_text, encoding="utf-8")

    chain = _auditor_chain()
    chain_log: list[dict] = []

    # Discovery file
    discovery_lines = [
        f"# Auditor Chain Discovery — {datetime.now(timezone.utc).isoformat()}\n",
        f"Chain candidates: {[name for name, _ in chain]}\n",
        f"AIMS_CODEX_AUDITOR_CMD: {os.environ.get('AIMS_CODEX_AUDITOR_CMD', 'default')}\n",
        f"AIMS_CODEX_AUDITOR_FALLBACK_CMD: {os.environ.get('AIMS_CODEX_AUDITOR_FALLBACK_CMD', 'default')}\n",
        f"AIMS_CLAUDE_BEDROCK_AUDITOR_CMD: {os.environ.get('AIMS_CLAUDE_BEDROCK_AUDITOR_CMD', 'default')}\n",
    ]

    for auditor_name, launcher_path in chain:
        # Preflight
        available, preflight_status = _run_preflight(launcher_path)
        chain_log.append({
            "auditor": auditor_name,
            "launcher": launcher_path,
            "preflight_status": preflight_status,
        })
        discovery_lines.append(f"\n{auditor_name}: preflight={preflight_status}\n")

        if not available:
            continue

        # Preflight passed — run audit
        raw_path = ev / f"codex_audit_raw_{auditor_name}.txt"
        returncode, raw_output = _run_audit(launcher_path, str(prompt_path), timeout_seconds)
        raw_path.write_text(raw_output, encoding="utf-8")
        chain_log[-1]["audit_rc"] = returncode
        chain_log[-1]["raw_path"] = str(raw_path)

        if returncode not in (0,) and returncode in _SKIP_TO_NEXT_CODES:
            # This auditor failed — try next
            chain_log[-1]["outcome"] = "skipped_to_next"
            continue

        # Parse output
        status, findings = _parse_findings(raw_output)
        chain_log[-1]["outcome"] = "used"

        (ev / "codex_cli_discovery.txt").write_text(
            "".join(discovery_lines), encoding="utf-8"
        )

        return CodexAuditResult(
            status=status,
            findings=findings,
            raw_output_path=str(raw_path),
            command_used=[launcher_path, "--audit", str(prompt_path)],
            auditor_available=True,
            auditor_name=auditor_name,
        )

    # All auditors failed or unavailable
    (ev / "codex_cli_discovery.txt").write_text(
        "".join(discovery_lines) + "\nResult: ALL_AUDITORS_UNAVAILABLE\n",
        encoding="utf-8",
    )
    (ev / "auditor_chain_log.json").write_text(
        json.dumps(chain_log, indent=2), encoding="utf-8"
    )

    return CodexAuditResult(
        status="SKIPPED",
        findings=[],
        raw_output_path=None,
        command_used=[],
        auditor_available=False,
        auditor_name="none",
    )
