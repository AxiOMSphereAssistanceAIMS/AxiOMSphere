#!/usr/bin/env python3
"""Argus Passive Pipeline Telemetry Integration Smoke Test.

Tests that Argus can emit telemetry events for health incidents
without breaking existing health check behavior.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Test that imports work
try:
    from agents.pipeline_telemetry import PipelineTelemetry
except ImportError as e:
    print(f"ERROR: Could not import telemetry module: {e}")
    sys.exit(1)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class MockMonitorEvent:
    """Mock MonitorEvent for testing."""

    def __init__(self, service: str, event_type: str, message: str, severity: str = "warning"):
        self.service = service
        self.event_type = event_type
        self.message = message
        self.severity = severity
        self.inc_id = 1


def emit_argus_telemetry_event(ev: MockMonitorEvent, telemetry: PipelineTelemetry) -> None:
    """Mimic the _emit_argus_telemetry_event function from argus_bot.py."""
    try:
        severity_map = {
            "critical": "critical",
            "warning": "medium",
            "info": "low",
        }
        severity = severity_map.get(ev.severity, "medium")

        incident_type_map = {
            "crash": "unhealthy",
            "oom": "resource_warning",
            "hang": "unhealthy",
            "restart_loop": "restart_loop",
            "log_error": "unhealthy",
            "test_fail": "unhealthy",
            "schedule_miss": "unhealthy",
            "model_missing": "resource_warning",
        }
        incident_type = incident_type_map.get(ev.event_type, "unhealthy")

        ceo_escalation_required = ev.severity == "critical" or incident_type == "restart_loop"

        import time
        telemetry.emit_incident_event(
            incident_id=f"argus_{ev.inc_id}_{int(time.time())}",
            detected_by="Argus",
            affected_service=ev.service,
            severity=severity,
            incident_type=incident_type,
            queue_backlog=None,
            restart_loop_detected=(incident_type == "restart_loop"),
            key_warning=None,
            ceo_escalation_required=ceo_escalation_required,
        )

        if ceo_escalation_required:
            telemetry.emit_ceo_escalation_event(
                escalation_id=f"escalation_argus_{ev.inc_id}",
                escalation_type="incident_critical",
                reason=f"Argus detected {incident_type}: {ev.message[:100]}",
                affected_pipeline="runtime_incident_workflow",
                required_decision="Review incident and restart if safe",
                urgency=ev.severity,
                subscription_or_limit=None,
            )
    except Exception as exc:
        # Telemetry failures must not break Argus
        raise AssertionError(f"Telemetry emission failed: {exc}")


def run_smoke() -> dict:
    """Run Argus telemetry integration smoke test."""
    issues = []

    with tempfile.TemporaryDirectory(prefix="argus_telemetry_") as tmpdir:
        telemetry = PipelineTelemetry(output_dir=tmpdir)

        # Test 1: Unhealthy service incident
        try:
            ev = MockMonitorEvent("omi-agent", "hang", "Omi agent not responding")
            emit_argus_telemetry_event(ev, telemetry)
        except Exception as e:
            issues.append(f"Unhealthy service event failed: {e}")

        # Test 2: Restart loop incident
        try:
            ev = MockMonitorEvent("doci-agent", "restart_loop", "Doci restarting repeatedly")
            emit_argus_telemetry_event(ev, telemetry)
        except Exception as e:
            issues.append(f"Restart loop event failed: {e}")

        # Test 3: OOM incident
        try:
            ev = MockMonitorEvent("knomi-agent", "oom", "Out of memory")
            emit_argus_telemetry_event(ev, telemetry)
        except Exception as e:
            issues.append(f"OOM event failed: {e}")

        # Test 4: Model missing warning
        try:
            ev = MockMonitorEvent("argus-bot", "model_missing", "Model not found in Ollama")
            emit_argus_telemetry_event(ev, telemetry)
        except Exception as e:
            issues.append(f"Model missing event failed: {e}")

        # Test 5: Critical service failure
        try:
            ev = MockMonitorEvent("omi-api", "crash", "Service crashed", severity="critical")
            emit_argus_telemetry_event(ev, telemetry)
        except Exception as e:
            issues.append(f"Critical incident event failed: {e}")

        # Verify events were written
        events_file = Path(tmpdir) / "events.jsonl"
        if not events_file.exists():
            issues.append("Events JSONL file was not created")
        else:
            try:
                with open(events_file) as f:
                    lines = f.readlines()
                    if len(lines) < 5:
                        issues.append(f"Expected at least 5 events, got {len(lines)}")

                    # Check for runtime_incident events
                    runtime_incident_count = 0
                    ceo_escalation_count = 0

                    for line in lines:
                        event = json.loads(line)
                        if event.get("type") == "runtime_incident":
                            runtime_incident_count += 1
                        elif event.get("type") == "ceo_escalation":
                            ceo_escalation_count += 1

                    if runtime_incident_count < 5:
                        issues.append(
                            f"Expected 5+ runtime_incident events, got {runtime_incident_count}"
                        )
                    if ceo_escalation_count < 2:
                        issues.append(
                            f"Expected 2+ ceo_escalation events, got {ceo_escalation_count}"
                        )

            except json.JSONDecodeError as e:
                issues.append(f"Invalid JSONL format: {e}")

        # Verify no secrets in events
        with open(events_file) as f:
            content = f.read()
            secret_patterns = ["sk-[a-z0-9]", "api_key=", "token=", "password="]
            for pattern in secret_patterns:
                if pattern.lower() in content.lower():
                    issues.append(f"Potential secret pattern found: {pattern}")

    return {
        "status": "pass" if not issues else "fail",
        "issues": issues,
        "total_events": len(lines) if "lines" in locals() else 0,
        "runtime_incident_count": runtime_incident_count if "runtime_incident_count" in locals() else 0,
        "ceo_escalation_count": ceo_escalation_count if "ceo_escalation_count" in locals() else 0,
    }


def main() -> int:
    """Run smoke test and output results."""
    result = run_smoke()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
