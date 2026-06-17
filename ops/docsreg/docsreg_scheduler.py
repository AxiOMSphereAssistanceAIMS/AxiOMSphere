"""
DOCSREG Redis scheduler — run-scoped state, metrics, gates, errors,
contract persistence, and heartbeat tracking via Redis.

All keys are namespaced under ``docsreg:run:{run_id}:*`` to allow multiple
concurrent certification runs without key collisions.

Usage:
    scheduler = DocsregRedisScheduler(redis_client, run_id="cert-2026-001")
    scheduler.set_state(DocsregState.CREATED)
    scheduler.transition_to(DocsregState.INTAKE_READY)
    scheduler.set_metric("quality_score", 0.98)
    scheduler.set_gate("EVIDENCE_GATE", "PASS")
    scheduler.record_error("Stage X failed: timeout")
    scheduler.beat_heartbeat("worker-01")
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ops.docsreg.docsreg_contracts import DocsregTaskContract
from ops.docsreg.docsreg_state_machine import VALID_TRANSITIONS, is_valid_transition

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# All known states (valid sources for transitions + terminals)
# ---------------------------------------------------------------------------
_ALL_KNOWN_STATES: frozenset[str] = frozenset(VALID_TRANSITIONS.keys())


def _decode(value: Any) -> str | None:
    """Return *value* as a ``str``, decoding bytes if needed, or ``None``."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


# ---------------------------------------------------------------------------
# DocsregRedisScheduler
# ---------------------------------------------------------------------------

class DocsregRedisScheduler:
    """
    Run-scoped Redis scheduler for a single DOCSREG certification run.

    Parameters
    ----------
    redis_client:
        Any object with ``.set()``, ``.get()``, ``.hset()``, ``.hget()``,
        ``.rpush()``, ``.lrange()``, ``.setex()`` — duck-typed so the module
        works without a hard ``import redis`` dependency.
    run_id:
        Unique identifier for this certification run.
    """

    def __init__(self, redis_client: Any, run_id: str) -> None:
        self._redis = redis_client
        self._run_id = run_id

    # ------------------------------------------------------------------
    # Key scheme
    # ------------------------------------------------------------------

    @property
    def run_id(self) -> str:
        """The unique identifier for this certification run."""
        return self._run_id

    @property
    def _state_key(self) -> str:
        return f"docsreg:run:{self._run_id}:state"

    @property
    def _metrics_key(self) -> str:
        return f"docsreg:run:{self._run_id}:metrics"

    @property
    def _gates_key(self) -> str:
        return f"docsreg:run:{self._run_id}:gates"

    @property
    def _errors_key(self) -> str:
        return f"docsreg:run:{self._run_id}:errors"

    @property
    def _heartbeat_prefix(self) -> str:
        return f"docsreg:run:{self._run_id}:heartbeat:"

    def _contract_key(self, stage: str) -> str:
        return f"docsreg:run:{self._run_id}:contract:{stage}"

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def set_state(self, state: str) -> None:
        """
        Persist *state* to Redis.

        Raises
        ------
        ValueError
            If *state* is not a recognised DocsregState constant.
        """
        if state not in _ALL_KNOWN_STATES:
            raise ValueError(
                f"Unknown DOCSREG state: {state!r}. "
                f"Valid states: {sorted(_ALL_KNOWN_STATES)}"
            )
        self._redis.set(self._state_key, state)
        logger.debug("State set: run=%s state=%s", self._run_id, state)

    def get_state(self) -> str | None:
        """Return the current state, or ``None`` if not yet set."""
        return _decode(self._redis.get(self._state_key))

    def transition_to(self, new_state: str) -> bool:
        """
        Validate and apply a state transition.

        - If no current state is recorded, sets *new_state* directly (initial
          seeding of the run).
        - If *new_state* is not a valid next state from the current one,
          returns ``False`` without modifying Redis.

        Returns
        -------
        bool
            ``True`` if the transition was applied, ``False`` otherwise.

        Note
        ----
        The state read and subsequent write are not atomic. Under concurrent
        callers, two processes could both read the same current state, both
        pass validation, and both write — resulting in a lost update.
        This implementation assumes single-process use per run_id.
        """
        current = self.get_state()

        if current is None:
            # Initial state — accept unconditionally (bootstrap case)
            try:
                self.set_state(new_state)
                logger.debug(
                    "Initial state set: run=%s state=%s", self._run_id, new_state
                )
                return True
            except ValueError:
                logger.warning(
                    "Invalid initial state requested: run=%s state=%s",
                    self._run_id,
                    new_state,
                )
                return False

        if current not in _ALL_KNOWN_STATES:
            logger.warning(
                "Transition rejected — unknown current state: run=%s current=%s",
                self._run_id,
                current,
            )
            return False

        if not is_valid_transition(current, new_state):
            logger.warning(
                "Invalid transition: run=%s %s -> %s",
                self._run_id,
                current,
                new_state,
            )
            return False

        try:
            self.set_state(new_state)
        except ValueError:
            logger.warning(
                "Transition target not a known state: run=%s new_state=%s",
                self._run_id,
                new_state,
            )
            return False

        logger.debug(
            "Transition applied: run=%s %s -> %s", self._run_id, current, new_state
        )
        return True

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def set_metric(self, key: str, value: Any) -> None:
        """Store *value* (JSON-serialised) in the run metrics hash."""
        self._redis.hset(self._metrics_key, key, json.dumps(value))

    def get_metric(self, key: str) -> Any | None:
        """
        Retrieve a previously stored metric value.

        Returns ``None`` if the key is absent.
        """
        raw = self._redis.hget(self._metrics_key, key)
        if raw is None:
            return None
        return json.loads(_decode(raw))  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Gates
    # ------------------------------------------------------------------

    def set_gate(self, gate_name: str, verdict: str) -> None:
        """Record a gate verdict (e.g. ``"PASS"`` / ``"FAIL"`` / ``"BLOCK"``)."""
        self._redis.hset(self._gates_key, gate_name, verdict)

    def get_gate(self, gate_name: str) -> str | None:
        """Return the verdict for *gate_name*, or ``None`` if not recorded."""
        raw = self._redis.hget(self._gates_key, gate_name)
        return _decode(raw)

    # ------------------------------------------------------------------
    # Errors
    # ------------------------------------------------------------------

    def record_error(self, error: str) -> None:
        """Append *error* to the run error list (Redis RPUSH)."""
        self._redis.rpush(self._errors_key, error)

    def get_errors(self) -> list[str]:
        """Return all recorded errors in insertion order."""
        raw_list = self._redis.lrange(self._errors_key, 0, -1)
        return [_decode(item) for item in raw_list]  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Contract persistence
    # ------------------------------------------------------------------

    def save_contract(self, contract: DocsregTaskContract) -> None:
        """Serialise and save *contract* under its stage key."""
        self._redis.set(self._contract_key(contract.stage), contract.to_json())
        logger.debug(
            "Contract saved: run=%s stage=%s status=%s",
            self._run_id,
            contract.stage,
            contract.status,
        )

    def load_contract(self, stage: str) -> DocsregTaskContract | None:
        """
        Load and deserialise the contract for *stage*.

        Returns ``None`` if no contract has been saved for that stage.
        """
        raw = self._redis.get(self._contract_key(stage))
        if raw is None:
            return None
        return DocsregTaskContract.from_json(_decode(raw))  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def beat_heartbeat(self, worker_id: str, ttl_seconds: int = 60) -> None:
        """
        Register or refresh the heartbeat for *worker_id*.

        The key expires automatically after *ttl_seconds* seconds of silence.
        """
        self._redis.setex(
            f"{self._heartbeat_prefix}{worker_id}", ttl_seconds, "alive"
        )
        logger.debug(
            "Heartbeat: run=%s worker=%s ttl=%ds",
            self._run_id,
            worker_id,
            ttl_seconds,
        )

    def get_heartbeat(self, worker_id: str) -> str | None:
        """
        Return the heartbeat value for *worker_id*, or ``None`` if expired/missing.
        """
        raw = self._redis.get(f"{self._heartbeat_prefix}{worker_id}")
        return _decode(raw)
