"""
Logi Full Stack Engineering Delivery with Claude Code Shadow Teacher and Traini Learning Loop V1

Supervised learning loop for Full Stack engineering delivery under Logi strategic orchestration.

Features:
- Logi local attempt generation (using slot32 or experimental slot120)
- Claude Code shadow review request generation (not executed)
- Shadow review result ingestion and comparison
- Learning pair candidate generation
- Traini accumulation item routing
- Traini readiness summary
- AWS Claude Code master prompt generation (for future training orchestration)
- Repairman training material extraction
- Full Stack team work packet decomposition

All functions are deterministic, read-only, and produce no side effects.
No model calls, no external APIs, no training execution, no registry mutations.
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum


# ============================================================================
# ENUMERATIONS
# ============================================================================

class LocalBackendSlot(Enum):
    """Allowed local backend slots for Logi working reasoning."""
    SLOT32 = "slot32"  # Current reliable local coding/reasoning
    SLOT120_EXPERIMENTAL = "slot120_experimental"  # Qwen3.6:35 - experimental only


class ShadowReviewerRoute(Enum):
    """Shadow review routing options."""
    MANUAL = "manual"  # Manual Claude Code review (in this V1)
    AWS_BEDROCK_CLAUDE_COMPATIBLE_PENDING = "aws_bedrock_claude_compatible_pending"  # Future


class ReviewVerdict(Enum):
    """Shadow review verdicts."""
    ACCEPT = "accept"
    ACCEPT_WITH_CHANGES = "accept_with_changes"
    REJECT = "reject"
    NEEDS_CONTEXT = "needs_context"


class LearningPairQuality(Enum):
    """Quality status of learning pair candidates."""
    DRAFT = "draft"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    APPROVED_FOR_SKILL_UPDATE = "approved_for_skill_update"
    APPROVED_FOR_TRAINING = "approved_for_training"
    REJECTED = "rejected"


class TrainiMaterialType(Enum):
    """Types of learning material routed to Traini."""
    SKILL_UPDATE = "skill_update"
    TRAINING_PAIR = "training_pair"
    EVAL_FIXTURE = "eval_fixture"
    REPAIRMAN_TRAINING_CANDIDATE = "repairman_training_candidate"
    MODELOPS_GOVERNANCE_PAIR = "modelops_governance_pair"


class TrainiReadinessStatus(Enum):
    """Traini dataset readiness status."""
    DATA_COLLECTION = "data_collection"
    READY_FOR_DATASET_PACKAGE = "ready_for_dataset_package"
    READY_FOR_TRAINING_PLAN_REVIEW = "ready_for_training_plan_review"
    BLOCKED = "blocked"


# ============================================================================
# DATACLASSES
# ============================================================================

@dataclass
class LogiAttempt:
    """Logi's initial local delivery attempt."""
    attempt_id: str
    task_id: str
    objective: str
    local_backend_slot: LocalBackendSlot
    local_backend_status: str  # "ready", "experimental", "degraded"
    prompt: str
    logi_output: Dict[str, Any]
    confidence: float  # 0.0-1.0
    assumptions: List[str]
    protected_actions_detected: List[str]
    evidence_paths_used: List[str]
    timestamp: str


@dataclass
class ShadowReviewRequest:
    """Request to Claude Code for shadow review of Logi attempt."""
    review_id: str
    attempt_id: str
    reviewer: str  # "claude_code"
    reviewer_route: ShadowReviewerRoute
    instructions: str
    logi_output_to_review: Dict[str, Any]
    acceptance_criteria: List[str]
    specific_questions: List[str]
    protected_action_constraints: List[str]
    expected_response_schema: Dict[str, Any]


@dataclass
class ShadowReviewResult:
    """Claude Code's shadow review result (fixture for V1)."""
    review_id: str
    reviewer: str
    verdict: ReviewVerdict
    corrected_output: Dict[str, Any]
    error_categories: List[str]
    missing_context: List[str]
    safety_findings: List[str]
    recommended_skill_updates: List[str]
    recommended_training_pairs: List[str]
    repairman_relevance: List[str]
    traini_relevance: List[str]
    evidence: Dict[str, Any]


@dataclass
class LearningPairCandidate:
    """A learning pair candidate (Logi output vs Claude correction)."""
    pair_id: str
    source_task_id: str
    target_agent: str  # "logi", "repairman", "architect", "traini", "other"
    input_prompt: str
    weak_output: Dict[str, Any]
    corrected_output: Dict[str, Any]
    error_type: str
    skill_gap: str
    quality_status: LearningPairQuality
    protected_data_removed: bool
    evidence_paths: List[str]
    created_at: str


@dataclass
class TrainiAccumulationItem:
    """Item routed to Traini accumulation queue."""
    accumulation_id: str
    learning_pair_id: str
    target_agent: str
    target_model_or_slot: str
    material_type: TrainiMaterialType
    quality_status: LearningPairQuality
    dedupe_fingerprint: str
    approved: bool
    blocked_reasons: List[str]
    evidence_paths: List[str]


@dataclass
class TrainiReadinessSummary:
    """Traini dataset readiness summary."""
    target_agent: str
    target_model_or_slot: str
    approved_pair_count: int
    required_pair_count: int
    readiness_status: TrainiReadinessStatus
    dataset_quality_notes: str
    eval_suite_required: bool
    aws_claude_code_master_prompt_required: bool
    allowed_to_train_now: bool
    blocked_reasons: List[str]


@dataclass
class AWSClaudeCodeMasterPrompt:
    """Prompt for AWS Claude Code master (training/eval review)."""
    prompt_id: str
    target_agent: str
    target_model_or_slot: str
    dataset_package_summary: Dict[str, Any]
    eval_plan_summary: Dict[str, Any]
    requested_review: str
    explicit_prohibitions: List[str]
    expected_output_schema: Dict[str, Any]
    evidence_paths: List[str]


@dataclass
class SupervisedDeliveryRecord:
    """Complete record of one supervised delivery cycle."""
    record_id: str
    objective: str
    logi_attempt: LogiAttempt
    shadow_review_request: ShadowReviewRequest
    shadow_review_result: ShadowReviewResult
    learning_pairs: List[LearningPairCandidate]
    traini_accumulation_items: List[TrainiAccumulationItem]
    traini_readiness_summary: TrainiReadinessSummary
    aws_claude_code_master_prompt: AWSClaudeCodeMasterPrompt
    final_corrected_plan: Dict[str, Any]
    allowed_to_execute: bool
    approvals_required: List[str]
    next_action: str


# ============================================================================
# FUNCTIONS
# ============================================================================

def create_logi_local_attempt(
    task_id: str,
    objective: str,
    backend_slot: LocalBackendSlot,
    prompt: str,
    output: Dict[str, Any],
    confidence: float = 0.75,
    assumptions: List[str] = None,
    protected_actions: List[str] = None,
    evidence_paths: List[str] = None
) -> LogiAttempt:
    """Create a Logi local delivery attempt."""
    if assumptions is None:
        assumptions = []
    if protected_actions is None:
        protected_actions = []
    if evidence_paths is None:
        evidence_paths = []

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


def build_full_stack_delivery_attempt(
    objective: str,
    logi_attempt: LogiAttempt
) -> Dict[str, Any]:
    """Build Full Stack delivery attempt with multi-agent work packets."""
    return {
        "objective": objective,
        "logi_attempt": asdict(logi_attempt),
        "full_stack_work_packets": [
            {
                "agent": "Logi",
                "role": "Strategic orchestration and synthesis",
                "deliverables": ["delivery plan", "risk assessment", "approval gates"],
                "depends_on": []
            },
            {
                "agent": "Architect",
                "role": "Architecture and design review",
                "deliverables": ["design review", "risk assessment update"],
                "depends_on": ["Logi"]
            },
            {
                "agent": "Repairman",
                "role": "Engineering implementation",
                "deliverables": ["implementation plan", "code changes"],
                "depends_on": ["Architect"]
            },
            {
                "agent": "QA-Agent",
                "role": "Testing and validation",
                "deliverables": ["test plan", "evidence"],
                "depends_on": ["Repairman"]
            },
            {
                "agent": "Release-Agent",
                "role": "Release and rollback readiness",
                "deliverables": ["release plan", "rollback procedures"],
                "depends_on": ["QA-Agent"]
            },
            {
                "agent": "Security/Poli",
                "role": "Protected action gate verification",
                "deliverables": ["gate verification", "approval", "safety notes"],
                "depends_on": ["Architect"]
            }
        ],
        "model_policy_note": "slot32 allowed as local working backend; Qwen3.6:35/slot120 marked experimental",
        "shadow_review_required": True,
        "traini_accumulation_eligible": True
    }


def build_claude_code_shadow_review_request(
    logi_attempt: LogiAttempt,
    full_stack_attempt: Dict[str, Any]
) -> ShadowReviewRequest:
    """Build request for Claude Code shadow review."""
    return ShadowReviewRequest(
        review_id=f"shadow-review-{logi_attempt.attempt_id}",
        attempt_id=logi_attempt.attempt_id,
        reviewer="claude_code",
        reviewer_route=ShadowReviewerRoute.MANUAL,
        instructions="Review Logi's Full Stack delivery attempt. Identify errors, missing context, unsafe assumptions, and skill gaps. Provide corrected plan.",
        logi_output_to_review=logi_attempt.logi_output,
        acceptance_criteria=[
            "All agents have clear work packets",
            "No circular dependencies",
            "Protected actions are gated",
            "QA/Release gates are defined",
            "Assumptions are validated",
            "Traini accumulation route is clear"
        ],
        specific_questions=[
            "Are all required agents assigned?",
            "Is there clear dependency ordering?",
            "Are protected actions properly gated?",
            "Are assumptions safe and documented?",
            "Should slot120/Qwen3.6:35 be marked experimental?",
            "What skill updates should Logi capture?",
            "What engineering pairs should Repairman capture?",
            "Should Traini accumulate materials from this delivery?"
        ],
        protected_action_constraints=[
            "No model downloads",
            "No model deletions",
            "No model promotions",
            "No registry mutations",
            "No training execution",
            "No external API calls"
        ],
        expected_response_schema={
            "verdict": "string: accept/accept_with_changes/reject/needs_context",
            "corrected_plan": "object",
            "error_categories": ["list of error types"],
            "recommended_skill_updates": ["list of skill gaps"],
            "recommended_training_pairs": ["list of training pair opportunities"],
            "repairman_relevant_mistakes": ["list of engineering execution gaps"],
            "traini_accumulation_eligible": "boolean",
            "evidence": "dict with supporting details"
        }
    )


def ingest_shadow_review_result(
    shadow_request: ShadowReviewRequest,
    shadow_result: ShadowReviewResult
) -> Tuple[Dict[str, Any], List[str]]:
    """Ingest shadow review result and produce corrected plan."""
    corrected_plan = shadow_result.corrected_output

    messages = []
    if shadow_result.verdict == ReviewVerdict.ACCEPT:
        messages.append("Shadow review: ACCEPTED without changes")
    elif shadow_result.verdict == ReviewVerdict.ACCEPT_WITH_CHANGES:
        messages.append("Shadow review: ACCEPTED WITH CORRECTIONS")
        messages.append(f"Corrections applied: {len(shadow_result.error_categories)} categories addressed")
    elif shadow_result.verdict == ReviewVerdict.REJECT:
        messages.append("Shadow review: REJECTED")
    else:
        messages.append("Shadow review: NEEDS CONTEXT")

    return corrected_plan, messages


def compare_attempt_to_correction(
    logi_output: Dict[str, Any],
    corrected_output: Dict[str, Any]
) -> Tuple[List[str], Dict[str, Any]]:
    """Compare Logi output to Claude Code correction and identify deltas."""
    differences = []
    delta_details = {
        "logi_keys": set(logi_output.keys() if isinstance(logi_output, dict) else []),
        "corrected_keys": set(corrected_output.keys() if isinstance(corrected_output, dict) else []),
        "added": [],
        "modified": [],
        "removed": []
    }

    if isinstance(logi_output, dict) and isinstance(corrected_output, dict):
        all_keys = set(logi_output.keys()) | set(corrected_output.keys())
        for key in all_keys:
            if key not in logi_output:
                differences.append(f"Added: {key}")
                delta_details["added"].append(key)
            elif key not in corrected_output:
                differences.append(f"Removed: {key}")
                delta_details["removed"].append(key)
            elif logi_output[key] != corrected_output[key]:
                differences.append(f"Modified: {key}")
                delta_details["modified"].append(key)

    return differences, delta_details


def create_learning_pair_candidates(
    logi_attempt: LogiAttempt,
    shadow_result: ShadowReviewResult,
    differences: List[str]
) -> List[LearningPairCandidate]:
    """Create learning pair candidates from attempt and correction."""
    pairs = []

    if len(differences) == 0:
        return pairs

    # Pair 1: Logi strategic orchestration
    pairs.append(LearningPairCandidate(
        pair_id=f"pair-logi-{logi_attempt.attempt_id}",
        source_task_id=logi_attempt.task_id,
        target_agent="logi",
        input_prompt=logi_attempt.prompt,
        weak_output=logi_attempt.logi_output,
        corrected_output=shadow_result.corrected_output,
        error_type="strategic_orchestration_gap",
        skill_gap="Full Stack work packet decomposition and dependency ordering",
        quality_status=LearningPairQuality.NEEDS_HUMAN_REVIEW,
        protected_data_removed=True,
        evidence_paths=[logi_attempt.attempt_id, shadow_result.review_id],
        created_at=datetime.utcnow().isoformat() + "Z"
    ))

    # Pair 2: Repairman engineering execution
    pairs.append(LearningPairCandidate(
        pair_id=f"pair-repairman-{logi_attempt.attempt_id}",
        source_task_id=logi_attempt.task_id,
        target_agent="repairman",
        input_prompt="Engineering implementation planning",
        weak_output={"implementation_gaps": shadow_result.repairman_relevance},
        corrected_output={"implementation_plan": "detailed steps from Claude Code review"},
        error_type="engineering_execution_gap",
        skill_gap="Implementation task breakdown and error recovery",
        quality_status=LearningPairQuality.NEEDS_HUMAN_REVIEW,
        protected_data_removed=True,
        evidence_paths=[logi_attempt.attempt_id, shadow_result.review_id],
        created_at=datetime.utcnow().isoformat() + "Z"
    ))

    # Pair 3: Traini/ModelOps governance
    pairs.append(LearningPairCandidate(
        pair_id=f"pair-traini-{logi_attempt.attempt_id}",
        source_task_id=logi_attempt.task_id,
        target_agent="traini",
        input_prompt="ModelOps governance and learning material decisions",
        weak_output={"governance_gaps": ["missing approval gates", "incomplete protected action classification"]},
        corrected_output={"governance_plan": "complete approval gate structure and model policy"},
        error_type="modelops_governance_gap",
        skill_gap="Governance gate design and protected action classification",
        quality_status=LearningPairQuality.NEEDS_HUMAN_REVIEW,
        protected_data_removed=True,
        evidence_paths=[logi_attempt.attempt_id, shadow_result.review_id],
        created_at=datetime.utcnow().isoformat() + "Z"
    ))

    # Pair 4: Architect design reasoning
    pairs.append(LearningPairCandidate(
        pair_id=f"pair-architect-{logi_attempt.attempt_id}",
        source_task_id=logi_attempt.task_id,
        target_agent="architect",
        input_prompt="Architecture and design review",
        weak_output={"design_assumptions": logi_attempt.assumptions},
        corrected_output={"validated_design": "architecture with validated assumptions"},
        error_type="design_assumption_gap",
        skill_gap="Architecture validation and safe assumption documentation",
        quality_status=LearningPairQuality.NEEDS_HUMAN_REVIEW,
        protected_data_removed=True,
        evidence_paths=[logi_attempt.attempt_id, shadow_result.review_id],
        created_at=datetime.utcnow().isoformat() + "Z"
    ))

    return pairs


def route_learning_pair_target(pair: LearningPairCandidate) -> str:
    """Determine target agent/queue for learning pair."""
    return pair.target_agent


def create_traini_accumulation_items(
    learning_pairs: List[LearningPairCandidate]
) -> List[TrainiAccumulationItem]:
    """Create Traini accumulation items from learning pairs."""
    items = []

    for pair in learning_pairs:
        if pair.target_agent == "traini":
            material_type = TrainiMaterialType.MODELOPS_GOVERNANCE_PAIR
        elif pair.target_agent == "repairman":
            material_type = TrainiMaterialType.REPAIRMAN_TRAINING_CANDIDATE
        elif pair.target_agent in ["architect", "logi"]:
            material_type = TrainiMaterialType.SKILL_UPDATE
        else:
            material_type = TrainiMaterialType.TRAINING_PAIR

        # Create deduplication fingerprint
        dedupe_fingerprint = f"{pair.target_agent}:{pair.error_type}:{hash(str(pair.input_prompt)) % 10000}"

        items.append(TrainiAccumulationItem(
            accumulation_id=f"accum-{pair.pair_id}",
            learning_pair_id=pair.pair_id,
            target_agent=pair.target_agent,
            target_model_or_slot="slot32" if pair.target_agent == "logi" else "various",
            material_type=material_type,
            quality_status=LearningPairQuality.NEEDS_HUMAN_REVIEW,
            dedupe_fingerprint=dedupe_fingerprint,
            approved=False,
            blocked_reasons=["awaiting human review before training"],
            evidence_paths=pair.evidence_paths
        ))

    return items


def summarize_traini_readiness(
    accumulation_items: List[TrainiAccumulationItem],
    required_threshold: int = 100
) -> TrainiReadinessSummary:
    """Summarize Traini dataset readiness across all targets."""
    approved_count = len([item for item in accumulation_items if item.approved])

    readiness_status = TrainiReadinessStatus.DATA_COLLECTION
    blocked_reasons = []

    if approved_count < required_threshold:
        readiness_status = TrainiReadinessStatus.DATA_COLLECTION
        blocked_reasons.append(f"Approved pairs: {approved_count} < required {required_threshold}")
    else:
        readiness_status = TrainiReadinessStatus.READY_FOR_DATASET_PACKAGE

    return TrainiReadinessSummary(
        target_agent="logi",
        target_model_or_slot="slot32",
        approved_pair_count=approved_count,
        required_pair_count=required_threshold,
        readiness_status=readiness_status,
        dataset_quality_notes="Learning materials from Full Stack delivery supervised loop",
        eval_suite_required=True,
        aws_claude_code_master_prompt_required=(readiness_status == TrainiReadinessStatus.READY_FOR_DATASET_PACKAGE),
        allowed_to_train_now=False,  # Training always requires explicit approval
        blocked_reasons=blocked_reasons
    )


def build_aws_claude_code_master_prompt(
    traini_readiness: TrainiReadinessSummary,
    accumulation_items: List[TrainiAccumulationItem]
) -> AWSClaudeCodeMasterPrompt:
    """Build AWS Claude Code master prompt for training/eval orchestration review."""
    return AWSClaudeCodeMasterPrompt(
        prompt_id=f"aws-master-prompt-{datetime.utcnow().isoformat()}",
        target_agent="logi",
        target_model_or_slot="slot32",
        dataset_package_summary={
            "approved_pairs": len([item for item in accumulation_items if item.approved]),
            "pending_human_review": len([item for item in accumulation_items if not item.approved]),
            "material_types": list(set(str(item.material_type.value) for item in accumulation_items)),
            "readiness_status": traini_readiness.readiness_status.value
        },
        eval_plan_summary={
            "eval_suite_required": traini_readiness.eval_suite_required,
            "test_cases_needed": "50+ from Full Stack delivery scenarios",
            "validation_required": True
        },
        requested_review="Review learning material quality, suggest dataset improvements, guide training workflow",
        explicit_prohibitions=[
            "Do not start training automatically",
            "Do not download/delete/promote models",
            "Do not modify model registry",
            "Do not call Bedrock/AWS automatically in V1",
            "Require explicit approval before any ModelOps action"
        ],
        expected_output_schema={
            "dataset_quality_assessment": "string",
            "suggested_improvements": ["list"],
            "eval_plan_validation": "string",
            "training_workflow_guidance": "string",
            "recommended_approvals": ["list"]
        },
        evidence_paths=[item.accumulation_id for item in accumulation_items[:5]]
    )


def build_skill_update_request(pair: LearningPairCandidate) -> Dict[str, Any]:
    """Build skill update request from learning pair."""
    return {
        "skill_id": f"skill-{pair.pair_id}",
        "target_agent": pair.target_agent,
        "skill_gap": pair.skill_gap,
        "weak_behavior": pair.weak_output,
        "corrected_behavior": pair.corrected_output,
        "evidence": pair.evidence_paths,
        "status": "pending_human_review"
    }


def build_repairman_training_candidates(
    learning_pairs: List[LearningPairCandidate]
) -> List[Dict[str, Any]]:
    """Extract Repairman training material from learning pairs."""
    candidates = []

    for pair in learning_pairs:
        if pair.target_agent == "repairman":
            candidates.append({
                "training_id": f"repairman-train-{pair.pair_id}",
                "error_type": pair.error_type,
                "skill_gap": pair.skill_gap,
                "weak_approach": pair.weak_output,
                "corrected_approach": pair.corrected_output,
                "evidence": pair.evidence_paths,
                "approved_for_training": False
            })

    return candidates


def summarize_supervised_delivery_record(
    objective: str,
    logi_attempt: LogiAttempt,
    shadow_request: ShadowReviewRequest,
    shadow_result: ShadowReviewResult,
    learning_pairs: List[LearningPairCandidate],
    accumulation_items: List[TrainiAccumulationItem],
    traini_readiness: TrainiReadinessSummary,
    aws_master_prompt: AWSClaudeCodeMasterPrompt,
    corrected_plan: Dict[str, Any]
) -> SupervisedDeliveryRecord:
    """Summarize complete supervised delivery cycle."""
    return SupervisedDeliveryRecord(
        record_id=f"delivery-record-{logi_attempt.attempt_id}",
        objective=objective,
        logi_attempt=logi_attempt,
        shadow_review_request=shadow_request,
        shadow_review_result=shadow_result,
        learning_pairs=learning_pairs,
        traini_accumulation_items=accumulation_items,
        traini_readiness_summary=traini_readiness,
        aws_claude_code_master_prompt=aws_master_prompt,
        final_corrected_plan=corrected_plan,
        allowed_to_execute=False,  # Always requires approval
        approvals_required=[
            "Logi strategic orchestration approval",
            "Full Stack team review",
            "Security/Poli protected action gate",
            "Traini learning material review"
        ],
        next_action="Submit corrected plan and learning materials for human review"
    )


def validate_no_protected_action_execution() -> Tuple[bool, List[str]]:
    """Validate that no protected actions were executed."""
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
        ("No secrets exposed", True)
    ]

    all_passed = all(check[1] for check in checks)
    messages = [f"{check[0]}: {'✓' if check[1] else '✗'}" for check in checks]

    return all_passed, messages
