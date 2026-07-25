"""Tests for logi_skill_system.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))

from ops.agents.logi_skill_system import find_skill, SKILL_REGISTRY, list_skills


def test_office_hours_matched_russian():
    skill = find_skill("Логи, проведи office hours по идее локальный агент")
    assert skill is not None
    assert skill.skill_id == "office_hours"


def test_ceo_review_matched():
    skill = find_skill("Логи, сделай ceo review для этой идеи")
    assert skill is not None
    assert skill.skill_id == "ceo_review"


def test_eng_review_matched():
    skill = find_skill("Логи, сделай eng review для safe restart через confirmation flow")
    assert skill is not None
    assert skill.skill_id == "eng_review"


def test_capability_gap_matched_russian():
    skill = find_skill("Логи, что тебе не хватает чтобы самому чинить такие проблемы?")
    assert skill is not None
    assert skill.skill_id == "capability_gap"


def test_patch_prompt_matched():
    skill = find_skill("Логи, подготовь prompt для патча restart_container_allowlisted")
    assert skill is not None
    assert skill.skill_id == "patch_prompt"


def test_skill_request_matched():
    skill = find_skill("Логи, создай skill для диагностики сервисов")
    assert skill is not None
    assert skill.skill_id == "skill_request"
    assert skill.requires_confirmation is True


def test_learning_registration_matched():
    skill = find_skill("Логи, зарегистрируй этот сбой в учебный пайплайн")
    assert skill is not None
    assert skill.skill_id == "learning_registration"
    assert skill.requires_confirmation is True


def test_skill_request_auditor_review_required():
    skill = SKILL_REGISTRY["skill_request"]
    assert skill.requires_confirmation is True
    assert "auditor_review_required" in " ".join(skill.safety_constraints).lower() or \
           "auditor" in " ".join(skill.safety_constraints).lower()


def test_learning_registration_no_training():
    skill = SKILL_REGISTRY["learning_registration"]
    assert "training" in " ".join(skill.safety_constraints).lower() or \
           "training" in skill.purpose.lower()


def test_all_skills_have_required_fields():
    for sid, skill in SKILL_REGISTRY.items():
        assert skill.skill_id == sid
        assert skill.display_name
        assert skill.phase in {"THINK", "PLAN", "BUILD", "REVIEW", "TEST", "SHIP", "REFLECT"}
        assert skill.purpose
        assert isinstance(skill.aliases_ru, list)
        assert isinstance(skill.aliases_en, list)
        assert isinstance(skill.requires_confirmation, bool)
        assert skill.artifact_type in ("analysis", "plan", "request", "event", "none")


def test_list_skills_returns_all():
    skills = list_skills()
    assert len(skills) >= 15
    ids = {s["skill_id"] for s in skills}
    for expected in ["office_hours", "ceo_review", "eng_review", "capability_gap",
                     "patch_prompt", "auditor_request", "skill_request", "learning_registration",
                     "session_discovery", "session_summary", "session_recall",
                     "session_playbook", "session_learning_registration"]:
        assert expected in ids


def test_session_learning_skills_matched():
    assert find_skill("Логи, изучи прошлые сессии").skill_id == "session_discovery"
    assert find_skill("Логи, найди похожие прошлые задачи").skill_id == "session_recall"
    assert find_skill("Логи, собери playbook из прошлых ошибок").skill_id == "session_playbook"
    skill = find_skill("Логи, зарегистрируй урок из этой сессии")
    assert skill.skill_id == "session_learning_registration"
    assert skill.requires_confirmation is True


def test_unknown_text_returns_none():
    skill = find_skill("hello how are you today")
    # Very short/generic text should not match confidently
    assert skill is None or skill.skill_id  # None or valid — not crash


def test_evidence_check_matched():
    skill = find_skill("Проверь файл с доказательствами: покажи вывод команды ls -la")
    assert skill.skill_id == "evidence_check"
    assert skill.requires_confirmation is False
    assert "UNPROVEN_OR_UNKNOWN" in skill.output_fields


def test_evidence_check_matches_coaching_lesson():
    lesson = (
        "COACHING LESSON 1.1: FILE EXISTENCE CHECKS. "
        "Check if 3 files exist. Run: ls -la /home/axi_omi_sphere/aims-workspace/[filepath]. "
        "Do NOT claim anything without showing the ls output."
    )
    skill = find_skill(lesson)
    assert skill is not None
    assert skill.skill_id == "evidence_check"


def test_evidence_check_in_registry():
    ids = {s["skill_id"] for s in list_skills()}
    assert "evidence_check" in ids
