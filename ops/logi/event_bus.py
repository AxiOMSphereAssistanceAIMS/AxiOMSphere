"""Event Bus — pub/sub coordination for AIMS project orchestration.

Event types:
- argus.critical_incident    - Production failure detected
- argus.warning_incident     - Degradation detected
- repair.requested           - Repair job created
- repair.started             - Repair execution begun
- repair.succeeded           - Repair completed successfully
- repair.failed              - Repair failed
- training.requested         - Training job queued
- training.started           - Training execution begun
- training.completed         - Training finished (with eval metrics)
- model.deployed             - New model pushed to production
- task.created               - Task added to state manager
- task.updated               - Task status changed
- task.completed             - Task finished
"""
from __future__ import annotations

import json
import asyncio
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Callable, Any, Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Event categories for the bus."""
    # Argus monitoring
    ARGUS_CRITICAL_INCIDENT = "argus.critical_incident"
    ARGUS_WARNING_INCIDENT = "argus.warning_incident"

    # Repair lifecycle
    REPAIR_REQUESTED = "repair.requested"
    REPAIR_STARTED = "repair.started"
    REPAIR_SUCCEEDED = "repair.succeeded"
    REPAIR_FAILED = "repair.failed"

    # Training lifecycle
    TRAINING_REQUESTED = "training.requested"
    TRAINING_STARTED = "training.started"
    TRAINING_COMPLETED = "training.completed"

    # Model lifecycle
    MODEL_DEPLOYED = "model.deployed"

    # Task lifecycle
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_SCHEDULED = "task.scheduled"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_RETRY_SCHEDULED = "task.retry_scheduled"
    TASK_ESCALATED = "task.escalated"

    # Task missed-start policy (Phase 3)
    TASK_MISSED_STARTUP_REVIEW = "task.missed_startup_review"  # Task held on startup
    TASK_HELD_FOR_DECISION = "task.held_for_decision"  # Task blocked, user must decide
    TASK_RESCHEDULE_REQUESTED = "task.reschedule_requested"  # User chose to reschedule
    TASK_KEEP_IN_REVIEW = "task.keep_in_review"  # User chose to keep in review queue

    # Learning
    LEARNING_TRIGGERED = "learning.triggered"
    SYNTHETIC_DATA_GENERATED = "synthetic_data.generated"


class EventSeverity(str, Enum):
    """Event severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Event:
    """Atomic event published to the bus."""
    event_type: EventType
    source: str                          # "argus", "repairman", "traini", "logi", "bedrock"
    timestamp: datetime
    severity: EventSeverity = EventSeverity.INFO
    data: Dict[str, Any] = None          # event-specific payload

    # Tracing
    correlation_id: Optional[str] = None  # link related events
    parent_event_id: Optional[str] = None # causality chain

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        d = asdict(self)
        d['event_type'] = self.event_type.value
        d['severity'] = self.severity.value
        d['timestamp'] = self.timestamp.isoformat()
        if not d.get('data'):
            d['data'] = {}
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> Event:
        """Deserialize from JSON dict."""
        d['event_type'] = EventType(d.get('event_type', 'task.created'))
        d['severity'] = EventSeverity(d.get('severity', 'info'))
        d['timestamp'] = datetime.fromisoformat(d.get('timestamp', datetime.utcnow().isoformat()))
        return Event(**d)


class EventBus:
    """Redis-backed pub/sub event bus for orchestration."""

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None
        self.pubsub: Optional[redis.client.PubSub] = None

        # Local handler registry (fallback/in-memory)
        self._handlers: Dict[str, List[Callable]] = {}

        # In-memory event ledger (fallback when Redis unavailable)
        self._event_ledger: Dict[str, List[Event]] = {}

    async def connect(self):
        """Connect to Redis backend."""
        try:
            self.redis_client = await redis.from_url(self.redis_url)
            await self.redis_client.ping()
            print(f"✓ EventBus connected to Redis at {self.redis_url}")
        except Exception as e:
            print(f"⚠ Redis connection failed: {e}, using in-memory fallback")
            self.redis_client = None

    async def disconnect(self):
        """Close Redis connection and cleanup.

        Clears the client/pubsub references after closing so a later
        get_bus() call on this same singleton detects "not connected" and
        reconnects, instead of retrying every publish/read against an
        already-closed connection until it silently falls back to an
        empty in-memory ledger.
        """
        if self.pubsub:
            await self.pubsub.close()
            self.pubsub = None
        if self.redis_client:
            await self.redis_client.close()
            self.redis_client = None

    # ============ Publishing ============

    async def publish(self, event: Event) -> bool:
        """Publish an event to the bus.

        Retries Redis publish up to 3 times with exponential backoff
        (0.5 s, 1 s, 2 s).  After all retries are exhausted the event
        falls back to local handler dispatch so no events are silently
        dropped on transient Redis issues.
        """
        channel = f"event:{event.event_type.value}"
        payload = json.dumps(event.to_dict())

        if self.redis_client:
            _backoff = [0.5, 1.0, 2.0]
            for attempt, delay in enumerate(_backoff, start=1):
                try:
                    await self.redis_client.publish(channel, payload)
                    # Also store in ledger for auditing
                    ledger_key = f"event_ledger:{event.event_type.value}"
                    await self.redis_client.lpush(ledger_key, payload)
                    # Keep last 1000 events per type
                    await self.redis_client.ltrim(ledger_key, 0, 999)
                    return True
                except Exception as e:
                    if attempt < len(_backoff):
                        logger.warning(
                            "Redis publish failed (attempt %d/3): %s — retrying in %.1fs",
                            attempt, e, delay,
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.warning(
                            "Redis publish failed after 3 attempts: %s — falling back to local handlers",
                            e,
                        )

        # Fallback: store in in-memory ledger and call local handlers
        ledger_key = event.event_type.value
        if ledger_key not in self._event_ledger:
            self._event_ledger[ledger_key] = []
        self._event_ledger[ledger_key].insert(0, event)  # newest first
        # Keep last 1000 events per type
        if len(self._event_ledger[ledger_key]) > 1000:
            self._event_ledger[ledger_key] = self._event_ledger[ledger_key][:1000]

        await self._call_handlers(event)
        return True

    # ============ Subscribing ============

    async def subscribe(
        self,
        event_type: EventType,
        handler: Callable[[Event], Any],
    ) -> None:
        """Subscribe a handler to an event type.

        Handler signature: async def handler(event: Event) -> None
        """
        if event_type.value not in self._handlers:
            self._handlers[event_type.value] = []

        self._handlers[event_type.value].append(handler)

        # If Redis is available, start listening. The pubsub subscription
        # itself is established synchronously here (not inside the spawned
        # task) so that publishes issued right after subscribe() returns are
        # not silently dropped by a not-yet-attached Redis pub/sub listener.
        if self.redis_client:
            channel = f"event:{event_type.value}"
            pubsub = self.redis_client.pubsub()
            await pubsub.subscribe(channel)
            asyncio.create_task(self._redis_listen_loop(pubsub, handler))

    async def subscribe_pattern(
        self,
        pattern: str,  # e.g., "repair.*" for all repair events
        handler: Callable[[Event], Any],
    ) -> None:
        """Subscribe to a pattern of events."""
        if self.redis_client:
            asyncio.create_task(self._redis_listen_pattern(pattern, handler))

    # ============ Internal ============

    async def _call_handlers(self, event: Event):
        """Call all local handlers for an event."""
        handlers = self._handlers.get(event.event_type.value, [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                print(f"⚠ Handler error for {event.event_type}: {e}")

    async def _redis_listen(self, channel: str, handler: Callable[[Event], Any]):
        """Listen to a Redis channel and call handler.

        Retained for any external caller relying on the old fire-and-forget
        signature; subscribe() itself no longer calls this.
        """
        if not self.redis_client:
            return

        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe(channel)
        await self._redis_listen_loop(pubsub, handler)

    async def _redis_listen_loop(self, pubsub, handler: Callable[[Event], Any]):
        """Consume messages from an already-subscribed pubsub object."""
        try:
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        data = json.loads(message['data'])
                        event = Event.from_dict(data)
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event)
                        else:
                            handler(event)
                    except Exception as e:
                        print(f"⚠ Error processing message: {e}")
        finally:
            await pubsub.close()

    async def _redis_listen_pattern(self, pattern: str, handler: Callable[[Event], Any]):
        """Listen to a Redis channel pattern and call handler."""
        if not self.redis_client:
            return

        pubsub = self.redis_client.pubsub()
        await pubsub.psubscribe(pattern)

        try:
            async for message in pubsub.listen():
                if message['type'] == 'pmessage':
                    try:
                        data = json.loads(message['data'])
                        event = Event.from_dict(data)
                        if asyncio.iscoroutinefunction(handler):
                            await handler(event)
                        else:
                            handler(event)
                    except Exception as e:
                        print(f"⚠ Error processing message: {e}")
        finally:
            await pubsub.close()

    # ============ Querying Event History ============

    async def get_events(
        self,
        event_type: EventType,
        limit: int = 100,
    ) -> List[Event]:
        """Retrieve recent events of a given type."""
        ledger_key = f"event_ledger:{event_type.value}"

        if self.redis_client:
            try:
                data = await self.redis_client.lrange(ledger_key, 0, limit - 1)
                if data:
                    events = [Event.from_dict(json.loads(item)) for item in data]
                    return list(reversed(events))  # newest first
            except Exception as e:
                pass

        # Fallback: return from in-memory ledger
        event_type_str = event_type.value
        if event_type_str in self._event_ledger:
            return self._event_ledger[event_type_str][:limit]
        return []

    async def get_event_stats(self) -> Dict[str, int]:
        """Get count of events by type."""
        stats = {}

        if self.redis_client:
            try:
                pattern = "event_ledger:*"
                cursor = 0
                while True:
                    cursor, keys = await self.redis_client.scan(cursor, match=pattern)
                    for key in keys:
                        count = await self.redis_client.llen(key)
                        event_type = key.decode() if isinstance(key, bytes) else key
                        event_type = event_type.replace("event_ledger:", "")
                        stats[event_type] = count
                    if cursor == 0:
                        break
            except Exception as e:
                pass

        # Fallback: merge in-memory ledger counts (ensures we don't miss events)
        for event_type, events in self._event_ledger.items():
            # Take max of Redis count and in-memory count
            stats[event_type] = max(stats.get(event_type, 0), len(events))

        return stats


# ============ Singleton Instance ============

_bus_instance: Optional[EventBus] = None


async def get_bus(redis_url: Optional[str] = None) -> EventBus:
    """Get or create the global EventBus instance.

    ``REDIS_URL`` overrides the default target when the caller doesn't pass
    an explicit ``redis_url`` — every production container already sets this
    explicitly (e.g. ``redis://aims-redis:6379``), so this only changes
    behavior for local/test runs that leave it unset. Tests point it at an
    isolated Redis DB instead of the shared production DB 0 (``aims-redis``
    publishes to ``127.0.0.1:6379``, so an unqualified ``localhost:6379``
    from a host-side test process is the same instance live containers
    publish/subscribe on). Uses the same env var name as
    ``argus_eventbus_bridge.get_event_bus()`` so both resolve to the same
    target even when the two modules are dual-imported under different
    dotted paths (``ops.logi.event_bus`` vs ``logi.event_bus``), which would
    otherwise give each its own singleton pointed at a different DB.
    """
    global _bus_instance

    if redis_url is None:
        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")

    if not _bus_instance:
        _bus_instance = EventBus(redis_url)
        await _bus_instance.connect()
    elif _bus_instance.redis_client is None:
        # A prior caller disconnected this singleton (e.g. end-of-test
        # cleanup); reconnect instead of silently degrading every
        # subsequent publish/read to the empty in-memory fallback.
        await _bus_instance.connect()

    return _bus_instance


async def reset_bus_instance() -> None:
    """Reset the global EventBus singleton (for testing)."""
    global _bus_instance
    if _bus_instance:
        await _bus_instance.disconnect()
    _bus_instance = None


if __name__ == "__main__":
    # Quick test
    async def test():
        bus = await get_bus()

        # Define a handler
        async def handle_repair_success(event: Event):
            print(f"✓ Repair succeeded: {event.data.get('task_id')}")

        # Subscribe
        await bus.subscribe(EventType.REPAIR_SUCCEEDED, handle_repair_success)

        # Publish
        event = Event(
            event_type=EventType.REPAIR_SUCCEEDED,
            source="repairman",
            timestamp=datetime.utcnow(),
            severity=EventSeverity.INFO,
            data={"task_id": "task_123", "fix_applied": "restart_service"},
        )
        await bus.publish(event)

        # Let handlers run
        await asyncio.sleep(1)

        # Check stats
        stats = await bus.get_event_stats()
        print(f"Event stats: {stats}")

        await bus.disconnect()

    asyncio.run(test())
