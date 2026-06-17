"""Tests for ops/self_healing/policy_gate.py — runtime_names.py migration."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ops"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from core.runtime_names import RESTARTABLE_SERVICES, SERVICE_AXI_BOT, SERVICE_OMI_BOT


class TestPolicyGateImports:
    def test_imports_restartable_services_from_runtime_names(self):
        import inspect
        import ops.self_healing.policy_gate as pg

        source = inspect.getsource(pg)
        assert "from core.runtime_names import RESTARTABLE_SERVICES" in source, \
            "policy_gate must import RESTARTABLE_SERVICES from core.runtime_names"

    def test_restartable_containers_aliased_to_runtime_names(self):
        from ops.self_healing.policy_gate import RESTARTABLE_CONTAINERS

        assert RESTARTABLE_CONTAINERS == RESTARTABLE_SERVICES, \
            "RESTARTABLE_CONTAINERS must equal RESTARTABLE_SERVICES from runtime_names"

    def test_no_hardcoded_service_names_in_restartable(self):
        """policy_gate must not define its own service name strings."""
        import inspect
        import ops.self_healing.policy_gate as pg

        source = inspect.getsource(pg)
        assert '"axi-bot"' not in source, \
            "policy_gate must not hardcode 'axi-bot' — use runtime_names"
        assert '"omi-bot"' not in source, \
            "policy_gate must not hardcode 'omi-bot' — use runtime_names"
        assert '"omi-api"' not in source, \
            "policy_gate must not hardcode 'omi-api' — use runtime_names"


class TestPolicyGateServiceNames:
    def test_allowed_services_use_compose_names_not_container_names(self):
        """RESTARTABLE_CONTAINERS must have compose service names (no axiomsphere- prefix)."""
        from ops.self_healing.policy_gate import RESTARTABLE_CONTAINERS

        for name in RESTARTABLE_CONTAINERS:
            assert not name.startswith("axiomsphere-"), \
                f"'{name}' looks like a container_name — use the compose service name instead"

    def test_known_services_in_restartable(self):
        from ops.self_healing.policy_gate import RESTARTABLE_CONTAINERS

        assert SERVICE_AXI_BOT in RESTARTABLE_CONTAINERS
        assert SERVICE_OMI_BOT in RESTARTABLE_CONTAINERS

    def test_policy_allows_valid_service_restart(self):
        from ops.self_healing.policy_gate import SysPolic

        policy = SysPolic()
        for svc in RESTARTABLE_SERVICES:
            assert policy.allow({"type": "restart_container", "target": svc})

    def test_policy_denies_container_name_restart(self):
        from ops.self_healing.policy_gate import SysPolic, PolicyDenied

        policy = SysPolic()
        with pytest.raises(PolicyDenied):
            policy.allow({"type": "restart_container", "target": "axiomsphere-omi-bot"})

    def test_policy_denies_dangerous_actions(self):
        from ops.self_healing.policy_gate import SysPolic, PolicyDenied

        policy = SysPolic()
        for bad in ("delete_db", "exec_shell", "wipe_storage", "drop_table", "rm_rf"):
            with pytest.raises(PolicyDenied):
                policy.allow({"type": bad})
