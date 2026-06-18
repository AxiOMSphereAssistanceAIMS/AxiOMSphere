"""PHASE 8 Recovery Simulator — validates that proposed strategies resolve retention failures.

Given a RecoveryProposal, the simulator:
1. Models the expected token loss after applying the strategy
2. Checks whether the simulated loss passes the retention hard gate (<=2.0%)
3. Assigns a RecoveryVerdict (RESOLVED, PARTIALLY_RESOLVED, UNRESOLVED)
"""
from typing import List

from ops.docsreg.skills.recovery.models import (
    RecoveryProposal,
    RecoveryOutcome,
    RecoveryVerdict,
    RecoveryStrategy,
)


# Retention hard gate threshold
RETENTION_GATE_THRESHOLD = 2.0

# Strategy simulation parameters — model how each strategy affects loss
_STRATEGY_SIM_PARAMS = {
    RecoveryStrategy.SECTION_LEVEL_DIFF: {
        "base_reduction_factor": 0.85,
        "residual_floor": 0.3,  # Minimum loss after applying strategy
        "variance": 0.05,
    },
    RecoveryStrategy.FIELD_MERGE_BACK: {
        "base_reduction_factor": 0.90,
        "residual_floor": 0.2,
        "variance": 0.03,
    },
    RecoveryStrategy.REFERENCE_REBIND: {
        "base_reduction_factor": 0.80,
        "residual_floor": 0.4,
        "variance": 0.08,
    },
    RecoveryStrategy.PRESERVE_BEFORE_REPAIR: {
        "base_reduction_factor": 0.75,
        "residual_floor": 0.5,
        "variance": 0.06,
    },
    RecoveryStrategy.CHUNKED_REPAIR: {
        "base_reduction_factor": 0.70,
        "residual_floor": 0.6,
        "variance": 0.10,
    },
    RecoveryStrategy.CONSERVATIVE_REPAIR: {
        "base_reduction_factor": 0.60,
        "residual_floor": 0.8,
        "variance": 0.12,
    },
}


class RecoverySimulator:
    """Simulates recovery strategies to predict whether they resolve retention failures."""

    def simulate(self, proposal: RecoveryProposal) -> RecoveryOutcome:
        """Simulate applying a recovery strategy to a blocked case.

        Args:
            proposal: The recovery proposal to simulate

        Returns:
            RecoveryOutcome with simulated metrics and verdict
        """
        original_loss = proposal.diagnosis.original_loss_pct
        params = _STRATEGY_SIM_PARAMS.get(proposal.strategy, {
            "base_reduction_factor": 0.50,
            "residual_floor": 1.0,
            "variance": 0.15,
        })

        # Calculate simulated loss
        reduction = original_loss * params["base_reduction_factor"]
        simulated_loss = max(params["residual_floor"], original_loss - reduction)
        simulated_loss = round(simulated_loss, 2)

        # Check retention gate
        passes_gate = simulated_loss <= RETENTION_GATE_THRESHOLD
        improvement = round(original_loss - simulated_loss, 2)

        # Determine verdict
        if passes_gate:
            verdict = RecoveryVerdict.RESOLVED
        elif simulated_loss <= original_loss * 0.7:
            verdict = RecoveryVerdict.PARTIALLY_RESOLVED
        else:
            verdict = RecoveryVerdict.UNRESOLVED

        notes = self._build_notes(proposal, simulated_loss, passes_gate, params)

        return RecoveryOutcome(
            proposal=proposal,
            simulated_loss_pct=simulated_loss,
            original_loss_pct=original_loss,
            improvement_pct=improvement,
            passes_retention_gate=passes_gate,
            verdict=verdict,
            simulation_notes=notes,
        )

    def simulate_all(self, proposals: List[RecoveryProposal]) -> List[RecoveryOutcome]:
        """Simulate all proposals.

        Args:
            proposals: List of recovery proposals

        Returns:
            List of RecoveryOutcome results
        """
        return [self.simulate(p) for p in proposals]

    def _build_notes(
        self,
        proposal: RecoveryProposal,
        simulated_loss: float,
        passes_gate: bool,
        params: dict,
    ) -> str:
        """Build simulation notes explaining the outcome."""
        original = proposal.diagnosis.original_loss_pct
        strategy = proposal.strategy.value

        if passes_gate:
            return (
                f"Strategy '{strategy}' reduces loss from {original:.2f}% to "
                f"{simulated_loss:.2f}% (below {RETENTION_GATE_THRESHOLD}% threshold). "
                f"Retention gate would PASS. Reduction factor: {params['base_reduction_factor']:.0%}."
            )
        else:
            gap = simulated_loss - RETENTION_GATE_THRESHOLD
            return (
                f"Strategy '{strategy}' reduces loss from {original:.2f}% to "
                f"{simulated_loss:.2f}% but still {gap:.2f}% above threshold. "
                f"Consider combining with additional strategies or using "
                f"a more aggressive approach."
            )
