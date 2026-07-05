# ops/agents/tests/test_logi_assistant_gateway.py
from ops.telegram.logi_bot_assistant import should_route_to_gateway


def test_logi_prefix_routes():
    assert should_route_to_gateway("Логи, проверь статус DOCSREG") is True


def test_logi_english_prefix_routes():
    assert should_route_to_gateway("Logi, check status") is True


def test_logi_slash_routes():
    assert should_route_to_gateway("/logi status") is True


def test_normal_message_does_not_route():
    assert should_route_to_gateway("Hello how are you?") is False


def test_other_slash_does_not_route():
    assert should_route_to_gateway("/help") is False
    assert should_route_to_gateway("/status") is False


def test_gateway_returns_dict():
    from ops.agents.logi_assistant_gateway import process_gateway_message
    result = process_gateway_message("покажи статус проекта", "cli", "0", "test_user")
    assert isinstance(result, dict)
    assert "status" in result


def test_gateway_operational_question_loads_context():
    from ops.agents.logi_assistant_gateway import process_gateway_message
    result = process_gateway_message(
        "есть ли сегодня обучение модели?", "cli", "0", "test_user")
    assert isinstance(result, dict)
    # Must not crash even if no live context available
    assert result.get("status") != "EXCEPTION"


def test_gateway_destructive_blocked():
    from ops.agents.logi_assistant_gateway import process_gateway_message
    result = process_gateway_message("удали базу данных", "telegram", "123", "user")
    assert result.get("status") in ("BLOCKED", "REQUIRES_CONFIRMATION")
    assert result.get("allowed") is False or result.get("requires_confirmation") is True


# ─── LogiAgent delegation fix ─────────────────────────────────────────────────

def test_gateway_delegates_to_logi_agent_run_when_chat_unavailable():
    """Gateway must call .run() when LogiAgent has no .chat() method."""
    from unittest.mock import MagicMock, patch
    from ops.agents.logi_assistant_gateway import process_gateway_message

    mock_agent = MagicMock(spec=[])  # no .chat attribute
    mock_agent.run = MagicMock(return_value="Принял. Работаю.")
    del mock_agent.chat  # ensure .chat is absent

    with patch("ops.agents.logi_assistant_gateway.LogiAgent", return_value=mock_agent,
               create=True):
        # We need to patch the import inside the function
        import ops.agents.logi_assistant_gateway as gw_mod
        orig = None
        try:
            from ops.logi import conversational_orchestrator as orch_mod
            orig = orch_mod.LogiAgent
            orch_mod.LogiAgent = lambda: mock_agent
            result = process_gateway_message("покажи статус", "telegram", "42", "user")
        finally:
            if orig is not None:
                orch_mod.LogiAgent = orig

    assert result.get("summary") == "Принял. Работаю."
    assert result.get("warning") is None or "unavailable" not in result.get("warning", "")


def test_gateway_no_logi_unavailable_when_run_succeeds():
    """When LogiAgent.run() returns a value, gateway must NOT say 'LogiAgent unavailable'."""
    from ops.agents.logi_assistant_gateway import process_gateway_message

    result = process_gateway_message("logi status", source="telegram", chat_id="1")
    assert result.get("warning") != "LogiAgent unavailable"
    assert "LogiAgent unavailable" not in result.get("summary", "")


def test_gateway_exposes_error_class_when_delegation_raises():
    """When LogiAgent raises an exception, gateway returns error_class, not silent None."""
    from unittest.mock import patch
    from ops.agents.logi_assistant_gateway import process_gateway_message

    class _BrokenAgent:
        def run(self, uid, text):
            raise RuntimeError("simulated failure")

    import ops.logi.conversational_orchestrator as orch_mod
    orig = orch_mod.LogiAgent
    try:
        orch_mod.LogiAgent = _BrokenAgent
        result = process_gateway_message("покажи статус", "telegram", "1", "user")
    finally:
        orch_mod.LogiAgent = orig

    assert result.get("status") == "DEGRADED"
    assert result.get("error_class") == "LOGI_AGENT_DELEGATION_FAILED"
    assert "simulated failure" in result.get("error_message", "")
    assert result.get("warning") == "LogiAgent delegation failed"


def test_executor_route_still_passes():
    """Executor route must remain unaffected by the LogiAgent fix."""
    from ops.agents.logi_assistant_gateway import process_gateway_message
    result = process_gateway_message(
        "run_local_executor_task aims_workspace/test_tasks/executor_test_01.json",
        source="telegram",
    )
    assert result.get("action_type") == "run_local_executor_task"
    assert result.get("status") == "PASSED"
