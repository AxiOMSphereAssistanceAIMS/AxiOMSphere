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
