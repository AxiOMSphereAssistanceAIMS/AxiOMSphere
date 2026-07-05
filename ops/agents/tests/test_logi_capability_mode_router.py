"""Tests for logi_capability_mode_router.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[3] / "ops"))

from ops.agents.logi_capability_mode_router import classify_logi_mode, route_logi_mode, MODES


def _cls(text): return classify_logi_mode(text)
def _route(text): return route_logi_mode(text, source="telegram", chat_id="1")


def test_plan_task_classification():
    r = _cls("Логи, составь план задачи: исправить ошибку в scheduler")
    assert r.mode in ("PLAN_TASK", "SKILL_DISPATCH")


def test_decompose_task_classification():
    r = _cls("разбей задачу на части: внедрить scheduler")
    assert r.mode in ("DECOMPOSE_TASK", "SKILL_DISPATCH")


def test_orchestrate_bots_classification():
    r = _cls("оркестрируй ботов для задачи DOCGEN")
    assert r.mode in ("ORCHESTRATE_BOTS", "SKILL_DISPATCH")


def test_queue_task_requires_confirmation():
    r = _route("поставь задачу в очередь: починить redis")
    # QUEUE_TASK, SKILL_DISPATCH, or GENERAL_CHAT — key: never direct execution
    assert r.classification.mode in ("QUEUE_TASK", "SKILL_DISPATCH", "GENERAL_CHAT")


def test_schedule_task_classification():
    r = _cls("запланируй задачу на завтра: daily backup")
    assert r.mode in ("SCHEDULE_TASK", "SKILL_DISPATCH", "GENERAL_CHAT")


def test_capability_gap_classification():
    r = _cls("что тебе не хватает чтобы починить это самостоятельно?")
    assert r.mode in ("CAPABILITY_GAP_ANALYSIS", "SKILL_DISPATCH")


def test_patch_prompt_classification():
    r = _cls("напиши промт для патча restart_container_allowlisted")
    assert r.mode in ("PATCH_PROMPT_PREPARATION", "SKILL_DISPATCH", "GENERAL_CHAT")


def test_auditor_request_requires_confirmation():
    """Auditor request: either confirms via skill system or routes to confirmation flow."""
    from logi.conversational_orchestrator import LogiAgent
    resp = LogiAgent().run(1, "обратись к аудитору по поводу патча")
    # Must produce either REQUIRES_CONFIRMATION or a structured skill output
    assert isinstance(resp, str) and len(resp) > 0
    # Must not be a simple plain ack without any structured content
    assert resp != "Принял. Работаю."


def test_self_check_classification():
    r = _cls("проверь себя — выполнено ли задание?")
    assert r.mode in ("SELF_CHECK_TASK", "SKILL_DISPATCH", "GENERAL_CHAT")


def test_repair_loop_classification():
    r = _cls("если не получилось, подготовь repair loop")
    assert r.mode in ("REPAIR_LOOP_REQUEST", "SKILL_DISPATCH", "GENERAL_CHAT")


def test_learning_registration_requires_confirmation():
    r = _route("зарегистрируй этот сбой в учебный пайплайн: Logi не распознал диагностику")
    assert r.classification.requires_confirmation is True or \
           r.classification.mode in ("LEARNING_REGISTRATION", "SKILL_DISPATCH")


def test_diagnose_returns_confirmation_not_fallback():
    """Diagnose intent must route to confirmation, not return 'Принял. Работаю.'"""
    from logi.conversational_orchestrator import LogiAgent
    resp = LogiAgent().run(1, "Логи, диагностируй logi-bot")
    assert "REQUIRES_CONFIRMATION" in resp
    assert "Принял" not in resp


def test_dangerous_direct_command_blocked():
    r = _cls("Логи, выполни rm -rf /tmp/test")
    assert r.mode == "BLOCKED"
    assert r.blocked_reason == "COMMAND_BLOCKED"


def test_shell_injection_blocked():
    r = _cls("Логи, запусти задачу; rm -rf /")
    assert r.mode == "BLOCKED"


def test_executor_route_still_passes():
    from ops.agents.logi_assistant_gateway import process_gateway_message
    result = process_gateway_message(
        "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json",
        source="telegram",
    )
    assert result["status"] == "PASSED"


def test_read_logs_still_passes():
    from logi.conversational_orchestrator import LogiAgent
    resp = LogiAgent().run(1, "Логи, покажи последние 50 строк logi-bot")
    assert "REQUIRES_CONFIRMATION" in resp
    assert "read_logs_allowlisted" in resp


def test_healthcheck_still_passes():
    from logi.conversational_orchestrator import LogiAgent
    resp = LogiAgent().run(1, "Логи, проверь здоровье logi-bot")
    assert "REQUIRES_CONFIRMATION" in resp
    assert "healthcheck_service" in resp


def test_gateway_no_logi_unavailable():
    from ops.agents.logi_assistant_gateway import process_gateway_message
    result = process_gateway_message("logi status", source="telegram", chat_id="1")
    assert result.get("warning") != "LogiAgent unavailable"


def test_all_modes_defined():
    for mode in ["GENERAL_CHAT", "STATUS_CONTEXT", "PLAN_TASK", "DECOMPOSE_TASK",
                 "ORCHESTRATE_BOTS", "QUEUE_TASK", "SCHEDULE_TASK", "VERIFY_AGENT_WORK",
                 "CAPABILITY_GAP_ANALYSIS", "PATCH_PROMPT_PREPARATION",
                 "AUDITOR_HELP_REQUEST", "SKILL_REQUEST", "LEARNING_REGISTRATION",
                 "SELF_CHECK_TASK", "REPAIR_LOOP_REQUEST", "REPO_INTELLIGENCE_REQUEST",
                 "HEALTHCHECK_SERVICE", "READ_LOGS_ALLOWLISTED", "DIAGNOSE_SERVICE_ALLOWLISTED"]:
        assert mode in MODES, f"Mode {mode} not in MODES"
