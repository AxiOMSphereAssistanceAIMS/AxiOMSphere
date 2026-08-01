from __future__ import annotations

import json

from ops.ft.traini.autopilot.clearance_registry import ClearanceRegistry
from ops.ft.traini.autopilot.route_store import persist_route_decisions


def test_clearance_registry_is_append_only_and_idempotent(tmp_path):
    registry = ClearanceRegistry(tmp_path / "clearance.jsonl")
    decision = {"pair_id": "p1", "candidate_hash": "h1", "clearance_version": "v1", "decision": "REJECT", "reviewer_identity": "reviewer"}
    assert registry.append(decision)["registry_event"] == "CLEARANCE_RECORDED"
    assert registry.append(decision)["duplicate_suppressed"] is True
    assert len((tmp_path / "clearance.jsonl").read_text().splitlines()) == 1


def test_route_store_isolated_and_hashed(tmp_path):
    result = persist_route_decisions(tmp_path, [{"learning_unit_id": "u1", "route": "MODEL_TRAINING_SLOT32"}], cycle_id="c1")
    manifest = json.loads((tmp_path / "route_store_manifest.json").read_text())
    assert result["counts"]["MODEL_TRAINING_SLOT32"] == 1
    assert manifest["stores"]["slot32_learning_units.jsonl"]["unique_ids"] == 1
