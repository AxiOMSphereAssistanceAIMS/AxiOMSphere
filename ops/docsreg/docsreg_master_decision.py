"""
DOCSREG master decision engine — aggregates all gate results into a single
certification verdict.

After all pipeline gates have run, the caller adds each :class:`GateResult`
to a :class:`DecisionEngine` and calls :meth:`DecisionEngine.decide` with the
final quality score.  The engine applies the verdict logic and returns a
:class:`MasterDecision` that is JSON-serialisable and round-trip-stable.

This module is intentionally free of LLM calls, HTTP calls, and subprocess
calls.  It uses only the Python standard library.

Exports
-------
GateResult : dataclass
    Result of a single certification gate.
MasterDecision : dataclass
    Aggregated certification verdict with full gate history.
DecisionEngine : class
    Fluent accumulator that computes the master verdict.
create_engine() -> DecisionEngine
    Module-level convenience factory — returns a fresh empty engine.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

log = logging.getLogger("docsreg_master_decision")


# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class GateResult:
    """Result of a single certification gate.

    Fields
    ------
    gate_name : str
        Unique identifier for the gate, e.g. ``"quality_score_gate"``.
    passed : bool
        Whether the gate passed.
    details : str
        Human-readable summary of the gate outcome.  Defaults to ``""``.
    blocking : bool
        If ``True``, failure of this gate blocks certification.
        Defaults to ``True``.
    """

    gate_name: str
    passed: bool
    details: str = ""
    blocking: bool = True


@dataclass
class MasterDecision:
    """Aggregated certification verdict for a DOCSREG pipeline run.

    Fields
    ------
    verdict : str
        One of ``"CERTIFIED"``, ``"BLOCKED"``, or ``"ADVISORY_ONLY_FAIL"``.
    passed : bool
        ``True`` iff *verdict* is ``"CERTIFIED"``.
    quality_score : float
        Overall quality score in the range ``0.0``–``1.0``.
    gate_results : list[GateResult]
        The full ordered list of gate results that were evaluated.
    blocking_failures : list[str]
        Names of gates that failed and whose *blocking* flag is ``True``.
    advisory_failures : list[str]
        Names of gates that failed but whose *blocking* flag is ``False``.
    created_at : str
        ISO-8601 UTC timestamp at which the decision was computed.
    notes : str
        Optional free-text context.  Defaults to ``""``.
    """

    verdict: str
    passed: bool
    quality_score: float
    gate_results: list[GateResult]
    blocking_failures: list[str]
    advisory_failures: list[str]
    created_at: str
    notes: str = ""

    # ── Serialisation ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return a JSON-serialisable dict representation.

        The returned dict has the shape::

            {
                "verdict": "CERTIFIED" | "BLOCKED" | "ADVISORY_ONLY_FAIL",
                "passed": bool,
                "quality_score": float,
                "gate_results": [<each GateResult as a dict>],
                "blocking_failures": [str, ...],
                "advisory_failures": [str, ...],
                "created_at": "ISO-8601 UTC string",
                "notes": str
            }
        """
        return {
            "verdict": self.verdict,
            "passed": self.passed,
            "quality_score": self.quality_score,
            "gate_results": [asdict(g) for g in self.gate_results],
            "blocking_failures": list(self.blocking_failures),
            "advisory_failures": list(self.advisory_failures),
            "created_at": self.created_at,
            "notes": self.notes,
        }

    def to_json(self) -> str:
        """Return the decision as a pretty-printed JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "MasterDecision":
        """Rebuild a :class:`MasterDecision` from a dict produced by :meth:`to_dict`.

        Args:
            data: A dict with the same shape as the output of :meth:`to_dict`.

        Returns:
            A new :class:`MasterDecision` whose fields match *data* exactly.
        """
        gate_results = [
            GateResult(
                gate_name=g["gate_name"],
                passed=g["passed"],
                details=g.get("details", ""),
                blocking=g.get("blocking", True),
            )
            for g in data.get("gate_results", [])
        ]
        return cls(
            verdict=data["verdict"],
            passed=data["passed"],
            quality_score=data["quality_score"],
            gate_results=gate_results,
            blocking_failures=list(data.get("blocking_failures", [])),
            advisory_failures=list(data.get("advisory_failures", [])),
            created_at=data["created_at"],
            notes=data.get("notes", ""),
        )


# ── Decision engine ────────────────────────────────────────────────────────────


class DecisionEngine:
    """Fluent accumulator that computes the master certification verdict.

    Usage
    -----
    >>> engine = DecisionEngine()
    >>> engine.add_gate(GateResult("quality_gate", passed=True))
    >>> engine.add_gate(GateResult("format_gate", passed=False, blocking=False))
    >>> decision = engine.decide(quality_score=0.87)
    >>> decision.verdict
    'ADVISORY_ONLY_FAIL'
    """

    def __init__(self) -> None:
        self._gates: list[GateResult] = []

    # ── Mutation ───────────────────────────────────────────────────────────────

    def add_gate(self, gate_result: GateResult) -> "DecisionEngine":
        """Accumulate a gate result.

        Args:
            gate_result: A :class:`GateResult` to add to the engine.

        Returns:
            *self*, to allow method chaining.
        """
        self._gates.append(gate_result)
        log.debug(
            "decision_engine: added gate %r passed=%s blocking=%s",
            gate_result.gate_name,
            gate_result.passed,
            gate_result.blocking,
        )
        return self

    # ── Verdict logic ──────────────────────────────────────────────────────────

    def decide(self, quality_score: float, notes: str = "") -> MasterDecision:
        """Compute and return the master certification verdict.

        Verdict rules (evaluated in order):

        1. If any gate failed with ``blocking=True`` **or** *quality_score* is
           below ``0.60`` → ``"BLOCKED"``.
        2. Elif any gate failed with ``blocking=False`` → ``"ADVISORY_ONLY_FAIL"``.
        3. Else → ``"CERTIFIED"``.

        Args:
            quality_score: Overall quality score in the range ``0.0``–``1.0``.
            notes: Optional free-text context appended to the decision.

        Returns:
            A :class:`MasterDecision` with the computed verdict and full gate
            history.
        """
        blocking_failures = [
            g.gate_name for g in self._gates if not g.passed and g.blocking
        ]
        advisory_failures = [
            g.gate_name for g in self._gates if not g.passed and not g.blocking
        ]

        if blocking_failures or quality_score < 0.60:
            verdict = "BLOCKED"
        elif advisory_failures:
            verdict = "ADVISORY_ONLY_FAIL"
        else:
            verdict = "CERTIFIED"

        passed = verdict == "CERTIFIED"
        created_at = datetime.now(tz=timezone.utc).isoformat()

        log.info(
            "decision_engine: verdict=%r quality_score=%.3f blocking_failures=%r "
            "advisory_failures=%r",
            verdict,
            quality_score,
            blocking_failures,
            advisory_failures,
        )

        return MasterDecision(
            verdict=verdict,
            passed=passed,
            quality_score=quality_score,
            gate_results=list(self._gates),
            blocking_failures=blocking_failures,
            advisory_failures=advisory_failures,
            created_at=created_at,
            notes=notes,
        )


# ── Module-level convenience ───────────────────────────────────────────────────


def create_engine() -> DecisionEngine:
    """Return a fresh empty :class:`DecisionEngine`."""
    return DecisionEngine()
