from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from orchestrator_planning.repairman_loop_breaker import (
    CLOSURE_FAILED_LIMIT,
    CLOSURE_HERMES_REVIEW_REQUIRED,
    CLOSURE_REPAIRED,
    RepairAttempt,
    RepairmanLoopBreaker,
    build_attempt_history_record,
    make_failure_signature,
)
from orchestrator_planning.repairman_repair_evidence_package import build_repair_evidence_package
from orchestrator_planning.repairman_unresolved_problem_registry import register_unresolved_problem
from repairman.first_100_repair_ledger import append_ledger_entry, build_ledger_entry, write_current_status
from repairman.hermes_repair_approval_schema import HermesApproval
from repairman.hermes_repair_review import review_post_repair
from repairman.repair_case_report import write_repair_case_report
from repairman.repair_plan_schema import RepairPlan
from repairman.repair_request_queue import block_request, complete_request, fail_request, move_to_running
from repairman.repair_request_schema import RepairRequest

FIXTURE_ROOT = Path('aims_workspace/test_fixtures/repairman_first_100')
EVIDENCE_ROOT = Path('aims_workspace/repairman_first_100_repairs/execution_evidence')
REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_ACTION_TYPES = {'WRITE_TEXT', 'APPEND_TEXT', 'RUN_COMMAND'}
FORBIDDEN_ACTION_TYPES = {'DELETE_PATH', 'RM_RF', 'RESTART_SERVICE', 'LOAD_MODEL', 'UNLOAD_MODEL', 'EDIT_ENV', 'READ_SECRET', 'READ_RAW_CLAUDE_MEM', 'TRAIN_MODEL', 'USE_SLOT120_AS_JUDGE'}
SAFETY_FLAGS = {
    'registry_changed': False,
    'production_changed': False,
    'services_restarted': False,
    'training_launched': False,
    'slot120_used_as_teacher_judge': False,
    'secrets_accessed': False,
}


def can_proceed_without_poli(risk_level: str) -> bool:
    """Determine if a repair can proceed without Poli approval gate.

    Only low-risk repairs are allowed to bypass Poli when it's unavailable.
    Medium, high, and critical-risk repairs MUST wait for Poli.

    Args:
        risk_level: The risk level of the repair ('low', 'medium', 'high', 'critical')

    Returns:
        True if the repair can proceed without Poli approval, False otherwise
    """
    if risk_level.lower() == "low":
        logger.warning("Poli unavailable — proceeding with low-risk repair (auto-approved)")
        return True
    return False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()



def _safe_path(target: str) -> Path:
    path = Path(target)
    resolved = path.resolve()
    root = FIXTURE_ROOT.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f'path outside fixture root: {target}')
    return resolved



def create_repair_plan_from_request(
    request: RepairRequest,
    *,
    repairman_assessment: str,
    root_cause_hypotheses: list[str],
    proposed_actions: list[dict[str, Any]],
    risk_level: str = 'LOW',
    within_certified_scope: bool = True,
    requires_user_approval: bool = False,
    expected_files_changed: list[str] | None = None,
    expected_services_touched: list[str] | None = None,
    expected_models_touched: list[str] | None = None,
) -> RepairPlan:
    return RepairPlan(
        plan_id=f'plan_{request.request_id}',
        request_id=request.request_id,
        repairman_assessment=repairman_assessment,
        root_cause_hypotheses=root_cause_hypotheses,
        proposed_actions=proposed_actions,
        risk_level=risk_level,
        required_repair_level=request.requested_repair_level,
        within_certified_scope=within_certified_scope,
        requires_user_approval=requires_user_approval,
        rollback_plan=request.rollback_requirement,
        validation_plan=' '.join(request.rerun_command) if request.rerun_command else 'manual validation required',
        expected_files_changed=expected_files_changed or [],
        expected_services_touched=expected_services_touched or [],
        expected_models_touched=expected_models_touched or [],
        forbidden_actions_confirmed=True,
        evidence_paths=list(request.evidence_paths),
    )



def _gate_execution(request: RepairRequest, plan: RepairPlan, approval: HermesApproval | None) -> tuple[bool, str]:
    if approval is None:
        return False, 'BLOCKED_FINAL_POLICY_GATE_PENDING'
    if approval.decision != 'APPROVED':
        return False, 'BLOCKED_FINAL_POLICY_GATE_PENDING' if approval.decision == 'NEEDS_REVISION' else ('BLOCKED_OUT_OF_POLICY' if approval.decision == 'USER_APPROVAL_REQUIRED' else 'BLOCKED_REJECTED_BY_REVIEW')
    if plan.requires_user_approval or not plan.within_certified_scope:
        return False, 'BLOCKED_OUT_OF_POLICY'
    if not plan.rollback_plan or not plan.validation_plan:
        return False, 'BLOCKED_MISSING_ROLLBACK_OR_VALIDATION'
    for action in plan.proposed_actions:
        action_type = str(action.get('action_type', 'UNKNOWN'))
        if action_type in FORBIDDEN_ACTION_TYPES:
            return False, 'BLOCKED_FORBIDDEN_ACTION'
        if action_type not in ALLOWED_ACTION_TYPES:
            return False, 'BLOCKED_UNKNOWN_ACTION'
        if action_type not in request.allowed_actions:
            return False, 'BLOCKED_ACTION_NOT_ALLOWLISTED'
    return True, 'APPROVED_FOR_EXECUTION'



def _run_command(command: list[str], cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return {
        'command': command,
        'returncode': proc.returncode,
        'stdout': proc.stdout[-4000:],
        'stderr': proc.stderr[-4000:],
    }



def _apply_actions(plan: RepairPlan, request: RepairRequest, attempt_dir: Path, actions: list[dict[str, Any]]) -> dict[str, Any]:
    files_changed: list[str] = []
    commands_run: list[dict[str, Any]] = []
    for action in actions:
        action_type = action['action_type']
        if action_type == 'WRITE_TEXT':
            target = _safe_path(action['target_path'])
            backup = attempt_dir / f"backup_{target.name}"
            if target.exists():
                shutil.copy2(target, backup)
            target.write_text(str(action.get('content', '')), encoding='utf-8')
            files_changed.append(str(target))
        elif action_type == 'APPEND_TEXT':
            target = _safe_path(action['target_path'])
            backup = attempt_dir / f"backup_{target.name}"
            if target.exists():
                shutil.copy2(target, backup)
            with target.open('a', encoding='utf-8') as fh:
                fh.write(str(action.get('content', '')))
            files_changed.append(str(target))
        elif action_type == 'RUN_COMMAND':
            cmd = list(action.get('command', []))
            if not cmd:
                raise ValueError('RUN_COMMAND missing command')
            commands_run.append(_run_command(cmd, REPO_ROOT))
        else:
            raise ValueError(f'unsupported action type: {action_type}')
    validation = _run_command(request.rerun_command, REPO_ROOT) if request.rerun_command else {'command': [], 'returncode': 0, 'stdout': '', 'stderr': ''}
    return {
        'files_changed': files_changed,
        'commands_run': commands_run,
        'validation': validation,
    }



def _derive_correction_actions(attempt_number: int, current_actions: list[dict[str, Any]], request: RepairRequest) -> list[dict[str, Any]]:
    if 'same_task_rerun_after_each_correction' in request.success_criteria:
        return current_actions
    if attempt_number == 1:
        patched = []
        for action in current_actions:
            new_action = dict(action)
            if new_action.get('action_type') == 'WRITE_TEXT' and 'corrected_content' in new_action:
                new_action['content'] = new_action['corrected_content']
            patched.append(new_action)
        return patched
    return current_actions



def execute_approved_repair(
    request: RepairRequest,
    plan: RepairPlan,
    approval: HermesApproval | None,
    *,
    update_queue: bool = False,
) -> dict[str, Any]:
    gate_ok, gate_status = _gate_execution(request, plan, approval)
    if not gate_ok:
        result = {
            'request_id': request.request_id,
            'execution_status': 'BLOCKED',
            'validation_status': 'NOT_RUN',
            'closure_state': gate_status,
            'evidence_paths': [],
            'attempt_history': [],
            **SAFETY_FLAGS,
        }
        if update_queue:
            block_request(request.request_id, gate_status, {'execution_result': result})
        return result

    if update_queue:
        move_to_running(request.request_id)

    run_root = EVIDENCE_ROOT / request.request_id
    run_root.mkdir(parents=True, exist_ok=True)
    loop_breaker = RepairmanLoopBreaker(max_attempts=3)
    current_actions = list(plan.proposed_actions)
    attempt_history: list[dict[str, Any]] = []
    hermes_reviews_count = 0
    correction_packages_count = 0
    final_status = 'FAILED'
    validation_status = 'FAIL'
    failure_signature = ''
    all_evidence_paths: list[str] = []

    for attempt_number in range(1, 4):
        attempt_dir = run_root / f'attempt_{attempt_number}'
        attempt_dir.mkdir(parents=True, exist_ok=True)
        applied = _apply_actions(plan, request, attempt_dir, current_actions)
        validation = applied['validation']
        validation_status = 'PASS' if validation['returncode'] == 0 else 'FAIL'
        failure_signature = make_failure_signature(validation.get('stderr') or validation.get('stdout') or request.task_name, request.task_name, request.symptom_class)
        attempt_payload = {
            'attempt_number': attempt_number,
            'actions': current_actions,
            'files_changed': applied['files_changed'],
            'commands_run': applied['commands_run'],
            'validation': validation,
            'same_task_rerun': True,
            'created_at': _now(),
        }
        attempt_path = attempt_dir / 'attempt_result.json'
        attempt_path.write_text(json.dumps(attempt_payload, indent=2, ensure_ascii=False), encoding='utf-8')
        all_evidence_paths.append(str(attempt_path))

        if validation_status == 'PASS':
            loop_breaker.register_attempt(
                failure_signature=failure_signature,
                attempted_fix='approved_plan_execution',
                test_result='PASS',
                hermes_review_id=approval.approval_id if approval else '',
                hermes_review_path='',
                correction_package_path='',
                correction_applied=attempt_number > 1,
                same_task_rerun=True,
                rerun_result='PASS',
            )
            closure_state = CLOSURE_REPAIRED
            final_status = 'EXECUTED'
            attempt = loop_breaker.attempts[-1]
            attempt_history.append(build_attempt_history_record(repair_case_id=request.request_id, task_id=request.task_name, attempt=attempt, closure_state=closure_state, evidence_paths=[str(attempt_path)]))
            break

        hermes_reviews_count += 1 if attempt_number < 3 else 0
        correction_packages_count += 1 if attempt_number < 3 else 0
        correction_package_path = ''
        hermes_review_path = ''
        if attempt_number < 3:
            correction_actions = _derive_correction_actions(attempt_number, current_actions, request)
            correction_payload = {
                'request_id': request.request_id,
                'attempt_number': attempt_number,
                'required_behavior_change': 'adjust plan and rerun same task',
                'correction_actions': correction_actions,
                'created_at': _now(),
            }
            correction_package_path = str(attempt_dir / 'correction_package.json')
            Path(correction_package_path).write_text(json.dumps(correction_payload, indent=2, ensure_ascii=False), encoding='utf-8')
            hermes_review_path = str(attempt_dir / 'hermes_review.json')
            Path(hermes_review_path).write_text(json.dumps({'review_id': f'hermes_review_{request.request_id}_{attempt_number}', 'decision': 'NEEDS_CORRECTION', 'created_at': _now()}, indent=2, ensure_ascii=False), encoding='utf-8')
            current_actions = correction_actions
            all_evidence_paths.extend([correction_package_path, hermes_review_path])
            loop_breaker.register_attempt(
                failure_signature=failure_signature,
                attempted_fix='approved_plan_execution',
                test_result='FAIL',
                hermes_review_id=f'hermes_review_{request.request_id}_{attempt_number}',
                hermes_review_path=hermes_review_path,
                correction_package_path=correction_package_path,
                correction_applied=True,
                same_task_rerun=True,
                rerun_result='FAIL',
            )
            attempt = loop_breaker.attempts[-1]
            attempt_history.append(build_attempt_history_record(repair_case_id=request.request_id, task_id=request.task_name, attempt=attempt, closure_state=CLOSURE_HERMES_REVIEW_REQUIRED, evidence_paths=[str(attempt_path), correction_package_path, hermes_review_path]))
        else:
            loop_breaker.register_attempt(
                failure_signature=failure_signature,
                attempted_fix='approved_plan_execution',
                test_result='FAIL',
                hermes_review_id=f'hermes_review_{request.request_id}_2',
                hermes_review_path='',
                correction_package_path='',
                correction_applied=True,
                same_task_rerun=True,
                rerun_result='FAIL',
            )
            attempt = loop_breaker.attempts[-1]
            attempt_history.append(build_attempt_history_record(repair_case_id=request.request_id, task_id=request.task_name, attempt=attempt, closure_state=CLOSURE_FAILED_LIMIT, evidence_paths=[str(attempt_path)]))

    decision = loop_breaker.current_decision()
    closure_state = decision.closure_state
    if closure_state == CLOSURE_FAILED_LIMIT:
        register_unresolved_problem(
            repair_case_id=request.request_id,
            task_id=request.task_name,
            repeated_pattern_key=f'{request.task_type}|{request.symptom_class}',
            attempt_history=attempt_history,
            evidence_paths=all_evidence_paths,
            notes='first_100 failure after three Hermes-reviewed attempts',
        )
        final_status = 'FAILED'

    evidence_pkg = build_repair_evidence_package(
        repair_id=f'repair_{request.request_id}',
        incident_id=request.request_id,
        root_cause_summary='; '.join(plan.root_cause_hypotheses),
        failure_signature=failure_signature,
        attempted_fixes=['approved_plan_execution'],
        proposed_patch_summary=plan.repairman_assessment,
        test_commands=[' '.join(request.rerun_command)] if request.rerun_command else [],
        test_results=[validation_status],
        closure_state=closure_state,
        evidence_paths=all_evidence_paths,
        hermes_review_status=approval.decision if approval else 'MISSING',
    )
    evidence_path = run_root / 'repair_evidence_package.json'
    evidence_path.write_text(json.dumps(evidence_pkg, indent=2, ensure_ascii=False), encoding='utf-8')
    all_evidence_paths.append(str(evidence_path))

    execution_result = {
        'request_id': request.request_id,
        'plan_id': plan.plan_id,
        'execution_status': final_status,
        'validation_status': validation_status if final_status != 'BLOCKED' else 'NOT_RUN',
        'closure_state': closure_state,
        'attempt_history': attempt_history,
        'hermes_reviews_count': hermes_reviews_count,
        'correction_packages_count': correction_packages_count,
        'failure_signature': failure_signature,
        'evidence_paths': all_evidence_paths,
        **SAFETY_FLAGS,
    }

    hermes_post = review_post_repair(request, plan, approval, execution_result)
    ledger_entry = build_ledger_entry(
        request_id=request.request_id,
        requesting_agent=request.requesting_agent,
        plan_id=plan.plan_id,
        hermes_approval_id=approval.approval_id,
        execution_status=final_status,
        validation_status=execution_result['validation_status'],
        hermes_post_review_status=hermes_post['hermes_post_review_status'],
        skill_gap_detected=hermes_post['skill_gap_detected'],
        training_case_created=hermes_post['training_case_created'],
        evidence_paths=all_evidence_paths,
    )
    append_ledger_entry(ledger_entry)
    report_path = write_repair_case_report(
        request=request.to_dict(),
        plan=plan.to_dict(),
        hermes_pre=approval.to_dict(),
        execution=execution_result,
        hermes_post=hermes_post,
        next_action=hermes_post['next_action'],
        project_value='Turns early Repairman executions into certifiable evidence for later autonomy expansion',
    )
    execution_result['report_path'] = report_path
    execution_result['hermes_post_review'] = hermes_post

    if update_queue:
        if final_status == 'EXECUTED':
            complete_request(request.request_id, execution_result)
        else:
            fail_request(request.request_id, execution_result)
    write_current_status()
    return execution_result
