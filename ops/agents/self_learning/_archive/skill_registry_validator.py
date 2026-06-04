"""
AIMS Self-Learning — Skill Registry Validator.

Validates SkillRegistryEntry objects and full registry snapshots
against safety invariants. No model calls, no I/O.
"""
from __future__ import annotations

import re
from typing import Any

from .skill_lifecycle import LIFECYCLE_STATES, LIFECYCLE_TRANSITIONS
from .agent_skill_ownership import AIMS_AGENTS
from .promotion_gates import GATE_DEFINITIONS, GATE_APPROVED

_SECRET_RE = re.compile(
    r"(?i)(api[_\-]?key|secret|password|bearer|credential|private[_\-]?key"
    r"|token)\s*[=:]\s*\S{8,}"
)

# Safety invariants — must all be True for any registry snapshot to be valid
SAFETY_INVARIANTS = {
    "self_approval_allowed": False,
    "runtime_activation_allowed": False,
    "direct_deletion_allowed": False,
    "secrets_in_registry_allowed": False,
    "model_slot_conflict_allowed": False,
}


class SkillRegistryValidator:

    def __init__(self) -> None:
        self._errors: list[str] = []
        self._warnings: list[str] = []

    @property
    def errors(self) -> list[str]:
        return list(self._errors)

    @property
    def warnings(self) -> list[str]:
        return list(self._warnings)

    def is_valid(self) -> bool:
        return len(self._errors) == 0

    def validate_entry(self, entry_dict: dict[str, Any]) -> bool:
        self._errors.clear()
        self._warnings.clear()

        skill_id = entry_dict.get("skill_id", "")
        if not skill_id or not re.match(r"^[a-z0-9][a-z0-9\-_]{0,62}$", skill_id):
            self._errors.append(
                f"skill_id must be kebab-case, 1–63 chars: {skill_id!r}"
            )

        owner = entry_dict.get("owner_agent_id", "")
        if owner not in AIMS_AGENTS:
            self._errors.append(
                f"owner_agent_id {owner!r} not in known AIMS agents: {AIMS_AGENTS}"
            )

        state = entry_dict.get("lifecycle_state", "")
        if state not in LIFECYCLE_STATES:
            self._errors.append(
                f"lifecycle_state {state!r} not in LIFECYCLE_STATES"
            )

        confidence = entry_dict.get("confidence", -1)
        if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
            self._errors.append(
                f"confidence must be float in [0.0, 1.0], got {confidence!r}"
            )

        desc = entry_dict.get("description", "")
        if len(desc) > 256:
            self._errors.append("description exceeds 256 characters")

        # Secret guard — no credential-like values anywhere in the entry
        entry_text = str(entry_dict)
        if _SECRET_RE.search(entry_text):
            self._errors.append(
                "Registry entry contains secret-like values — not allowed"
            )

        # Safety invariant: ACTIVE_RUNTIME_SKILL must not appear without
        # prior manual promotion gates approved (runtime_activation_allowed=False
        # means we flag it as requiring human review in registry, not auto-activate)
        if state == "ACTIVE_RUNTIME_SKILL":
            gate_statuses = entry_dict.get("gate_statuses", {})
            if gate_statuses.get("poli_gate") != GATE_APPROVED:
                self._warnings.append(
                    "ACTIVE_RUNTIME_SKILL state requires poli_gate=APPROVED "
                    "(runtime_activation_allowed=False: human confirmation needed)"
                )

        return self.is_valid()

    def validate_snapshot(self, snapshot_dict: dict[str, Any]) -> bool:
        self._errors.clear()
        self._warnings.clear()

        # Schema version present
        if not snapshot_dict.get("schema_version"):
            self._errors.append("snapshot missing schema_version")

        # All 9 agents must be registered
        agents = set(snapshot_dict.get("agents", []))
        missing_agents = set(AIMS_AGENTS) - agents
        if missing_agents:
            self._errors.append(
                f"snapshot missing required agents: {sorted(missing_agents)}"
            )

        # Safety invariants block
        inv = snapshot_dict.get("safety_invariants", {})
        for key, required_value in SAFETY_INVARIANTS.items():
            if inv.get(key) != required_value:
                self._errors.append(
                    f"safety_invariant {key!r} must be {required_value}, "
                    f"got {inv.get(key)!r}"
                )

        # next_allowed_phase must be present
        if not snapshot_dict.get("next_allowed_phase"):
            self._errors.append("snapshot missing next_allowed_phase")

        # Validate each entry
        for i, entry in enumerate(snapshot_dict.get("entries", [])):
            sub = SkillRegistryValidator()
            if not sub.validate_entry(entry):
                for err in sub.errors:
                    self._errors.append(f"entry[{i}] {entry.get('skill_id', '?')}: {err}")
            self._warnings.extend(
                f"entry[{i}] {entry.get('skill_id', '?')}: {w}"
                for w in sub.warnings
            )

        return self.is_valid()
