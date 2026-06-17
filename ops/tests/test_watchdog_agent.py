#!/usr/bin/env python3
"""Tests for WatchdogAgent — pure functions and import smoke.

No HTTP server or httpx calls required — tests the stability logic
and config loading directly.
"""
import sys
from pathlib import Path

repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root / "ops"))
sys.path.insert(0, str(repo_root))

import pytest

from agents.watchdog_agent import (
    ServiceState,
    compute_stability,
    load_config,
    _DEFAULT_CONFIG,
)


# ---------------------------------------------------------------------------
# compute_stability
# ---------------------------------------------------------------------------

class TestComputeStability:
    def test_empty_states_is_stable(self):
        assert compute_stability({}) == 1.0

    def test_all_up(self):
        states = {
            "a": ServiceState("a", "http://a/health", status="up"),
            "b": ServiceState("b", "http://b/health", status="up"),
        }
        assert compute_stability(states) == 1.0

    def test_all_down(self):
        states = {
            "a": ServiceState("a", "http://a/health", status="down"),
            "b": ServiceState("b", "http://b/health", status="down"),
        }
        assert compute_stability(states) == 0.0

    def test_half_up_half_down(self):
        states = {
            "a": ServiceState("a", "http://a/health", status="up"),
            "b": ServiceState("b", "http://b/health", status="down"),
        }
        s = compute_stability(states)
        assert 0.4 < s < 0.6  # ~0.5

    def test_unknown_counts_as_half(self):
        states = {
            "a": ServiceState("a", "http://a/health", status="unknown"),
        }
        assert compute_stability(states) == 0.5

    def test_required_down_zeroes_stability(self):
        states = {
            "a": ServiceState("a", "http://a/health", required=True, status="down"),
            "b": ServiceState("b", "http://b/health", required=False, status="up"),
            "c": ServiceState("c", "http://c/health", required=False, status="up"),
        }
        assert compute_stability(states) == 0.0

    def test_required_up_does_not_zero(self):
        states = {
            "a": ServiceState("a", "http://a/health", required=True, status="up"),
            "b": ServiceState("b", "http://b/health", required=False, status="down"),
        }
        s = compute_stability(states)
        assert s > 0.0  # required is up, so no forced zero

    def test_multiple_required_all_down_is_zero(self):
        states = {
            "a": ServiceState("a", "http://a/health", required=True, status="down"),
            "b": ServiceState("b", "http://b/health", required=True, status="down"),
        }
        assert compute_stability(states) == 0.0

    def test_result_is_clamped_0_to_1(self):
        states = {
            "a": ServiceState("a", "http://a/health", status="up"),
        }
        s = compute_stability(states)
        assert 0.0 <= s <= 1.0

    def test_three_up_one_down_no_required(self):
        states = {
            "a": ServiceState("a", "http://a/health", status="up"),
            "b": ServiceState("b", "http://b/health", status="up"),
            "c": ServiceState("c", "http://c/health", status="up"),
            "d": ServiceState("d", "http://d/health", status="down"),
        }
        s = compute_stability(states)
        assert 0.7 < s < 0.8  # 3/4 = 0.75


# ---------------------------------------------------------------------------
# ServiceState
# ---------------------------------------------------------------------------

class TestServiceState:
    def test_defaults(self):
        s = ServiceState("svc", "http://svc/health")
        assert s.status == "unknown"
        assert s.required is False
        assert s.consecutive_failures == 0
        assert s.consecutive_successes == 0

    def test_to_dict_keys(self):
        s = ServiceState("svc", "http://svc/health")
        d = s.to_dict()
        assert "name" in d
        assert "url" in d
        assert "required" in d
        assert "status" in d
        assert "last_checked" in d
        assert "last_ok" in d
        assert "consecutive_failures" in d
        assert "latency_ms" in d

    def test_to_dict_last_ok_none_when_zero(self):
        s = ServiceState("svc", "http://svc/health")
        d = s.to_dict()
        assert d["last_ok"] is None

    def test_to_dict_last_ok_present(self):
        import time
        s = ServiceState("svc", "http://svc/health")
        s.last_ok = time.time()
        d = s.to_dict()
        assert d["last_ok"] is not None


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_default_config_loads(self):
        cfg = load_config()
        assert "poll_interval_sec" in cfg
        assert "services" in cfg
        assert isinstance(cfg["services"], list)

    def test_default_config_has_required_keys(self):
        cfg = load_config()
        assert "failure_threshold" in cfg
        assert "recovery_threshold" in cfg

    def test_config_services_have_name_and_url(self):
        cfg = load_config()
        for svc in cfg["services"]:
            assert "name" in svc, f"Service missing 'name': {svc}"
            assert "url" in svc, f"Service missing 'url': {svc}"

    def test_missing_config_returns_defaults(self, tmp_path):
        missing = tmp_path / "nonexistent.yaml"
        cfg = load_config(missing)
        assert cfg["services"] == []
        assert cfg["poll_interval_sec"] == 30

    def test_custom_config(self, tmp_path):
        cfg_file = tmp_path / "watch.yaml"
        cfg_file.write_text(
            "poll_interval_sec: 10\nfailure_threshold: 1\nrecovery_threshold: 1\n"
            "services:\n  - name: test\n    url: http://test/health\n    required: true\n"
        )
        cfg = load_config(cfg_file)
        assert cfg["poll_interval_sec"] == 10
        assert len(cfg["services"]) == 1
        assert cfg["services"][0]["required"] is True

    def test_config_services_include_review_gates(self):
        cfg = load_config()
        names = {s["name"] for s in cfg["services"]}
        assert "architect-agent" in names
        assert "security-agent" in names
        assert "qa-agent" in names
        assert "release-agent" in names
        assert "docs-agent" in names

    def test_active_self_healing_services_are_required(self):
        cfg = load_config()
        required = {s["name"] for s in cfg["services"] if s.get("required")}
        assert "security-agent" in required
        assert "repairman-api" in required
        assert "poli-agent" not in {s["name"] for s in cfg["services"]}


# ---------------------------------------------------------------------------
# WatchdogAgent import smoke
# ---------------------------------------------------------------------------

class TestWatchdogImports:
    def test_app_importable(self):
        from agents.watchdog_agent import app
        assert app is not None
        assert app.title == "WatchdogAgent"

    def test_port_and_name(self):
        import agents.watchdog_agent as m
        assert m.PORT == 8016
        assert m.AGENT_NAME == "watchdog_agent"

    def test_health_endpoint_direct(self):
        from agents.watchdog_agent import health
        result = health()
        assert result["status"] == "ok"
        assert result["service"] == "watchdog_agent"
        assert result["port"] == 8016
        assert "stability" in result

    def test_status_endpoint_direct(self):
        from agents.watchdog_agent import status
        result = status()
        assert hasattr(result, "stability")
        assert hasattr(result, "services_total")
        assert hasattr(result, "services_up")
        assert hasattr(result, "services_down")
        assert hasattr(result, "services_unknown")

    def test_status_empty_states(self):
        from agents import watchdog_agent as m
        # Patch states to empty for isolation
        original = m._states
        m._states = {}
        try:
            result = m.status()
            assert result.stability == 1.0
            assert result.services_total == 0
        finally:
            m._states = original


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
