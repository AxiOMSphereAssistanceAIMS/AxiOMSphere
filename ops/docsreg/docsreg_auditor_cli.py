"""
docsreg_auditor_cli.py — ClaudeCodeAuditor: calls the Claude Code CLI as an auditor subprocess.

Public API:
    AUDITOR_VERDICT_PASS
    AUDITOR_VERDICT_FAIL_REPAIRABLE
    AUDITOR_VERDICT_BLOCKED
    AUDITOR_VERDICT_REGRESSION
    AUDITOR_PROMPT_TEMPLATE
    AuditorRequest
    AuditorResponse
    ClaudeCodeAuditor
    make_claude_code_auditor
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Verdict constants
# ---------------------------------------------------------------------------

AUDITOR_VERDICT_PASS = "COMPONENT_PASS"
AUDITOR_VERDICT_FAIL_REPAIRABLE = "COMPONENT_FAIL_REPAIRABLE"
AUDITOR_VERDICT_BLOCKED = "COMPONENT_BLOCKED"
AUDITOR_VERDICT_REGRESSION = "PIPELINE_REGRESSION"

_VALID_VERDICTS: frozenset[str] = frozenset(
    {
        AUDITOR_VERDICT_PASS,
        AUDITOR_VERDICT_FAIL_REPAIRABLE,
        AUDITOR_VERDICT_BLOCKED,
        AUDITOR_VERDICT_REGRESSION,
    }
)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

AUDITOR_PROMPT_TEMPLATE: str = (
    "You are auditing a DOCSREG certification cycle for document type: {document_type}\n"
    "Cycle ID: {cycle_id}\n"
    "Evidence directory: {evidence_dir}\n"
    "Current quality score: {quality:.3f}\n"
    "Notes: {notes}\n"
    "\n"
    "Your job: inspect the evidence directory and assess whether the certification cycle passes.\n"
    "\n"
    "Respond ONLY with a valid JSON object, no other text:\n"
    "{{\n"
    '  "verdict": "<COMPONENT_PASS | COMPONENT_FAIL_REPAIRABLE | PIPELINE_REGRESSION | COMPONENT_BLOCKED>",\n'
    '  "quality": <float 0.0-1.0>,\n'
    '  "notes": "<brief explanation>"\n'
    "}}"
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AuditorRequest:
    document_type: str
    cycle_id: str
    evidence_dir: str
    quality: float
    notes: str = ""


@dataclass
class AuditorResponse:
    verdict: str          # one of AUDITOR_VERDICT_* constants
    quality: float        # 0.0–1.0
    notes: str = ""
    raw_output: str = ""  # raw stdout from CLI (stored to evidence)
    evidence_dir: str = ""


# ---------------------------------------------------------------------------
# ClaudeCodeAuditor
# ---------------------------------------------------------------------------


class ClaudeCodeAuditor:
    """Calls the Claude Code CLI as an auditor subprocess.

    Never raises — the entire ``__call__`` body is wrapped in try/except.
    """

    def __init__(
        self,
        *,
        claude_bin: str = "claude",
        timeout: int = 120,
        evidence_root: str | Path = "",
    ) -> None:
        self._claude_bin = claude_bin
        self._timeout = timeout
        self._evidence_root = Path(evidence_root) if evidence_root else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, request: AuditorRequest) -> str:
        return AUDITOR_PROMPT_TEMPLATE.format(
            document_type=request.document_type,
            cycle_id=request.cycle_id,
            evidence_dir=request.evidence_dir,
            quality=request.quality,
            notes=request.notes,
        )

    def _write_evidence(self, cycle_id: str, raw_output: str) -> None:
        """Best-effort write of raw CLI output to evidence directory."""
        if self._evidence_root is None:
            return
        try:
            evidence_dir = self._evidence_root / cycle_id
            evidence_dir.mkdir(parents=True, exist_ok=True)
            output_file = evidence_dir / "auditor_raw_output.txt"
            output_file.write_text(raw_output, encoding="utf-8")
            log.info("Auditor raw output written to %s", output_file)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to write auditor evidence for cycle %s: %s", cycle_id, exc)

    @staticmethod
    def _parse_response(
        raw_text: str,
    ) -> tuple[str, float, str] | None:
        """Parse stdout into (verdict, quality, notes).

        Returns None if parsing fails.
        """
        text = raw_text.strip()
        if not text:
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract a JSON object embedded in surrounding text
            start = text.find("{")
            end = text.rfind("}") + 1
            if start == -1 or end == 0:
                return None
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                return None

        if not isinstance(data, dict):
            return None
        if "verdict" not in data or "quality" not in data:
            return None

        verdict = str(data["verdict"])
        try:
            quality = float(data["quality"])
        except (TypeError, ValueError):
            quality = 0.0

        # Clamp quality to [0.0, 1.0]
        quality = max(0.0, min(1.0, quality))

        notes = str(data.get("notes", ""))
        return verdict, quality, notes

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def __call__(self, request: AuditorRequest) -> AuditorResponse:
        """Call Claude Code CLI with a structured prompt. Never raises."""
        try:
            prompt_text = self._build_prompt(request)

            log.info(
                "ClaudeCodeAuditor: starting audit for cycle=%s doc_type=%s",
                request.cycle_id,
                request.document_type,
            )

            result = subprocess.run(
                [self._claude_bin, "--print", prompt_text],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )

            raw_stdout = result.stdout or ""
            raw_stderr = result.stderr or ""

            # Always write evidence (best-effort)
            self._write_evidence(request.cycle_id, raw_stdout)

            # Non-zero exit code → BLOCKED
            if result.returncode != 0:
                msg = f"subprocess exit {result.returncode}"
                log.warning(
                    "ClaudeCodeAuditor: %s for cycle=%s", msg, request.cycle_id
                )
                return AuditorResponse(
                    verdict=AUDITOR_VERDICT_BLOCKED,
                    quality=0.0,
                    raw_output=raw_stderr,
                    notes=msg,
                    evidence_dir=request.evidence_dir,
                )

            # Parse response
            parsed = self._parse_response(raw_stdout)
            if parsed is None:
                log.warning(
                    "ClaudeCodeAuditor: non-JSON response for cycle=%s", request.cycle_id
                )
                return AuditorResponse(
                    verdict=AUDITOR_VERDICT_BLOCKED,
                    quality=0.0,
                    raw_output=raw_stdout,
                    notes="non-JSON response",
                    evidence_dir=request.evidence_dir,
                )

            verdict, quality, notes = parsed

            # Validate verdict
            if verdict not in _VALID_VERDICTS:
                log.warning(
                    "ClaudeCodeAuditor: unknown verdict %r for cycle=%s — treating as BLOCKED",
                    verdict,
                    request.cycle_id,
                )
                return AuditorResponse(
                    verdict=AUDITOR_VERDICT_BLOCKED,
                    quality=quality,
                    raw_output=raw_stdout,
                    notes=f"unknown verdict: {verdict}",
                    evidence_dir=request.evidence_dir,
                )

            log.info(
                "ClaudeCodeAuditor: cycle=%s verdict=%s quality=%.3f",
                request.cycle_id,
                verdict,
                quality,
            )
            return AuditorResponse(
                verdict=verdict,
                quality=quality,
                raw_output=raw_stdout,
                notes=notes,
                evidence_dir=request.evidence_dir,
            )

        except subprocess.TimeoutExpired as exc:
            msg = f"subprocess timeout after {self._timeout}s"
            log.warning("ClaudeCodeAuditor: %s for cycle=%s", msg, request.cycle_id)
            # Best-effort evidence write on timeout
            self._write_evidence(request.cycle_id, "")
            return AuditorResponse(
                verdict=AUDITOR_VERDICT_BLOCKED,
                quality=0.0,
                raw_output="",
                notes=msg,
                evidence_dir=request.evidence_dir,
            )
        except Exception as exc:  # noqa: BLE001
            cycle_id = getattr(request, "cycle_id", "unknown")
            evidence_dir = getattr(request, "evidence_dir", "")
            log.error(
                "ClaudeCodeAuditor: unexpected error for cycle=%s: %s",
                cycle_id,
                exc,
                exc_info=True,
            )
            # Best-effort evidence write even on unexpected errors
            self._write_evidence(cycle_id, "")
            return AuditorResponse(
                verdict=AUDITOR_VERDICT_BLOCKED,
                quality=0.0,
                raw_output="",
                notes=f"unexpected error: {exc}",
                evidence_dir=evidence_dir,
            )


# ---------------------------------------------------------------------------
# Public factory function
# ---------------------------------------------------------------------------


def make_claude_code_auditor(
    *,
    claude_bin: str = "claude",
    timeout: int = 120,
    evidence_root: str | Path = "",
) -> ClaudeCodeAuditor:
    """Thin wrapper that returns a configured :class:`ClaudeCodeAuditor` instance."""
    return ClaudeCodeAuditor(
        claude_bin=claude_bin,
        timeout=timeout,
        evidence_root=evidence_root,
    )
