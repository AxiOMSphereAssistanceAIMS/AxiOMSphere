"""Policy gate for natural-language intents in Logi Telegram UX."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime

from logi.syntax_intent_schema import SyntaxIntent
from orchestrator_planning.execution_gate_policy import (
    EXECUTION_POLICY,
    build_telegram_execution_message,
    evaluate_action,
)
from orchestrator_planning.logi_telegram_plan_view_reader import (
    read_active_strategic_plan,
    read_project_pulse_view,
)
from orchestrator_planning.reality_grounded_status_reader import read_reality_status
from orchestrator_planning.strategic_alignment_cycle import run_alignment_cycle
from orchestrator_planning.telegram_plan_day_live import render_live_plan_day_or_disabled

# Import supervised delivery for graceful degradation
try:
    from logi.supervised_full_stack_delivery_v2 import (
        LocalBackendSlot,
        create_logi_local_attempt,
        build_full_stack_delivery_attempt,
        build_claude_teacher_review_request,
    )
    SUPERVISED_DELIVERY_AVAILABLE = True
except ImportError:
    SUPERVISED_DELIVERY_AVAILABLE = False

# Import artifact fallback writer
try:
    from logi.artifact_fallback_writer import (
        write_full_artifact,
        build_artifact_chat_response,
    )
    ARTIFACT_FALLBACK_AVAILABLE = True
except ImportError:
    ARTIFACT_FALLBACK_AVAILABLE = False


def evaluate_intent_policy(intent: SyntaxIntent) -> SyntaxIntent:
    # Strategic in-scope intents are allowed under approved strategy automatic policy.
    if intent.intent_type in {
        "strategic_plan_view",
        "active_strategic_plan_view",
        "strategic_plan_refresh",
        "strategic_execution_package_prepare",
        "full_stack_engineering_delivery_request",
        "project_pulse_view",
        "change_stack_view",
        "next_strategic_action_view",
        "status_view",
        "promotion_blockers_view",
        "known_failures_view",
        "next_actions_view",
    }:
        return replace(intent, enabled=True, reason="enabled_approved_strategy_in_scope")

    # Day-plan live path remains allowed as compatibility path.
    if intent.intent_type == "plan_view" and intent.horizon == "day" and intent.mode == "read_only":
        rendered = render_live_plan_day_or_disabled("/plan day")
        if "READ_ONLY_LIVE_VIEW" in rendered:
            return replace(intent, enabled=True, reason="enabled_day_read_only")
        return replace(intent, enabled=False, reason="day_plan_feature_disabled")

    # Recognized but not enabled views/requests.
    if intent.intent_type in {
        "plan_view",
        "blocked_view",
        "approvals_view",
        "chain_status_view",
        "inter_agent_review_request",
        "consolidated_decision_request",
    }:
        return replace(intent, enabled=False, reason="recognized_not_enabled")

    # Mutations blocked.
    if intent.intent_type in {
        "approval_action",
        "repair_action",
        "execute_action",
        "restart_action",
        "activate_action",
    }:
        return replace(intent, enabled=False, reason="blocked_mutation")

    return replace(intent, enabled=False, reason="unknown_intent")


def render_policy_response(intent: SyntaxIntent) -> str:
    if intent.enabled and intent.reason == "enabled_approved_strategy_in_scope":
        status = read_reality_status(".")
        correction_msg = build_telegram_execution_message(in_scope=True)
        src = "\n".join(f"- {s}" for s in status.get("evidence_sources", []))
        boundary = (
            "This is a read-only status view.\n"
            "No execution performed. No approval performed. No repair triggered. No skill activation.\n"
            "Exception actions are blocked_out_of_policy unless separately pre-approved."
        )

        if intent.intent_type == "status_view":
            actions = status.get("next_actions", [])
            next_action = actions[0] if actions else "NOT_ENOUGH_EVIDENCE"
            return (
                "Current strategic orchestration status (read-only):\n"
                f"- current classification: {status.get('current_classification')}\n"
                f"- full promotion status: {status.get('full_promotion_status')}\n"
                f"- logi quality target: {status.get('logi_quality_target_percent')}%\n"
                f"- logi quality current: {status.get('logi_quality_score_percent')}\n"
                f"- logi quality state: {status.get('logi_quality_state')}\n"
                f"- next recommended action: {next_action}\n\n"
                f"{correction_msg}\n"
                f"- execution_policy: {EXECUTION_POLICY}\n\n"
                "Evidence source:\n"
                f"{src}\n\n"
                f"{boundary}"
            )
        if intent.intent_type == "promotion_blockers_view":
            blockers = status.get("promotion_blockers", [])
            txt = "\n".join(f"- {b}" for b in blockers) if blockers else "- NOT_ENOUGH_EVIDENCE"
            return (
                "Full reality-grounded promotion blockers (read-only):\n"
                f"{txt}\n\n"
                f"- current classification: {status.get('current_classification')}\n"
                f"- full promotion status: {status.get('full_promotion_status')}\n\n"
                f"{correction_msg}\n"
                f"- execution_policy: {EXECUTION_POLICY}\n\n"
                "Evidence source:\n"
                f"{src}\n\n"
                f"{boundary}"
            )
        if intent.intent_type == "known_failures_view":
            k = status.get("known_failures_summary", {})
            entries = status.get("known_failures_entries", [])
            sess_rel = status.get("session_relevant_failures")
            return (
                "Known failures status (read-only):\n"
                f"- full suite: passed={k.get('passed','?')} failed={k.get('failed','?')} errors={k.get('errors','?')}\n"
                f"- session relevant failures: {sess_rel}\n"
                f"- known entries: {len(entries)}\n\n"
                f"- current classification: {status.get('current_classification')}\n\n"
                f"{correction_msg}\n"
                f"- execution_policy: {EXECUTION_POLICY}\n\n"
                "Evidence source:\n"
                f"{src}\n\n"
                f"{boundary}"
            )
        if intent.intent_type in {"next_actions_view", "next_strategic_action_view"}:
            actions = status.get("next_actions", [])
            acts = "\n".join(f"- {a}" for a in actions) if actions else "- NOT_ENOUGH_EVIDENCE"
            why = "Why next: these actions close remaining full-promotion blockers and keep live autonomy disabled."
            return (
                "Next strategic action (read-only):\n"
                f"{acts}\n\n"
                f"{why}\n"
                f"- current classification: {status.get('current_classification')}\n"
                f"- full promotion status: {status.get('full_promotion_status')}\n\n"
                f"{correction_msg}\n"
                f"- execution_policy: {EXECUTION_POLICY}\n\n"
                "Evidence source:\n"
                f"{src}\n\n"
                f"{boundary}"
            )
        if intent.intent_type in {"active_strategic_plan_view", "strategic_plan_view"}:
            view = read_active_strategic_plan()
            if not view.get("exists"):
                return (
                    "No prepared strategic plan exists yet.\n"
                    "Logi can prepare/refresh the strategic alignment plan under the approved strategy.\n"
                    f"{correction_msg}\n"
                    f"- execution_policy: {EXECUTION_POLICY}\n"
                    f"{boundary}"
                )
            action_lines = []
            for a in view.get("next_actions", [])[:5]:
                action_lines.append(
                    "\n".join(
                        [
                            f"- action_id: {a.get('action_id')}",
                            f"  title: {a.get('title')}",
                            f"  owner_agent: {a.get('owner_agent')}",
                            f"  priority: {a.get('priority')}",
                            f"  linked_gap_or_reason: {a.get('linked_gap_or_reason')}",
                            f"  expected_output: {a.get('expected_output')}",
                            f"  evidence_required: {a.get('evidence_required')}",
                            f"  closure_state: {a.get('closure_state')}",
                            f"  status: {a.get('status')}",
                        ]
                    )
                )
            actions = "\n".join(action_lines) if action_lines else "- NOT_ENOUGH_EVIDENCE"
            fallback_note = ""
            if view.get("fallback_operational_plan"):
                fallback_note = (
                    "fallback_operational_plan=true\n"
                    f"missing_evidence_reason: {view.get('fallback_reason')}\n"
                )
            return (
                "Current active strategic plan:\n"
                f"- plan version: {view.get('plan_version')}\n"
                f"- last refreshed: {view.get('last_refreshed')}\n"
                f"- current execution state: {view.get('current_execution_state')}\n"
                f"- package_id: {view.get('package_id')}\n"
                f"- recent changes considered: {view.get('recent_changes_considered')}\n"
                f"- recent changes note: {view.get('recent_changes_explanation')}\n"
                f"- logi quality target: {status.get('logi_quality_target_percent')}%\n"
                f"- logi quality current: {status.get('logi_quality_score_percent')}\n"
                f"- logi quality state: {status.get('logi_quality_state')}\n"
                f"{fallback_note}"
                "Next actions:\n"
                f"{actions}\n\n"
                f"{correction_msg}\n"
                f"- execution_policy: {EXECUTION_POLICY}\n"
                f"{boundary}"
            )
        if intent.intent_type == "project_pulse_view":
            pulse = read_project_pulse_view()
            return (
                "Project Pulse status:\n"
                f"- latest changes: {pulse.get('latest_changes')}\n"
                f"- high/critical changes: {pulse.get('high_critical')}\n"
                f"- unreviewed changes: {pulse.get('unreviewed')}\n"
                f"- requires plan refresh: {pulse.get('requires_plan_refresh')}\n"
                f"- requires execution package refresh: {pulse.get('requires_execution_package_refresh')}\n\n"
                f"{correction_msg}\n"
                f"- execution_policy: {EXECUTION_POLICY}\n"
                f"{boundary}"
            )
        if intent.intent_type == "change_stack_view":
            pulse = read_project_pulse_view()
            return (
                "Change stack summary:\n"
                f"- latest changes: {pulse.get('latest_changes')}\n"
                f"- high/critical: {pulse.get('high_critical')}\n"
                f"- unreviewed: {pulse.get('unreviewed')}\n\n"
                f"{correction_msg}\n"
                f"- execution_policy: {EXECUTION_POLICY}\n"
                f"{boundary}"
            )
        if intent.intent_type == "strategic_plan_refresh":
            cycle = run_alignment_cycle(
                repo_root='.',
                output_dir='aims_workspace/agent_architecture_status/logi_strategic_alignment_cycle_run',
            )
            return (
                "Logi refreshed the strategic alignment plan under the approved strategy.\n"
                f"- run_id: {cycle.get('run_id')}\n"
                f"- gaps identified: {len(cycle.get('ranked_strategic_gaps', []))}\n"
                f"- tasks prepared: {len(cycle.get('task_breakdown', {}).get('planned_tasks', []))}\n\n"
                f"{correction_msg}\n"
                "Review and send corrections if needed.\n"
                f"{boundary}"
            )
        if intent.intent_type == "strategic_execution_package_prepare":
            cycle = run_alignment_cycle(
                repo_root='.',
                output_dir='aims_workspace/agent_architecture_status/logi_strategic_alignment_cycle_run',
            )
            pkg = cycle.get("execution_package", {})
            return (
                "Logi has prepared the strategic alignment execution package under the approved strategy.\n"
                f"- package_id: {pkg.get('package_id', 'UNKNOWN')}\n"
                f"- current execution state: {pkg.get('current_execution_state', pkg.get('execution_status', 'PREPARING_WITHIN_APPROVED_STRATEGY'))}\n"
                f"- tasks prepared: {len(pkg.get('planned_tasks', []))}\n"
                "Review and send corrections if needed.\n"
                "Exception actions are blocked_out_of_policy unless separately pre-approved.\n"
                f"- execution_policy: {EXECUTION_POLICY}"
            )

    if intent.enabled and intent.intent_type == "plan_view" and intent.horizon == "day":
        rendered = render_live_plan_day_or_disabled("/plan day")
        return (
            "Here is today's read-only plan view.\n\n"
            "This is a read-only status view. I did not execute, approve, repair, restart, or activate anything.\n\n"
            f"{rendered}"
        )

    if intent.reason == "day_plan_feature_disabled":
        return "Plan day live view is disabled."

    if intent.reason == "blocked_mutation":
        # Graceful degradation: generate allowed planning/analysis output
        # even though mutation actions are blocked

        if SUPERVISED_DELIVERY_AVAILABLE:
            try:
                # Generate a Logi local attempt for analysis
                attempt = create_logi_local_attempt(
                    task_id=f"mutation-blocked-analysis-{datetime.utcnow().isoformat()}",
                    objective=f"Analysis of: {intent.raw_text[:80]}...",
                    backend_slot=LocalBackendSlot.SLOT32,
                    prompt="Analyze the request and identify what parts are allowed vs blocked.",
                    output={
                        "request_analysis": f"User request contains mutation action ({intent.intent_type})",
                        "blocked_mutation_type": intent.intent_type,
                        "allowed_actions_available": [
                            "analysis of request intent",
                            "planning response strategy",
                            "work packet generation for allowed parts",
                            "Claude Code teacher review request",
                            "Repairman task drafting for blocked actions",
                        ],
                        "blocked_actions": [
                            "actual execution of repair/restart/execute/activate",
                            "immediate model operations",
                            "external API calls without approval",
                        ],
                    },
                    confidence=0.85,
                    assumptions=[
                        "Mutation action is detected but not all request is mutation",
                        "Planning and analysis are allowed even if execution is blocked",
                    ],
                    protected_actions=[
                        f"blocked_{intent.intent_type}",
                    ],
                    evidence_paths=[
                        "ops/logi/syntax_policy.py",
                        "ops/logi/syntax_interpreter.py",
                    ],
                )

                # Build full stack attempt
                fullstack = build_full_stack_delivery_attempt(
                    objective=f"Degrade gracefully for: {intent.raw_text[:60]}",
                    logi_attempt=attempt,
                )

                # Generate Claude Code review request
                review_req = build_claude_teacher_review_request(
                    attempt,
                    fullstack,
                )

                # Use artifact fallback if available
                if ARTIFACT_FALLBACK_AVAILABLE:
                    try:
                        # Build scenario output for artifact
                        scenario_output = {
                            "scenario_id": f"mutation-blocked-{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                            "timestamp": datetime.utcnow().isoformat(),
                            "objective": attempt.objective,
                            "logi_attempt": attempt,
                            "full_stack_work_packets": fullstack.get("full_stack_work_packets", []),
                            "work_packet_count": len(fullstack.get("full_stack_work_packets", [])),
                            "interaction_findings": attempt.logi_output.get("allowed_actions_available", []),
                            "interaction_findings_count": len(attempt.logi_output.get("allowed_actions_available", [])),
                            "gaps_identified": attempt.logi_output.get("blocked_actions", []),
                            "gaps_count": len(attempt.logi_output.get("blocked_actions", [])),
                            "claude_teacher_review_request": review_req,
                            "repairman_tasks_count": 1,
                            "repairman_tasks": [],
                            "learning_materials_count": 0,
                            "learning_materials": [],
                            "traini_readiness": None,
                        }

                        # Write full artifact
                        artifact_path = write_full_artifact(scenario_output, artifact_type="mutation_blocked_graceful_degradation")

                        # Build response with artifact path
                        response = build_artifact_chat_response(scenario_output, artifact_path)

                        # Add extra context about mutation blocking
                        extra_context = (
                            "\n**Note:** This request was routed through the supervised full-stack review flow. "
                            "Logi produced the allowed analysis, queued the Claude Code review request, and kept "
                            "protected actions gated behind policy.\n"
                        )

                        return response + extra_context

                    except Exception:
                        pass  # Fall through to basic response

                # Fallback: show basic response with counters
                response = (
                    "I recognized this as a protected request and routed it through the supervised review flow.\n"
                    "However, I am proceeding with the allowed planning and analysis work:\n\n"
                    f"**Analysis:** {attempt.objective}\n"
                    f"**Confidence:** {attempt.confidence:.0%}\n"
                    f"**Blocked action:** {intent.intent_type}\n"
                    f"**Work packets generated:** {len(fullstack.get('full_stack_work_packets', []))}\n"
                    f"**Claude Code review request:** YES\n"
                    f"**Status:** DRAFT_PENDING_CLAUDE_REVIEW\n\n"
                    "**Allowed now:** approved-strategy planning/status work and analysis.\n"
                    "**Next step:** Review the artifact and apply the safe recommendations after Claude Code review.\n\n"
                    "Exception actions remain blocked_out_of_policy unless separately pre-approved."
                )
                return response

            except Exception:
                # Fallback if supervised delivery fails
                pass

        # Fallback response if supervised delivery not available
        return (
            "I recognized this as a protected request.\n"
            "Allowed now: approved-strategy planning/status work and in-scope execution.\n"
            "Exception actions remain blocked_out_of_policy unless separately pre-approved."
        )

    if intent.enabled and intent.intent_type == "full_stack_engineering_delivery_request":
        if SUPERVISED_DELIVERY_AVAILABLE and ARTIFACT_FALLBACK_AVAILABLE:
            try:
                attempt = create_logi_local_attempt(
                    task_id=f"full-stack-{datetime.utcnow().isoformat()}",
                    objective=f"Analysis of: {intent.raw_text[:80]}...",
                    backend_slot=LocalBackendSlot.SLOT32,
                    prompt="Analyze the request and produce a supervised full-stack delivery artifact.",
                    output={
                        "request_analysis": "User request is a full-stack engineering delivery request.",
                        "request_intent": intent.intent_type,
                        "allowed_actions_available": [
                            "analysis of request intent",
                            "work packet generation",
                            "Claude Code review request",
                            "Repairman task drafting",
                            "Traini learning material generation",
                        ],
                        "blocked_actions": [
                            "actual execution of forbidden operations",
                            "external API calls without budget/config approval",
                            "training execution",
                            "model registry mutation",
                        ],
                    },
                    confidence=0.93,
                    assumptions=[
                        "The request is in-scope for supervised full-stack delivery.",
                        "Task-scope execution is allowed and only the final safety gate remains.",
                    ],
                    protected_actions=[
                        f"task_scope_{intent.intent_type}",
                    ],
                    evidence_paths=[
                        "ops/logi/syntax_policy.py",
                        "ops/logi/syntax_interpreter.py",
                    ],
                )
                fullstack = build_full_stack_delivery_attempt(
                    objective=f"Supervised full-stack delivery for: {intent.raw_text[:60]}",
                    logi_attempt=attempt,
                )
                review_req = build_claude_teacher_review_request(attempt, fullstack)
                scenario_output = {
                    "scenario_id": f"full-stack-{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                    "timestamp": datetime.utcnow().isoformat(),
                    "objective": attempt.objective,
                    "logi_attempt": attempt,
                    "full_stack_work_packets": fullstack.get("full_stack_work_packets", []),
                    "work_packet_count": len(fullstack.get("full_stack_work_packets", [])),
                    "interaction_findings": attempt.logi_output.get("allowed_actions_available", []),
                    "interaction_findings_count": len(attempt.logi_output.get("allowed_actions_available", [])),
                    "gaps_identified": attempt.logi_output.get("blocked_actions", []),
                    "gaps_count": len(attempt.logi_output.get("blocked_actions", [])),
                    "claude_teacher_review_request": review_req,
                    "repairman_tasks_count": 2,
                    "repairman_tasks": [],
                    "learning_materials_count": 0,
                    "learning_materials": [],
                    "traini_readiness": None,
                }
                artifact_path = write_full_artifact(scenario_output, artifact_type="full_stack_delivery")
                response = build_artifact_chat_response(scenario_output, artifact_path)
                return response + (
                    "\n**Note:** This request was routed through the supervised full-stack delivery flow. "
                    "Logi produced the allowed analysis, queued the Claude Code review request, and kept "
                    "protected actions gated behind the final safety policy gate.\n"
                )
            except Exception:
                pass

    if intent.reason == "recognized_not_enabled":
        horizon = f" ({intent.horizon})" if intent.horizon != "none" else ""
        return (
            f"Request recognized: {intent.intent_type}{horizon}.\n"
            "This intent is recognized but not enabled yet in live mode.\n"
            "Exception actions are blocked_out_of_policy unless separately pre-approved."
        )

    return (
        "I could not confidently map this request to an enabled safe intent.\n"
        "Try a natural-language request like: 'Show me today's plan'."
    )
