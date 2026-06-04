"""
AIMS Self-Learning — Sandbox Execution Schema.

Defines SandboxExecutionRequest and SandboxExecutionResult dataclasses
for Phase 9 dry-run harness execution. No model calls, no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Execution result statuses
EXEC_STATUS_PASS = "SANDBOX_PASS"
EXEC_STATUS_WARN = "SANDBOX_WARN"
EXEC_STATUS_FAIL = "SANDBOX_FAIL"
EXEC_STATUS_REJECTED = "REJECTED_UNSAFE"

EXEC_STATUSES: tuple[str, ...] = (
    EXEC_STATUS_PASS,
    EXEC_STATUS_WARN,
    EXEC_STATUS_FAIL,
    EXEC_STATUS_REJECTED,
)

# Evidence keys that every result must include
REQUIRED_EVIDENCE_KEYS: tuple[str, ...] = (
    "dry_run_log",
    "assertion_results",
    "no_forbidden_action_triggered",
)

# Lifecycle transition enforced at execution phase
EXECUTION_LIFECYCLE_TRANSITION = "SANDBOX_SKILL -> CERTIFIED_SKILL"

_SECRET_RE = re.compile(
    r"(?i)(api[_\-]?key|secret|password|bearer|credential|private[_\-]?key"
    r"|token)\s*[=:]\s*\S{8,}"
)


@dataclass
class SandboxExecutionRequest:
    """
    Input descriptor for a single sandbox dry-run execution.

    plan_id must reference a SandboxSkillPlan from Phase 8.
    input_fixture_path points to a file under sandbox_execution_inputs/.
    dry_run must be True — execution harness never activates real runtime.
    """

    plan_id: str
    skill_id: str
    owner_agent_id: str
    input_fixture_path: str
    dry_run: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.dry_run:
            raise ValueError("SandboxExecutionRequest.dry_run must be True")
        if not self.plan_id:
            raise ValueError("plan_id must be non-empty")
        if not self.skill_id:
            raise ValueError("skill_id must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "skill_id": self.skill_id,
            "owner_agent_id": self.owner_agent_id,
            "input_fixture_path": self.input_fixture_path,
            "dry_run": self.dry_run,
            "metadata": self.metadata,
        }

    @classmethod
    def from_plan(cls, plan_dict: dict[str, Any], input_fixture_path: str) -> "SandboxExecutionRequest":
        return cls(
            plan_id=plan_dict["plan_id"],
            skill_id=plan_dict["skill_id"],
            owner_agent_id=plan_dict.get("owner_agent_id", ""),
            input_fixture_path=input_fixture_path,
            dry_run=True,
            metadata=plan_dict.get("metadata", {}),
        )


@dataclass
class SandboxExecutionResult:
    """
    Output of a sandbox dry-run execution.

    status must be one of EXEC_STATUSES.
    evidence_pack must contain all REQUIRED_EVIDENCE_KEYS.
    dry_run is always True.
    no_secrets_detected must be True for PASS status.
    """

    execution_id: str
    plan_id: str
    skill_id: str
    status: str                     # one of EXEC_STATUSES
    dry_run: bool                   # always True
    evidence_pack: dict[str, Any]   # must contain REQUIRED_EVIDENCE_KEYS
    assertion_failures: list[str]
    warnings: list[str]
    no_secrets_detected: bool
    forbidden_actions_triggered: list[str]
    execution_log: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in EXEC_STATUSES:
            raise ValueError(
                f"status must be one of {EXEC_STATUSES}, got {self.status!r}"
            )
        if not self.dry_run:
            raise ValueError("SandboxExecutionResult.dry_run must be True")
        missing = [k for k in REQUIRED_EVIDENCE_KEYS if k not in self.evidence_pack]
        if missing:
            raise ValueError(f"evidence_pack missing required keys: {missing}")

    def is_pass(self) -> bool:
        return self.status == EXEC_STATUS_PASS

    def is_rejected(self) -> bool:
        return self.status == EXEC_STATUS_REJECTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "plan_id": self.plan_id,
            "skill_id": self.skill_id,
            "status": self.status,
            "dry_run": self.dry_run,
            "evidence_pack": self.evidence_pack,
            "assertion_failures": self.assertion_failures,
            "warnings": self.warnings,
            "no_secrets_detected": self.no_secrets_detected,
            "forbidden_actions_triggered": self.forbidden_actions_triggered,
            "execution_log": self.execution_log,
            "metadata": self.metadata,
        }
