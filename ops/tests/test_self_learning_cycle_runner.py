import json
from datetime import datetime as RealDatetime

from ops.traini import self_learning_cycle_runner as module


class StubRunner(module.SelfLearningCycleRunner):
    def _handle_slc_collect_experience_daily(self):
        return {"state": "COMPLETED", "marker": "collected"}

    def _handle_slc_prepare_datasets_14_32(self):
        return {"state": "COMPLETED", "marker": "prepared"}


def test_dependency_blocks_out_of_order_step(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "RUN_ROOT", tmp_path)
    runner = StubRunner(run_id="run", dry_run=True)

    result = runner.run("slc_prepare_datasets_14_32")

    assert result["state"] == "BLOCKED_DEPENDENCY"
    assert result["missing_dependencies"] == ["slc_collect_experience_daily"]


def test_completed_step_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "RUN_ROOT", tmp_path)
    runner = StubRunner(run_id="run", dry_run=True)

    first = runner.run("slc_collect_experience_daily")
    second = runner.run("slc_collect_experience_daily")

    assert first["state"] == "COMPLETED"
    assert second["idempotent_result"] == "SKIPPED_ALREADY_COMPLETED"
    stored = json.loads(
        (tmp_path / "run" / "steps" / "slc_collect_experience_daily.json").read_text()
    )
    assert stored["marker"] == "collected"


def test_run_id_keeps_post_midnight_steps_in_previous_cycle(monkeypatch):
    class BeforeNoon:
        @classmethod
        def now(cls, tz):
            return RealDatetime(2026, 6, 6, 3, 30, tzinfo=tz)

    monkeypatch.delenv("AIMS_SELF_LEARNING_RUN_ID", raising=False)
    monkeypatch.setattr(module, "datetime", BeforeNoon)

    assert module._run_id() == "2026-06-05"
