"""
DOCSREG retry policy — defines retry behaviour for failed or blocked pipeline stages.
"""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class RetryDecision:
    """Result of a retry evaluation for a single failure."""

    should_retry: bool
    delay_seconds: float
    reason: str


@dataclass
class DocsregRetryPolicy:
    """
    Configurable retry policy with exponential back-off and optional jitter.

    Parameters
    ----------
    max_attempts:
        Total number of attempts allowed (including the first one).
        When attempt >= max_attempts the run is considered exhausted.
    base_delay_seconds:
        Delay after the first failure (attempt=1).
    backoff_multiplier:
        Multiplicative factor applied per additional attempt.
        delay = min(base_delay * backoff_multiplier^(attempt-1), max_delay_seconds)
    max_delay_seconds:
        Upper bound on the computed delay.
    jitter:
        When True, multiplies the computed delay by random.uniform(0.9, 1.1).
    """

    max_attempts: int = 3
    base_delay_seconds: float = 5.0
    backoff_multiplier: float = 2.0
    max_delay_seconds: float = 120.0
    jitter: bool = False

    def decide(self, attempt: int, error: str | None = None) -> RetryDecision:
        """
        Return a RetryDecision for the given attempt number (1-based).

        Parameters
        ----------
        attempt:
            The current failure count (1 = first failure).
        error:
            Optional error message for context (included in reason).
        """
        if attempt >= self.max_attempts:
            reason = (
                f"Exhausted all {self.max_attempts} attempt(s)"
                + (f": {error}" if error else "")
            )
            return RetryDecision(
                should_retry=False,
                delay_seconds=0.0,
                reason=reason,
            )

        raw_delay = self.base_delay_seconds * (
            self.backoff_multiplier ** (attempt - 1)
        )
        delay = min(raw_delay, self.max_delay_seconds)

        if self.jitter:
            delay *= random.uniform(0.9, 1.1)

        remaining = self.max_attempts - attempt
        reason = (
            f"Retrying (attempt {attempt}/{self.max_attempts - 1}, "
            f"{remaining} attempt(s) remaining) after {delay:.1f}s"
            + (f": {error}" if error else "")
        )
        return RetryDecision(
            should_retry=True,
            delay_seconds=delay,
            reason=reason,
        )

    def total_max_wait_seconds(self) -> float:
        """
        Sum of all delays across all retry attempts (excluding the final failure).

        For max_attempts=1 (NO_RETRY) this returns 0.
        """
        total = 0.0
        for attempt in range(1, self.max_attempts):
            raw = self.base_delay_seconds * (self.backoff_multiplier ** (attempt - 1))
            total += min(raw, self.max_delay_seconds)
        return total


# ---------------------------------------------------------------------------
# Module-level policy constants
# ---------------------------------------------------------------------------

STANDARD_RETRY = DocsregRetryPolicy()
"""Default policy: 3 attempts, 5 s base delay, ×2 back-off, 120 s cap."""

AGGRESSIVE_RETRY = DocsregRetryPolicy(max_attempts=5, base_delay_seconds=2.0)
"""Aggressive policy: 5 attempts, 2 s base delay."""

NO_RETRY = DocsregRetryPolicy(max_attempts=1)
"""Policy that never retries (first failure is terminal)."""
