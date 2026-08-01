from __future__ import annotations

import json
from types import SimpleNamespace

from ops.ft.traini.autopilot.engineering_contract_learning_unit_extractor import extract_engineering_units
from ops.ft.traini.autopilot.learning_unit_route_classifier import classify_unit


def _record(mode: str = "agent_skill_learning") -> SimpleNamespace:
    payload = {"event_type": "contract_resolution", "contract": "ENG-H1", "objective": "Preserve the consumer contract", "learning_problem": "Do not infer runtime fields", "accepted_resolution": {"status": "accepted_raw_only", "payload": {"status": "accepted"}}, "source_truth": {"decision": "runtime_verified", "runtime_checks_pass": True, "evidence_hashes": {"a": "hash-a"}, "model_route": {"slot": "32"}}}
    return SimpleNamespace(record_id="source-1", checksum="source-hash", content=json.dumps(payload), metadata={"mode": mode})


def test_skill_mode_is_preserved_and_not_overridden() -> None:
    units = extract_engineering_units(_record())
    assert len(units) == 1
    assert units[0].unit_type == "SKILL_LEARNING_UNIT"
    assert classify_unit(units[0])["route"] == "AGENT_SKILL_LEARNING"


def test_explicit_verified_model_route_can_create_bounded_model_unit() -> None:
    unit = extract_engineering_units(_record(mode="traini_model_tuning"))[0]
    assert unit.unit_type == "MODEL_LEARNING_UNIT"
    assert "full_source_json" in unit.excluded_content
    assert classify_unit(unit)["route"] == "MODEL_TRAINING_SLOT32"
