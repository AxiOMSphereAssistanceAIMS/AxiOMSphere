"""M-001: Claim Evidence Verifier — prevents false completed_successfully.

Verifies that a step/plan completion claim is backed by real evidence:
  1. Error-signal scan (result text analysis)
  2. Artifact path extraction + existence check
  3. Freshness check (artifact modified within STALE_AFTER_HOURS)

Confidence levels:
  ARTIFACT_VERIFIED  — found and fresh artifact paths in result
  HEURISTIC          — no artifact paths; decided by text signal only
  NOT_CHECKED        — verifier skipped (e.g. agent returned empty result)

Verdict results:
  SUPPORTED          — claim is backed; safe to mark done
  UNSUPPORTED        — clear error signal detected; mark failed
  STALE_SOURCE       — artifact exists but is too old; mark failed
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

STALE_AFTER_HOURS = 24
WORKSPACE_ROOT = Path("/home/axi_omi_sphere/aims-workspace")

# Patterns that indicate a genuine error in the result text
_ERROR_PATTERNS = re.compile(
    r"\b(error|exception|traceback|failed|failure|timeout|refused|errno|crash|"
    r"not found|no such file|permission denied|503|502|500)\b",
    re.IGNORECASE,
)

# Patterns that are strong positive signals
_SUCCESS_PATTERNS = re.compile(
    r"\b(success|stored|completed|done|ok|saved|registered|created|approved|"
    r"repaired|passed|ready)\b",
    re.IGNORECASE,
)

# Extract file-system paths from result text
_PATH_RE = re.compile(r"(?:aims_workspace|/home/axi_omi_sphere)[^\s\"'<>]+")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso() -> str:
    return _now_utc().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _age_hours(path: Path) -> float:
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return (_now_utc() - mtime).total_seconds() / 3600
    except OSError:
        return float("inf")


def _resolve(raw: str) -> Path:
    p = Path(raw)
    if p.is_absolute():
        return p
    return WORKSPACE_ROOT / p


@dataclass
class ClaimVerdict:
    claim_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    claim_type: str = "STEP_COMPLETION"
    subject: str = ""                   # step_id or plan_id
    result: str = "SUPPORTED"           # SUPPORTED | UNSUPPORTED | STALE_SOURCE
    confidence: str = "HEURISTIC"       # ARTIFACT_VERIFIED | HEURISTIC | NOT_CHECKED
    evidence_found: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    stale_paths: list[str] = field(default_factory=list)
    rationale: str = ""
    verified_at: str = field(default_factory=_iso)


class ClaimVerifier:
    """Verifies step/plan completion claims against evidence."""

    def verify_step_completion(self, step_id: str, agent: str, result_text: str) -> ClaimVerdict:
        verdict = ClaimVerdict(claim_type="STEP_COMPLETION", subject=step_id)

        if not result_text or not result_text.strip():
            verdict.result = "UNSUPPORTED"
            verdict.confidence = "NOT_CHECKED"
            verdict.rationale = "Empty result — no evidence of completion."
            return verdict

        # Extract and check artifact paths
        raw_paths = _PATH_RE.findall(result_text)
        found_paths: list[str] = []
        missing_paths: list[str] = []
        stale_paths: list[str] = []

        for raw in raw_paths:
            p = _resolve(raw.rstrip(".,;)\"'"))
            if p.exists():
                age = _age_hours(p)
                if age > STALE_AFTER_HOURS:
                    stale_paths.append(str(p))
                else:
                    found_paths.append(str(p))
            else:
                missing_paths.append(raw)

        verdict.evidence_found = found_paths
        verdict.missing_evidence = missing_paths
        verdict.stale_paths = stale_paths

        # Stale artifact → STALE_SOURCE
        if stale_paths and not found_paths:
            verdict.result = "STALE_SOURCE"
            verdict.confidence = "ARTIFACT_VERIFIED"
            verdict.rationale = (
                f"All referenced artifacts are stale (>{STALE_AFTER_HOURS}h): "
                + ", ".join(stale_paths[:3])
            )
            return verdict

        # Fresh artifact found → boost confidence
        if found_paths:
            verdict.confidence = "ARTIFACT_VERIFIED"

        # Error signal in first 150 chars (summary region)
        summary = result_text[:150].lower()
        has_error = bool(_ERROR_PATTERNS.search(summary))

        if has_error:
            verdict.result = "UNSUPPORTED"
            m = _ERROR_PATTERNS.search(summary)
            verdict.rationale = f"Error signal '{m.group()}' detected in result summary."
            return verdict

        has_success = bool(_SUCCESS_PATTERNS.search(result_text[:300]))
        verdict.result = "SUPPORTED"
        verdict.rationale = (
            f"Fresh artifact verified." if found_paths
            else f"Success signal detected." if has_success
            else f"No error signal; assuming completion."
        )
        return verdict

    def verify_plan_completion(self, plan_id: str, step_verdicts: Sequence[ClaimVerdict]) -> ClaimVerdict:
        """Aggregate step verdicts into a plan-level verdict."""
        verdict = ClaimVerdict(claim_type="PLAN_COMPLETION", subject=plan_id)
        unsupported = [v for v in step_verdicts if v.result == "UNSUPPORTED"]
        stale = [v for v in step_verdicts if v.result == "STALE_SOURCE"]

        if unsupported:
            verdict.result = "UNSUPPORTED"
            verdict.confidence = "HEURISTIC"
            verdict.rationale = (
                f"{len(unsupported)} step(s) have UNSUPPORTED verdicts: "
                + ", ".join(v.subject for v in unsupported[:3])
            )
        elif stale:
            verdict.result = "STALE_SOURCE"
            verdict.confidence = "ARTIFACT_VERIFIED"
            verdict.rationale = f"{len(stale)} step(s) have stale evidence."
        else:
            verdict.result = "SUPPORTED"
            verdict.confidence = (
                "ARTIFACT_VERIFIED"
                if any(v.confidence == "ARTIFACT_VERIFIED" for v in step_verdicts)
                else "HEURISTIC"
            )
            verdict.rationale = f"All {len(step_verdicts)} step verdicts SUPPORTED."

        verdict.evidence_found = [p for v in step_verdicts for p in v.evidence_found]
        verdict.missing_evidence = [p for v in step_verdicts for p in v.missing_evidence]
        verdict.stale_paths = [p for v in step_verdicts for p in v.stale_paths]
        return verdict


_VERIFIER = ClaimVerifier()


def get_verifier() -> ClaimVerifier:
    return _VERIFIER
