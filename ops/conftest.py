from __future__ import annotations

import os

import pytest

# Redirect EventBus/ProjectStateManager test traffic to an isolated Redis
# DB instead of the shared production DB 0. aims-redis publishes
# 127.0.0.1:6379, so an unqualified redis://localhost:6379 from a
# host-side test process is the SAME Redis instance live containers
# (argus-bot, watchdog-agent, etc.) publish/subscribe on via
# redis://aims-redis:6379 — tests asserting on "the latest event" were
# flaking against real production traffic once those containers were
# activated. REDIS_URL is the same var argus_eventbus_bridge.py already
# reads, and every production container sets it explicitly, so this only
# changes behavior for local/test runs that leave it unset. Set before any
# test module imports event_bus/project_state_manager so the singletons
# pick it up on first use.
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture(autouse=True)
def _docsreg_runtime_mode_for_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default DOCSREG runtime to in-process for unit tests.

    Production code uses the compose launcher. Tests that need the canonical
    compose path can override this with ``monkeypatch.setenv(...)``.
    """
    if os.environ.get("DOCSREG_RUNTIME_MODE") is None:
        monkeypatch.setenv("DOCSREG_RUNTIME_MODE", "inproc")


@pytest.fixture(scope="session", autouse=True)
def _flush_test_event_bus_db() -> None:
    """Flush the isolated test Redis DB once per session, best-effort.

    Guards against stale keys from a previous interrupted test run leaking
    into this session's assertions. If Redis isn't reachable, tests that
    need it will fail with a clear connection error on their own — nothing
    to hide here.
    """
    import redis as _redis_sync

    url = os.environ.get("REDIS_URL", "redis://localhost:6379/15")
    try:
        client = _redis_sync.from_url(url)
        client.flushdb()
        client.close()
    except Exception:
        pass
