#!/usr/bin/env python3
"""Smoke test for Agent Factory OS pipeline telemetry."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agents.pipeline_telemetry import (
    PipelineTelemetry,
    emit_approval_request_event,
    emit_ceo_escalation_event,
    emit_gate_decision,
    emit_handoff_event,
    emit_incident_event,
    emit_omi_gap_check_event,
    summarize_telemetry_events,
)


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def run_smoke() -> dict:
    issues: list[str] = []

    with tempfile.TemporaryDirectory(prefix="pipeline_telemetry_smoke_") as tmpdir:
        out_dir = Path(tmpdir)

        # 1. Axi -> Omi -> Doci handoff event
        emit_handoff_event(
            pipeline_id="customer_document_intake_routing",
            task_id="task_001",
            source_agent="axi",
            target_agent="omi",
            intent="validate_document_dialogue_gap",
            handoff_status="SUCCESS",
            required_inputs_present=True,
            evidence_required=True,
            approval_required=False,
            result_status="READY_FOR_DOCI_OR_OMI_HANDOFF",
            output_dir=str(out_dir),
        )

        # 2. Security/Poli gate decision
        emit_gate_decision(
            gate_id="security_poli_001",
            gate_owner="Security",
            protected_area="production_registry",
            decision="BLOCK",
            reason="direct_db_write_requested",
            evidence="doc_dialogue_gap_gate",
            rollback_required=True,
            output_dir=str(out_dir),
        )

        # 3. QA / Release gate decision
        emit_gate_decision(
            gate_id="qa_release_001",
            gate_owner="Release",
            protected_area="release_readiness",
            decision="NEEDS_APPROVAL",
            reason="qa_current_evidence_required",
            evidence="qa_current_missing",
            rollback_required=True,
            output_dir=str(out_dir),
        )

        # 4. Omi document-dialogue-gap-check NEEDS_CONTEXT event
        emit_omi_gap_check_event(
            check_id="omi_gap_001",
            status="NEEDS_CONTEXT",
            trigger_count=1,
            false_positive_review_flag=False,
            rollback_flag=False,
            output_dir=str(out_dir),
        )

        # 5. Runtime incident event
        emit_incident_event(
            incident_id="incident_001",
            detected_by="Watchdog",
            affected_service="omi-bot",
            severity="medium",
            incident_type="unhealthy",
            queue_backlog=12,
            restart_loop_detected=False,
            key_warning=None,
            ceo_escalation_required=False,
            output_dir=str(out_dir),
        )

        # 6. Approval request event
        emit_approval_request_event(
            request_id="approval_001",
            requesting_agent="omi",
            target_area="runtime_activation",
            approval_required=True,
            risk_level="medium",
            expected_effect="enable gated runtime validation",
            rollback_plan="set runtime_activation=false",
            user_decision="APPROVED",
            status="approved",
            output_dir=str(out_dir),
        )

        # 7. CEO escalation event
        emit_ceo_escalation_event(
            escalation_id="escalation_001",
            escalation_type="resource_limit",
            reason="subscription_limit_reached",
            affected_pipeline="knowledge_support_workflow",
            required_decision="increase_limit_or_throttle",
            urgency="high",
            subscription_or_limit="subscription_limit",
            output_dir=str(out_dir),
        )

        # 8. Secret redaction isolated in a second temp writer so sample counts stay deterministic.
        with tempfile.TemporaryDirectory(prefix="pipeline_telemetry_redaction_") as redacted_dir:
            redacted_telemetry = PipelineTelemetry(output_dir=redacted_dir)
            redacted_telemetry._emit(  # noqa: SLF001 - intentional smoke validation of the safe writer path
                {
                    "type": "approval_request",
                    "request_id": "approval_secret",
                    "requesting_agent": "security",
                    "target_area": "keys",
                    "approval_required": True,
                    "risk_level": "high",
                    "expected_effect": "rotate keys",
                    "rollback_plan": "restore previous config",
                    "user_decision": "PENDING",
                    "status": "pending",
                    "token": "sk-test-ABCDEF123456",
                    "password": "password=supersecret",
                    "api_key": "api_key=ABC-SECRET-123",
                    "bearer": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
                }
            )
            redacted_events = _load_jsonl(Path(redacted_dir) / "events.jsonl")
            if not redacted_events:
                issues.append("redaction test did not write an event")
            else:
                redacted_payload = json.dumps(redacted_events[0], ensure_ascii=False)
                if "sk-test-ABCDEF123456" in redacted_payload:
                    issues.append("secret key was not redacted")
                if "supersecret" in redacted_payload:
                    issues.append("password was not redacted")
                if "ABC-SECRET-123" in redacted_payload:
                    issues.append("api key was not redacted")
                if "Bearer eyJhbGci" in redacted_payload and "[REDACTED_TOKEN]" not in redacted_payload:
                    issues.append("bearer token was not redacted")

        events_file = out_dir / "events.jsonl"
        if not events_file.exists():
            issues.append("events.jsonl was not created")
        else:
            try:
                events = _load_jsonl(events_file)
            except Exception as exc:  # pragma: no cover - explicit smoke reporting
                issues.append(f"events.jsonl invalid JSONL: {exc}")
                events = []

            expected_types = {
                "pipeline_handoff": 1,
                "gate_decision": 2,
                "omi_gap_check": 1,
                "runtime_incident": 1,
                "approval_request": 1,
                "ceo_escalation": 1,
            }
            counts: dict[str, int] = {}
            for event in events:
                if not isinstance(event, dict):
                    issues.append(f"event is not a dict: {event!r}")
                    continue
                for field in ("type", "timestamp", "event_id"):
                    if field not in event:
                        issues.append(f"missing field {field} in event: {event}")
                etype = str(event.get("type", "unknown"))
                counts[etype] = counts.get(etype, 0) + 1

            for etype, expected in expected_types.items():
                if counts.get(etype, 0) != expected:
                    issues.append(f"event count mismatch for {etype}: expected {expected}, got {counts.get(etype, 0)}")
            redacted_text = events_file.read_text(encoding="utf-8", errors="replace")
            if "sk-test-ABCDEF123456" in redacted_text or "supersecret" in redacted_text:
                issues.append("secret-like values were not redacted")
            if "Bearer " in redacted_text and "[REDACTED_TOKEN]" not in redacted_text:
                issues.append("Bearer token was not redacted")

        summary = summarize_telemetry_events(output_dir=str(out_dir))
        if summary["total_events"] < 7:
            issues.append(f"unexpected total events: {summary['total_events']}")
        if summary["handoff_event_count"] != 1:
            issues.append("handoff_event_count mismatch")
        if summary["gate_decision_count"] != 2:
            issues.append("gate_decision_count mismatch")
        if summary["omi_gap_check_count"] != 1:
            issues.append("omi_gap_check_count mismatch")
        if summary["omi_gap_needs_context_count"] != 1:
            issues.append("omi_gap_needs_context_count mismatch")
        if summary["incident_event_count"] != 1:
            issues.append("incident_event_count mismatch")
        if summary["approval_request_count"] < 1:
            issues.append("approval_request_count mismatch")
        if summary["ceo_escalation_count"] != 1:
            issues.append("ceo_escalation_count mismatch")

        summary_path = out_dir / "telemetry_summary.json"
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        return {
            "status": "pass" if not issues else "fail",
            "issues": issues,
            "sample_events_total": summary["total_events"],
            "sample_events_valid": not issues,
            "event_types": summary["event_types"],
            "summary_path": str(summary_path),
            "events_file": str(events_file),
            "output_dir": str(out_dir),
            "production_db_changed": False,
            "service_restarted": False,
            "model_calls": False,
            "network_calls": False,
        }


def main() -> int:
    result = run_smoke()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
