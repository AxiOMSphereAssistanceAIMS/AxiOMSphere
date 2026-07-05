"""
model_self_check.py

Deterministic self-check for local model actor output.

Checks actor output for known mistake classes before Codex audit or verifier.
Never grants final PASS — that requires the deterministic verifier.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_FAKE_OUTPUT_PATTERNS = [
    re.compile(r"\b(1234|5678|9101|1121)\b"),          # placeholder file sizes
    re.compile(r"size:\s*\d+\s*bytes\s*\(fictional\)", re.IGNORECASE),
    re.compile(r"<simulated|<fabricated|<mock output>", re.IGNORECASE),
    re.compile(r"\[bash\]\s*\$\s*\w+.*\n.*Output:\s*\[not executed\]", re.IGNORECASE),
]

_STATIC_ONLY_PATTERNS = [
    re.compile(r"according to (the|our) (schedule|CLAUDE\.md|static|plan)", re.IGNORECASE),
    re.compile(r"based on (the static|the configured|the plan|CLAUDE\.md)", re.IGNORECASE),
]

_OPERATIONAL_KEYWORDS = re.compile(
    r"\b(today|сегодня|now|сейчас|currently|сейчас|running|запущено|"
    r"scheduled|запланировано|training|обучение)\b",
    re.IGNORECASE,
)

_PASS_WITHOUT_EVIDENCE_RE = re.compile(
    r"\b(PASS(ED)?|VERIFIED_PASS|status:\s*PASS)\b", re.IGNORECASE
)

_DESTRUCTIVE_KEYWORDS = re.compile(
    r"\b(rm\s+-rf|drop\s+table|delete\s+database|truncate|purge\s+all|"
    r"удали\s+базу|wipe)\b",
    re.IGNORECASE,
)


@dataclass
class SelfCheckResult:
    status: str                              # PASS | MISMATCH | INSUFFICIENT_EVIDENCE | POLICY_VIOLATION
    mistake_class: str | None                # FAKE_OUTPUT | STATIC_ONLY_OPERATIONAL | PASS_WITHOUT_EVIDENCE | DESTRUCTIVE_UNCONFIRMED | MISMATCH
    findings: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)
    correction_recommendations: list[str] = field(default_factory=list)
    learning_candidate: bool = False


def run_self_check(
    user_request: str,
    actor_output: str,
    action_results: list[dict],
    policy_context: dict,
) -> SelfCheckResult:
    """
    Deterministically check actor output for known mistake classes.

    Parameters
    ----------
    user_request     : original user query
    actor_output     : what the actor produced
    action_results   : list of real tool/execution results (may be empty)
    policy_context   : dict with keys like source, confirmed_by_operator
    """
    findings: list[str] = []
    gaps: list[str] = []
    recs: list[str] = []
    mistake_class: str | None = None
    learning_candidate = False

    has_real_results = bool(action_results)
    source = policy_context.get("source", "cli")
    confirmed = policy_context.get("confirmed_by_operator", False)

    # Check 1: fake command output patterns
    for pat in _FAKE_OUTPUT_PATTERNS:
        if pat.search(actor_output):
            findings.append("Actor output contains known fake/placeholder output pattern")
            gaps.append("Real command output not present in conversation")
            recs.append("Output NEED_EXECUTION with exact commands instead of simulating results")
            mistake_class = "FAKE_OUTPUT"
            learning_candidate = True
            break

    # Check 2: operational/today query without live context
    if _OPERATIONAL_KEYWORDS.search(user_request) and not has_real_results:
        if any(pat.search(actor_output) for pat in _STATIC_ONLY_PATTERNS):
            findings.append(
                "Operational/current-status query answered from static config only — "
                "live Telegram/scheduler context not loaded"
            )
            gaps.append("Live operational context not fetched")
            recs.append(
                "Load live operational context before answering today/current/running queries. "
                "If unavailable, disclose explicitly."
            )
            if mistake_class is None:
                mistake_class = "STATIC_ONLY_OPERATIONAL"
            learning_candidate = True

    # Check 3: PASS claimed without verifier evidence in action_results
    if _PASS_WITHOUT_EVIDENCE_RE.search(actor_output):
        verifier_present = any(
            r.get("type") in ("verifier_result", "test_result", "pytest_result")
            for r in action_results
        )
        if not verifier_present:
            findings.append(
                "Actor claims PASS but no verifier/test result is present in action_results"
            )
            gaps.append("Deterministic verifier result missing")
            recs.append(
                "Run deterministic verifier (pytest/post_state_verifier) before claiming PASS. "
                "Final PASS authority belongs to the verifier, not the actor."
            )
            if mistake_class is None:
                mistake_class = "PASS_WITHOUT_EVIDENCE"
            learning_candidate = True

    # Check 4: destructive action without confirmation
    if _DESTRUCTIVE_KEYWORDS.search(actor_output) and not confirmed:
        findings.append(
            "Actor output contains destructive action without confirmed operator approval"
        )
        gaps.append("confirmed_by_operator not set in policy_context")
        recs.append(
            "Destructive actions require explicit operator confirmation. "
            "Set confirmed_by_operator=True in policy_context or ask for confirmation."
        )
        if mistake_class is None:
            mistake_class = "DESTRUCTIVE_UNCONFIRMED"
        learning_candidate = True

    # Check 5: intent mismatch — actor output doesn't reference user's topic
    # Only fires when actor_output is very short and clearly off-topic.
    # Skipped if actor output already has a FINAL/NEED_EXECUTION structure
    # or if any standard operational output keyword is present.
    _SAFE_OUTPUT_WORDS = {
        "final", "answer", "status", "pass", "fail", "warn", "unknown",
        "evidence", "next", "need_execution", "reason", "commands",
        "master", "passed", "verified", "gateway", "agent",
    }
    request_low = user_request.lower()
    output_low = actor_output.lower()
    # Suppress mismatch check when output has known structured format keywords
    if not any(w in output_low for w in _SAFE_OUTPUT_WORDS):
        topic_words = [
            w for w in re.findall(r"\b\w{7,}\b", request_low)
            if w not in ("проверь", "покажи", "показать", "статусом")
        ]
        if topic_words and not any(w in output_low for w in topic_words[:3]):
            findings.append(
                f"Possible intent mismatch: user asked about {topic_words[:3]} "
                f"but actor output does not mention these topics"
            )
            recs.append("Verify actor addressed the actual user request")
            if mistake_class is None:
                mistake_class = "MISMATCH"

    if not findings:
        return SelfCheckResult(
            status="PASS",
            mistake_class=None,
            findings=[],
            evidence_gaps=[],
            correction_recommendations=[],
            learning_candidate=False,
        )

    # Determine overall status
    critical_classes = {"FAKE_OUTPUT", "PASS_WITHOUT_EVIDENCE", "DESTRUCTIVE_UNCONFIRMED"}
    if mistake_class in critical_classes:
        status = "POLICY_VIOLATION" if mistake_class == "DESTRUCTIVE_UNCONFIRMED" else "INSUFFICIENT_EVIDENCE"
    else:
        status = "MISMATCH"

    return SelfCheckResult(
        status=status,
        mistake_class=mistake_class,
        findings=findings,
        evidence_gaps=gaps,
        correction_recommendations=recs,
        learning_candidate=learning_candidate,
    )
