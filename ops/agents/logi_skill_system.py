"""
logi_skill_system.py

Chief-engineer process skill registry for Logi.

These are process skills (THINK/PLAN/BUILD/REVIEW/TEST/SHIP/REFLECT),
not to be confused with agent capability skills in ops/agents/skill_registry.py.

Each skill is pure text analysis + structured output — no shell execution.
Skills that write artifacts or trigger actions require confirmation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillSpec:
    skill_id: str
    display_name: str
    phase: str              # THINK | PLAN | BUILD | REVIEW | TEST | SHIP | REFLECT
    aliases_ru: list[str]
    aliases_en: list[str]
    purpose: str
    requires_confirmation: bool
    produces_artifact: bool
    artifact_type: str      # analysis | plan | request | event | none
    output_fields: list[str]
    next_recommended_skills: list[str]
    safety_constraints: list[str] = field(default_factory=list)


SKILL_REGISTRY: dict[str, SkillSpec] = {
    "office_hours": SkillSpec(
        skill_id="office_hours",
        display_name="Office Hours",
        phase="THINK",
        aliases_ru=["office hours", "офис часы", "обсуди идею", "проведи office hours", "проведи офис"],
        aliases_en=["office hours", "discuss idea", "frame problem", "problem framing"],
        purpose="Six forcing questions to frame a problem before planning.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="analysis",
        output_fields=["SIX_FORCING_QUESTIONS", "PAIN_HYPOTHESIS", "USER_PROBLEM_FRAMING",
                       "ALTERNATIVE_PATHS", "RECOMMENDED_FIRST_SLICE", "NEXT_RECOMMENDED_SKILLS"],
        next_recommended_skills=["ceo_review", "eng_review", "autoplan"],
    ),
    "ceo_review": SkillSpec(
        skill_id="ceo_review",
        display_name="CEO Review",
        phase="THINK",
        aliases_ru=["ceo review", "сeo обзор", "обзор CEO", "проверь CEO", "масштаб проекта"],
        aliases_en=["ceo review", "scope challenge", "10x review", "ten star"],
        purpose="Challenge scope: 10-star version, reduction/expansion options, risks.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="analysis",
        output_fields=["SCOPE_CHALLENGE", "TEN_STAR_VERSION", "REDUCTION_OPTION",
                       "EXPANSION_OPTION", "RISKS", "DECISION_REQUIRED_FROM_USER"],
        next_recommended_skills=["eng_review", "autoplan"],
    ),
    "eng_review": SkillSpec(
        skill_id="eng_review",
        display_name="Engineering Review",
        phase="PLAN",
        aliases_ru=["eng review", "engineering review", "инженерный обзор", "сделай eng review",
                    "архитектурный обзор", "arch review"],
        aliases_en=["eng review", "engineering review", "architecture review", "arch review"],
        purpose="Architecture summary, data flow, failure modes, test matrix, implementation plan.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="plan",
        output_fields=["ARCHITECTURE_SUMMARY", "DATA_FLOW", "STATE_TRANSITIONS",
                       "FAILURE_MODES", "TEST_MATRIX", "SECURITY_CONCERNS", "IMPLEMENTATION_PLAN"],
        next_recommended_skills=["security_cso", "qa", "autoplan"],
    ),
    "design_review": SkillSpec(
        skill_id="design_review",
        display_name="Design Review",
        phase="PLAN",
        aliases_ru=["design review", "дизайн обзор", "ux review", "ux обзор"],
        aliases_en=["design review", "ux review", "ui review", "clarity check"],
        purpose="UX risks, AI-slop risks, clarity score, copy/UI improvements.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="analysis",
        output_fields=["UX_RISKS", "AI_SLOP_RISKS", "CLARITY_SCORE",
                       "RECOMMENDED_COPY_OR_UI_IMPROVEMENTS"],
        next_recommended_skills=["eng_review"],
    ),
    "devex_review": SkillSpec(
        skill_id="devex_review",
        display_name="Developer Experience Review",
        phase="PLAN",
        aliases_ru=["devex review", "devex обзор", "опыт разработчика"],
        aliases_en=["devex review", "developer experience", "dx review", "api ux review"],
        purpose="Developer personas, setup friction, API/CLI docs pain points, time-to-hello-world.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="analysis",
        output_fields=["DEVELOPER_PERSONAS", "SETUP_FRICTION", "API_CLI_DOCS_PAIN_POINTS",
                       "TIME_TO_HELLO_WORLD_ESTIMATE", "IMPROVEMENT_PLAN"],
        next_recommended_skills=["eng_review"],
    ),
    "autoplan": SkillSpec(
        skill_id="autoplan",
        display_name="Auto Plan",
        phase="PLAN",
        aliases_ru=["autoplan", "автоплан", "сделай autoplan", "автоматический план",
                    "план внедрения", "создай план"],
        aliases_en=["autoplan", "auto plan", "generate plan", "create plan", "plan this"],
        purpose="Combined CEO + Eng + Security + Release review producing actionable implementation plan.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="plan",
        output_fields=["CEO_REVIEW_SUMMARY", "ENG_REVIEW_SUMMARY", "SECURITY_CONCERNS",
                       "RELEASE_CHECKLIST", "IMPLEMENTATION_STEPS", "NEXT_RECOMMENDED_SKILLS"],
        next_recommended_skills=["patch_prompt", "auditor_request"],
    ),
    "investigate": SkillSpec(
        skill_id="investigate",
        display_name="Investigate",
        phase="PLAN",
        aliases_ru=["расследуй", "исследуй", "investigate", "проанализируй"],
        aliases_en=["investigate", "analyze", "research", "dig into"],
        purpose="Symptom analysis, hypotheses, evidence to collect, likely root cause.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="analysis",
        output_fields=["SYMPTOMS", "HYPOTHESES", "EVIDENCE_TO_COLLECT",
                       "LIKELY_ROOT_CAUSE", "NEXT_DIAGNOSTIC_ACTION"],
        next_recommended_skills=["diagnose_service_allowlisted", "read_logs_allowlisted", "capability_gap"],
    ),
    "review": SkillSpec(
        skill_id="review",
        display_name="Code Review",
        phase="REVIEW",
        aliases_ru=["сделай review", "проверь код", "code review", "обзор кода"],
        aliases_en=["review", "code review", "review this", "check the code"],
        purpose="Code review checklist, risk areas, test gaps, issues requiring approval.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="analysis",
        output_fields=["CODE_REVIEW_CHECKLIST", "RISK_AREAS", "TEST_GAPS",
                       "ISSUES_REQUIRING_AUDITOR_OR_USER_APPROVAL"],
        next_recommended_skills=["security_cso", "qa", "patch_prompt"],
    ),
    "qa": SkillSpec(
        skill_id="qa",
        display_name="QA",
        phase="TEST",
        aliases_ru=["qa", "тестирование", "тест план", "написать тесты", "добавь тесты"],
        aliases_en=["qa", "test plan", "quality assurance", "write tests", "testing"],
        purpose="Test plan, manual QA checklist, automated test candidates.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="plan",
        output_fields=["TEST_PLAN", "MANUAL_QA_CHECKLIST", "AUTOMATED_TEST_CANDIDATES",
                       "BROWSER_QA_REQUIRED"],
        next_recommended_skills=["release_ship"],
    ),
    "security_cso": SkillSpec(
        skill_id="security_cso",
        display_name="Security CSO Review",
        phase="REVIEW",
        aliases_ru=["security review", "обзор безопасности", "security cso", "аудит безопасности"],
        aliases_en=["security review", "security cso", "security audit", "threat model"],
        purpose="Threat model, OWASP/STRIDE checklist, secret/path/command risks, required mitigations.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="analysis",
        output_fields=["THREAT_MODEL", "OWASP_STRIDE_CHECKLIST", "SECRET_PATH_COMMAND_RISKS",
                       "REQUIRED_MITIGATIONS"],
        next_recommended_skills=["qa", "release_ship"],
    ),
    "release_ship": SkillSpec(
        skill_id="release_ship",
        display_name="Release Ship",
        phase="SHIP",
        aliases_ru=["release", "выпуск", "деплой", "deploy", "release ship", "отгрузка"],
        aliases_en=["release", "ship", "deploy", "release ship", "go live"],
        purpose="Release checklist, migration notes, rollback notes, canary plan. No actual deployment.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="plan",
        output_fields=["RELEASE_CHECKLIST", "TESTS_REQUIRED", "MIGRATION_NOTES",
                       "ROLLBACK_NOTES", "CANARY_PLAN"],
        next_recommended_skills=["retro"],
    ),
    "retro": SkillSpec(
        skill_id="retro",
        display_name="Retrospective",
        phase="REFLECT",
        aliases_ru=["retro", "ретро", "ретроспектива", "что пошло не так"],
        aliases_en=["retro", "retrospective", "post-mortem", "what happened"],
        purpose="What happened, worked, failed, recurring failure patterns, learning events to register.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="analysis",
        output_fields=["WHAT_HAPPENED", "WHAT_WORKED", "WHAT_FAILED",
                       "RECURRING_FAILURE_PATTERNS", "LEARNING_EVENTS_TO_REGISTER"],
        next_recommended_skills=["learn", "learning_registration"],
    ),
    "learn": SkillSpec(
        skill_id="learn",
        display_name="Learn",
        phase="REFLECT",
        aliases_ru=["learn", "учись", "запиши урок", "уроки", "что мы узнали"],
        aliases_en=["learn", "lessons", "record lesson", "what did we learn"],
        purpose="Lessons, failure class, candidate training pair, proposed skill improvements.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="analysis",
        output_fields=["LESSONS", "FAILURE_CLASS", "CANDIDATE_TRAINING_PAIR",
                       "PROPOSED_SKILL_IMPROVEMENTS", "LEARNING_REGISTRATION_DRAFT"],
        next_recommended_skills=["learning_registration"],
    ),
    "capability_gap": SkillSpec(
        skill_id="capability_gap",
        display_name="Capability Gap Analysis",
        phase="THINK",
        aliases_ru=["capability gap", "чего не хватает", "пробел в возможностях",
                    "что мне не хватает", "недостающие возможности", "что тебе не хватает"],
        aliases_en=["capability gap", "what is missing", "gap analysis", "missing capability"],
        purpose="Missing capability, why needed, existing close capabilities, proposed action/skill.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="analysis",
        output_fields=["MISSING_CAPABILITY", "WHY_NEEDED", "EXISTING_CLOSE_CAPABILITIES",
                       "PROPOSED_ACTION_TYPE_OR_SKILL", "PATCH_NEEDED",
                       "AUDITOR_HELP_RECOMMENDED", "TESTS_NEEDED"],
        next_recommended_skills=["patch_prompt", "auditor_request", "skill_request"],
    ),
    "patch_prompt": SkillSpec(
        skill_id="patch_prompt",
        display_name="Patch Prompt Preparation",
        phase="BUILD",
        aliases_ru=["patch prompt", "подготовь патч", "подготовь prompt для патча",
                    "патч prompt", "создай патч промпт"],
        aliases_en=["patch prompt", "prepare patch", "patch preparation", "write patch prompt"],
        purpose="Prepare a structured prompt for a code patch. No patch application.",
        requires_confirmation=False,
        produces_artifact=True,
        artifact_type="plan",
        output_fields=["PATCH_PROMPT"],
        next_recommended_skills=["auditor_request"],
    ),
    "auditor_request": SkillSpec(
        skill_id="auditor_request",
        display_name="Auditor Help Request",
        phase="BUILD",
        aliases_ru=["auditor request", "запроси аудитора", "помощь аудитора",
                    "попроси аудитора", "отправь аудитору", "обратись к аудитору"],
        aliases_en=["auditor request", "request auditor", "ask auditor", "auditor help"],
        purpose="Create a pending auditor request artifact. Requires CONFIRM.",
        requires_confirmation=True,
        produces_artifact=True,
        artifact_type="request",
        output_fields=["AUDITOR_REQUEST_PATH"],
        next_recommended_skills=["patch_prompt"],
        safety_constraints=["Requires CONFIRM before writing artifact",
                            "Routes to existing Codex/Bedrock auditor chain"],
    ),
    "skill_request": SkillSpec(
        skill_id="skill_request",
        display_name="Skill Request Governance",
        phase="BUILD",
        aliases_ru=["skill request", "запрос навыка", "создай skill", "новый навык",
                    "предложи skill", "создай skill для"],
        aliases_en=["skill request", "request skill", "new skill", "propose skill", "create skill for"],
        purpose="Create a pending skill request with auditor_review_required=true. Requires CONFIRM.",
        requires_confirmation=True,
        produces_artifact=True,
        artifact_type="request",
        output_fields=["SKILL_REQUEST_PATH", "AUDITOR_REVIEW_REQUIRED"],
        next_recommended_skills=["auditor_request"],
        safety_constraints=["Requires CONFIRM before writing artifact",
                            "auditor_review_required always true"],
    ),
    "learning_registration": SkillSpec(
        skill_id="learning_registration",
        display_name="Learning Registration",
        phase="REFLECT",
        aliases_ru=["зарегистрируй", "learning registration", "запиши в обучение",
                    "добавь в обучение", "зарегистрируй сбой", "зарегистрируй в учебный пайплайн"],
        aliases_en=["learning registration", "register learning", "register failure",
                    "add to training", "register event"],
        purpose="Register a failure/correction as a learning event candidate. Requires CONFIRM.",
        requires_confirmation=True,
        produces_artifact=True,
        artifact_type="event",
        output_fields=["LEARNING_EVENT_PATH"],
        next_recommended_skills=["retro"],
        safety_constraints=["Requires CONFIRM before writing event",
                            "training_eligible=false until verifier present",
                            "Does not start training automatically"],
    ),
}


def find_skill(text: str) -> SkillSpec | None:
    """Return the best matching skill spec for a given text, or None."""
    low = (text or "").lower()
    # Score each skill by alias match
    best: tuple[int, SkillSpec | None] = (0, None)
    for skill in SKILL_REGISTRY.values():
        score = 0
        for alias in skill.aliases_ru + skill.aliases_en:
            if alias.lower() in low:
                score = max(score, len(alias))
        if score > best[0]:
            best = (score, skill)
    return best[1] if best[0] > 3 else None


def list_skills() -> list[dict[str, Any]]:
    """Return a flat list of skill summaries."""
    return [
        {"skill_id": s.skill_id, "display_name": s.display_name, "phase": s.phase,
         "requires_confirmation": s.requires_confirmation, "purpose": s.purpose}
        for s in SKILL_REGISTRY.values()
    ]
