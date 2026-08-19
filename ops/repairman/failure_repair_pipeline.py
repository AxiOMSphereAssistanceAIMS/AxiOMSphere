from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repairman.claude_code_repair_backend import backend_health, run_repair_backend
from repairman.repair_packet_builder import build_repair_packet
from repairman.repair_request_schema import FailureRepairRequest
from repairman.repair_result_schema import FailureRepairResult


EVIDENCE_ROOT = Path(os.environ.get('REPAIRMAN_FAILURE_EVIDENCE_DIR', 'aims_workspace/repairman_failure_repairs'))


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')


def _result_with_evidence(result: FailureRepairResult, evidence_path: str) -> FailureRepairResult:
    data = result.to_dict()
    data['evidence_path'] = evidence_path
    if not data.get('argus_summary'):
        data['argus_summary'] = {
            'status': result.status,
            'summary': f'{result.request_id}: {result.failure_classification} via {result.backend_mode}',
            'severity': 'medium',
        }
    return FailureRepairResult.from_dict(data)


def execute_failure_repair_request(
    request: FailureRepairRequest,
    *,
    evidence_root: Path | None = None,
    timeout_s: int = 120,
    allow_legacy_fallback: bool = False,
    governance_preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request.validate()
    root = evidence_root or EVIDENCE_ROOT
    attempt_dir = root / request.request_id / _now_stamp()
    attempt_dir.mkdir(parents=True, exist_ok=True)

    packet = build_repair_packet(request)
    _write_json(attempt_dir / 'failure_repair_request.json', request.to_dict())
    _write_json(attempt_dir / 'repair_packet.json', packet)

    health = backend_health()
    result, backend_raw = run_repair_backend(
        request,
        packet,
        timeout_s=timeout_s,
        allow_legacy_fallback=allow_legacy_fallback,
    )
    _write_json(attempt_dir / 'backend_health.json', health)
    _write_json(attempt_dir / 'backend_response.json', backend_raw)

    result_path = attempt_dir / 'failure_repair_result.json'
    result = _result_with_evidence(result, str(result_path))
    _write_json(result_path, result.to_dict())

    controlled_patch_result: dict[str, Any] | None = None
    if os.environ.get('REPAIRMAN_PATCH_PHASE2', '').strip().lower() in {'1', 'true', 'yes', 'on'}:
        try:
            from repairman.controlled_patch_pipeline import run_controlled_patch_pipeline

            controlled = run_controlled_patch_pipeline(
                request=request,
                phase1_result=result,
                backend_raw={**backend_raw, 'selected_skills': packet.get('selected_claude_code_skills', [])},
                evidence_root=attempt_dir / 'controlled_patch_phase2',
                timeout_s=min(timeout_s, 60),
                governance_preflight=governance_preflight,
            )
            controlled_patch_result = controlled.to_dict()
            data = result.to_dict()
            data.setdefault('argus_summary', {})
            data['argus_summary']['controlled_patch'] = controlled_patch_result.get('argus_summary', {})
            data['argus_summary']['controlled_patch_evidence_path'] = controlled_patch_result.get('evidence_path', '')
            data['verification_result'] = f"{data.get('verification_result', '')}; phase2={controlled_patch_result.get('final_status')}"
            result = FailureRepairResult.from_dict(data)
            _write_json(result_path, result.to_dict())
        except Exception as exc:
            controlled_patch_result = {'error': repr(exc), 'phase2_status': 'failed'}
            data = result.to_dict()
            data.setdefault('argus_summary', {})
            data['argus_summary']['controlled_patch'] = {
                'patch_detected': False,
                'policy_decision': 'phase2_error',
                'risk_level': 'unknown',
                'apply_mode': os.environ.get('REPAIRMAN_APPLY_MODE', ''),
                'sandbox_passed': False,
                'sandbox_stage_ran': False,
                'approval_state': 'not_required',
                'applied_to_main_tree': False,
                'auditor_backend': os.environ.get('REPAIRMAN_AUDITOR_BACKEND', ''),
                'auditor_required': os.environ.get('REPAIRMAN_AUDITOR_REQUIRED', ''),
                'real_bedrock_enabled': os.environ.get('REPAIRMAN_AUDITOR_REAL_BEDROCK', '') == '1',
                'auditor_verdict': 'unavailable',
                'auditor_allowed_to_apply': False,
                'patch_applied_blocked_by_auditor': True,
                'blocked_by_policy': False,
                'autonomy_level': None,
                'auto_apply_eligible': False,
                'auto_applied': False,
                'blocked_reason': repr(exc),
                'learning_registered': False,
            }
            result = FailureRepairResult.from_dict(data)
            _write_json(result_path, result.to_dict())

    try:
        from argus.repairman_reporting import record_repairman_result

        argus_record = record_repairman_result(result)
    except Exception as exc:
        argus_record = {'error': repr(exc)}
    _write_json(attempt_dir / 'argus_repairman_payload.json', argus_record)

    return {
        'ok': True,
        'request': request.to_dict(),
        'packet': packet,
        'backend_health': health,
        'backend_raw': backend_raw,
        'controlled_patch_result': controlled_patch_result,
        'result': result.to_dict(),
        'argus_record': argus_record,
        'evidence_dir': str(attempt_dir),
        'result_path': str(result_path),
    }


__all__ = ['execute_failure_repair_request']
