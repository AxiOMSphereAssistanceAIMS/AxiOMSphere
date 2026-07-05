from ops.agents.m10_safety_adapter import check_m10_safety, SafetyCheckResult


def test_status_query_allowed():
    r = check_m10_safety("покажи статус проекта", "telegram", 0.9)
    assert r.allowed is True


def test_destructive_keyword_blocked():
    r = check_m10_safety("удали базу данных", "telegram", 0.9)
    assert r.allowed is False
    assert "destructive" in r.reason.lower() or "запрещ" in r.reason.lower()


def test_low_confidence_blocks_execution():
    r = check_m10_safety("запусти что-нибудь", "cli", 0.5)
    assert r.allowed is False or r.requires_confirmation is True


def test_telegram_execution_requires_confirmation():
    r = check_m10_safety("запусти задачу CC-TASK-0001", "telegram", 0.9)
    assert r.requires_confirmation is True


def test_repair_requires_confirmation():
    r = check_m10_safety("исправь scheduler", "telegram", 0.85)
    assert r.requires_confirmation is True


def test_redis_heavy_with_status_passed():
    r = check_m10_safety(
        "перезапусти Redis scheduler", "telegram", 0.85,
        redis_integration_passed=True
    )
    assert r.requires_confirmation is True


def test_result_is_dataclass():
    r = check_m10_safety("show status", "cli", 0.8)
    assert hasattr(r, "allowed")
    assert hasattr(r, "action")
    assert hasattr(r, "reason")
    assert hasattr(r, "requires_confirmation")


def test_rm_rf_blocked():
    r = check_m10_safety("run rm -rf /tmp", "cli", 0.95)
    assert r.allowed is False
