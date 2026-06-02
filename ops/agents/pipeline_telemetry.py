"""Agent Factory OS Pipeline Telemetry — safe, append-only event tracking.

Non-invasive telemetry for certified agent handoff chains, gates, and incidents.
All events are written to test-local workspace by default (no production DB writes).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_TELEMETRY_DIR = "aims_workspace/runtime_telemetry/test_events"
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret|private[_-]?key)\s*[:=]\s*([^\s,'\";]+)"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-+/=]{8,}"),
)


def _redact_secrets(text: str) -> str:
    """Redact obvious secret-like values from text."""
    if not isinstance(text, str):
        return text
    # Redact common secret patterns
    redacted = text
    redacted = re.sub(r"sk-[a-zA-Z0-9]+", "[REDACTED_KEY]", redacted)
    redacted = re.sub(r"api[_-]?key[=:][\S]+", "[REDACTED_API_KEY]", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"token[=:][\S]+", "[REDACTED_TOKEN]", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"password[=:][\S]+", "[REDACTED_PASSWORD]", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"secret[=:][\S]+", "[REDACTED_SECRET]", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"bearer\s+[A-Za-z0-9._\-+/=]{8,}", "Bearer [REDACTED_TOKEN]", redacted, flags=re.IGNORECASE)
    return redacted


def _safe_dict(obj: Any) -> Dict[str, Any]:
    """Convert object to safe dict, redacting secrets."""
    if isinstance(obj, dict):
        return {k: _redact_secrets(str(v)) if isinstance(v, str) else v for k, v in obj.items()}
    return {"value": _redact_secrets(str(obj))}


def _now_utc() -> str:
    """Current UTC timestamp ISO format."""
    return datetime.now(timezone.utc).isoformat()


class PipelineTelemetry:
    """Safe, test-local telemetry writer for Agent Factory OS pipelines."""

    def __init__(self, output_dir: str = DEFAULT_TELEMETRY_DIR):
        """Initialize telemetry writer.
        
        Args:
            output_dir: Base directory for test events (default: test-local workspace)
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.events: List[Dict[str, Any]] = []
        self.event_counts: Dict[str, int] = {}

    def _emit(self, event: Dict[str, Any]) -> None:
        """Emit event to JSONL file and memory."""
        # Redact any secret-like values
        safe_event = {k: _redact_secrets(str(v)) if isinstance(v, str) else v for k, v in event.items()}
        
        # Add metadata
        safe_event["timestamp"] = safe_event.get("timestamp", _now_utc())
        safe_event["event_id"] = hashlib.sha256(
            (str(safe_event) + _now_utc()).encode()
        ).hexdigest()[:12]
        
        # Track in memory
        self.events.append(safe_event)
        event_type = safe_event.get("type", "unknown")
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1

        # Append to JSONL file
        events_file = self.output_dir / "events.jsonl"
        with open(events_file, "a") as f:
            f.write(json.dumps(safe_event, ensure_ascii=False) + "\n")

    def emit_handoff_event(
        self,
        pipeline_id: str,
        task_id: str,
        source_agent: str,
        target_agent: str,
        intent: str,
        handoff_status: str,  # SUCCESS, FAILED, NEEDS_APPROVAL, NEEDS_CONTEXT
        required_inputs_present: bool,
        evidence_required: bool,
        approval_required: bool,
        result_status: str,
    ) -> None:
        """Emit pipeline handoff event."""
        self._emit({
            "type": "pipeline_handoff",
            "pipeline_id": pipeline_id,
            "task_id": task_id,
            "source_agent": source_agent,
            "target_agent": target_agent,
            "intent": intent,
            "handoff_status": handoff_status,
            "required_inputs_present": required_inputs_present,
            "evidence_required": evidence_required,
            "approval_required": approval_required,
            "result_status": result_status,
        })

    def emit_gate_decision(
        self,
        gate_id: str,
        gate_owner: str,  # Security, Poli, QA, Release, Omi
        protected_area: str,
        decision: str,  # ALLOW, BLOCK, NEEDS_APPROVAL, NEEDS_CONTEXT
        reason: str,
        evidence: str = "",
        rollback_required: bool = False,
    ) -> None:
        """Emit gate decision event."""
        self._emit({
            "type": "gate_decision",
            "gate_id": gate_id,
            "gate_owner": gate_owner,
            "protected_area": protected_area,
            "decision": decision,
            "reason": reason,
            "evidence": evidence,
            "rollback_required": rollback_required,
        })

    def emit_omi_gap_check_event(
        self,
        check_id: str,
        status: str,  # READY_FOR_DOCI_OR_DOCS_HANDOFF, READY_FOR_DOCI_OR_OMI_HANDOFF, NEEDS_CONTEXT, BLOCK
        trigger_count: int = 1,
        false_positive_review_flag: bool = False,
        rollback_flag: bool = False,
    ) -> None:
        """Emit Omi document-dialogue-gap-check event."""
        self._emit({
            "type": "omi_gap_check",
            "check_id": check_id,
            "status": status,
            "trigger_count": trigger_count,
            "ready_for_doci_or_docs_handoff_count": 1 if status == "READY_FOR_DOCI_OR_DOCS_HANDOFF" else 0,
            "ready_for_doci_or_omi_handoff_count": 1 if status == "READY_FOR_DOCI_OR_OMI_HANDOFF" else 0,
            "needs_context_count": 1 if status == "NEEDS_CONTEXT" else 0,
            "block_count": 1 if status == "BLOCK" else 0,
            "false_positive_review_flag": false_positive_review_flag,
            "rollback_flag": rollback_flag,
        })

    def emit_incident_event(
        self,
        incident_id: str,
        detected_by: str,  # Watchdog, Argus
        affected_service: str,
        severity: str,  # low, medium, high, critical
        incident_type: str,  # unhealthy, restart_loop, timeout, resource_warning
        queue_backlog: Optional[int] = None,
        restart_loop_detected: bool = False,
        key_warning: Optional[str] = None,
        ceo_escalation_required: bool = False,
    ) -> None:
        """Emit runtime incident event."""
        self._emit({
            "type": "runtime_incident",
            "incident_id": incident_id,
            "detected_by": detected_by,
            "affected_service": affected_service,
            "severity": severity,
            "incident_type": incident_type,
            "queue_backlog": queue_backlog,
            "restart_loop_detected": restart_loop_detected,
            "unhealthy_service_detected": incident_type in {"unhealthy", "restart_loop", "timeout"},
            "key_warning": key_warning,
            "ceo_escalation_required": ceo_escalation_required,
        })

    def emit_approval_request_event(
        self,
        request_id: str,
        requesting_agent: str,
        target_area: str,
        approval_required: bool,
        risk_level: str,  # low, medium, high
        expected_effect: str,
        rollback_plan: str,
        user_decision: Optional[str] = None,  # APPROVED, REJECTED, PENDING
        status: str = "pending",
    ) -> None:
        """Emit approval request event."""
        self._emit({
            "type": "approval_request",
            "request_id": request_id,
            "requesting_agent": requesting_agent,
            "target_area": target_area,
            "approval_required": approval_required,
            "risk_level": risk_level,
            "expected_effect": expected_effect,
            "rollback_plan": rollback_plan,
            "user_decision": user_decision,
            "status": status,
        })

    def emit_ceo_escalation_event(
        self,
        escalation_id: str,
        escalation_type: str,  # approval_required, incident_critical, resource_limit, strategic_decision
        reason: str,
        affected_pipeline: str,
        required_decision: str,
        urgency: str,  # low, medium, high, critical
        subscription_or_limit: Optional[str] = None,
    ) -> None:
        """Emit CEO escalation event."""
        self._emit({
            "type": "ceo_escalation",
            "escalation_id": escalation_id,
            "escalation_type": escalation_type,
            "reason": reason,
            "affected_pipeline": affected_pipeline,
            "required_decision": required_decision,
            "urgency": urgency,
            "subscription_or_limit": subscription_or_limit,
        })

    def summarize_events(self) -> Dict[str, Any]:
        """Summarize all emitted events."""
        event_types = dict(self.event_counts)
        gap_events = [e for e in self.events if e.get("type") == "omi_gap_check"]
        return {
            "total_events": len(self.events),
            "event_types": event_types,
            "handoff_event_count": event_types.get("pipeline_handoff", 0),
            "gate_decision_count": event_types.get("gate_decision", 0),
            "omi_gap_check_count": event_types.get("omi_gap_check", 0),
            "omi_gap_ready_for_docs_count": sum(int(e.get("ready_for_doci_or_docs_handoff_count", 0)) for e in gap_events),
            "omi_gap_ready_for_omi_count": sum(int(e.get("ready_for_doci_or_omi_handoff_count", 0)) for e in gap_events),
            "omi_gap_needs_context_count": sum(int(e.get("needs_context_count", 0)) for e in gap_events),
            "omi_gap_block_count": sum(int(e.get("block_count", 0)) for e in gap_events),
            "incident_event_count": event_types.get("runtime_incident", 0),
            "approval_request_count": event_types.get("approval_request", 0),
            "ceo_escalation_count": event_types.get("ceo_escalation", 0),
            "events_file": str(self.output_dir / "events.jsonl"),
            "timestamp": _now_utc(),
        }

    def save_summary(self, output_file: Optional[str] = None) -> str:
        """Save telemetry summary to JSON file."""
        if output_file is None:
            output_file = str(self.output_dir / "telemetry_summary.json")
        
        summary = self.summarize_events()
        summary["events"] = self.events
        
        with open(output_file, "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        return output_file

    def validate_events(self) -> Dict[str, Any]:
        """Validate all events for schema correctness."""
        issues = []
        valid_types = {
            "pipeline_handoff",
            "gate_decision",
            "omi_gap_check",
            "runtime_incident",
            "approval_request",
            "ceo_escalation",
        }
        
        for event in self.events:
            if "type" not in event:
                issues.append(f"Event missing 'type' field: {event}")
            elif event["type"] not in valid_types:
                issues.append(f"Event has unknown type: {event['type']}")
            
            if "timestamp" not in event:
                issues.append(f"Event missing 'timestamp': {event}")
            
            if "event_id" not in event:
                issues.append(f"Event missing 'event_id': {event}")
        
        return {
            "valid": len(issues) == 0,
            "total_events": len(self.events),
            "issues": issues,
        }


def _writer(output_dir: str | None = None) -> PipelineTelemetry:
    return PipelineTelemetry(output_dir=output_dir or DEFAULT_TELEMETRY_DIR)


def emit_handoff_event(
    *,
    pipeline_id: str,
    task_id: str,
    source_agent: str,
    target_agent: str,
    intent: str,
    handoff_status: str,
    required_inputs_present: bool,
    evidence_required: bool,
    approval_required: bool,
    result_status: str,
    output_dir: str | None = None,
) -> dict[str, Any]:
    writer = _writer(output_dir)
    writer.emit_handoff_event(
        pipeline_id=pipeline_id,
        task_id=task_id,
        source_agent=source_agent,
        target_agent=target_agent,
        intent=intent,
        handoff_status=handoff_status,
        required_inputs_present=required_inputs_present,
        evidence_required=evidence_required,
        approval_required=approval_required,
        result_status=result_status,
    )
    return writer.events[-1]


def emit_gate_decision(
    *,
    gate_id: str,
    gate_owner: str,
    protected_area: str,
    decision: str,
    reason: str,
    evidence: str = "",
    rollback_required: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    writer = _writer(output_dir)
    writer.emit_gate_decision(
        gate_id=gate_id,
        gate_owner=gate_owner,
        protected_area=protected_area,
        decision=decision,
        reason=reason,
        evidence=evidence,
        rollback_required=rollback_required,
    )
    return writer.events[-1]


def emit_omi_gap_check_event(
    *,
    check_id: str,
    status: str,
    trigger_count: int = 1,
    false_positive_review_flag: bool = False,
    rollback_flag: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    writer = _writer(output_dir)
    writer.emit_omi_gap_check_event(
        check_id=check_id,
        status=status,
        trigger_count=trigger_count,
        false_positive_review_flag=false_positive_review_flag,
        rollback_flag=rollback_flag,
    )
    return writer.events[-1]


def emit_incident_event(
    *,
    incident_id: str,
    detected_by: str,
    affected_service: str,
    severity: str,
    incident_type: str,
    queue_backlog: Optional[int] = None,
    restart_loop_detected: bool = False,
    key_warning: Optional[str] = None,
    ceo_escalation_required: bool = False,
    output_dir: str | None = None,
) -> dict[str, Any]:
    writer = _writer(output_dir)
    writer.emit_incident_event(
        incident_id=incident_id,
        detected_by=detected_by,
        affected_service=affected_service,
        severity=severity,
        incident_type=incident_type,
        queue_backlog=queue_backlog,
        restart_loop_detected=restart_loop_detected,
        key_warning=key_warning,
        ceo_escalation_required=ceo_escalation_required,
    )
    return writer.events[-1]


def emit_approval_request_event(
    *,
    request_id: str,
    requesting_agent: str,
    target_area: str,
    approval_required: bool,
    risk_level: str,
    expected_effect: str,
    rollback_plan: str,
    user_decision: Optional[str] = None,
    status: str = "pending",
    output_dir: str | None = None,
) -> dict[str, Any]:
    writer = _writer(output_dir)
    writer.emit_approval_request_event(
        request_id=request_id,
        requesting_agent=requesting_agent,
        target_area=target_area,
        approval_required=approval_required,
        risk_level=risk_level,
        expected_effect=expected_effect,
        rollback_plan=rollback_plan,
        user_decision=user_decision,
        status=status,
    )
    return writer.events[-1]


def emit_ceo_escalation_event(
    *,
    escalation_id: str,
    escalation_type: str,
    reason: str,
    affected_pipeline: str,
    required_decision: str,
    urgency: str,
    subscription_or_limit: Optional[str] = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    writer = _writer(output_dir)
    writer.emit_ceo_escalation_event(
        escalation_id=escalation_id,
        escalation_type=escalation_type,
        reason=reason,
        affected_pipeline=affected_pipeline,
        required_decision=required_decision,
        urgency=urgency,
        subscription_or_limit=subscription_or_limit,
    )
    return writer.events[-1]


def summarize_telemetry_events(output_dir: str = DEFAULT_TELEMETRY_DIR) -> Dict[str, Any]:
    """Summarize telemetry events from an existing JSONL file."""
    path = Path(output_dir) / "events.jsonl"
    if not path.exists():
        return {
            "total_events": 0,
            "event_types": {},
            "handoff_event_count": 0,
            "gate_decision_count": 0,
            "omi_gap_check_count": 0,
            "omi_gap_ready_for_docs_count": 0,
            "omi_gap_ready_for_omi_count": 0,
            "omi_gap_needs_context_count": 0,
            "omi_gap_block_count": 0,
            "incident_event_count": 0,
            "approval_request_count": 0,
            "ceo_escalation_count": 0,
            "events_file": str(path),
            "timestamp": _now_utc(),
        }
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        events.append(json.loads(line))
    counts: Dict[str, int] = {}
    gap_events = [e for e in events if e.get("type") == "omi_gap_check"]
    for e in events:
        t = str(e.get("type", "unknown"))
        counts[t] = counts.get(t, 0) + 1
    return {
        "total_events": len(events),
        "event_types": counts,
        "handoff_event_count": counts.get("pipeline_handoff", 0),
        "gate_decision_count": counts.get("gate_decision", 0),
        "omi_gap_check_count": counts.get("omi_gap_check", 0),
        "omi_gap_ready_for_docs_count": sum(int(e.get("ready_for_doci_or_docs_handoff_count", 0)) for e in gap_events),
        "omi_gap_ready_for_omi_count": sum(int(e.get("ready_for_doci_or_omi_handoff_count", 0)) for e in gap_events),
        "omi_gap_needs_context_count": sum(int(e.get("needs_context_count", 0)) for e in gap_events),
        "omi_gap_block_count": sum(int(e.get("block_count", 0)) for e in gap_events),
        "incident_event_count": counts.get("runtime_incident", 0),
        "approval_request_count": counts.get("approval_request", 0),
        "ceo_escalation_count": counts.get("ceo_escalation", 0),
        "events_file": str(path),
        "timestamp": _now_utc(),
    }
