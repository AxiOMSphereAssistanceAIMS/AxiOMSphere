"""Review gate logic for self-healing repair proposals.

Five deterministic, pure-function reviewers — no I/O, no LLM calls.
Each accepts a proposal dict and returns a ReviewResult.

Proposal dict fields (all optional, safe defaults applied):
  files_changed    list[str]  — files the repair touches
  patch_diff       str        — unified diff of the change
  risk_level       str        — "low" | "medium" | "high"
  root_cause       str        — one-paragraph diagnosis
  restorative      bool       — change restores prior known-good state
  concept_preserved bool      — system concept / architecture unchanged
  test_result      str        — "pass" | "fail" | "not_run"
  rollback_notes   str        — how to undo the change

Call order (enforcement vs advisory):
  architect → blocking
  security  → blocking
  qa        → blocking
  release   → blocking
  docs      → advisory (score only, never blocks)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ReviewResult:
    approved: bool
    concerns: list[str] = field(default_factory=list)
    score: float = 1.0
    reviewer: str = ""

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "concerns": self.concerns,
            "score": round(max(0.0, min(1.0, self.score)), 3),
            "reviewer": self.reviewer,
        }


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_CORE_ARCH_FILES = frozenset({
    "docker-compose.yml",
    "docker-compose.dgx.yml",
    "ops/core/queue.py",
    "ops/core/worker.py",
    "ops/core/orchestrator.py",
    "ops/core/runtime_names.py",
    "core/runtime_names.py",
})

_SUBSYSTEMS = {
    "knomi":     ("knomi",),
    "poli":      ("poli",),
    "mainy":     ("mainy",),
    "argus":     ("argus",),
    "omi":       ("/omi",),
    "repairman": ("repairman",),
    "logi":      ("logi",),
    "doci":      ("doci",),
}

_ENTRYPOINTS = frozenset({
    "ops/axi_bot.py",
    "ops/agents/omi_agent.py",
    "ops/agents/argus_agent.py",
    "ops/agents/poli_agent.py",
    "ops/telegram/repairman_bot.py",
})

_AUTH_FILES = frozenset({
    ".env",
    "ops/core/service_auth.py",
    "core/service_auth.py",
})

# Shell / Python patterns that are never safe in a diff
_DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bos\.system\(",
    r"\bos\.popen\(",
    r"\bsubprocess\.(?:call|run|Popen)\(.*shell\s*=\s*True",
    r"\bsubprocess\.(?:call|run|Popen|check_call|check_output)\([^\n]*(?:f['\"]|\.format\(|\s\+\s*)",
    r"\beval\s*\(",
    r"\bexec\s*\(",
]

_DANGER_RE = re.compile("|".join(_DANGEROUS_PATTERNS), re.IGNORECASE)

_PRODUCTION_COMPOSE = re.compile(r"docker-compose.*\.yml")


# ---------------------------------------------------------------------------
# 1. Architect review
# ---------------------------------------------------------------------------

def architect_review(proposal: dict) -> ReviewResult:
    """Checks architectural impact: coupling, core-file safety, concept preservation."""
    files      = proposal.get("files_changed", [])
    risk       = proposal.get("risk_level", "low")
    restorative     = proposal.get("restorative", True)
    concept_preserved = proposal.get("concept_preserved", True)

    concerns: list[str] = []
    approved = True
    score = 1.0

    # Rule A1 — core architecture files without restorative flag
    arch_touched = [f for f in files if any(s in f for s in _CORE_ARCH_FILES)]
    if arch_touched and not restorative:
        concerns.append(
            f"core architecture files changed without restorative=True: {arch_touched}"
        )
        approved = False
        score -= 0.5

    # Rule A2 — high-risk without concept preservation
    if risk == "high" and not concept_preserved:
        concerns.append(
            "high-risk change must preserve system concept (concept_preserved=False)"
        )
        approved = False
        score -= 0.3

    # Rule A3 (advisory) — cross-subsystem coupling
    affected = [
        sub for sub, patterns in _SUBSYSTEMS.items()
        if any(any(p in f for p in patterns) for f in files)
    ]
    if len(affected) > 2:
        concerns.append(
            f"change spans {len(affected)} subsystems ({', '.join(sorted(affected))}) "
            "— high coupling risk, validate integration contracts"
        )
        score -= 0.1

    return ReviewResult(approved=approved, concerns=concerns,
                        score=score, reviewer="architect")


# ---------------------------------------------------------------------------
# 2. Security review
# ---------------------------------------------------------------------------

def security_review(proposal: dict) -> ReviewResult:
    """Checks security implications: dangerous code patterns, auth file exposure."""
    files      = proposal.get("files_changed", [])
    patch      = proposal.get("patch_diff", "")
    risk       = proposal.get("risk_level", "low")
    restorative = proposal.get("restorative", True)

    concerns: list[str] = []
    approved = True
    score = 1.0

    # Rule S1 — dangerous patterns in diff
    match = _DANGER_RE.search(patch)
    if match:
        concerns.append(
            f"dangerous pattern detected in patch: '{match.group(0)}' — manual review required"
        )
        approved = False
        score -= 0.6

    # Rule S2 — auth/secrets files without restorative flag
    auth_touched = [f for f in files if any(a in f for a in _AUTH_FILES)]
    if auth_touched and not restorative:
        concerns.append(
            f"auth/config files changed without restorative flag: {auth_touched}"
        )
        approved = False
        score -= 0.4

    # Rule S3 — high-risk change touches auth files
    if risk == "high" and auth_touched:
        concerns.append(
            "high-risk change touches auth/config files — requires manual approval"
        )
        approved = False
        score -= 0.2

    # Rule S4 (advisory) — subprocess usage (not necessarily dangerous)
    if "subprocess" in patch and "shell=True" not in patch:
        concerns.append(
            "subprocess usage detected in patch — verify no unsanitized inputs"
        )
        score -= 0.05

    return ReviewResult(approved=approved, concerns=concerns,
                        score=score, reviewer="security")


# ---------------------------------------------------------------------------
# 3. QA review
# ---------------------------------------------------------------------------

def qa_review(proposal: dict) -> ReviewResult:
    """Checks test coverage: test_result validation, missing test files."""
    files       = proposal.get("files_changed", [])
    risk        = proposal.get("risk_level", "low")
    test_result = proposal.get("test_result", "not_run")

    concerns: list[str] = []
    approved = True
    score = 1.0

    # Rule Q1 — test suite failure is always a hard block
    if test_result == "fail":
        concerns.append(
            "proposed change caused test failures — do not apply until tests pass"
        )
        approved = False
        score -= 0.7

    # Rule Q2 — high-risk change with no tests run
    if risk == "high" and test_result == "not_run":
        concerns.append(
            "high-risk change has no test results — run and pass tests before applying"
        )
        approved = False
        score -= 0.4

    # Rule Q3 (advisory) — Python files changed without test files
    py_changed  = [f for f in files if f.endswith(".py") and "test_" not in f]
    test_files  = [f for f in files if "test_" in f]
    if py_changed and not test_files and risk in ("medium", "high"):
        concerns.append(
            f"{len(py_changed)} Python file(s) changed with no test updates "
            f"({', '.join(py_changed[:3])}{'...' if len(py_changed) > 3 else ''})"
        )
        score -= 0.1

    return ReviewResult(approved=approved, concerns=concerns,
                        score=score, reviewer="qa")


# ---------------------------------------------------------------------------
# 4. Release review
# ---------------------------------------------------------------------------

def release_review(proposal: dict) -> ReviewResult:
    """Checks deployment safety: compose file changes, rollback notes, entrypoints."""
    files          = proposal.get("files_changed", [])
    risk           = proposal.get("risk_level", "low")
    restorative    = proposal.get("restorative", True)
    rollback_notes = proposal.get("rollback_notes", "")

    concerns: list[str] = []
    approved = True
    score = 1.0

    # Rule R1 — docker-compose changes require dedicated release, not inline repair
    compose_files = [f for f in files if _PRODUCTION_COMPOSE.search(f)]
    if compose_files:
        concerns.append(
            f"docker-compose file(s) changed: {compose_files} — "
            "infrastructure changes require a dedicated deployment, not inline repair"
        )
        approved = False
        score -= 0.5

    # Rule R2 — high-risk non-restorative change
    if risk == "high" and not restorative:
        concerns.append(
            "high-risk, non-restorative change in a repair context is not allowed — "
            "repair must restore a known-good state"
        )
        approved = False
        score -= 0.4

    # Rule R3 (advisory) — production entrypoints without rollback notes
    entry_touched = [f for f in files if f in _ENTRYPOINTS]
    if entry_touched and not rollback_notes.strip():
        concerns.append(
            f"production entrypoints modified ({', '.join(entry_touched)}) "
            "without rollback notes — add rollback_notes before applying"
        )
        score -= 0.1

    return ReviewResult(approved=approved, concerns=concerns,
                        score=score, reviewer="release")


# ---------------------------------------------------------------------------
# 5. Docs review  (advisory — never blocks)
# ---------------------------------------------------------------------------

def docs_review(proposal: dict) -> ReviewResult:
    """Advisory: checks documentation completeness. Never blocks approval."""
    files = proposal.get("files_changed", [])
    patch = proposal.get("patch_diff", "")

    concerns: list[str] = []
    score = 1.0

    # Rule D1 — Python files changed but no .md files
    py_changed = [f for f in files if f.endswith(".py") and "test_" not in f]
    md_changed = [f for f in files if f.endswith(".md")]
    if py_changed and not md_changed:
        concerns.append(
            f"{len(py_changed)} Python file(s) changed with no documentation update"
        )
        score -= 0.05

    # Rule D2 — new public API (def/class) without docstring additions
    new_defs = len(re.findall(r"^\+\s*(def |class |async def )", patch, re.MULTILINE))
    new_docs = len(re.findall(r'^\+\s*"""', patch, re.MULTILINE))
    if new_defs > 0 and new_docs == 0:
        concerns.append(
            f"{new_defs} new function/class definition(s) added without docstrings"
        )
        score -= 0.05

    return ReviewResult(approved=True, concerns=concerns,
                        score=score, reviewer="docs")


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def run_all_reviews(proposal: dict) -> dict:
    """Run all 5 reviews and aggregate.

    Returns:
      {
        "approved": bool,    # False if any blocking reviewer denies
        "score": float,      # min across all reviewers
        "results": {         # per-reviewer ReviewResult.to_dict()
          "architect": {...},
          ...
        }
      }
    """
    reviews = {
        "architect": architect_review(proposal),
        "security":  security_review(proposal),
        "qa":        qa_review(proposal),
        "release":   release_review(proposal),
        "docs":      docs_review(proposal),
    }

    # docs is advisory — excluded from blocking logic
    blocking = {k: v for k, v in reviews.items() if k != "docs"}
    all_approved = all(r.approved for r in blocking.values())
    min_score    = min(r.score    for r in reviews.values())

    return {
        "approved": all_approved,
        "score":    round(max(0.0, min_score), 3),
        "results":  {k: v.to_dict() for k, v in reviews.items()},
    }
