from __future__ import annotations

from ops.ft.traini.autopilot.learning_unit import LearningUnit, validate_learning_unit
from ops.ft.traini.autopilot.learning_unit_store import LearningUnitStore


def test_learning_unit_id_is_deterministic() -> None:
    args = ("s1", "v1", "SKILL_LEARNING_UNIT", "problem", "target")
    assert LearningUnit.deterministic_id(*args) == LearningUnit.deterministic_id(*args)


def test_store_holds_private_content(tmp_path) -> None:
    unit = LearningUnit("id", "s", "v1", "h", [], "SKILL_LEARNING_UNIT", "<think>secret</think>", "e", "", "", "UNKNOWN", "", "x", "y", "skill")
    row = LearningUnitStore(tmp_path / "units.jsonl").append(unit)
    assert row["validation_errors"]
    assert not (tmp_path / "units.jsonl").exists()
    assert (tmp_path / "learning_unit_hold_store.jsonl").exists()


def test_valid_unit_is_persisted(tmp_path) -> None:
    unit = LearningUnit("id", "s", "v1", "h", [], "SKILL_LEARNING_UNIT", "problem", "evidence", "", "decision", "PASS", "ref", "problem", "target", "skill")
    row = LearningUnitStore(tmp_path / "units.jsonl").append(unit)
    assert row["validation_errors"] == []
    assert (tmp_path / "units.jsonl").read_text()
