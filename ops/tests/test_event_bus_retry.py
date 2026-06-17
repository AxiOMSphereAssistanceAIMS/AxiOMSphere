"""Test EventBus retry behavior on Redis publish failure."""
from __future__ import annotations

import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


def _make_event():
    """Helper: build a minimal Event object."""
    import sys
    sys.path.insert(0, 'ops')
    from logi.event_bus import Event, EventType, EventSeverity

    return Event(
        event_type=EventType.TASK_CREATED,
        source="test",
        timestamp=datetime.utcnow(),
        severity=EventSeverity.INFO,
        data={"data": "value"},
    )


class TestEventBusRetry(unittest.TestCase):
    """Verify EventBus.publish() retries on transient Redis errors."""

    def test_publish_retries_on_redis_error(self):
        """publish() should retry 3 times before giving up."""
        import sys
        sys.path.insert(0, 'ops')
        from logi.event_bus import EventBus

        bus = EventBus.__new__(EventBus)
        bus._handlers = {}

        # Succeed on the 3rd attempt
        redis_mock = MagicMock()
        redis_mock.publish = AsyncMock(side_effect=[
            ConnectionError("refused"),
            ConnectionError("refused"),
            42,  # success on 3rd try
        ])
        redis_mock.lpush = AsyncMock(return_value=1)
        redis_mock.ltrim = AsyncMock(return_value=True)
        bus.redis_client = redis_mock

        async def _run():
            with patch('asyncio.sleep', new_callable=AsyncMock):
                await bus.publish(_make_event())

        asyncio.run(_run())
        assert redis_mock.publish.call_count == 3

    def test_publish_falls_back_after_max_retries(self):
        """After 3 failures, falls back to local handler dispatch."""
        import sys
        sys.path.insert(0, 'ops')
        from logi.event_bus import EventBus, EventType

        bus = EventBus.__new__(EventBus)
        handler = AsyncMock()
        bus._handlers = {EventType.TASK_CREATED.value: [handler]}
        bus._event_ledger = {}

        redis_mock = MagicMock()
        redis_mock.publish = AsyncMock(side_effect=ConnectionError("down"))
        bus.redis_client = redis_mock

        async def _run():
            with patch('asyncio.sleep', new_callable=AsyncMock):
                await bus.publish(_make_event())

        asyncio.run(_run())
        assert redis_mock.publish.call_count == 3
        handler.assert_called_once()

    def test_publish_succeeds_first_try_no_retry(self):
        """When Redis is healthy, publish() completes on first attempt."""
        import sys
        sys.path.insert(0, 'ops')
        from logi.event_bus import EventBus

        bus = EventBus.__new__(EventBus)
        bus._handlers = {}

        redis_mock = MagicMock()
        redis_mock.publish = AsyncMock(return_value=1)
        redis_mock.lpush = AsyncMock(return_value=1)
        redis_mock.ltrim = AsyncMock(return_value=True)
        bus.redis_client = redis_mock

        asyncio.run(bus.publish(_make_event()))
        assert redis_mock.publish.call_count == 1

    def test_publish_no_redis_goes_straight_to_local(self):
        """With redis_client=None, local handlers are called immediately."""
        import sys
        sys.path.insert(0, 'ops')
        from logi.event_bus import EventBus, EventType

        bus = EventBus.__new__(EventBus)
        bus.redis_client = None
        handler = AsyncMock()
        bus._handlers = {EventType.TASK_CREATED.value: [handler]}
        bus._event_ledger = {}

        asyncio.run(bus.publish(_make_event()))
        handler.assert_called_once()


if __name__ == "__main__":
    unittest.main()
