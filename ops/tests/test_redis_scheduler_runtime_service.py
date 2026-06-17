#!/usr/bin/env python3
"""
Phase 8/10: Redis Scheduler always-on runtime service tests (8 tests).

Validates that the deployment artifacts introduced in Phases 3–4 and 8 are
correctly wired:

  1. docker-compose.yml contains the redis-scheduler service
  2. redis-scheduler uses condition: service_healthy for depends_on
  3. redis-scheduler uses restart: unless-stopped
  4. redis-scheduler healthcheck calls healthcheck.py
  5. healthcheck.py HEARTBEAT_STALE_THRESHOLD == 150
  6. healthcheck.py checks scheduler:daemon:heartbeat and scheduler:tasks:pending
  7. run_scheduler_daemon.py reads AIMS_REDIS_URL (primary) before TASK_SCHEDULER_REDIS_URL
  8. run_scheduler_daemon.py DAEMON_HEARTBEAT_TTL == 180 (3× the 60 s write interval)
"""

import ast
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker-compose.yml"
HEALTHCHECK_PY = ROOT / "ops" / "scheduler" / "healthcheck.py"
ENTRYPOINT_PY = ROOT / "ops" / "scheduler" / "run_scheduler_daemon.py"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_compose() -> dict:
    with COMPOSE_FILE.open() as f:
        return yaml.safe_load(f)


def _get_assignments(filepath: Path) -> dict:
    """Return all top-level NAME = LITERAL assignments from a Python source file."""
    tree = ast.parse(filepath.read_text())
    result = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                    result[target.id] = node.value.value
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Tests: docker-compose.yml
# ─────────────────────────────────────────────────────────────────────────────

def test_compose_has_redis_scheduler_service():
    """redis-scheduler must be defined in docker-compose.yml."""
    cfg = _load_compose()
    assert "redis-scheduler" in cfg.get("services", {}), (
        "redis-scheduler service missing from docker-compose.yml"
    )


def test_redis_scheduler_depends_on_service_healthy():
    """redis-scheduler must wait for aims-redis to be healthy before starting."""
    svc = _load_compose()["services"]["redis-scheduler"]
    depends = svc.get("depends_on", {})
    assert "aims-redis" in depends, "depends_on: aims-redis not found"
    condition = depends["aims-redis"].get("condition")
    assert condition == "service_healthy", (
        f"Expected condition: service_healthy, got: {condition!r}"
    )


def test_redis_scheduler_restart_policy():
    """restart: unless-stopped lets manual docker stop stay stopped."""
    svc = _load_compose()["services"]["redis-scheduler"]
    policy = svc.get("restart")
    assert policy == "unless-stopped", (
        f"Expected restart: unless-stopped, got: {policy!r}"
    )


def test_redis_scheduler_healthcheck_calls_healthcheck_py():
    """Docker healthcheck must invoke healthcheck.py, not a shell ping."""
    svc = _load_compose()["services"]["redis-scheduler"]
    hc = svc.get("healthcheck", {})
    test_cmd = hc.get("test", [])
    cmd_str = " ".join(str(t) for t in test_cmd)
    assert "healthcheck.py" in cmd_str, (
        f"healthcheck test does not reference healthcheck.py: {cmd_str!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests: healthcheck.py
# ─────────────────────────────────────────────────────────────────────────────

def test_healthcheck_stale_threshold_is_150():
    """HEARTBEAT_STALE_THRESHOLD must be 150 (2.5× the 60 s write interval)."""
    assignments = _get_assignments(HEALTHCHECK_PY)
    assert "HEARTBEAT_STALE_THRESHOLD" in assignments, (
        "HEARTBEAT_STALE_THRESHOLD not defined in healthcheck.py"
    )
    assert assignments["HEARTBEAT_STALE_THRESHOLD"] == 150


def test_healthcheck_checks_expected_redis_keys():
    """healthcheck.py must reference the daemon heartbeat key and pending queue key."""
    src = HEALTHCHECK_PY.read_text()
    assert "scheduler:daemon:heartbeat" in src, (
        "healthcheck.py does not reference scheduler:daemon:heartbeat"
    )
    assert "scheduler:tasks:pending" in src, (
        "healthcheck.py does not reference scheduler:tasks:pending"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests: run_scheduler_daemon.py
# ─────────────────────────────────────────────────────────────────────────────

def test_entrypoint_reads_aims_redis_url_first():
    """AIMS_REDIS_URL must be the primary env var (legacy alias second)."""
    src = ENTRYPOINT_PY.read_text()
    # AIMS_REDIS_URL must appear before TASK_SCHEDULER_REDIS_URL
    pos_aims = src.find("AIMS_REDIS_URL")
    pos_legacy = src.find("TASK_SCHEDULER_REDIS_URL")
    assert pos_aims != -1, "AIMS_REDIS_URL not referenced in entrypoint"
    assert pos_legacy != -1, "TASK_SCHEDULER_REDIS_URL not referenced in entrypoint"
    assert pos_aims < pos_legacy, (
        "AIMS_REDIS_URL should appear before TASK_SCHEDULER_REDIS_URL in REDIS_URL resolution"
    )


def test_entrypoint_heartbeat_ttl_is_180():
    """DAEMON_HEARTBEAT_TTL must be 180 (3× Docker healthcheck interval of 30 s * 2)."""
    assignments = _get_assignments(ENTRYPOINT_PY)
    assert "DAEMON_HEARTBEAT_TTL" in assignments, (
        "DAEMON_HEARTBEAT_TTL not defined in run_scheduler_daemon.py"
    )
    assert assignments["DAEMON_HEARTBEAT_TTL"] == 180
