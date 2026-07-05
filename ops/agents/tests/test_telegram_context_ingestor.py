# ops/agents/tests/test_telegram_context_ingestor.py
from ops.agents.telegram_context_ingestor import parse_operational_message

_TRAINI_MSG = """Traini slot32: 750-pair gate reached — training scheduled
Candidate: qwen3-32b-ft-coding-v3-candidate
Pairs ready: 802/750
Scheduled at: 2026-07-04T05:28:31.173551+00:00 UTC"""

def test_parse_traini_training_scheduled_message():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert result["detected_status"] == "TRAINING_SCHEDULED"

def test_parse_pairs_ready_802_750():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert result["pairs_ready"] == 802
    assert result["pairs_required"] == 750

def test_parse_candidate_name():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert result["candidate"] == "qwen3-32b-ft-coding-v3-candidate"

def test_parse_model_slot():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert result["model_slot"] == "slot32"

def test_parse_scheduled_at_utc():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert "2026-07-04" in (result["scheduled_at_utc"] or "")

def test_parse_detected_topics_include_training_and_slot():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert "training" in result["detected_topics"]
    assert "slot32" in result["detected_topics"]

def test_parse_channel_traini():
    result = parse_operational_message(_TRAINI_MSG, "2026-07-04T05:28:31Z")
    assert result["channel"] == "traini"

def test_parse_unknown_message_low_confidence():
    result = parse_operational_message("just a normal chat message", "2026-07-04T05:00:00Z")
    assert result["detected_status"] == "UNKNOWN"
    assert result["confidence"] < 0.5
