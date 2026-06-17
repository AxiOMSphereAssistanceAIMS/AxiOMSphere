from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "ops"
for p in (str(ROOT), str(OPS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from ops.ft.orchestrator_qwen36.checkpoint_validator import audit_checkpoint
from ops.ft.orchestrator_qwen36.real_training_runner import build_payload as build_real_training_payload
from ops.ft.orchestrator_qwen36.tiny_lora_runner import build_payload as build_tiny_payload
from ops.traini.orchestrator_training.hermes_review_job import build_review_request
from ops.traini.orchestrator_training.package_builder import build_dataset_readiness
from ops.traini.orchestrator_training.schema import validate_sample


FIXTURES = Path("ops/traini/orchestrator_training/fixtures_test_only_orchestrator_samples.jsonl")


def test_checkpoint_audit_confirms_mixed_shards_and_text_only_path() -> None:
    payload = audit_checkpoint()
    assert payload["classification"] == "TEXT_ONLY_BF16_PATH_IMPLEMENTABLE_FOR_CONTROLLED_TEST"
    assert payload["tensor_prefix_counts"]["model.visual"] > 0
    assert payload["mixed_visual_language_shards"]


def test_fixture_samples_validate() -> None:
    lines = [json.loads(line) for line in FIXTURES.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    for row in lines:
        assert validate_sample(row) == []


def test_dataset_readiness_is_test_only_and_not_real_training_ready() -> None:
    payload = build_dataset_readiness(FIXTURES)
    assert payload["sample_count"] == 2
    assert payload["accepted_count"] == 2
    assert payload["ready_for_real_training"] is False


def test_tiny_lora_refuses_without_phase10_pass(tmp_path: Path) -> None:
    payload = build_tiny_payload(tmp_path, execute=False)
    assert payload["status"] == "BLOCKED_PHASE10_RESULT_MISSING"


def test_real_training_refuses_without_prereqs(tmp_path: Path) -> None:
    payload = build_real_training_payload(tmp_path, tmp_path / "missing.json", execute=False)
    assert payload["status"] == "BLOCKED_PHASE10_NOT_PASS"


def test_hermes_review_request_marks_local_fallback_risk() -> None:
    payload = build_review_request(
        package_path=Path("dummy.json"),
        models_payload={"data": [{"id": "project1"}, {"id": "local/nemotron120b"}]},
    )
    assert payload["status"] == "EXECUTION_PENDING_NO_LOCAL_FALLBACK_PATCH"
    assert "local/nemotron120b" in payload["detected_local_fallback_models"]
