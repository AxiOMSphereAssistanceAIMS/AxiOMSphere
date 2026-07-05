from ops.agents.operational_context_merger import merge_operational_context, is_operational_question

_STATIC = {
    "00:30 UTC": "training_generate_pairs — 32B",
    "02:30 UTC": "ft_prepare_chain_run — QLoRA 14B",
}

_LIVE = [{
    "source": "telegram", "channel": "traini",
    "received_at_utc": "2026-07-04T05:28:31Z",
    "raw_text": "Traini slot32: 750-pair gate reached — training scheduled",
    "detected_topics": ["training", "slot32"],
    "detected_status": "TRAINING_SCHEDULED",
    "model_slot": "slot32",
    "candidate": "qwen3-32b-ft-coding-v3-candidate",
    "scheduled_at_utc": "2026-07-04T05:28:31.173551+00:00",
    "pairs_ready": 802, "pairs_required": 750, "confidence": 0.95,
}]

def test_merge_returns_training_scheduled_today():
    r = merge_operational_context(
        "есть ли сегодня обучение?", _STATIC, _LIVE, None, "2026-07-04T06:00:00Z")
    assert r["status"] == "TRAINING_SCHEDULED_TODAY"

def test_sources_include_both():
    r = merge_operational_context(
        "есть ли сегодня обучение?", _STATIC, _LIVE, None, "2026-07-04T06:00:00Z")
    assert "static_schedule" in r["sources_used"]
    assert "telegram_operational_context" in r["sources_used"]

def test_answer_mentions_candidate():
    r = merge_operational_context(
        "есть ли сегодня обучение?", _STATIC, _LIVE, None, "2026-07-04T06:00:00Z")
    assert "qwen3-32b-ft-coding-v3-candidate" in r["answer_summary"]

def test_answer_mentions_pairs():
    r = merge_operational_context(
        "есть ли сегодня обучение?", _STATIC, _LIVE, None, "2026-07-04T06:00:00Z")
    assert "802" in r["answer_summary"]

def test_live_signal_overrides_generic_schedule():
    r = merge_operational_context(
        "обучение сегодня?", _STATIC, _LIVE, None, "2026-07-04T06:00:00Z")
    assert r["live_signal_match"] is True
    assert r["static_schedule_match"] is True

def test_static_only_discloses_unavailability():
    r = merge_operational_context(
        "есть ли сегодня обучение?", _STATIC, [], None, "2026-07-04T06:00:00Z")
    summary_low = r["answer_summary"].lower()
    assert ("live" in summary_low or "unavailable" in summary_low
            or "static" in summary_low or "недоступен" in summary_low)

def test_is_operational_question_true():
    assert is_operational_question("есть ли сегодня обучение модели?") is True
    assert is_operational_question("is training running now?") is True
    assert is_operational_question("проверь нынешний статус scheduler") is True

def test_is_operational_question_false():
    assert is_operational_question("what is ISO 55001?") is False
