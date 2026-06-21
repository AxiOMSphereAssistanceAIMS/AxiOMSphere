"""Learning Loop Consumer — consume EventBus events and trigger learning.

Listens to:
- learning_need_created → FailureLearningLoop
- training_complete → OptimizationLoop
- model_deployed → MetaLearningEngine
- multiple_successes → SkillFusionEngine

Bridges Phase 5 orchestration with Phase 2B learning loops.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

from ops.logi.event_bus import (
    EventBus,
    Event,
    EventType,
    EventSeverity,
    get_bus,
)

# Import Phase 2B learning loops (lazy)
_learning_loops_available = False
try:
    from ops.ecc_core.learning_loops import (
        FailureLearningLoop,
        OptimizationLoop,
        MetaLearningEngine,
        SkillFusionEngine,
    )
    _learning_loops_available = True
except ImportError:
    pass


_DEFAULT_STATE_DIR = Path(
    os.environ.get(
        "AIMS_ECC_STATE_DIR",
        Path(__file__).resolve().parent.parent.parent / "aims_workspace" / "ecc_learning_state",
    )
)


class LearningLoopConsumer:
    """Consume EventBus learning events and trigger loops."""

    def __init__(self, bus: EventBus, state_dir: Path | None = None):
        self.bus = bus
        self.state_dir = Path(state_dir) if state_dir else _DEFAULT_STATE_DIR

        # Initialize learning engines — load persisted state if available
        if _learning_loops_available:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            self.failure_loop = FailureLearningLoop.load(self.state_dir / "failure_patterns.json")
            self.optimization_loop = OptimizationLoop.load(self.state_dir / "optimization_candidates.json")
            self.meta_learning = MetaLearningEngine.load(self.state_dir / "meta_strategies.json")
            self.skill_fusion = SkillFusionEngine.load(self.state_dir / "fusion_proposals.json")
        else:
            print("⚠ Learning loops not available (Phase 2B not installed)")
            self.failure_loop = None
            self.optimization_loop = None
            self.meta_learning = None
            self.skill_fusion = None

    async def subscribe_to_learning_events(self):
        """Register handlers for all learning events."""
        # Listen to Traini events
        await self.bus.subscribe(
            EventType.TRAINING_REQUESTED,
            self._handle_traini_event,
        )

        # Listen to Repair events
        await self.bus.subscribe(
            EventType.REPAIR_SUCCEEDED,
            self._handle_repair_success,
        )

        # Listen to Training completion
        await self.bus.subscribe(
            EventType.TRAINING_COMPLETED,
            self._handle_training_complete,
        )

    def _save_state(self) -> None:
        """Persist all learning loop state to disk."""
        if not _learning_loops_available:
            return
        try:
            if self.failure_loop:
                self.failure_loop.save(self.state_dir / "failure_patterns.json")
            if self.optimization_loop:
                self.optimization_loop.save(self.state_dir / "optimization_candidates.json")
            if self.meta_learning:
                self.meta_learning.save(self.state_dir / "meta_strategies.json")
            if self.skill_fusion:
                self.skill_fusion.save(self.state_dir / "fusion_proposals.json")
        except Exception as e:
            print(f"⚠ Failed to save learning loop state: {e}")

    async def _handle_traini_event(self, event: Event):
        """Handle Traini loop events."""
        traini_type = event.data.get("traini_event_type")

        if traini_type == "learning_need_created":
            await self._process_learning_need(event)
        elif traini_type == "loop_complete":
            await self._process_loop_complete(event)

    async def _process_learning_need(self, event: Event):
        """Process learning need from Traini loop.

        Triggers FailureLearningLoop to:
        - Identify failure patterns
        - Suggest fixes
        - Track frequency
        """
        if not self.failure_loop:
            return

        data = event.data
        incident_id = data.get("incident_id")
        incident_type = data.get("incident_type")
        correction = data.get("correction_applied")

        print(f"📚 Learning from {incident_type} incident {incident_id}")
        print(f"   Correction: {correction}")

        # Analyze this single incident as a failure pattern
        failure_events = [
            {
                "event_type": "skill_failure",
                "payload": {
                    "skill_id": f"repair_{incident_type}",
                    "error_category": incident_type,
                    "incident_id": incident_id,
                    "correction": correction,
                },
            }
        ]

        patterns = self.failure_loop.analyze_failure_events(failure_events)

        if patterns:
            print(f"   📊 Pattern identified: {patterns[0].pattern_id}")
            print(f"   Suggested fix: {patterns[0].suggested_fix}")
            print(f"   Confidence: {patterns[0].confidence:.2f}")
            self._save_state()

    async def _process_loop_complete(self, event: Event):
        """Process completed Traini loop result.

        If ACCEPT: trigger OptimizationLoop to suggest further improvements.
        """
        if not self.optimization_loop:
            return

        data = event.data
        run_id = data.get("run_id")
        verdict = data.get("final_verdict")

        print(f"🔄 Traini loop complete: {run_id}")
        print(f"   Verdict: {verdict}")

        if verdict == "ACCEPT":
            print(f"   ✅ Accepted — triggering optimization loop")
            # Publish training_requested event to trigger next phase
            try:
                training_event = Event(
                    event_type=EventType.TRAINING_REQUESTED,
                    source="learning_loop_consumer",
                    timestamp=datetime.now(UTC),
                    severity=EventSeverity.INFO,
                    data={
                        "training_source": "traini_loop_accepted",
                        "run_id": run_id,
                        "iterations_used": data.get("iterations_used"),
                        "total_evidence_size": data.get("total_evidence_size"),
                    },
                )
                await self.bus.publish(training_event)
            except Exception as e:
                print(f"⚠ Failed to publish training_requested event: {e}")
            self._save_state()

    async def _handle_repair_success(self, event: Event):
        """Handle successful repair completion.

        Triggers learning from repair patterns.
        """
        if not self.failure_loop:
            return

        data = event.data
        task_id = data.get("task_id")
        fix = data.get("fix")

        print(f"🔧 Repair success: {task_id}")
        print(f"   Fix applied: {fix}")

        # Could trigger SkillFusionEngine to suggest combining repair skills

    async def _handle_training_complete(self, event: Event):
        """Handle training completion.

        Triggers MetaLearningEngine to learn from training outcomes.
        """
        if not self.meta_learning:
            return

        data = event.data
        task_id = data.get("task_id")
        eval_score = data.get("eval_score")

        print(f"🎓 Training complete: {task_id}")
        print(f"   Eval score: {eval_score}")

        # MetaLearningEngine could suggest next training direction


async def create_learning_loop_consumer(redis_url: str | None = None) -> Optional[LearningLoopConsumer]:
    """Create and initialize learning loop consumer."""
    try:
        import os
        url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        bus = await get_bus(url)
        if not bus:
            return None

        consumer = LearningLoopConsumer(bus)
        await consumer.subscribe_to_learning_events()
        return consumer
    except Exception as e:
        print(f"⚠ Failed to create learning loop consumer: {e}")
        return None


if __name__ == "__main__":
    # Test
    async def test():
        print("Testing Learning Loop Consumer...")

        consumer = await create_learning_loop_consumer()
        if not consumer:
            print("⚠ Consumer creation failed")
            return

        print("✓ Consumer initialized and subscribed")

        # Simulate learning need event
        from logi.traini_eventbus_bridge import publish_learning_need

        result = await publish_learning_need(
            incident_id="inc_test_001",
            incident_type="timeout",
            correction_applied="Increased timeout from 30s to 45s",
            severity="warning",
        )
        print(f"Learning need published: {result}")

        await asyncio.sleep(1)

        await consumer.bus.disconnect()

    asyncio.run(test())
