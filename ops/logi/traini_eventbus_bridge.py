"""Traini Loop Runner → EventBus Bridge — unified learning coordination.

Connects Traini Claude Review Loop with EventBus:
- Loop runner events → EventBus (for visibility)
- EventBus learning needs → Traini processing queue
- Incident corrections → Training data + learning loops

This completes the self-improving cycle:
Incident → Detect → Analyze → Correct → Learn → Train → Deploy → Better Handling
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, UTC
from typing import Optional, Dict, Any

from ops.logi.event_bus import (
    EventBus,
    Event,
    EventType,
    EventSeverity,
    get_bus,
)


async def publish_traini_event(
    event_type: str,  # "baseline_created", "loop_started", "candidate_tested", "loop_complete"
    source: str,      # "traini_loop_runner"
    data: Dict[str, Any],
) -> bool:
    """Publish Traini loop event to EventBus.

    Args:
        event_type: Event category
        source: Origin (usually "traini_loop_runner")
        data: Event payload

    Returns:
        True if published, False otherwise
    """
    try:
        bus = await get_bus()
        if not bus:
            return False

        # Map Traini event to EventBus event type
        # For now, use TRAINING_REQUESTED as catch-all (will add specific types)
        eb_event_type = EventType.TRAINING_REQUESTED

        event = Event(
            event_type=eb_event_type,
            source=source,
            timestamp=datetime.now(UTC),
            severity=EventSeverity.INFO,
            data={
                "traini_event_type": event_type,
                **data,
            },
        )

        await bus.publish(event)
        return True
    except Exception as e:
        print(f"⚠ Traini EventBus publish failed: {e}")
        return False


async def publish_baseline_created(
    baseline_name: str,
    model_slot: str,
    eval_score: float,
    eval_suite: str,
) -> bool:
    """Publish baseline model creation event."""
    return await publish_traini_event(
        event_type="baseline_created",
        source="traini_loop_runner",
        data={
            "baseline_name": baseline_name,
            "model_slot": model_slot,
            "eval_score": eval_score,
            "eval_suite": eval_suite,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


async def publish_loop_started(
    run_id: str,
    baseline_name: str,
    candidate_name: str,
    objective: str,
    max_iterations: int = 3,
) -> bool:
    """Publish loop start event."""
    return await publish_traini_event(
        event_type="loop_started",
        source="traini_loop_runner",
        data={
            "run_id": run_id,
            "baseline_name": baseline_name,
            "candidate_name": candidate_name,
            "objective": objective,
            "max_iterations": max_iterations,
        },
    )


async def publish_candidate_tested(
    run_id: str,
    iteration: int,
    verdict: str,  # "ACCEPT", "RETUNE", "CONTINUE"
    confidence: float,
    delta_expected: float,
    delta_observed: float,
) -> bool:
    """Publish candidate evaluation result."""
    return await publish_traini_event(
        event_type="candidate_tested",
        source="traini_loop_runner",
        data={
            "run_id": run_id,
            "iteration": iteration,
            "verdict": verdict,
            "confidence": confidence,
            "delta_expected": delta_expected,
            "delta_observed": delta_observed,
            "progress_detected": delta_observed >= delta_expected * 0.8,
        },
    )


async def publish_loop_complete(
    run_id: str,
    final_verdict: str,  # "ACCEPT", "RETUNE"
    iterations_used: int,
    total_evidence_size_bytes: int,
) -> bool:
    """Publish loop completion event."""
    return await publish_traini_event(
        event_type="loop_complete",
        source="traini_loop_runner",
        data={
            "run_id": run_id,
            "final_verdict": final_verdict,
            "iterations_used": iterations_used,
            "total_evidence_size": total_evidence_size_bytes,
            "timestamp_complete": datetime.now(UTC).isoformat(),
        },
    )


async def publish_learning_need(
    incident_id: str,
    incident_type: str,  # "crash", "timeout", "oom", etc.
    correction_applied: str,
    severity: str,  # "critical", "warning"
    learning_priority: int = 50,
) -> bool:
    """Publish learning need (for learning loops to consume).

    Called after Traini loop confirms a fix works, to trigger:
    - FailureLearningLoop (learn pattern)
    - OptimizationLoop (suggest parameter tweaks)
    - SkillFusionEngine (combine skills)
    """
    return await publish_traini_event(
        event_type="learning_need_created",
        source="traini_loop_runner",
        data={
            "incident_id": incident_id,
            "incident_type": incident_type,
            "correction_applied": correction_applied,
            "severity": severity,
            "learning_priority": learning_priority,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


async def subscribe_to_traini_events(
    handler_func,  # async def handler(event: Event) -> None
) -> bool:
    """Subscribe to Traini-related events from EventBus.

    Handler will receive all TRAINING_REQUESTED events with traini_event_type.
    """
    try:
        bus = await get_bus()
        if not bus:
            return False

        await bus.subscribe(EventType.TRAINING_REQUESTED, handler_func)
        return True
    except Exception as e:
        print(f"⚠ Traini EventBus subscribe failed: {e}")
        return False


if __name__ == "__main__":
    # Test
    async def test():
        print("Testing Traini → EventBus bridge...")

        # Publish baseline
        result = await publish_baseline_created(
            baseline_name="qwen3:32b-v15",
            model_slot="32",
            eval_score=0.85,
            eval_suite="golden_v2",
        )
        print(f"Baseline event published: {result}")

        # Publish loop start
        result = await publish_loop_started(
            run_id="test_run_001",
            baseline_name="qwen3:32b-v15",
            candidate_name="qwen3:32b-v16-candidate",
            objective="Improve repair skill accuracy",
            max_iterations=3,
        )
        print(f"Loop start event published: {result}")

        # Simulate iteration
        result = await publish_candidate_tested(
            run_id="test_run_001",
            iteration=1,
            verdict="CONTINUE",
            confidence=0.72,
            delta_expected=0.05,
            delta_observed=0.04,
        )
        print(f"Candidate test event published: {result}")

        # Publish loop complete
        result = await publish_loop_complete(
            run_id="test_run_001",
            final_verdict="ACCEPT",
            iterations_used=2,
            total_evidence_size_bytes=524288,
        )
        print(f"Loop complete event published: {result}")

        # Publish learning need
        result = await publish_learning_need(
            incident_id="inc_020260603_001",
            incident_type="timeout",
            correction_applied="Increased timeout threshold from 30s to 45s",
            severity="warning",
            learning_priority=70,
        )
        print(f"Learning need event published: {result}")

        await asyncio.sleep(0.5)

        # Check EventBus
        bus = await get_bus()
        if bus:
            stats = await bus.get_event_stats()
            print(f"Event stats: {stats}")
            await bus.disconnect()

    asyncio.run(test())
