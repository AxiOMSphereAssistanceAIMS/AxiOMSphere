from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ops.ft.traini.autopilot.learning_cycle import run_learning_cycle


def _record() -> SimpleNamespace:
    payload = {"event_type": "contract_rejection", "contract": "ENG-H1", "learning_problem": "bounded issue", "rejection_reason": "not verified"}
    return SimpleNamespace(record_id="source-1", checksum="hash-1", content=json.dumps(payload), metadata={})


def test_cycle_is_idempotent_for_unchanged_source(tmp_path: Path) -> None:
    first = run_learning_cycle([_record()], tmp_path, cycle_id="a")
    second = run_learning_cycle([_record()], tmp_path, cycle_id="b")
    assert first["records_discovered"] == 1
    assert second["records_discovered"] == 0
    assert second["records_skipped_unchanged"] == 1
    assert len((tmp_path / "learning_value_assessment_ledger.jsonl").read_text().splitlines()) == 1
