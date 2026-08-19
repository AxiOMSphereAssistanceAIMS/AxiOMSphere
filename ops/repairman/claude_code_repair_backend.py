from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from repairman.repair_packet_builder import build_repair_prompt
from repairman.repair_request_schema import FailureRepairRequest
from repairman.repair_result_schema import FailureRepairResult


DEFAULT_TOKEN = 'aims-local-repair-token'
DEFAULT_TIMEOUT_S = int(os.environ.get('REPAIRMAN_CLAUDE_CODE_TIMEOUT_S', '120'))


class RepairmanBackendError(RuntimeError):
    pass


def _running_in_container() -> bool:
    if Path('/.dockerenv').exists():
        return True
    return Path('/workspace/ops').exists() and not Path('/home/axi_omi_sphere/aims-workspace/ops').exists()


def repairman_backend_mode() -> str:
    raw = os.environ.get('REPAIRMAN_BACKEND', 'claude_code').strip().lower()
    return raw if raw in {'claude_code', 'legacy'} else 'claude_code'


def bridge_url() -> str:
    explicit = os.environ.get('REPAIRMAN_CLAUDE_CODE_URL', '').strip()
    if explicit:
        url = explicit
    elif _running_in_container():
        url = 'http://172.17.0.1:8094/run'
    else:
        url = 'http://127.0.0.1:8094/run'
    if url.rstrip('/').endswith('/run'):
        return url
    return url.rstrip('/') + '/run'


def bridge_token() -> str:
    return os.environ.get('REPAIRMAN_CLAUDE_CODE_TOKEN', DEFAULT_TOKEN)


def health_url(run_url: str | None = None) -> str:
    url = run_url or bridge_url()
    return re.sub(r'/run/?$', '/health', url.rstrip('/'))


def backend_health(timeout_s: int = 8) -> dict[str, Any]:
    url = health_url()
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
        payload = json.loads(raw)
        return {
            'ok': bool(payload.get('ok')),
            'url': url,
            'backend_mode': payload.get('backend_mode', ''),
            'slot32_ok': bool(((payload.get('routes') or {}).get('slot32') or {}).get('proxy', {}).get('ok')),
            'payload': payload,
        }
    except Exception as exc:
        return {'ok': False, 'url': url, 'error': repr(exc), 'backend_mode': ''}


def _extract_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith('```'):
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
        cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start >= 0 and end > start:
        try:
            data = json.loads(cleaned[start:end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None


def _extract_json_string_field(text: str, key: str) -> str | None:
    import re

    match = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', text, re.S)
    if not match:
        return None
    try:
        return json.loads(f'"{match.group(1)}"')
    except Exception:
        return None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [str(value)]


def _status_from_payload(payload: dict[str, Any]) -> str:
    raw = str(((payload.get('ARGUS_SUMMARY') or {}).get('status') or payload.get('STATUS') or 'deferred')).lower()
    mapping = {
        'fixed': 'fixed',
        'partially_fixed': 'partially_fixed',
        'partial': 'partially_fixed',
        'needs_human': 'needs_human',
        'human': 'needs_human',
        'not_reproducible': 'not_reproducible',
        'no_action': 'no_action',
        'failed': 'failed',
        'deferred': 'deferred',
    }
    return mapping.get(raw, 'deferred')


def result_from_backend_payload(
    *,
    request: FailureRepairRequest,
    payload: dict[str, Any],
    backend_mode: str,
) -> FailureRepairResult:
    status = _status_from_payload(payload)
    tests_run = _as_list(payload.get('TEST_PLAN') or payload.get('tests_run'))
    rollback = _as_list(payload.get('ROLLBACK') or payload.get('rollback_steps'))
    if status in {'fixed', 'partially_fixed'}:
        # This backend creates a repair plan/result. It does not apply patches.
        status = 'needs_human'
    if status in {'fixed', 'partially_fixed'} and (not tests_run or not rollback):
        status = 'needs_human'
    proposed_files = [
        item for item in _as_list(payload.get('FILES_TO_CHANGE') or payload.get('files_changed'))
        if item != 'NO_CHANGE_REQUIRED'
    ]
    return FailureRepairResult(
        request_id=request.request_id,
        status=status,
        backend_mode=backend_mode if backend_mode in {'claude_code_cli', 'direct_proxy_fallback'} else 'legacy',
        root_cause=str(payload.get('ROOT_CAUSE') or payload.get('root_cause') or 'Not determined.'),
        failure_classification=str(payload.get('FAILURE_CLASSIFICATION') or payload.get('failure_classification') or request.failure_origin),
        repair_strategy=str(payload.get('REPAIR_STRATEGY') or payload.get('repair_strategy') or 'Inspect failure evidence and propose bounded repair.'),
        proposed_fix=str(payload.get('PROPOSED_FIX') or payload.get('proposed_fix') or 'No safe fix proposed.'),
        applied_changes=[],
        files_changed=[],
        commands_run=_as_list(payload.get('COMMANDS_TO_RUN') or payload.get('commands_run')),
        tests_run=tests_run,
        verification_result=str(payload.get('VERIFICATION_RESULT') or payload.get('verification_result') or 'not_applied_by_backend'),
        rollback_steps=rollback or ['No changes applied by Repairman backend.'],
        argus_summary={
            **(payload.get('ARGUS_SUMMARY') if isinstance(payload.get('ARGUS_SUMMARY'), dict) else {}),
            'proposed_files_to_change': proposed_files,
        },
    )


def legacy_repair_result(request: FailureRepairRequest, reason: str = 'legacy backend selected') -> FailureRepairResult:
    return FailureRepairResult(
        request_id=request.request_id,
        status='deferred',
        backend_mode='legacy',
        root_cause=request.failure_summary,
        failure_classification=request.failure_origin,
        repair_strategy='Legacy Repairman path preserved; manual/old queue execution remains available.',
        proposed_fix=f'Deferred to legacy path: {reason}',
        applied_changes=[],
        files_changed=[],
        commands_run=[],
        tests_run=[],
        verification_result='not_run_legacy_deferred',
        rollback_steps=['No changes applied.'],
        argus_summary={
            'status': 'deferred',
            'summary': f'{request.request_id}: legacy backend deferred repair execution',
            'severity': request.severity,
        },
    )


def call_claude_code_backend(
    request: FailureRepairRequest,
    packet: dict[str, Any],
    *,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> tuple[FailureRepairResult, dict[str, Any]]:
    prompt = build_repair_prompt(packet)
    body = json.dumps({'route': 'slot32', 'prompt': prompt}).encode('utf-8')
    req = urllib.request.Request(
        bridge_url(),
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {bridge_token()}',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as exc:
        err = exc.read().decode('utf-8', errors='replace')
        raise RepairmanBackendError(f'bridge HTTP {exc.code}: {err[-2000:]}') from exc
    except Exception as exc:
        raise RepairmanBackendError(f'bridge request failed: {exc!r}') from exc

    try:
        bridge_payload = json.loads(raw)
    except Exception as exc:
        raise RepairmanBackendError(f'bridge returned non-JSON: {raw[-2000:]}') from exc
    if not bridge_payload.get('ok'):
        raise RepairmanBackendError(f'bridge returned error: {json.dumps(bridge_payload, ensure_ascii=False)[-2000:]}')
    answer = str(bridge_payload.get('answer') or '').strip()
    parsed = _extract_json(answer)
    if parsed is None:
        patch_text = _extract_json_string_field(answer, 'PATCH')
        root_cause = _extract_json_string_field(answer, 'ROOT_CAUSE') or 'Backend returned non-JSON repair analysis.'
        failure_classification = _extract_json_string_field(answer, 'FAILURE_CLASSIFICATION') or request.failure_origin
        repair_strategy = _extract_json_string_field(answer, 'REPAIR_STRATEGY') or 'Escalate for human review because backend output was not machine-parseable.'
        proposed_fix = _extract_json_string_field(answer, 'PROPOSED_FIX') or (answer[:1200] or 'No parseable output.')
        parsed = {
            'ROOT_CAUSE': root_cause,
            'FAILURE_CLASSIFICATION': failure_classification,
            'REPAIR_STRATEGY': repair_strategy,
            'PROPOSED_FIX': proposed_fix,
            'FILES_TO_CHANGE': ['NO_CHANGE_REQUIRED'],
            'COMMANDS_TO_RUN': [],
            'TEST_PLAN': [],
            'ROLLBACK': ['No changes applied.'],
            'ARGUS_SUMMARY': {'status': 'deferred', 'summary': 'Repair backend returned non-JSON output.', 'severity': request.severity},
        }
        if patch_text:
            parsed['PATCH'] = patch_text
    backend_mode = str(bridge_payload.get('backend') or bridge_payload.get('backend_mode') or 'direct_proxy_fallback')
    result = result_from_backend_payload(request=request, payload=parsed, backend_mode=backend_mode)
    return result, {'bridge_payload': bridge_payload, 'model_payload': parsed}


def run_repair_backend(
    request: FailureRepairRequest,
    packet: dict[str, Any],
    *,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    allow_legacy_fallback: bool = False,
) -> tuple[FailureRepairResult, dict[str, Any]]:
    request.validate()
    if repairman_backend_mode() == 'legacy':
        raise RepairmanBackendError('LEGACY_REPAIR_BACKEND_RETIRED: use governed Claude Code repair path')

    health = backend_health()
    if not health.get('ok'):
        if allow_legacy_fallback:
            result = legacy_repair_result(request, reason=f"bridge unhealthy: {health.get('error', 'health false')}")
            return result, {'health': health, 'fallback': 'bridge_unhealthy'}
        raise RepairmanBackendError(f'bridge unhealthy: {health}')

    try:
        result, raw = call_claude_code_backend(request, packet, timeout_s=timeout_s)
        raw['health'] = health
        return result, raw
    except Exception as exc:
        if allow_legacy_fallback:
            result = legacy_repair_result(request, reason=repr(exc))
            return result, {'health': health, 'fallback': 'claude_code_error', 'error': repr(exc)}
        raise
