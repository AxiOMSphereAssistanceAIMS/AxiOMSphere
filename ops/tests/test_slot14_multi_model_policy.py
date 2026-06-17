from __future__ import annotations

import os
from pathlib import Path

from ops.learning.compare_14b_chat_models import rank_models
from ops.traini.slot14_rebenchmark_skill import build_rebenchmark_task
from ops.scripts.weekly_model_upgrade import _registry_slot14_model


def test_rank_models_prefers_higher_pass_rate_then_json_then_latency() -> None:
    stats = {
        "omi-ft-14b-v16:latest": {
            "pass_rate": 0.93,
            "json_valid_count": 57,
            "avg_latency_ms": 700.0,
        },
        "omi-ft-14b-v18:latest": {
            "pass_rate": 0.93,
            "json_valid_count": 57,
            "avg_latency_ms": 650.0,
        },
        "omi-ft-14b-v19:latest": {
            "pass_rate": 0.95,
            "json_valid_count": 56,
            "avg_latency_ms": 800.0,
        },
    }
    ranking = rank_models(stats)
    assert [name for name, _ in ranking] == [
        "omi-ft-14b-v19:latest",
        "omi-ft-14b-v18:latest",
        "omi-ft-14b-v16:latest",
    ]


def test_slot14_rebenchmark_task_uses_four_model_pool() -> None:
    task = build_rebenchmark_task()
    assert task["candidate_pool"] == [
        "omi-ft-14b-v16:latest",
        "omi-ft-14b-v18:latest",
        "omi-ft-14b-v19:latest",
        "omi-ft-14b-v20:latest",
    ]
    assert task["champion_policy"]["retain_runner_up"] is True
    assert task["champion_policy"]["max_retained_models"] == 2
    assert "cleanup_losers" in task["champion_policy"]


def test_registry_slot14_model_reads_current_champion(tmp_path: Path, monkeypatch) -> None:
    registry = tmp_path / "model_registry.yaml"
    registry.write_text(
        """
model_slots:
  "14":
    current: "omi-ft-14b-v18:latest"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AIMS_MODEL_REGISTRY", str(registry))
    monkeypatch.delenv("FT_MODEL_14", raising=False)
    assert _registry_slot14_model() == "omi-ft-14b-v18:latest"
