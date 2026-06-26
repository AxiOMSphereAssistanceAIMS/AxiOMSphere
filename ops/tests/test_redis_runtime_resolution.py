from __future__ import annotations

from ops.runtime import redis_runtime


def test_resolver_prefers_explicit_redis_url(monkeypatch) -> None:
    monkeypatch.setenv("DOCSREG_REDIS_URL", "redis://custom:6379/0")
    monkeypatch.setattr(redis_runtime, "_compose_services", lambda: ["aims-redis"])
    monkeypatch.setattr(redis_runtime, "_localhost_port_open", lambda: False)
    monkeypatch.setattr(redis_runtime, "_hostname_resolves", lambda hostname: False)

    report = redis_runtime.resolve_redis_url()

    assert report["selected_redis_url"] == "redis://custom:6379/0"
    assert report["redis_service_present"] is True


def test_healthy_compose_redis_not_reported_absent(monkeypatch) -> None:
    monkeypatch.delenv("DOCSREG_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("AIMS_REDIS_URL", raising=False)
    monkeypatch.setattr(redis_runtime, "_compose_services", lambda: ["aims-redis", "aims-worker"])
    monkeypatch.setattr(redis_runtime, "_localhost_port_open", lambda: False)
    monkeypatch.setattr(redis_runtime, "_hostname_resolves", lambda hostname: True)

    report = redis_runtime.resolve_redis_url(runtime_hint="compose_network")

    assert report["redis_service_present"] is True
    assert report["selected_redis_url"] == "redis://aims-redis:6379/0"
    assert report["runtime_mode"] == "compose_network"
    assert report["blocker"] is None


def test_host_localhost_closed_reported_as_runtime_network_mismatch(monkeypatch) -> None:
    monkeypatch.delenv("DOCSREG_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("AIMS_REDIS_URL", raising=False)
    monkeypatch.setattr(redis_runtime, "_compose_services", lambda: ["aims-redis"])
    monkeypatch.setattr(redis_runtime, "_localhost_port_open", lambda: False)
    monkeypatch.setattr(redis_runtime, "_hostname_resolves", lambda hostname: False)

    report = redis_runtime.resolve_redis_url(runtime_hint="host")

    assert report["selected_redis_url"] == "redis://aims-redis:6379/0"
    assert report["runtime_mode"] == "blocked"
    assert report["blocker"] == "runtime_network_mismatch"


def test_resolver_uses_aims_redis_inside_compose_network(monkeypatch) -> None:
    monkeypatch.delenv("DOCSREG_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("AIMS_REDIS_URL", raising=False)
    monkeypatch.setattr(redis_runtime, "_compose_services", lambda: ["aims-redis"])
    monkeypatch.setattr(redis_runtime, "_localhost_port_open", lambda: False)
    monkeypatch.setattr(redis_runtime, "_hostname_resolves", lambda hostname: True)

    report = redis_runtime.resolve_redis_url(runtime_hint="compose_network")

    assert report["selected_redis_url"] == "redis://aims-redis:6379/0"
    assert report["compose_hostname_expected"] is True
