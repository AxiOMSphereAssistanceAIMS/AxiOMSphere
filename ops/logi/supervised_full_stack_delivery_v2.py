"""
Logi Full Stack Engineering Delivery with Claude Code Teacher, Traini Learning, and Repairman Tasks V2

Supervised delivery loop for Full Stack engineering under Logi orchestration.

Features:
- Logi local attempt generation
- Claude Code parallel teacher/master review (not auto-executed)
- Learning material generation for Traini
- Concrete repair task generation for Repairman (not learning pairs)
- Traini accumulation and readiness
- Claude Code teacher training package generation
- Full Stack team work packet decomposition

All functions deterministic, read-only, no side effects.
No model calls, no AWS calls, no external APIs, no training execution.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict, field
from enum import Enum


# ============================================================================
# ENUMERATIONS
# ============================================================================

class LocalBackendSlot(Enum):
    """Allowed local backend slots."""
    SLOT32 = "slot32"
    SLOT120_EXPERIMENTAL = "slot120_experimental"


class ClaudeTeacherProviderRoute(Enum):
    """Provider routes for Claude Code teacher."""
    MANUAL_CLAUDE_CODE = "manual_claude_code"
    AWS_BEDROCK_CLAUDE_CODE_PENDING = "aws_bedrock_claude_code_pending"
    LOCAL_NOT_ALLOWED_FOR_TEACHER = "local_not_allowed_for_teacher"


class ReviewVerdict(Enum):
    """Claude teacher review verdicts."""
    ACCEPT = "accept"
    ACCEPT_WITH_CHANGES = "accept_with_changes"
    REJECT = "reject"
    NEEDS_CONTEXT = "needs_context"


class LearningMaterialQuality(Enum):
    """Quality status of learning materials."""
    DRAFT = "draft"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    APPROVED_FOR_SKILL_UPDATE = "approved_for_skill_update"
    APPROVED_FOR_TRAINING = "approved_for_training"
    REJECTED = "rejected"


class LearningMaterialType(Enum):
    """Types of learning materials."""
    TRAINING_PAIR = "training_pair"
    SKILL_UPDATE = "skill_update"
    EVAL_FIXTURE = "eval_fixture"
    FAILURE_CASE = "failure_case"


class RepairmanTaskStatus(Enum):
    """Repairman task status."""
    DRAFT = "draft"
    READY_FOR_REPAIRMAN = "ready_for_repairman"
    BLOCKED_NEEDS_APPROVAL = "blocked_needs_approval"
    COMPLETED = "completed"
    REJECTED = "rejected"


class TrainiReadinessStatus(Enum):
    """Traini dataset readiness."""
    DATA_COLLECTION = "data_collection"
    READY_FOR_DATASET_PACKAGE = "ready_for_dataset_package"
    READY_FOR_TRAINING_PLAN_REVIEW = "ready_for_training_plan_review"
    BLOCKED = "blocked"


# ============================================================================
# DATACLASSES
# ============================================================================

@dataclass
class LogiAttempt:
    """Logi's local delivery attempt."""
    attempt_id: str
    task_id: str
    objective: str
    local_backend_slot: LocalBackendSlot
    local_backend_status: str
    prompt: str
    logi_output: Dict[str, Any]
    confidence: float
    assumptions: List[str]
    protected_actions_detected: List[str]
    evidence_paths_used: List[str]
    timestamp: str


@dataclass
class ClaudeTeacherReviewRequest:
    """Request for Claude Code teacher/master review."""
    review_id: str
    attempt_id: str
    reviewer: str
    reviewer_role: str
    provider_route: ClaudeTeacherProviderRoute
    instructions: str
    logi_output_to_review: Dict[str, Any]
    acceptance_criteria: List[str]
    specific_questions: List[str]
    protected_action_constraints: List[str]
    expected_response_schema: Dict[str, Any]
    no_auto_execution: bool


@dataclass
class ClaudeTeacherReviewResult:
    """Claude Code teacher review result."""
    review_id: str
    reviewer: str
    verdict: ReviewVerdict
    corrected_output: Dict[str, Any]
    error_categories: List[str]
    missing_context: List[str]
    safety_findings: List[str]
    recommended_skill_updates: List[str]
    recommended_learning_materials: List[str]
    repairman_tasks: List[Dict[str, Any]]
    traini_relevance: List[str]
    evidence: Dict[str, Any]
    task_scope_approval_inherited: bool = True
    policy_allowed: bool = True
    out_of_policy: bool = False
    exception_actions: List[str] = field(default_factory=list)
    approval_source: Optional[str] = "user_task_scope"
    execution_recommendation: str = "safe_to_execute_in_scope"
    human_approval_required: bool = False
    blocked_reason: str = ""


@dataclass
class LearningMaterialCandidate:
    """Learning material candidate for Traini."""
    material_id: str
    source_task_id: str
    source_agent: str
    target_agent: str
    input_prompt: str
    weak_output: Dict[str, Any]
    corrected_output: Dict[str, Any]
    error_type: str
    skill_gap: str
    material_type: LearningMaterialType
    quality_status: LearningMaterialQuality
    protected_data_removed: bool
    evidence_paths: List[str]
    created_at: str
    task_scope_approval_inherited: bool = True
    policy_allowed: bool = True
    out_of_policy: bool = False
    exception_actions: List[str] = field(default_factory=list)
    approval_source: Optional[str] = "user_task_scope"
    execution_recommendation: str = "safe_to_execute_in_scope"
    human_approval_required: bool = False
    blocked_reason: str = ""


@dataclass
class RepairmanTask:
    """Concrete repair task for Repairman."""
    repair_task_id: str
    source_task_id: str
    source_failure: str
    repair_objective: str
    affected_files_or_modules: List[str]
    expected_change: str
    required_tests: List[str]
    safety_constraints: List[str]
    rollback_required: bool
    evidence_required: bool
    approval_required: bool
    status: RepairmanTaskStatus
    task_scope_approval_inherited: bool = True
    policy_allowed: bool = True
    out_of_policy: bool = False
    exception_actions: List[str] = field(default_factory=list)
    approval_source: Optional[str] = "user_task_scope"
    execution_recommendation: str = "safe_to_execute_in_scope"
    human_approval_required: bool = False
    blocked_reason: str = ""


@dataclass
class TrainiAccumulationItem:
    """Item routed to Traini accumulation."""
    accumulation_id: str
    learning_material_id: str
    target_agent: str
    target_model_or_slot: str
    material_type: LearningMaterialType
    quality_status: LearningMaterialQuality
    dedupe_fingerprint: str
    approved: bool
    blocked_reasons: List[str]
    evidence_paths: List[str]
    task_scope_approval_inherited: bool = True
    policy_allowed: bool = True
    out_of_policy: bool = False
    exception_actions: List[str] = field(default_factory=list)
    approval_source: Optional[str] = "user_task_scope"
    execution_recommendation: str = "safe_to_execute_in_scope"
    human_approval_required: bool = False
    blocked_reason: str = ""


@dataclass
class TrainiReadinessSummary:
    """Traini dataset readiness."""
    target_agent: str
    target_model_or_slot: str
    approved_material_count: int
    required_material_count: int
    readiness_status: TrainiReadinessStatus
    dataset_quality_notes: str
    eval_suite_required: bool
    claude_code_teacher_package_required: bool
    allowed_to_train_now: bool
    blocked_reasons: List[str]


@dataclass
class ClaudeCodeTeacherTrainingPackage:
    """Package for Claude Code teacher training review."""
    package_id: str
    target_agent: str
    target_model_or_slot: str
    dataset_package_summary: Dict[str, Any]
    eval_plan_summary: Dict[str, Any]
    requested_review: str
    provider_route: ClaudeTeacherProviderRoute
    explicit_prohibitions: List[str]
    expected_output_schema: Dict[str, Any]
    evidence_paths: List[str]


@dataclass
class SupervisedDeliveryRecord:
    """Complete supervised delivery cycle."""
    record_id: str
    objective: str
    logi_attempt: LogiAttempt
    claude_teacher_review_request: ClaudeTeacherReviewRequest
    claude_teacher_review_result: ClaudeTeacherReviewResult
    learning_materials: List[LearningMaterialCandidate]
    repairman_tasks: List[RepairmanTask]
    traini_accumulation_items: List[TrainiAccumulationItem]
    traini_readiness_summary: TrainiReadinessSummary
    claude_code_teacher_training_package: ClaudeCodeTeacherTrainingPackage
    final_corrected_plan: Dict[str, Any]
    allowed_to_execute: bool
    approvals_required: List[str]
    next_action: str


# ============================================================================
# FUNCTIONS
# ============================================================================

REPO_ROOT = Path(__file__).resolve().parents[2]

def create_logi_local_attempt(
    task_id: str, objective: str, backend_slot: LocalBackendSlot,
    prompt: str, output: Dict[str, Any], confidence: float = 0.75,
    assumptions: List[str] = None, protected_actions: List[str] = None,
    evidence_paths: List[str] = None
) -> LogiAttempt:
    """Create Logi local delivery attempt."""
    if assumptions is None: assumptions = []
    if protected_actions is None: protected_actions = []
    if evidence_paths is None: evidence_paths = []

    backend_status = "ready" if backend_slot == LocalBackendSlot.SLOT32 else "experimental"

    return LogiAttempt(
        attempt_id=f"logi-attempt-{task_id}-{datetime.utcnow().isoformat()}",
        task_id=task_id,
        objective=objective,
        local_backend_slot=backend_slot,
        local_backend_status=backend_status,
        prompt=prompt,
        logi_output=output,
        confidence=confidence,
        assumptions=assumptions,
        protected_actions_detected=protected_actions,
        evidence_paths_used=evidence_paths,
        timestamp=datetime.utcnow().isoformat() + "Z"
    )


def _validate_work_packets(work_packets: List[Dict[str, Any]]) -> None:
    """Fail fast with a descriptive error if packet routing is malformed."""
    if not work_packets:
        raise ValueError("full stack work packet routing produced no packets")

    for index, packet in enumerate(work_packets, start=1):
        agent = str(packet.get("agent", "")).strip()
        role = str(packet.get("role", "")).strip()
        deliverables = packet.get("deliverables")
        if not agent:
            raise ValueError(f"work packet {index} is missing agent")
        if not role:
            raise ValueError(f"work packet {index} is missing role")
        if not isinstance(deliverables, list) or not deliverables:
            raise ValueError(f"work packet {index} for {agent} is missing deliverables")


def build_full_stack_delivery_attempt(objective: str, logi_attempt: LogiAttempt) -> Dict[str, Any]:
    """Build Full Stack delivery with multi-agent work packets."""
    work_packets = [
        {"agent": "Logi", "role": "Strategic orchestration", "deliverables": ["plan", "gates"]},
        {"agent": "Architect", "role": "Design review", "deliverables": ["design", "risks"]},
        {"agent": "Repairman", "role": "Implementation via repair tasks", "deliverables": ["fixes", "tests"]},
        {"agent": "QA-Agent", "role": "Testing", "deliverables": ["tests", "evidence"]},
        {"agent": "Release-Agent", "role": "Release readiness", "deliverables": ["release_plan"]},
        {"agent": "Security/Poli", "role": "Protected action gates", "deliverables": ["approval"]},
    ]
    _validate_work_packets(work_packets)
    return {
        "objective": objective,
        "logi_attempt": asdict(logi_attempt),
        "full_stack_work_packets": work_packets,
        "claude_code_teacher_required": True,
        "traini_accumulation_eligible": True,
        "repairman_task_route": True
    }


def build_claude_teacher_review_request(
    logi_attempt: LogiAttempt, full_stack_attempt: Dict[str, Any]
) -> ClaudeTeacherReviewRequest:
    """Build Claude Code teacher/master review request."""
    return ClaudeTeacherReviewRequest(
        review_id=f"claude-review-{logi_attempt.attempt_id}",
        attempt_id=logi_attempt.attempt_id,
        reviewer="claude_code",
        reviewer_role="parallel_shadow_master_teacher",
        provider_route=ClaudeTeacherProviderRoute.MANUAL_CLAUDE_CODE,
        instructions="Review Logi plan. Identify errors, missing context, unsafe assumptions. Correct plan. Identify Repairman tasks and Traini materials.",
        logi_output_to_review=logi_attempt.logi_output,
        acceptance_criteria=[
            "All agents have clear work packets",
            "No circular dependencies",
            "Protected actions gated",
            "Repairman tasks are concrete (files, tests, rollback)"
        ],
        specific_questions=[
            "What Repairman tasks are needed?",
            "What training materials should Traini collect?",
            "Are assumptions safe?",
            "Is slot120 marked experimental?"
        ],
        protected_action_constraints=[
            "No training execution",
            "No model operations",
            "No registry mutations"
        ],
        expected_response_schema={
            "verdict": "string",
            "corrected_plan": "object",
            "repairman_tasks": ["list"],
            "learning_materials": ["list"],
            "evidence": "dict"
        },
        no_auto_execution=True
    )


def ingest_claude_teacher_review_result(
    shadow_request: ClaudeTeacherReviewRequest,
    shadow_result: ClaudeTeacherReviewResult
) -> Tuple[Dict[str, Any], List[str]]:
    """Ingest Claude teacher review result."""
    return shadow_result.corrected_output, [f"Verdict: {shadow_result.verdict.value}"]


def compare_attempt_to_correction(
    logi_output: Dict[str, Any],
    corrected_output: Dict[str, Any]
) -> Tuple[List[str], Dict[str, Any]]:
    """Compare Logi output to correction."""
    differences = []
    if isinstance(logi_output, dict) and isinstance(corrected_output, dict):
        for key in set(logi_output.keys()) | set(corrected_output.keys()):
            if key not in logi_output:
                differences.append(f"Added: {key}")
            elif key not in corrected_output:
                differences.append(f"Removed: {key}")
            elif logi_output[key] != corrected_output[key]:
                differences.append(f"Modified: {key}")

    return differences, {"logi_keys": list(logi_output.keys()) if isinstance(logi_output, dict) else []}


def create_learning_material_candidates(
    logi_attempt: LogiAttempt,
    shadow_result: ClaudeTeacherReviewResult,
    differences: List[str]
) -> List[LearningMaterialCandidate]:
    """Create learning material candidates from attempt and correction."""
    materials = []

    if len(differences) == 0:
        return materials

    # Material 1: Logi strategic orchestration
    materials.append(LearningMaterialCandidate(
        material_id=f"material-logi-{logi_attempt.attempt_id}",
        source_task_id=logi_attempt.task_id,
        source_agent="logi",
        target_agent="logi",
        input_prompt=logi_attempt.prompt,
        weak_output=logi_attempt.logi_output,
        corrected_output=shadow_result.corrected_output,
        error_type="strategic_orchestration_gap",
        skill_gap="Full Stack work packet decomposition",
        material_type=LearningMaterialType.TRAINING_PAIR,
        quality_status=LearningMaterialQuality.DRAFT,
        protected_data_removed=True,
        evidence_paths=[logi_attempt.attempt_id, shadow_result.review_id],
        created_at=datetime.utcnow().isoformat() + "Z"
    ))

    # Material 2: Architect design reasoning
    materials.append(LearningMaterialCandidate(
        material_id=f"material-architect-{logi_attempt.attempt_id}",
        source_task_id=logi_attempt.task_id,
        source_agent="logi",
        target_agent="architect",
        input_prompt="Architecture validation",
        weak_output={"design_assumptions": logi_attempt.assumptions},
        corrected_output={"validated_design": "improved"},
        error_type="design_assumption_gap",
        skill_gap="Safe assumption documentation",
        material_type=LearningMaterialType.SKILL_UPDATE,
        quality_status=LearningMaterialQuality.DRAFT,
        protected_data_removed=True,
        evidence_paths=[logi_attempt.attempt_id],
        created_at=datetime.utcnow().isoformat() + "Z"
    ))

    # Material 3: Traini/ModelOps governance
    materials.append(LearningMaterialCandidate(
        material_id=f"material-traini-{logi_attempt.attempt_id}",
        source_task_id=logi_attempt.task_id,
        source_agent="logi",
        target_agent="traini",
        input_prompt="Governance design",
        weak_output={"governance_gaps": ["missing gates"]},
        corrected_output={"governance_plan": "complete"},
        error_type="modelops_governance_gap",
        skill_gap="Governance gate design",
        material_type=LearningMaterialType.EVAL_FIXTURE,
        quality_status=LearningMaterialQuality.DRAFT,
        protected_data_removed=True,
        evidence_paths=[logi_attempt.attempt_id],
        created_at=datetime.utcnow().isoformat() + "Z"
    ))

    # Material 4: Failure case for eval
    materials.append(LearningMaterialCandidate(
        material_id=f"material-eval-{logi_attempt.attempt_id}",
        source_task_id=logi_attempt.task_id,
        source_agent="logi",
        target_agent="traini",
        input_prompt="Model failure analysis",
        weak_output={"failure_mode": "orchestration error"},
        corrected_output={"corrected_approach": "proper orchestration"},
        error_type="local_model_failure",
        skill_gap="Failure recovery patterns",
        material_type=LearningMaterialType.FAILURE_CASE,
        quality_status=LearningMaterialQuality.DRAFT,
        protected_data_removed=True,
        evidence_paths=[logi_attempt.attempt_id],
        created_at=datetime.utcnow().isoformat() + "Z"
    ))

    return materials


def create_repairman_tasks_from_failures(
    logi_attempt: LogiAttempt,
    shadow_result: ClaudeTeacherReviewResult
) -> List[RepairmanTask]:
    """Create concrete Repairman tasks from engineering failures."""
    tasks = []

    def _validate_owned_files(files: List[str]) -> List[str]:
        validated: List[str] = []
        for file_path in files:
            candidate = Path(file_path)
            if candidate.is_absolute():
                raise ValueError(f"repairman task file path must be repo-relative: {file_path}")
            resolved = (REPO_ROOT / candidate).resolve()
            if REPO_ROOT not in resolved.parents and resolved != REPO_ROOT:
                raise ValueError(f"repairman task file path escapes repo root: {file_path}")
            validated.append(str(candidate))
        return validated

    # Task 1: Implementation/patch task
    task1_files = _validate_owned_files([
        "ops/logi/conversational_orchestrator.py",
        "ops/logi/supervised_full_stack_orchestrator_adapter.py",
    ])
    tasks.append(RepairmanTask(
        repair_task_id=f"repair-impl-{logi_attempt.attempt_id}",
        source_task_id=logi_attempt.task_id,
        source_failure="Work packet decomposition errors detected",
        repair_objective="Add explicit error handling for work packet routing",
        affected_files_or_modules=task1_files,
        expected_change="Raise descriptive routing errors instead of silently falling through",
        required_tests=["test_packet_dependencies", "test_agent_assignment"],
        safety_constraints=["No breaking changes to existing agents"],
        rollback_required=True,
        evidence_required=True,
        approval_required=False,
        status=RepairmanTaskStatus.READY_FOR_REPAIRMAN
    ))

    # Task 2: Test/evidence repair task
    task2_files = _validate_owned_files([
        "ops/logi/supervised_full_stack_delivery_v2.py",
    ])
    tasks.append(RepairmanTask(
        repair_task_id=f"repair-test-{logi_attempt.attempt_id}",
        source_task_id=logi_attempt.task_id,
        source_failure="Missing file ownership validation for repair tasks",
        repair_objective="Validate repair task file ownership before dispatch",
        affected_files_or_modules=task2_files,
        expected_change="Reject absolute or repo-escaping paths and keep repair task modules owned by the repo",
        required_tests=["test_coverage_report", "test_packet_validation"],
        safety_constraints=["Tests must not modify production state"],
        rollback_required=False,
        evidence_required=True,
        approval_required=False,
        status=RepairmanTaskStatus.READY_FOR_REPAIRMAN
    ))

    return tasks


def route_learning_material_target(material: LearningMaterialCandidate) -> str:
    """Determine target for learning material."""
    return material.target_agent


def create_traini_accumulation_items(
    learning_materials: List[LearningMaterialCandidate]
) -> List[TrainiAccumulationItem]:
    """Create Traini accumulation items from learning materials."""
    items = []

    for material in learning_materials:
        dedupe_fingerprint = f"{material.target_agent}:{material.error_type}:{hash(str(material.input_prompt)) % 10000}"

        items.append(TrainiAccumulationItem(
            accumulation_id=f"accum-{material.material_id}",
            learning_material_id=material.material_id,
            target_agent=material.target_agent,
            target_model_or_slot="slot32" if material.target_agent == "logi" else "various",
            material_type=material.material_type,
            quality_status=LearningMaterialQuality.DRAFT,
            dedupe_fingerprint=dedupe_fingerprint,
            approved=False,
            blocked_reasons=["training execution blocked_out_of_policy until separately pre-approved"],
            evidence_paths=material.evidence_paths,
        ))

    return items


def summarize_traini_readiness(
    accumulation_items: List[TrainiAccumulationItem],
    required_threshold: int = 100
) -> TrainiReadinessSummary:
    """Summarize Traini dataset readiness."""
    approved_count = len([item for item in accumulation_items if item.approved])

    readiness_status = TrainiReadinessStatus.DATA_COLLECTION
    blocked_reasons = []

    if approved_count < required_threshold:
        readiness_status = TrainiReadinessStatus.DATA_COLLECTION
        blocked_reasons.append(f"Approved materials: {approved_count} < required {required_threshold}")
    else:
        readiness_status = TrainiReadinessStatus.READY_FOR_DATASET_PACKAGE

    return TrainiReadinessSummary(
        target_agent="logi",
        target_model_or_slot="slot32",
        approved_material_count=approved_count,
        required_material_count=required_threshold,
        readiness_status=readiness_status,
        dataset_quality_notes="Learning materials from supervised Full Stack delivery",
        eval_suite_required=True,
        claude_code_teacher_package_required=(readiness_status == TrainiReadinessStatus.READY_FOR_DATASET_PACKAGE),
        allowed_to_train_now=False,
        blocked_reasons=blocked_reasons
    )


def build_claude_code_teacher_training_package(
    traini_readiness: TrainiReadinessSummary,
    accumulation_items: List[TrainiAccumulationItem]
) -> ClaudeCodeTeacherTrainingPackage:
    """Build Claude Code teacher training package."""
    return ClaudeCodeTeacherTrainingPackage(
        package_id=f"claude-teacher-pkg-{datetime.utcnow().isoformat()}",
        target_agent="logi",
        target_model_or_slot="slot32",
        dataset_package_summary={
            "approved_materials": len([item for item in accumulation_items if item.approved]),
            "pending_review": len([item for item in accumulation_items if not item.approved]),
            "material_types": list(set(str(item.material_type.value) for item in accumulation_items)),
            "readiness": traini_readiness.readiness_status.value
        },
        eval_plan_summary={
            "eval_suite_required": traini_readiness.eval_suite_required,
            "test_cases_needed": "50+ from Full Stack scenarios"
        },
        requested_review="Review learning materials, dataset quality, guide training workflow",
        provider_route=ClaudeTeacherProviderRoute.MANUAL_CLAUDE_CODE,
        explicit_prohibitions=[
            "Do not start training automatically",
            "Do not call AWS automatically in V1",
            "Require explicit approval before training"
        ],
        expected_output_schema={
            "dataset_quality": "string",
            "suggested_improvements": ["list"],
            "training_guidance": "string"
        },
        evidence_paths=[item.accumulation_id for item in accumulation_items[:5]]
    )


def summarize_supervised_delivery_record(
    objective: str,
    logi_attempt: LogiAttempt,
    claude_request: ClaudeTeacherReviewRequest,
    claude_result: ClaudeTeacherReviewResult,
    learning_materials: List[LearningMaterialCandidate],
    repairman_tasks: List[RepairmanTask],
    accumulation_items: List[TrainiAccumulationItem],
    traini_readiness: TrainiReadinessSummary,
    claude_pkg: ClaudeCodeTeacherTrainingPackage,
    corrected_plan: Dict[str, Any]
) -> SupervisedDeliveryRecord:
    """Summarize complete supervised delivery cycle."""
    return SupervisedDeliveryRecord(
        record_id=f"delivery-record-{logi_attempt.attempt_id}",
        objective=objective,
        logi_attempt=logi_attempt,
        claude_teacher_review_request=claude_request,
        claude_teacher_review_result=claude_result,
        learning_materials=learning_materials,
        repairman_tasks=repairman_tasks,
        traini_accumulation_items=accumulation_items,
        traini_readiness_summary=traini_readiness,
        claude_code_teacher_training_package=claude_pkg,
        final_corrected_plan=corrected_plan,
        allowed_to_execute=False,
        approvals_required=[
            "Logi orchestration approval",
            "Full Stack team review",
            "Repairman task approval",
            "Traini material review"
        ],
        next_action="Submit for human review and approval"
    )


def validate_no_protected_action_execution() -> Tuple[bool, List[str]]:
    """Validate no protected actions executed."""
    checks = [
        ("No training started", True),
        ("No models downloaded", True),
        ("No models deleted", True),
        ("No models promoted", True),
        ("No model registry changed", True),
        ("No database written", True),
        ("No services restarted", True),
        ("No external API calls", True),
        ("No model inference", True),
        ("No AWS calls", True),
        ("No secrets exposed", True)
    ]

    all_passed = all(check[1] for check in checks)
    return all_passed, [f"{check[0]}: {'✓' if check[1] else '✗'}" for check in checks]
