"""Universal improvement loop orchestration—bi-nested inner/outer cycle.

Inner cycle: 5 stages (initialization, generation, validation, repair-loop with plateau
detection, terminal decision).

Outer cycle: failure aggregation, failure class recurrence detection, capability
modification proposals.
"""
import asyncio
from datetime import datetime
from typing import Any

from ops.docsreg.universal_loop.context import LoopDependencies, UniversalLoopContext
from ops.docsreg.universal_loop.data_retention_validator import (
    DataRetentionValidator,
    RetentionVerdict,
)
from ops.docsreg.universal_loop.evidence import EvidenceStore
from ops.docsreg.universal_loop.result import UniversalLoopResult
from ops.docsreg.universal_loop.stage_result import StageResult, StageOutcome
from ops.docsreg.universal_loop.terminal_state import TerminalState
from ops.docsreg.integration.phase6_orchestration import Phase6OrchestrationLayer


class UniversalImprovementLoop:
    """Orchestrates bi-nested document improvement cycle."""

    QUALITY_TARGET = 0.95
    ASPIRATIONAL_TARGET = 0.98
    QUALITY_PLATEAU_THRESHOLD = 0.02  # 2% delta triggers plateau detection
    MAX_ITERATIONS = 5
    MAX_REPAIRS = 3

    def __init__(
        self, dependencies: LoopDependencies, logger: Any = None, event_bus: Any = None
    ):
        """Initialize loop with injected dependencies."""
        self.dependencies = dependencies
        self.logger = logger
        self.event_bus = event_bus
        self.validator = DataRetentionValidator()
        self.orchestrator = Phase6OrchestrationLayer()

    async def run(
        self,
        document_id: str,
        archetype_type: str,
        content: str,
        max_iterations: int = MAX_ITERATIONS,
        max_repairs: int = MAX_REPAIRS,
    ) -> UniversalLoopResult:
        """Execute universal improvement loop."""
        started_at = datetime.utcnow()

        # Initialize context
        initial_score = await self.dependencies.scorer.score(content, archetype_type)
        context = UniversalLoopContext(
            document_id=document_id,
            archetype_type=archetype_type,
            content=content,
            quality_score=initial_score,
        )

        stage_results = []
        outer_cycle_failures = []

        # Inner cycle: 5 stages repeated up to max_iterations
        for iteration in range(max_iterations):
            context.iteration_count = iteration + 1

            # Stage 1: Initialization
            stage_init = await self._stage_initialization(context)
            stage_results.append(stage_init)
            if stage_init.outcome == StageOutcome.BLOCKED:
                return self._create_result(
                    context, stage_results, TerminalState.INPUT_BLOCKED, started_at
                )

            # Stage 2: Generation
            stage_gen = await self._stage_generation(context)
            stage_results.append(stage_gen)
            if stage_gen.outcome == StageOutcome.FAILURE:
                return self._create_result(
                    context,
                    stage_results,
                    TerminalState.VALIDATION_FAILED,
                    started_at,
                )

            # Stage 3: Validation
            stage_val = await self._stage_validation(context)
            stage_results.append(stage_val)
            if stage_val.outcome == StageOutcome.FAILURE:
                return self._create_result(
                    context,
                    stage_results,
                    TerminalState.VALIDATION_FAILED,
                    started_at,
                )

            # Stage 4: Repair loop (with plateau detection)
            stage_repair = await self._stage_repair_loop(
                context, max_repairs, outer_cycle_failures
            )
            stage_results.append(stage_repair)
            if stage_repair.outcome == StageOutcome.BLOCKED:
                return self._create_result(
                    context,
                    stage_results,
                    TerminalState.REPAIR_REQUIRED,
                    started_at,
                )

            # Check for plateau (no meaningful quality improvement)
            if len(context.quality_history) >= 2:
                recent_delta = (
                    context.quality_history[-1] - context.quality_history[-2]
                )
                if recent_delta < self.QUALITY_PLATEAU_THRESHOLD:
                    outer_cycle_failures.append(
                        f"Iteration {iteration+1}: Quality plateau detected "
                        f"(delta={recent_delta:.4f} < threshold={self.QUALITY_PLATEAU_THRESHOLD})"
                    )
                    return self._create_result(
                        context,
                        stage_results,
                        TerminalState.PLATEAU_DETECTED,
                        started_at,
                    )

            # Stage 5: Terminal decision
            stage_terminal = await self._stage_terminal_decision(context)
            stage_results.append(stage_terminal)

            # Check if we should exit loop
            if context.quality_score >= self.ASPIRATIONAL_TARGET:
                return self._create_result(
                    context,
                    stage_results,
                    TerminalState.QUALITY_TARGET_EXCEEDED,
                    started_at,
                )
            if context.quality_score >= self.QUALITY_TARGET:
                return self._create_result(
                    context,
                    stage_results,
                    TerminalState.READY_FOR_REVIEW,
                    started_at,
                )

        # Max iterations reached without meeting quality target
        return self._create_result(
            context,
            stage_results,
            TerminalState.MAX_ITERATIONS_REACHED,
            started_at,
        )

    async def _stage_initialization(self, context: UniversalLoopContext) -> StageResult:
        """Stage 1: Initialize and validate input."""
        started_at = datetime.utcnow()
        try:
            is_valid, errors = await self.dependencies.validator.validate(
                context.content, context.archetype_type
            )

            if not is_valid:
                context.record_failure(f"Validation errors: {errors}")
                return StageResult(
                    stage_name="initialization",
                    outcome=StageOutcome.FAILURE,
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    quality_before=context.quality_score,
                    quality_after=context.quality_score,
                    content_before=context.content,
                    content_after=context.content,
                    errors=errors,
                    failure_detected=True,
                    failure_class=EvidenceStore.detect_failure_class(
                        str(errors), "VALIDATION_ERROR"
                    ),
                )

            return StageResult(
                stage_name="initialization",
                outcome=StageOutcome.SUCCESS,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                quality_before=context.quality_score,
                quality_after=context.quality_score,
                content_before=context.content,
                content_after=context.content,
            )
        except Exception as e:
            context.record_failure(f"Initialization error: {str(e)}")
            return StageResult(
                stage_name="initialization",
                outcome=StageOutcome.BLOCKED,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                quality_before=context.quality_score,
                quality_after=context.quality_score,
                content_before=context.content,
                content_after=context.content,
                errors=[str(e)],
                failure_detected=True,
                failure_class="UNKNOWN",
            )

    async def _stage_generation(self, context: UniversalLoopContext) -> StageResult:
        """Stage 2: Generate improved content."""
        started_at = datetime.utcnow()
        try:
            gen_context = {
                "iteration": context.iteration_count,
                "previous_quality": context.quality_score,
                "failure_history": context.failure_history[-3:],
            }

            improved = await self.dependencies.generator.generate(
                context.content, context.archetype_type, gen_context
            )

            if not improved or improved == context.content:
                return StageResult(
                    stage_name="generation",
                    outcome=StageOutcome.PARTIAL_SUCCESS,
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    quality_before=context.quality_score,
                    quality_after=context.quality_score,
                    content_before=context.content,
                    content_after=improved or context.content,
                    actions_taken=["generate_attempted_no_change"],
                )

            context.content = improved
            context.record_action("generate")

            return StageResult(
                stage_name="generation",
                outcome=StageOutcome.SUCCESS,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                quality_before=context.quality_score,
                quality_after=context.quality_score,
                content_before=context.content,
                content_after=improved,
                actions_taken=["generate"],
            )
        except Exception as e:
            context.record_failure(f"Generation error: {str(e)}")
            return StageResult(
                stage_name="generation",
                outcome=StageOutcome.FAILURE,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                quality_before=context.quality_score,
                quality_after=context.quality_score,
                content_before=context.content,
                content_after=context.content,
                errors=[str(e)],
                failure_detected=True,
                failure_class=EvidenceStore.detect_failure_class(
                    str(e), type(e).__name__
                ),
            )

    async def _stage_validation(self, context: UniversalLoopContext) -> StageResult:
        """Stage 3: Validate generated content."""
        started_at = datetime.utcnow()
        try:
            is_valid, errors = await self.dependencies.validator.validate(
                context.content, context.archetype_type
            )

            if not is_valid:
                context.validation_failures += 1
                context.record_failure(f"Validation failed: {errors}")
                return StageResult(
                    stage_name="validation",
                    outcome=StageOutcome.FAILURE,
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                    quality_before=context.quality_score,
                    quality_after=context.quality_score,
                    content_before=context.content,
                    content_after=context.content,
                    errors=errors,
                    failure_detected=True,
                    failure_class=EvidenceStore.detect_failure_class(
                        str(errors), "VALIDATION_ERROR"
                    ),
                )

            return StageResult(
                stage_name="validation",
                outcome=StageOutcome.SUCCESS,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                quality_before=context.quality_score,
                quality_after=context.quality_score,
                content_before=context.content,
                content_after=context.content,
            )
        except Exception as e:
            context.record_failure(f"Validation error: {str(e)}")
            return StageResult(
                stage_name="validation",
                outcome=StageOutcome.FAILURE,
                started_at=started_at,
                completed_at=datetime.utcnow(),
                quality_before=context.quality_score,
                quality_after=context.quality_score,
                content_before=context.content,
                content_after=context.content,
                errors=[str(e)],
                failure_detected=True,
                failure_class="UNKNOWN",
            )

    async def _stage_repair_loop(
        self,
        context: UniversalLoopContext,
        max_repairs: int,
        outer_cycle_failures: list[str],
    ) -> StageResult:
        """Stage 4: Repair loop with plateau detection."""
        started_at = datetime.utcnow()

        for repair_attempt in range(max_repairs):
            context.repair_attempts = repair_attempt + 1

            try:
                # Audit content
                diagnostics = await self.dependencies.auditor.audit(
                    context.content, context.archetype_type
                )

                # Detect failure class
                failure_msg = diagnostics.get("issues", "")
                failure_class = EvidenceStore.detect_failure_class(
                    failure_msg, "AUDIT"
                )

                if not failure_msg:
                    # No issues detected
                    break

                # Repair
                before_content = context.content
                before_snapshot = await self.dependencies.snapshot_builder.build(
                    before_content, context.archetype_type
                )

                repaired = await self.dependencies.repair_service.repair(
                    context.content, context.archetype_type, failure_class
                )

                if not repaired or repaired == context.content:
                    # Repair produced no change
                    outer_cycle_failures.append(
                        f"Repair attempt {repair_attempt+1}: No change produced"
                    )
                    continue

                # Validate retention via orchestrator hard gate
                passed_gate, retention_report = self.orchestrator.validate_repair_retention(
                    before_content=before_content,
                    after_content=repaired,
                    archetype_type=context.archetype_type,
                )

                # Hard gate: if retention fails, reject repair candidate
                if not passed_gate:
                    outer_cycle_failures.append(
                        f"Repair attempt {repair_attempt+1}: Data loss {retention_report.get('token_loss_percentage', 0):.2f}% "
                        f"exceeds limit. Lost: {retention_report.get('lost_sections', []) + retention_report.get('lost_required_fields', [])}"
                    )
                    context.record_failure(
                        f"Repair rejected: data retention FAIL"
                    )
                    # Candidate output written to evidence only; active content unchanged
                    continue

                # Retention passed or advisory; accept repair and re-score
                context.content = repaired
                context.record_action(f"repair_attempt_{repair_attempt+1}")

                new_score = await self.dependencies.scorer.score(
                    context.content, context.archetype_type
                )
                context.record_quality(new_score)

                # Check plateau
                if len(context.quality_history) >= 2:
                    recent_delta = (
                        context.quality_history[-1] - context.quality_history[-2]
                    )
                    if recent_delta < self.QUALITY_PLATEAU_THRESHOLD:
                        break

            except Exception as e:
                context.record_failure(f"Repair error: {str(e)}")
                outer_cycle_failures.append(f"Repair attempt {repair_attempt+1}: {str(e)}")

        return StageResult(
            stage_name="repair_loop",
            outcome=StageOutcome.SUCCESS,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            quality_before=context.quality_history[0] if context.quality_history else 0.0,
            quality_after=context.quality_score,
            content_before=context.content,
            content_after=context.content,
            actions_taken=context.actions_executed[-context.repair_attempts:],
        )

    async def _stage_terminal_decision(
        self, context: UniversalLoopContext
    ) -> StageResult:
        """Stage 5: Decide terminal state."""
        started_at = datetime.utcnow()

        # Re-score one final time
        final_score = await self.dependencies.scorer.score(
            context.content, context.archetype_type
        )
        context.record_quality(final_score)

        return StageResult(
            stage_name="terminal_decision",
            outcome=StageOutcome.SUCCESS,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            quality_before=context.quality_history[-2] if len(context.quality_history) >= 2 else 0.0,
            quality_after=final_score,
            content_before=context.content,
            content_after=context.content,
        )

    def _create_result(
        self,
        context: UniversalLoopContext,
        stage_results: list[StageResult],
        terminal_state: TerminalState,
        started_at: datetime,
    ) -> UniversalLoopResult:
        """Create immutable result from execution context."""
        completed_at = datetime.utcnow()
        initial_quality = context.quality_history[0] if context.quality_history else 0.0
        final_quality = context.quality_score

        # Calculate data retention rate (simplified for now)
        data_retention_rate = 100.0
        data_loss_percentage = 0.0

        failure_classes = list(set(sr.failure_class for sr in stage_results if sr.failure_detected))

        result = UniversalLoopResult(
            document_id=context.document_id,
            archetype_type=context.archetype_type,
            terminal_state=terminal_state,
            started_at=started_at,
            completed_at=completed_at,
            quality_initial=initial_quality,
            quality_final=final_quality,
            iterations=context.iteration_count,
            stage_results=stage_results,
            failure_classes=failure_classes,
            failures=context.failure_history,
            actions_executed=context.actions_executed,
            data_retention_rate=data_retention_rate,
            data_loss_percentage=data_loss_percentage,
            terminal_reason=self._get_terminal_reason(terminal_state, context),
        )

        return result

    def _get_terminal_reason(
        self, terminal_state: TerminalState, context: UniversalLoopContext
    ) -> str:
        """Generate human-readable terminal reason."""
        reasons = {
            TerminalState.INPUT_BLOCKED: "Input validation blocked further processing",
            TerminalState.VALIDATION_FAILED: f"Content validation failed after {context.iteration_count} iteration(s)",
            TerminalState.REPAIR_REQUIRED: "Repairs could not resolve issues",
            TerminalState.REPAIR_REJECTED_DATA_LOSS: "Repair candidates rejected due to data loss exceeding threshold",
            TerminalState.PLATEAU_DETECTED: f"Quality plateau detected (delta < {self.QUALITY_PLATEAU_THRESHOLD})",
            TerminalState.MAX_ITERATIONS_REACHED: f"Reached maximum iterations ({context.iteration_count})",
            TerminalState.READY_FOR_REVIEW: f"Quality target {self.QUALITY_TARGET} reached (final={context.quality_score:.4f})",
            TerminalState.QUALITY_TARGET_EXCEEDED: f"Aspirational target {self.ASPIRATIONAL_TARGET} exceeded (final={context.quality_score:.4f})",
            TerminalState.READY_FOR_BEST_VERSION_SELECTION: "Ready for best version selection",
            TerminalState.READY_FOR_REGISTRATION: "Ready for registration (after best-version selection)",
            TerminalState.REGISTRATION_COMPLETED: "Document registered successfully",
            TerminalState.OPERATOR_REVIEW_REQUIRED: "Operator review required",
            TerminalState.SKILL_CREATION_REQUIRED: "Skill creation required",
            TerminalState.POLICY_PATCH_REQUIRED: "Policy patch required",
            TerminalState.TRAINING_DATASET_REQUIRED: "Training dataset required",
            TerminalState.UNKNOWN_FAILURE_REQUIRES_TRIAGE: "Unknown failure requires triage",
        }
        return reasons.get(terminal_state, "Unknown terminal state")


async def run_universal_improvement_loop(
    document_id: str,
    archetype_type: str,
    content: str,
    dependencies: LoopDependencies,
    max_iterations: int = 5,
    max_repairs: int = 3,
    logger: Any = None,
    event_bus: Any = None,
) -> UniversalLoopResult:
    """Entry point for universal improvement loop.

    Args:
        document_id: Unique document identifier
        archetype_type: Document archetype/type
        content: Initial document content
        dependencies: Injected service dependencies
        max_iterations: Maximum outer loop iterations
        max_repairs: Maximum repair attempts per iteration
        logger: Optional logger instance
        event_bus: Optional event bus for status updates

    Returns:
        UniversalLoopResult: Immutable result with full execution trace
    """
    loop = UniversalImprovementLoop(dependencies, logger, event_bus)
    return await loop.run(document_id, archetype_type, content, max_iterations, max_repairs)
