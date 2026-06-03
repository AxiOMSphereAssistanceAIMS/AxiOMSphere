"""Argus → EventBus Bridge — publish monitoring events to unified orchestration.

Converts MonitorEvent from Argus monitoring into EventBus events:
- CRITICAL incidents → ARGUS_CRITICAL_INCIDENT
- WARNING incidents → ARGUS_WARNING_INCIDENT

This allows:
- Logi ProjectStateManager to create repair/analysis tasks
- Self-healing loop to orchestrate fixes
- Training pipeline to learn from incidents
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Optional

# EventBus imports (lazy)
_event_bus = None
_event_bus_enabled = os.environ.get("AIMS_PHASE5_EVENTBUS_ENABLED", "true").lower() in ("true", "1", "yes")


async def get_event_bus():
    """Get or initialize EventBus (lazy load)."""
    global _event_bus
    if _event_bus is None and _event_bus_enabled:
        try:
            from logi.event_bus import get_bus
            _event_bus = await get_bus(
                redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379")
            )
        except Exception as e:
            print(f"⚠ EventBus initialization failed: {e}")
    return _event_bus


async def publish_monitor_event(
    event_type: str,  # "critical" or "warning"
    service: str,     # container name, e.g., "docagent", "omi-bot"
    error: str,       # error message
    log_snippet: Optional[str] = None,
    incident_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    **extra_data,
) -> bool:
    """Publish Argus monitoring event to EventBus.

    Args:
        event_type: "critical" or "warning"
        service: service/container name
        error: error message
        log_snippet: relevant log lines
        incident_id: unique incident ID
        correlation_id: trace ID for correlation
        **extra_data: additional context (temperature, memory, etc.)

    Returns:
        True if published successfully, False otherwise
    """
    if not _event_bus_enabled:
        return False

    bus = await get_event_bus()
    if not bus:
        return False

    try:
        from logi.event_bus import Event, EventType, EventSeverity

        # Map event type to EventType
        if event_type == "critical":
            eb_event_type = EventType.ARGUS_CRITICAL_INCIDENT
            severity = EventSeverity.CRITICAL
        elif event_type == "warning":
            eb_event_type = EventType.ARGUS_WARNING_INCIDENT
            severity = EventSeverity.WARNING
        else:
            return False

        # Create event
        event = Event(
            event_type=eb_event_type,
            source="argus",
            timestamp=datetime.utcnow(),
            severity=severity,
            correlation_id=correlation_id,
            data={
                "service": service,
                "error": error,
                "incident_id": incident_id or f"argus_{service}_{int(datetime.utcnow().timestamp())}",
                "log_snippet": log_snippet,
                **extra_data,
            },
        )

        # Publish
        await bus.publish(event)
        return True

    except Exception as e:
        print(f"⚠ Failed to publish event: {e}")
        return False


async def publish_container_crash(
    container_name: str,
    error_message: str,
    exit_code: Optional[int] = None,
    log_tail: Optional[str] = None,
    incident_id: Optional[str] = None,
) -> bool:
    """Publish container crash event as CRITICAL incident."""
    return await publish_monitor_event(
        event_type="critical",
        service=container_name,
        error=f"Container crashed (exit code: {exit_code})" if exit_code is not None else error_message,
        log_snippet=log_tail,
        incident_id=incident_id,
        exit_code=exit_code,
    )


async def publish_health_check_failure(
    service_name: str,
    failure_reason: str,
    is_critical: bool = False,
    incident_id: Optional[str] = None,
) -> bool:
    """Publish health check failure event."""
    return await publish_monitor_event(
        event_type="critical" if is_critical else "warning",
        service=service_name,
        error=f"Health check failed: {failure_reason}",
        incident_id=incident_id,
    )


async def publish_resource_exhaustion(
    service_name: str,
    resource_type: str,  # "memory", "gpu", "cpu", "disk"
    current_value: float,
    threshold: float,
    is_critical: bool = False,
    incident_id: Optional[str] = None,
) -> bool:
    """Publish resource exhaustion event."""
    return await publish_monitor_event(
        event_type="critical" if is_critical else "warning",
        service=service_name,
        error=f"Resource exhaustion: {resource_type}={current_value:.1f}% (threshold={threshold}%)",
        incident_id=incident_id,
        resource_type=resource_type,
        current_value=current_value,
        threshold=threshold,
    )


async def publish_anomaly_detected(
    service_name: str,
    anomaly_type: str,  # "latency_spike", "error_rate_high", "throughput_drop", etc.
    severity: str,      # "warning" or "critical"
    description: str,
    incident_id: Optional[str] = None,
) -> bool:
    """Publish anomaly detection event."""
    return await publish_monitor_event(
        event_type=severity,
        service=service_name,
        error=f"Anomaly: {anomaly_type}",
        incident_id=incident_id,
        anomaly_type=anomaly_type,
        description=description,
    )


def create_argus_monitor_event_handler(publish_fn=None):
    """Create handler for MonitorEvent from Argus.

    Returns an async function that converts MonitorEvent to EventBus event.

    Usage:
        handler = create_argus_monitor_event_handler()
        # In Argus main loop:
        await handler(monitor_event)
    """
    if publish_fn is None:
        publish_fn = publish_monitor_event

    async def handle_monitor_event(ev):
        """Handle MonitorEvent from Argus monitoring."""
        # Map MonitorEvent fields to EventBus
        is_critical = ev.severity == "critical"

        await publish_fn(
            event_type="critical" if is_critical else "warning",
            service=ev.service or "unknown",
            error=ev.message or "Unknown error",
            log_snippet=ev.log_snippet,
            incident_id=ev.incident_id or f"argus_{ev.service}_{int(ev.timestamp.timestamp())}",
            correlation_id=getattr(ev, "correlation_id", None),
            event_type_argus=ev.event_type,
            restart_count=getattr(ev, "restart_count", None),
        )

    return handle_monitor_event


if __name__ == "__main__":
    # Test
    async def test():
        print("Testing Argus→EventBus bridge...")

        # Test 1: Critical incident
        result = await publish_container_crash(
            container_name="docagent",
            error_message="OOM killer invoked",
            exit_code=137,
            incident_id="test_001",
        )
        print(f"Critical incident published: {result}")

        # Test 2: Warning incident
        result = await publish_health_check_failure(
            service_name="omi-bot",
            failure_reason="Slow response time",
            is_critical=False,
            incident_id="test_002",
        )
        print(f"Warning incident published: {result}")

        # Let events settle
        await asyncio.sleep(1)

        # Check EventBus
        bus = await get_event_bus()
        if bus:
            stats = await bus.get_event_stats()
            print(f"Event stats: {stats}")

            await bus.disconnect()

    asyncio.run(test())
