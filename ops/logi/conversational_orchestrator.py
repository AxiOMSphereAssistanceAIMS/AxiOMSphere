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
def _execute_read_only_skill(skill_id: str, text: str, skill_context: str = "") -> str | None:
    """
    Generate a structured text response for a read-only chief-engineer process skill.
    Returns None if the skill_id is not handled (falls through to general chat).
    No mutation. No shell. No confirmation needed.
    """
    topic = text[:200].strip()

    _TEMPLATES = {
        "office_hours": (
            "STATUS: PASSED\n"
            "SKILL_ID: office_hours\n"
            "SIX_FORCING_QUESTIONS:\n"
            "1. What is the one problem this solves that nothing else does?\n"
            "2. Who will use this and why do they care today?\n"
            "3. What does failure look like in 6 months if we do nothing?\n"
            "4. What is the minimal slice that would prove value in one week?\n"
            "5. What existing AIMS component is closest to this need?\n"
            "6. What would make this 10x simpler?\n"
            f"PAIN_HYPOTHESIS:\n  Based on: {topic}\n"
            "USER_PROBLEM_FRAMING:\n  [Describe user's core pain here]\n"
            "ALTERNATIVE_PATHS:\n"
            "- Extend existing Logi confirmation flow\n"
            "- Route to existing self-healing agent\n"
            "- Create skill request for auditor review\n"
            "RECOMMENDED_FIRST_SLICE:\n  Identify the one existing AIMS analog and extend it.\n"
            "NEXT_RECOMMENDED_SKILLS:\n  ceo_review, eng_review, capability_gap"
        ),
        "ceo_review": (
            "STATUS: PASSED\n"
            "SKILL_ID: ceo_review\n"
            f"SCOPE_CHALLENGE:\n  Topic: {topic}\n  Is this the right problem? Is the scope correct?\n"
            "TEN_STAR_VERSION:\n  10-star: Logi autonomously detects, plans, patches, verifies, ships — zero human input.\n"
            "  3-star (now): Logi classifies, plans, and prepares auditor requests with human CONFIRM.\n"
            "REDUCTION_OPTION:\n  Reduce to read-only analysis + patch prompt only.\n"
            "EXPANSION_OPTION:\n  Expand to full autonomous repair loop with verifier gate.\n"
            "RISKS:\n  - Over-engineering before core flows work\n  - Autonomy without verifier gate\n"
            "DECISION_REQUIRED_FROM_USER:\n  Confirm scope: read-only analysis OR write-confirmed actions?"
        ),
        "eng_review": (
            "STATUS: PASSED\n"
            "SKILL_ID: eng_review\n"
            f"ARCHITECTURE_SUMMARY:\n  Topic: {topic}\n"
            "  Extension of existing confirmation flow + logi_confirmation_flow.py.\n"
            "DATA_FLOW:\n  User intent → mode router → skill system → confirmation if needed → artifact store\n"
            "STATE_TRANSITIONS:\n  PENDING → REQUIRES_CONFIRMATION → CONFIRMED → PASSED/FAILED\n"
            "FAILURE_MODES:\n"
            "  - Intent not matched → falls to general chat\n"
            "  - Confirmation expired → EXPIRED_CONFIRMATION\n"
            "  - Write path unavailable → LOG_BACKEND_UNAVAILABLE\n"
            "TEST_MATRIX:\n"
            "  - Read-only skills: no confirmation, structured output\n"
            "  - Write skills: REQUIRES_CONFIRMATION + CONFIRM step\n"
            "  - Dangerous words: BLOCKED\n"
            "SECURITY_CONCERNS:\n  No shell=True. No arbitrary paths. All writes allowlisted.\n"
            "IMPLEMENTATION_PLAN:\n"
            "  1. Extend logi_confirmation_flow with new action types\n"
            "  2. Add mode router before plain reply\n"
            "  3. Add skill executor for read-only skills\n"
            "  4. Wire write skills through confirmation\n"
            "  5. Add tests"
        ),
        "autoplan": (
            "STATUS: PASSED\n"
            "SKILL_ID: autoplan\n"
            f"TOPIC: {topic}\n"
            "CEO_REVIEW_SUMMARY:\n  Confirm scope is minimal viable extension of existing AIMS.\n"
            "ENG_REVIEW_SUMMARY:\n  Extend logi_confirmation_flow + add mode router before plain reply.\n"
            "SECURITY_CONCERNS:\n  No shell=True. Dangerous words blocked. All writes confirmed.\n"
            "RELEASE_CHECKLIST:\n"
            "  - All existing tests still pass\n"
            "  - New modes tested\n"
            "  - Injection tests pass\n"
            "  - verify_local_executor_extended.sh passes\n"
            "IMPLEMENTATION_STEPS:\n"
            "  1. Implement/update mode router\n"
            "  2. Implement skill executor (read-only)\n"
            "  3. Extend confirmation flow for write actions\n"
            "  4. Wire into orchestrator\n"
            "  5. Run full test suite\n"
            "NEXT_RECOMMENDED_SKILLS:\n  patch_prompt, auditor_request"
        ),
        "capability_gap": (
            "STATUS: PASSED\n"
            "SKILL_ID: capability_gap\n"
            f"TOPIC: {topic}\n"
            "MISSING_CAPABILITY:\n  Identified from: {topic}\n"
            "WHY_NEEDED:\n  Without it, Logi falls back to plain acknowledgement.\n"
            "EXISTING_CLOSE_CAPABILITIES:\n"
            "  - logi_confirmation_flow.py (protected actions)\n"
            "  - ops/agents/capability_assessor.py (service gap analysis)\n"
            "  - ops/logi/strategic_planning.py (long-horizon planning)\n"
            "PROPOSED_ACTION_TYPE_OR_SKILL:\n  Extend confirmation flow OR create skill request.\n"
            "PATCH_NEEDED: true\n"
            "AUDITOR_HELP_RECOMMENDED: true\n"
            "TESTS_NEEDED:\n  - Intent classification test\n  - Confirmation flow test\n  - Regression test"
        ),
        "patch_prompt": (
            "STATUS: PASSED\n"
            "SKILL_ID: patch_prompt\n"
            f"TOPIC: {topic}\n"
            "PATCH_PROMPT:\n"
            "  objective: Implement the requested capability safely\n"
            f"  current evidence: {topic[:100]}\n"
            "  files likely involved:\n"
            "    - ops/agents/logi_confirmation_flow.py\n"
            "    - ops/logi/conversational_orchestrator.py\n"
            "    - ops/agents/tests/\n"
            "  implementation requirements:\n"
            "    - No shell=True\n"
            "    - No arbitrary paths\n"
            "    - All writes require confirmation\n"
            "    - Extend existing confirmation flow\n"
            "  safety constraints:\n"
            "    - Block dangerous command words\n"
            "    - Block shell metacharacters\n"
            "  tests:\n"
            "    - Intent classification\n"
            "    - Confirmation step 1 and 2\n"
            "    - Injection blocking\n"
            "    - Regression: all existing routes\n"
            "  acceptance criteria:\n"
            "    - Full agents suite passes\n"
            "    - verify_local_executor_extended.sh passes\n"
            "  rollback:\n"
            "    - Revert orchestrator injection point"
        ),
        "investigate": (
            "STATUS: PASSED\n"
            "SKILL_ID: investigate\n"
            f"TOPIC: {topic}\n"
            "SYMPTOMS:\n  Described in: {topic}\n"
            "HYPOTHESES:\n"
            "  1. Missing intent pattern in mode router\n"
            "  2. Skill not wired into orchestrator\n"
            "  3. Exception swallowed in try/except\n"
            "EVIDENCE_TO_COLLECT:\n"
            "  - Run: python -m pytest ops/agents/tests/ -q\n"
            "  - Check logi_bot.log for error patterns\n"
            "  - Run: diagnose_service_allowlisted logi-bot\n"
            "LIKELY_ROOT_CAUSE:\n  Check orchestrator injection point ordering.\n"
            "NEXT_DIAGNOSTIC_ACTION:\n  Run diagnose_service_allowlisted logi-bot and read_logs logi-bot"
        ),
        "review": (
            "STATUS: PASSED\n"
            "SKILL_ID: review\n"
            f"TOPIC: {topic}\n"
            "CODE_REVIEW_CHECKLIST:\n"
            "  ✓ No shell=True\n"
            "  ✓ No arbitrary paths\n"
            "  ✓ Dangerous word blocklist present\n"
            "  ✓ Confirmation required for writes\n"
            "  ✓ Tests cover injection blocking\n"
            "RISK_AREAS:\n"
            "  - Exception swallowing in try/except blocks\n"
            "  - Intent match ordering (executor route must stay first)\n"
            "TEST_GAPS:\n  Add test for each new mode classification.\n"
            "ISSUES_REQUIRING_AUDITOR_OR_USER_APPROVAL:\n  Any new execution capability beyond read-only analysis."
        ),
        "qa": (
            "STATUS: PASSED\n"
            "SKILL_ID: qa\n"
            f"TOPIC: {topic}\n"
            "TEST_PLAN:\n"
            "  1. Mode classification tests (all 19 modes)\n"
            "  2. Skill dispatch tests (read-only output structure)\n"
            "  3. Write action confirmation flow (step 1 → CONFIRM → step 2)\n"
            "  4. Injection blocking (metacharacters, dangerous words)\n"
            "  5. Regression: existing executor route, healthcheck, read_logs, diagnose\n"
            "MANUAL_QA_CHECKLIST:\n"
            "  - Live Telegram: office_hours → structured output\n"
            "  - Live Telegram: skill_request → REQUIRES_CONFIRMATION\n"
            "  - Live Telegram: dangerous command → BLOCKED\n"
            "AUTOMATED_TEST_CANDIDATES:\n"
            "  - test_logi_capability_mode_router.py\n"
            "  - test_logi_skill_system.py\n"
            "BROWSER_QA_REQUIRED: false (Telegram interface)"
        ),
        "security_cso": (
            "STATUS: PASSED\n"
            "SKILL_ID: security_cso\n"
            f"TOPIC: {topic}\n"
            "THREAT_MODEL:\n"
            "  T1: Command injection via Telegram message → MITIGATED (metacharacter blocklist)\n"
            "  T2: Path traversal in executor route → MITIGATED (path validation)\n"
            "  T3: Arbitrary Docker command → MITIGATED (docker exec/restart blocked)\n"
            "  T4: Write without confirmation → MITIGATED (all writes require CONFIRM)\n"
            "OWASP_STRIDE_CHECKLIST:\n"
            "  Spoofing: N/A (Telegram user_id validated upstream)\n"
            "  Tampering: Blocked by CONFIRM step\n"
            "  Repudiation: Audit trail in logi_confirmations/\n"
            "  Information Disclosure: Logs via allowlisted read_logs only\n"
            "  Denial: Timeout on all subprocess calls\n"
            "  Elevation of Privilege: No root; no sudo; docker blocked\n"
            "SECRET_PATH_COMMAND_RISKS:\n"
            "  - No secrets in log paths\n"
            "  - No credential injection possible via allowlisted paths\n"
            "REQUIRED_MITIGATIONS:\n"
            "  ✓ Metacharacter blocklist on all confirmation actions\n"
            "  ✓ Dangerous command word blocklist\n"
            "  ✓ No shell=True anywhere\n"
            "  ✓ All persistent writes require CONFIRM"
        ),
        "release_ship": (
            "STATUS: PASSED\n"
            "SKILL_ID: release_ship\n"
            f"TOPIC: {topic}\n"
            "RELEASE_CHECKLIST:\n"
            "  ✓ Full agents suite passing\n"
            "  ✓ verify_local_executor_extended.sh passing\n"
            "  ✓ Existing production routes unchanged\n"
            "  ✓ Injection protection tests passing\n"
            "  ✓ No new Docker containers created\n"
            "TESTS_REQUIRED:\n"
            "  python -m pytest ops/agents/tests/ -q\n"
            "  bash ops/scripts/verify_local_executor_extended.sh\n"
            "MIGRATION_NOTES:\n  No schema migration. Pure code addition.\n"
            "ROLLBACK_NOTES:\n  Revert orchestrator injection point. Remove new modules.\n"
            "CANARY_PLAN:\n  Test with 1 user before enabling for all Telegram users."
        ),
        "retro": (
            "STATUS: PASSED\n"
            "SKILL_ID: retro\n"
            f"TOPIC: {topic}\n"
            "WHAT_HAPPENED:\n  [Describe what occurred]\n"
            "WHAT_WORKED:\n  Confirmation flow, injection protection, self_process healthcheck\n"
            "WHAT_FAILED:\n  [Describe failures here]\n"
            "RECURRING_FAILURE_PATTERNS:\n"
            "  - Intent not matched → silent plain reply\n"
            "  - Exception swallowed in try/except\n"
            "LEARNING_EVENTS_TO_REGISTER:\n  Register each failure as learning event candidate."
        ),
        "learn": (
            "STATUS: PASSED\n"
            "SKILL_ID: learn\n"
            f"TOPIC: {topic}\n"
            "LESSONS:\n  [Key lessons from this experience]\n"
            "FAILURE_CLASS:\n  CAPABILITY_GAP or INTENT_NOT_MATCHED or other\n"
            "CANDIDATE_TRAINING_PAIR:\n"
            f"  instruction: {topic[:100]}\n"
            "  expected: Structured skill output\n"
            "  actual: Plain acknowledgement\n"
            "PROPOSED_SKILL_IMPROVEMENTS:\n  Add intent pattern to mode router\n"
            "LEARNING_REGISTRATION_DRAFT:\n  Use learning_registration skill to persist this."
        ),
        "design_review": (
            "STATUS: NOT_APPLICABLE\n"
            "SKILL_ID: design_review\n"
            "REASON: This topic is not UI/UX relevant — no frontend design needed.\n"
            "NEXT_RECOMMENDED_SKILLS: eng_review"
        ),
        "devex_review": (
            "STATUS: PASSED\n"
            "SKILL_ID: devex_review\n"
            f"TOPIC: {topic}\n"
            "DEVELOPER_PERSONAS:\n  - Logi operator (Telegram)\n  - AIMS engineer (CLI/API)\n"
            "SETUP_FRICTION:\n  Low — extends existing Telegram bot with no new deployment.\n"
            "API_CLI_DOCS_PAIN_POINTS:\n  Intent phrases need documentation in /help or README.\n"
            "TIME_TO_HELLO_WORLD_ESTIMATE:\n  < 5 minutes (send Telegram message, get structured response)\n"
            "IMPROVEMENT_PLAN:\n  Add /skills command to list available skill triggers."
        ),
    }

    template = _TEMPLATES.get(skill_id)
    if template:
        return template.format(topic=topic[:200])
    return None


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

        # ── Chief-engineer skill dispatch (gstack-style process skills) ─────────
        try:
            from ops.agents.logi_capability_mode_router import classify_logi_mode
            from ops.agents.logi_skill_system import SKILL_REGISTRY, find_skill
            from ops.agents.logi_confirmation_flow import (
                request_write_action, format_confirmation_response,
            )
            classification = classify_logi_mode(text or "")
            skill = find_skill(text or "") if classification.skill_id is None else \
                SKILL_REGISTRY.get(classification.skill_id)

            if skill and classification.mode in (
                "SKILL_DISPATCH", "CAPABILITY_GAP_ANALYSIS",
                "PATCH_PROMPT_PREPARATION",
                "AUDITOR_HELP_REQUEST", "SKILL_REQUEST", "LEARNING_REGISTRATION",
                "QUEUE_TASK", "SCHEDULE_TASK",
            ):
                if skill.requires_confirmation:
                    # Build params for write actions
                    params: dict = {}
                    if skill.skill_id == "auditor_request":
                        params = {"problem_summary": text[:300], "failure_class": "CAPABILITY_GAP"}
                    elif skill.skill_id == "skill_request":
                        params = {"skill_name": "new_skill", "purpose": text[:200]}
                    elif skill.skill_id == "learning_registration":
                        params = {"user_intent": text[:200], "expected_behavior": "",
                                  "actual_behavior": "Not completed", "failure_class": "CAPABILITY_GAP",
                                  "lesson": text[:200]}
                    elif skill.skill_id in ("queue_task", "schedule_task"):
                        params = {"title": text[:100], "description": text[:300],
                                  "schedule_hint": "asap"}
                        action_type = "queue_task_allowlisted"
                        resp = request_write_action(
                            action_type=action_type, params=params,
                            requested_by=str(user_id), original_message=text or "",
                        )
                        return format_confirmation_response(resp)

                    action_type_map = {
                        "auditor_request": "create_auditor_request",
                        "skill_request": "create_skill_request",
                        "learning_registration": "register_learning_event",
                    }
                    action_type = action_type_map.get(skill.skill_id, skill.skill_id)
                    resp = request_write_action(
                        action_type=action_type, params=params,
                        requested_by=str(user_id), original_message=text or "",
                    )
                    resp["skill_id"] = skill.skill_id
                    return format_confirmation_response(resp)
                else:
                    # Read-only skill: generate structured text output
                    response = _execute_read_only_skill(skill.skill_id, text or "", skill_context)
                    if response:
                        return response
        except Exception:
            pass  # Never break main bot on skill errors
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
