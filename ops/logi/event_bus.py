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
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from typing import Dict, List, Callable, Any, Optional

import redis.asyncio as redis


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
    TASK_COMPLETED = "task.completed"

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
        """Close Redis connection and cleanup."""
        if self.pubsub:
            await self.pubsub.close()
        if self.redis_client:
            await self.redis_client.close()

    # ============ Publishing ============

    async def publish(self, event: Event) -> bool:
        """Publish an event to the bus."""
        channel = f"event:{event.event_type.value}"
        payload = json.dumps(event.to_dict())

        if self.redis_client:
            try:
                await self.redis_client.publish(channel, payload)
                # Also store in ledger for auditing
                ledger_key = f"event_ledger:{event.event_type.value}"
                await self.redis_client.lpush(ledger_key, payload)
                # Keep last 1000 events per type
                await self.redis_client.ltrim(ledger_key, 0, 999)
                return True
            except Exception as e:
                print(f"⚠ Redis publish failed: {e}")

        # Fallback: call local handlers
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

        # If Redis is available, start listening
        if self.redis_client:
            # Start a background task to listen on this channel
            channel = f"event:{event_type.value}"
            asyncio.create_task(self._redis_listen(channel, handler))

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
        """Listen to a Redis channel and call handler."""
        if not self.redis_client:
            return

        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe(channel)

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
                events = [Event.from_dict(json.loads(item)) for item in data]
                return list(reversed(events))  # newest first
            except Exception as e:
                print(f"⚠ Redis read failed: {e}")

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
                print(f"⚠ Redis scan failed: {e}")

        return stats


# ============ Singleton Instance ============

_bus_instance: Optional[EventBus] = None


async def get_bus(redis_url: str = "redis://localhost:6379") -> EventBus:
    """Get or create the global EventBus instance."""
    global _bus_instance

    if not _bus_instance:
        _bus_instance = EventBus(redis_url)
        await _bus_instance.connect()

    return _bus_instance


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
