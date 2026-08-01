"""Canonical bounded learning-unit model."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


EXTRACTION_VERSION = "learning-unit-v1"


@dataclass(frozen=True)
class LearningUnit:
    learning_unit_id: str
    source_id: str
    source_version: str
    raw_source_hash: str
    evidence_hashes: list[str]
    unit_type: str
    problem: str
    observed_evidence: str
    root_cause: str
    accepted_decision: str
    verification_status: str
    verification_reference: str
    bounded_input: str
    bounded_target: str
    task_family: str
    extraction_version: str = EXTRACTION_VERSION
    route_candidates: list[str] = field(default_factory=list)
    excluded_content: list[str] = field(default_factory=list)
    producer_mode: str | None = None

    @staticmethod
    def deterministic_id(source_id: str, source_version: str, unit_type: str, bounded_input: str, bounded_target: str, extraction_version: str = EXTRACTION_VERSION) -> str:
        payload = "\x1f".join((source_id, source_version, unit_type, bounded_input, bounded_target, extraction_version))
        return "lu_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_learning_unit(unit: LearningUnit) -> list[str]:
    errors: list[str] = []
    for field_name in ("learning_unit_id", "source_id", "source_version", "raw_source_hash", "unit_type", "bounded_input", "task_family", "extraction_version"):
        if not str(getattr(unit, field_name) or "").strip():
            errors.append(f"MISSING_{field_name}")
    if len(unit.bounded_input) > 12000 or len(unit.bounded_target) > 12000:
        errors.append("BOUNDED_CONTEXT_TOO_LARGE")
    searchable = "\n".join(
        (unit.problem, unit.observed_evidence, unit.root_cause, unit.accepted_decision,
         unit.bounded_input, unit.bounded_target)
    ).lower()
    if any(marker in searchable for marker in ("<think>", "</think>", "private scratchpad", "chain of thought")):
        errors.append("PRIVATE_OR_HIDDEN_REASONING")
    return errors
