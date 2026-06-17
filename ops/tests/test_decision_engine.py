"""Tests for ops/factory/decision_engine.py — runtime_names.py migration."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.runtime_names import RESTARTABLE_SERVICES, STEP_SERVICE_MAP


class TestDecisionEngineImports:
    def test_imports_step_service_map_from_runtime_names(self):
        import inspect
        import ops.factory.decision_engine as de

        source = inspect.getsource(de)
        assert "from core.runtime_names import STEP_SERVICE_MAP" in source, \
            "decision_engine must import STEP_SERVICE_MAP from core.runtime_names"

    def test_step_service_map_not_defined_locally(self):
        """STEP_SERVICE_MAP must not be redefined locally in decision_engine."""
        import inspect
        import ops.factory.decision_engine as de

        source = inspect.getsource(de)
        assert "STEP_SERVICE_MAP" not in source.split("import STEP_SERVICE_MAP")[1] or \
               "STEP_SERVICE_MAP: " not in source, \
            "STEP_SERVICE_MAP should not be redefined in decision_engine — import from runtime_names"


class TestDecisionEngineStepServiceMap:
    def test_all_service_values_are_valid_or_none(self):
        """Every non-None value in STEP_SERVICE_MAP must be a valid compose service name."""
        for step, svc in STEP_SERVICE_MAP.items():
            if svc is not None:
                assert svc in RESTARTABLE_SERVICES, \
                    f"STEP_SERVICE_MAP['{step}'] = '{svc}' not in RESTARTABLE_SERVICES"

    def test_context_filter_is_none(self):
        assert STEP_SERVICE_MAP.get("context_filter") is None, \
            "context_filter is a pure function — its service must be None"

    def test_expected_steps_present(self):
        expected = {"knomi_search", "context_filter", "doci_compose",
                    "cloud_validate", "poli_check", "omi_store"}
        assert expected.issubset(STEP_SERVICE_MAP.keys()), \
            f"Missing steps: {expected - STEP_SERVICE_MAP.keys()}"

    def test_no_axiomsphere_prefix_in_values(self):
        for step, svc in STEP_SERVICE_MAP.items():
            if svc is not None:
                assert not svc.startswith("axiomsphere-"), \
                    f"STEP_SERVICE_MAP['{step}'] = '{svc}' uses container_name, not service name"


class TestDecisionEngineDecide:
    def test_repair_action_targets_valid_service(self):
        """repair_action['target'] for known steps must be a valid service name."""
        from ops.factory.decision_engine import decide, Action

        for step, svc in STEP_SERVICE_MAP.items():
            if svc is None:
                continue
            d = decide(error="HTTP 503 service unavailable", http_status=503,
                       step_name=step, attempt=0)
            if d.action == Action.REPAIR and d.repair_action:
                target = d.repair_action.get("target")
                if target:
                    assert target in RESTARTABLE_SERVICES, \
                        f"repair_action target '{target}' for step '{step}' not in RESTARTABLE_SERVICES"
