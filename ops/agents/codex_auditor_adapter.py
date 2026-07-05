"""
codex_auditor_adapter.py

External code review channel via Codex CLI (or compatible LLM auditor CLI).

If Codex CLI is unavailable or not a supported non-interactive LLM auditor,
returns CodexAuditResult with status=SKIPPED — the deterministic flow continues
uninterrupted. Never fabricates auditor output.

Detection priority:
  1. AIMS_CODEX_CLI_CMD env var (explicit path/command override)
  2. which claude-code / which cc (Claude Code CLI in non-interactive mode)
  3. which codex (must be OpenAI Codex-style CLI, not static site generator)
  4. SKIPPED — no usable auditor found

Note on this environment: `npx codex` resolves to a static site generator
(v0.2.3), not an LLM auditor CLI. AIMS_CODEX_CLI_CMD must be set explicitly
to use a different auditor.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
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


_SKIPPED_REASON = (
    "No usable Codex-style LLM auditor CLI found. "
    "Set AIMS_CODEX_CLI_CMD to a non-interactive LLM auditor command. "
    "Deterministic flow continues uninterrupted."
)


def _detect_auditor() -> list[str] | None:
    """Return the auditor command list, or None if no usable auditor found."""
    # 1. Explicit override
    override = os.environ.get("AIMS_CODEX_CLI_CMD", "").strip()
    if override:
        parts = shlex.split(override)
        if parts and shutil.which(parts[0]):
            return parts

    # 2. claude CLI in non-interactive mode (if available and not slot32 proxy)
    if shutil.which("claude"):
        return ["claude", "-p"]

    return None


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
    # Strip markdown code fences if present
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
    except (json.JSONDecodeError, KeyError):
        return "WARN", [CodexAuditFinding(
            severity="WARN",
            category="auditor_format",
            finding="Codex output was not valid JSON",
            recommendation="Review raw output manually or improve Codex audit prompt",
            evidence_reference="codex_audit_raw.txt",
        )]


def run_codex_audit(
    request: CodexAuditRequest,
    evidence_dir: str,
    timeout_seconds: int = 300,
) -> CodexAuditResult:
    """
    Run a Codex-style CLI audit against the request.

    Returns SKIPPED if no usable auditor is available.
    Never fabricates auditor output.
    """
    ev = Path(evidence_dir)
    ev.mkdir(parents=True, exist_ok=True)

    # Detect auditor
    cmd_base = _detect_auditor()
    if cmd_base is None:
        # Save discovery note
        (ev / "codex_cli_discovery.txt").write_text(
            f"# Codex CLI Discovery — {datetime.now(timezone.utc).isoformat()}\n\n"
            f"Result: NO_USABLE_AUDITOR_FOUND\n\n"
            f"AIMS_CODEX_CLI_CMD: {os.environ.get('AIMS_CODEX_CLI_CMD', 'not set')}\n"
            f"which claude: {shutil.which('claude') or 'not found'}\n"
            f"Reason: {_SKIPPED_REASON}\n",
            encoding="utf-8",
        )
        return CodexAuditResult(
            status="SKIPPED",
            findings=[],
            raw_output_path=None,
            command_used=[],
            auditor_available=False,
        )

    prompt = _build_audit_prompt(request)
    prompt_path = ev / "codex_audit_prompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    raw_path = ev / "codex_audit_raw.txt"
    cmd = cmd_base + [prompt]

    # Save discovery
    (ev / "codex_cli_discovery.txt").write_text(
        f"# Codex CLI Discovery — {datetime.now(timezone.utc).isoformat()}\n\n"
        f"Result: AUDITOR_FOUND\n"
        f"Command: {' '.join(cmd_base)}\n",
        encoding="utf-8",
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            cwd=str(Path(evidence_dir).parent.parent),
        )
        raw_output = result.stdout or result.stderr or ""
        raw_path.write_text(raw_output, encoding="utf-8")

        if result.returncode != 0 and not raw_output.strip():
            return CodexAuditResult(
                status="ERROR",
                findings=[CodexAuditFinding(
                    severity="WARN",
                    category="auditor_format",
                    finding=f"Auditor exited with code {result.returncode} and no output",
                    recommendation="Check auditor command and credentials",
                    evidence_reference=str(raw_path),
                )],
                raw_output_path=str(raw_path),
                command_used=cmd,
                auditor_available=True,
            )

        status, findings = _parse_findings(raw_output)
        return CodexAuditResult(
            status=status,
            findings=findings,
            raw_output_path=str(raw_path),
            command_used=cmd,
            auditor_available=True,
        )

    except subprocess.TimeoutExpired:
        raw_path.write_text(f"TIMEOUT after {timeout_seconds}s", encoding="utf-8")
        return CodexAuditResult(
            status="ERROR",
            findings=[CodexAuditFinding(
                severity="WARN",
                category="auditor_format",
                finding=f"Auditor timed out after {timeout_seconds}s",
                recommendation="Increase timeout or reduce audit scope",
                evidence_reference=str(raw_path),
            )],
            raw_output_path=str(raw_path),
            command_used=cmd,
            auditor_available=True,
        )
    except Exception as exc:
        raw_path.write_text(f"EXCEPTION: {exc}", encoding="utf-8")
        return CodexAuditResult(
            status="ERROR",
            findings=[CodexAuditFinding(
                severity="WARN",
                category="auditor_format",
                finding=f"Auditor raised exception: {type(exc).__name__}: {exc}",
                recommendation="Check auditor availability and configuration",
                evidence_reference=str(raw_path),
            )],
            raw_output_path=str(raw_path),
            command_used=cmd,
            auditor_available=True,
        )
