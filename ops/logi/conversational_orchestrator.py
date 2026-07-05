"""Logi Conversational Orchestrator — CEO/strategy planning interface.

This is a minimal implementation to support skill-wiring verification.
Full orchestrator implementation will be in Phase 5.

Integrated features:
- Supervised Full Stack delivery (test-production mode)
- Continuous work mode with protected-action gating
- All solutions routed through Claude Code for review
- Normal in-scope work is task-scope executable
- Only one final safety gate remains at task end
- Exception actions are blocked/deferred by policy rather than repeatedly asking the user
- Logi never stops with blocker-only responses
"""
from __future__ import annotations

import os
import json
import re
from pathlib import Path
from datetime import datetime

# Import canonical executor task regex from local_executor_action (single source of truth).
# Covers English strict/natural + Russian/mixed forms.
from ops.agents.local_executor_action import EXECUTOR_TASK_RE as _EXECUTOR_TASK_RE

from logi.claude_review_queue import (
    create_review_request_from_logi_artifact,
    get_queue_status,
    get_review_status,
    load_review_result,
    apply_review_recommendations,
)
from logi.claude_review_transport_policy import is_claude_code_auto_review_enabled
from logi.syntax_intent_schema import SyntaxIntent

# Phase 1 Skill: context-compression
try:
    from ops.ecc_skills.phase_1_context.context_compression import ContextCompressor
    ECC_CONTEXT_COMPRESSOR_AVAILABLE = True
except ImportError:
    ECC_CONTEXT_COMPRESSOR_AVAILABLE = False

# Test-production mode: enable supervised full stack delivery routing
LOGI_SUPERVISED_FULL_STACK_MODE_ENABLED = os.environ.get(
    "AIMS_ENABLE_LOGI_SUPERVISED_FULL_STACK_MODE", "true"
).lower() in ("true", "1", "yes")

# Continuous work mode: Logi works on allowed actions, protected actions gated by Claude Code + policy
LOGI_CONTINUOUS_WORK_MODE_ENABLED = os.environ.get(
    "AIMS_ENABLE_LOGI_CONTINUOUS_WORK_MODE", "true"
).lower() in ("true", "1", "yes")


class LogiAgent:
    """Logi agent — CEO/strategy planning orchestrator.

    Minimal implementation for Phase 4 skill wiring verification.

    In continuous work mode:
    - Planning and analysis work never blocked (always allowed)
    - Code repairs/executions require Claude Code review before execution
    - Protected actions (training, model ops, service restart, data mutation) are blocked/deferred out_of_policy unless separately pre-approved
    - Logi always produces useful allowed work, never returns blocker-only responses
    """

    def __init__(self):
        """Initialize Logi agent."""
        self.user_history = {}
        self.supervised_delivery_adapter = None
        self.claude_code_gate = None
        self.context_compressor = None
        self.compression_stats = {"ratio": 0.0, "tokens_saved": 0}

        # Initialize Phase 1 context-compression skill
        if ECC_CONTEXT_COMPRESSOR_AVAILABLE:
            try:
                self.context_compressor = ContextCompressor()
            except Exception as e:
                self.context_compressor = None

        # Lazy-load supervised delivery adapter if enabled
        if LOGI_SUPERVISED_FULL_STACK_MODE_ENABLED:
            try:
                from logi.supervised_full_stack_orchestrator_adapter import handle_full_stack_request
                self.handle_full_stack = handle_full_stack_request
            except ImportError:
                self.handle_full_stack = None

        # Load Claude Code gate if continuous work mode enabled
        if LOGI_CONTINUOUS_WORK_MODE_ENABLED:
            try:
                from logi.claude_code_cli_gate import get_gate
                from logi.logi_duties_rights_unrestricted import summarize_duties
                self.claude_code_gate = get_gate()
                self.duties_summary = summarize_duties()
            except ImportError:
                self.claude_code_gate = None
                self.duties_summary = None

    def _compress_context(self, context_data: dict) -> dict:
        """Apply Phase 1 context-compression skill to reduce token usage.

        Args:
            context_data: Dictionary with context information

        Returns:
            Compressed context dictionary with compression metrics
        """
        if not self.context_compressor:
            return context_data

        try:
            # Build task context and compress
            task_type = context_data.get("task_type", "general")
            compressed = self.context_compressor.build_logi_task_context(task_type, context_data)

            # Track compression metrics
            original_size = len(str(context_data))
            compressed_size = len(str(compressed))
            ratio = 1 - (compressed_size / original_size) if original_size > 0 else 0

            self.compression_stats["ratio"] = ratio
            self.compression_stats["tokens_saved"] = original_size - compressed_size

            return compressed
        except Exception:
            # Graceful degradation: return original context if compression fails
            return context_data

    def _is_claude_review_transport_request(self, text: str) -> bool:
        """Detect a request to send work to Claude Code review transport."""
        lowered = text.lower()
        return (
            "claude code" in lowered
            and (
                "review" in lowered
                or "decision" in lowered
                or "approval" in lowered
                or "right decision" in lowered
                or "right call" in lowered
            )
        )

    def _latest_logi_artifact_path(self) -> str | None:
        """Return the newest Logi artifact, if any."""
        artifacts_dir = Path("aims_workspace/logi_artifacts")
        if not artifacts_dir.exists():
            return None

        candidates = [p for p in artifacts_dir.glob("*.json") if p.is_file()]
        if not candidates:
            return None

        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        return str(newest)

    def _ensure_transport_artifact(self, text: str) -> str:
        """Use the latest Logi artifact or create a minimal request artifact."""
        latest = self._latest_logi_artifact_path()
        if latest:
            return latest

        artifacts_dir = Path("aims_workspace/logi_artifacts")
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = artifacts_dir / f"logi_claude_review_request_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.json"
        payload = {
            "metadata": {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "artifact_type": "claude_review_transport_request",
            },
            "objective": text,
            "status": "DRAFT_PENDING_CLAUDE_REVIEW",
            "logi_local_attempt": {"objective": text},
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(path)

    def _build_plain_reply(self, text: str, skill_context: str = "") -> str:
        """Return a short answer for ordinary Telegram chat."""
        lowered = text.lower().strip()

        readiness_markers = (
            "ты готов работать",
            "готов работать",
            "ready to work",
            "are you ready",
            "can you work",
        )
        if any(marker in lowered for marker in readiness_markers):
            return "Да, готов."

        if lowered.endswith("?"):
            if skill_context:
                return "Да. Разберу вопрос по контексту и отвечу кратко."
            return "Да. Разберу вопрос и отвечу кратко."

        if skill_context:
            return "Принял. Работаю по контексту."
        return "Принял. Работаю."

    def _handle_claude_review_transport(self, text: str) -> str:
        """Create a review request and report queue status without fake acknowledgements."""
        artifact_path = self._ensure_transport_artifact(text)
        review_id = create_review_request_from_logi_artifact(
            artifact_path,
            text,
            acceptance_criteria=[
                "Review request created",
                "Queue status visible",
                "Corrected plan or feedback returned when completed",
                "No automatic execution after review",
            ],
        )

        status = get_review_status(review_id) or {}
        queue = get_queue_status()
        auto_enabled = is_claude_code_auto_review_enabled()
        result = load_review_result(review_id)

        lines = [
            "Claude Code review transport:",
            f"- review request created: YES",
            f"- review_id: {review_id}",
            f"- source artifact: {artifact_path}",
            f"- queue status: {status.get('status', 'pending')}",
            f"- queue path: {status.get('queue_path', 'aims_workspace/logi_claude_review_queue/pending/unknown.json')}",
            f"- queue counts: pending={queue['pending']} in_progress={queue['in_progress']} completed={queue['completed']} failed={queue['failed']}",
            f"- auto-review enabled: {'YES' if auto_enabled else 'NO'}",
            f"- task-scope execution allowed: YES",
            f"- final safety gate: {status.get('final_gate_status', 'PENDING')}",
        ]

        if auto_enabled:
            lines.append("Claude Code auto-review is enabled.")
            lines.append("- env flag: AIMS_ENABLE_CLAUDE_CODE_AUTO_REVIEW=1")
            lines.append("- next step: worker may be run manually or by local transport; final safety gate is checked after review completion.")
        else:
            lines.append("Claude Code auto-review is not enabled.")
            lines.append("- env flag required: AIMS_ENABLE_CLAUDE_CODE_AUTO_REVIEW=1")
            lines.append("- next step: run worker manually or enable env")

        if result:
            execution = apply_review_recommendations(result, artifact_path=artifact_path)
            result = load_review_result(review_id) or result
            lines.extend([
                f"- review result path: aims_workspace/logi_claude_review_queue/completed/{review_id}.json",
                f"- verdict: {result.get('verdict', 'unknown')}",
                f"- corrected_plan summary: {list((result.get('corrected_plan') or {}).keys())[:8]}",
                f"- feedback_for_logi: {result.get('feedback_for_logi', '')[:400]}",
                f"- recommendation execution status: {execution.get('status', 'unknown')}",
                f"- recommendations executed: {', '.join(execution.get('applied_recommendations', [])) or 'none'}",
                f"- repairman requests dispatched: {len(execution.get('repairman_request_paths', []))}",
            ])
        else:
            lines.extend([
                "- review result path: not available yet",
                "- verdict: pending",
            ])

        return "\n".join(lines)

    def run(self, user_id: int, text: str, notify_callback=None, skill_context: str = "") -> str:
        """Execute Logi orchestration with skill context.

        Args:
            user_id: Telegram user ID
            text: User input text
            notify_callback: Optional callback for status updates
            skill_context: Strategy skill pack context (injected from LOGI_SKILL_CONTEXT)

        Returns:
            Response text
        """
        # Minimal implementation: echo + placeholder
        if not text:
            return "(empty request)"

        # Store in history
        if user_id not in self.user_history:
            self.user_history[user_id] = []
        self.user_history[user_id].append(text)

        # Phase 1 Skill: Apply context-compression to reduce token usage
        context_for_compression = {
            "task_type": "user_query",
            "user_history_size": len(self.user_history.get(user_id, [])),
            "input_text": text,
            "skill_context_available": bool(skill_context)
        }
        _ = self._compress_context(context_for_compression)

        # ── Approved local executor route ────────────────────────────────────
        # Narrow allowlisted path: only python3 aims_local_executor.py <task_json>
        # under aims_workspace/test_tasks/. No arbitrary shell execution.
        _executor_match = _EXECUTOR_TASK_RE.search(text or "")
        if _executor_match:
            task_json = _executor_match.group(1).strip()
            try:
                from ops.agents.local_executor_action import (
                    run_local_executor_task,
                    format_telegram_executor_result,
                    validate_executor_message,
                    LocalExecutorActionResult,
                )
                msg_ok, msg_reason = validate_executor_message(text or "")
                if not msg_ok:
                    blocked = LocalExecutorActionResult(
                        status="FAILED",
                        execution_route="logi_telegram_local_executor",
                        task_json=task_json,
                        stdout="", stderr=msg_reason, exit_code=1,
                        executor_result={},
                        file_created=False, content_verified=False,
                        sha256=None, error_class="COMMAND_BLOCKED",
                    )
                    return format_telegram_executor_result(blocked)
                result = run_local_executor_task(task_json)
                return format_telegram_executor_result(result)
            except Exception as exc:
                return f"STATUS: FAILED\nERROR_CLASS: EXECUTOR_IMPORT_ERROR\nDETAIL: {exc}"
        # ─────────────────────────────────────────────────────────────────────

        # ── Confirmation flow: CONFIRM <action_id> ────────────────────────────
        try:
            from ops.agents.logi_confirmation_flow import (
                parse_confirm_intent,
                confirm_action,
                format_confirmation_response,
            )
            confirm_id = parse_confirm_intent(text or "")
            if confirm_id is not None:
                result = confirm_action(confirm_id)
                return format_confirmation_response(result)
        except Exception as exc:
            pass  # Never break main bot on confirmation errors
        # ─────────────────────────────────────────────────────────────────────

        # ── Confirmation flow: healthcheck intent ─────────────────────────────
        try:
            from ops.agents.logi_confirmation_flow import (
                parse_healthcheck_intent,
                request_healthcheck,
                format_confirmation_response,
            )
            intent = parse_healthcheck_intent(text or "")
            if intent is not None:
                if intent.get("blocked"):
                    return (
                        "STATUS: BLOCKED\n"
                        f"ERROR_CLASS: COMMAND_BLOCKED\n"
                        f"REASON: {intent.get('reason', '')}"
                    )
                resp = request_healthcheck(
                    raw_service=intent["raw_service"],
                    requested_by=str(user_id),
                    original_message=text or "",
                )
                return format_confirmation_response(resp)
        except Exception:
            pass  # Never break main bot on confirmation errors
        # ─────────────────────────────────────────────────────────────────────

        # ── Confirmation flow: read_logs_allowlisted intent ───────────────────
        try:
            from ops.agents.logi_confirmation_flow import (
                parse_read_logs_intent,
                request_read_logs,
                format_confirmation_response,
            )
            intent = parse_read_logs_intent(text or "")
            if intent is not None:
                if intent.get("blocked"):
                    return (
                        "STATUS: BLOCKED\n"
                        f"ERROR_CLASS: COMMAND_BLOCKED\n"
                        f"REASON: {intent.get('reason', '')}"
                    )
                resp = request_read_logs(
                    raw_service=intent["raw_service"],
                    lines=intent["lines"],
                    lines_clamped=intent["lines_clamped"],
                    requested_by=str(user_id),
                    original_message=text or "",
                )
                return format_confirmation_response(resp)
        except Exception:
            pass  # Never break main bot on confirmation errors
        # ─────────────────────────────────────────────────────────────────────

        # ── Confirmation flow: diagnose_service_allowlisted intent ────────────
        try:
            from ops.agents.logi_confirmation_flow import (
                parse_diagnose_intent,
                request_diagnose,
                format_confirmation_response,
            )
            intent = parse_diagnose_intent(text or "")
            if intent is not None:
                if intent.get("blocked"):
                    return (
                        "STATUS: BLOCKED\n"
                        f"ERROR_CLASS: COMMAND_BLOCKED\n"
                        f"REASON: {intent.get('reason', '')}"
                    )
                resp = request_diagnose(
                    raw_service=intent["raw_service"],
                    requested_by=str(user_id),
                    original_message=text or "",
                )
                return format_confirmation_response(resp)
        except Exception:
            pass  # Never break main bot on confirmation errors
        # ─────────────────────────────────────────────────────────────────────

        # Dedicated Claude Code review transport path must create a real queue request.
        if self._is_claude_review_transport_request(text):
            return self._handle_claude_review_transport(text)

        # Route Full Stack requests to supervised delivery (if enabled and available)
        if (LOGI_SUPERVISED_FULL_STACK_MODE_ENABLED and
            self.handle_full_stack is not None):
            try:
                is_full_stack, response, scenario = self.handle_full_stack(user_id, text, skill_context)
            except Exception as exc:
                return "Full Stack routing failed explicitly: " f"{type(exc).__name__}: {exc}"
            if is_full_stack:
                return response

        # Block dangerous execution intent without approved .json task path.
        # E.g. "Логи, выполни rm -rf ..." or "запусти docker restart ..."
        try:
            from ops.agents.local_executor_action import is_dangerous_execution_intent
            if is_dangerous_execution_intent(text or ""):
                return (
                    "STATUS: BLOCKED\n"
                    "EXECUTION_ROUTE: logi_telegram_local_executor\n"
                    "ERROR_CLASS: COMMAND_BLOCKED\n"
                    "REASON: dangerous command word detected in execution-intent message"
                )
        except Exception:
            pass

        # Plain text should stay short and context-shaped, without service banners.
        return self._build_plain_reply(text, skill_context=skill_context)

    def get_phase1_skill_status(self) -> dict:
        """Get status of Phase 1 deployed skills.

        Returns:
            Dictionary with skill statuses and metrics
        """
        return {
            "context_compression": {
                "available": self.context_compressor is not None,
                "compression_ratio": self.compression_stats.get("ratio", 0),
                "tokens_saved": self.compression_stats.get("tokens_saved", 0)
            }
        }

    def clear_history(self, user_id: int) -> None:
        """Clear conversation history for user."""
        if user_id in self.user_history:
            del self.user_history[user_id]
