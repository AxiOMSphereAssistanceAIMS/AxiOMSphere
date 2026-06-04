"""
AIMS Self-Learning — Promotion Gates.

Defines the approval gates that must be satisfied before a skill
can advance through the lifecycle. No model calls, no runtime side effects.

Gate identifiers:
  argus_gate   — infra stability check (always required)
  logi_gate    — coordination approval (always required)
  qa_gate      — test coverage check (always required)
  traini_gate  — model safety check (required when model_related=True)
  poli_gate    — access control / production approval (required for ACTIVE)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# Canonical gate identifiers
GATE_ARGUS = "argus_gate"
GATE_LOGI = "logi_gate"
GATE_QA = "qa_gate"
GATE_TRAINI = "traini_gate"
GATE_POLI = "poli_gate"

# Gate statuses
GATE_PENDING = "PENDING"
GATE_APPROVED = "APPROVED"
GATE_REJECTED = "REJECTED"
GATE_SKIPPED = "SKIPPED"   # only valid for conditional gates not applicable


@dataclass(frozen=True)
class GateDefinition:
    gate_id: str
    description: str
    always_required: bool          # if True, required for every lifecycle step
    required_for_states: tuple[str, ...]  # additional states that trigger this gate
    conditional_flag: str | None   # risk flag that triggers this gate when True

    def is_required(
        self,
        target_state: str,
        risk_flags: dict[str, bool],
    ) -> bool:
        if self.always_required:
            return True
        if target_state in self.required_for_states:
            return True
        if self.conditional_flag and risk_flags.get(self.conditional_flag, False):
            return True
        return False


GATE_DEFINITIONS: tuple[GateDefinition, ...] = (
    GateDefinition(
        gate_id=GATE_ARGUS,
        description="Argus infra stability — no active P0/P1 incidents in affected service.",
        always_required=True,
        required_for_states=(),
        conditional_flag=None,
    ),
    GateDefinition(
        gate_id=GATE_LOGI,
        description="Logi coordination — skill does not conflict with active cross-dept workflows.",
        always_required=True,
        required_for_states=(),
        conditional_flag=None,
    ),
    GateDefinition(
        gate_id=GATE_QA,
        description="QA gate — skill has test coverage and dry-run evidence.",
        always_required=True,
        required_for_states=(),
        conditional_flag=None,
    ),
    GateDefinition(
        gate_id=GATE_TRAINI,
        description="Traini gate — model-related skill has been evaluated for inference safety.",
        always_required=False,
        required_for_states=("SANDBOX_SKILL", "CERTIFIED_SKILL", "ACTIVE_RUNTIME_SKILL"),
        conditional_flag="model_related",
    ),
    GateDefinition(
        gate_id=GATE_POLI,
        description=(
            "Poli access-control gate — production-facing changes approved by Poli agent. "
            "Required before ACTIVE_RUNTIME_SKILL state."
        ),
        always_required=False,
        required_for_states=("ACTIVE_RUNTIME_SKILL",),
        conditional_flag="production_related",
    ),
)

_GATE_MAP: dict[str, GateDefinition] = {g.gate_id: g for g in GATE_DEFINITIONS}


class PromotionGates:
    """Checks whether all required gates are satisfied for a lifecycle transition."""

    def __init__(
        self,
        risk_flags: dict[str, bool],
        gate_statuses: dict[str, str],
    ) -> None:
        self._risk_flags = risk_flags
        self._statuses = gate_statuses

    def required_gates(self, target_state: str) -> list[str]:
        return [
            g.gate_id
            for g in GATE_DEFINITIONS
            if g.is_required(target_state, self._risk_flags)
        ]

    def missing_approvals(self, target_state: str) -> list[str]:
        return [
            gate_id
            for gate_id in self.required_gates(target_state)
            if self._statuses.get(gate_id) != GATE_APPROVED
        ]

    def all_gates_approved(self, target_state: str) -> bool:
        return len(self.missing_approvals(target_state)) == 0

    def gate_summary(self, target_state: str) -> dict[str, Any]:
        required = self.required_gates(target_state)
        return {
            "target_state": target_state,
            "required_gates": required,
            "statuses": {g: self._statuses.get(g, GATE_PENDING) for g in required},
            "all_approved": self.all_gates_approved(target_state),
            "missing": self.missing_approvals(target_state),
        }
