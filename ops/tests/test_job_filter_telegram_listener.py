from __future__ import annotations

import json

import pytest

import job_filter_telegram_listener as listener


def test_extract_json_object_plain() -> None:
    assert listener._extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_object_code_fenced() -> None:
    text = '```json\n{"a": 1}\n```'
    assert listener._extract_json_object(text) == {"a": 1}


def test_extract_json_object_embedded_in_prose() -> None:
    text = 'Sure, here is the JSON: {"a": 1} — hope that helps.'
    assert listener._extract_json_object(text) == {"a": 1}


def test_extract_json_object_garbage_returns_none() -> None:
    assert listener._extract_json_object("not json at all") is None


def test_parse_change_request_confident_match(monkeypatch) -> None:
    reply = json.dumps(
        {
            "confident": True,
            "action": "add_title_exclusion",
            "target": "mechanical",
            "understood_summary": "Exclude titles containing 'mechanical'.",
        }
    )
    monkeypatch.setattr(listener, "_local_llm_chat", lambda messages: reply)

    result = listener.parse_change_request("уберите чистых механиков")

    assert result["confident"] is True
    assert result["action"] == "add_title_exclusion"
    assert result["target"] == "mechanical"


def test_parse_change_request_rejects_unsupported_action(monkeypatch) -> None:
    """If the model invents an action outside the fixed vocabulary, that
    must degrade to a clarifying question, not be executed as if it were
    real — this is the hallucination guard.
    """
    reply = json.dumps(
        {
            "confident": True,
            "action": "rewrite_scraper_from_scratch",
            "target": "linkedin",
            "understood_summary": "Rewrite the LinkedIn scraper.",
        }
    )
    monkeypatch.setattr(listener, "_local_llm_chat", lambda messages: reply)

    result = listener.parse_change_request("перепиши скрапер линкедина")

    assert result["confident"] is False
    assert "clarifying_question" in result


def test_parse_change_request_llm_unreachable_asks_clarification(monkeypatch) -> None:
    def _boom(messages):
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(listener, "_local_llm_chat", _boom)

    result = listener.parse_change_request("что-нибудь")

    assert result["confident"] is False
    assert "clarifying_question" in result


def test_parse_change_request_malformed_llm_output_asks_clarification(monkeypatch) -> None:
    monkeypatch.setattr(listener, "_local_llm_chat", lambda messages: "I cannot help with that.")

    result = listener.parse_change_request("что-нибудь")

    assert result["confident"] is False


def test_parse_change_request_confident_without_target_is_rejected(monkeypatch) -> None:
    reply = json.dumps(
        {
            "confident": True,
            "action": "add_title_exclusion",
            "target": "",
            "understood_summary": "x",
        }
    )
    monkeypatch.setattr(listener, "_local_llm_chat", lambda messages: reply)

    result = listener.parse_change_request("x")

    assert result["confident"] is False


def test_current_filter_summary_reflects_live_config(monkeypatch) -> None:
    monkeypatch.setenv("JOB_FILTER_DRAFT_MIN_ATS_PERCENT", "20")
    summary = listener.current_filter_summary()
    assert "electrical" in summary
    assert "mechanical" in summary
    assert "20%" in summary


def test_current_task_summary_reflects_queue(monkeypatch, tmp_path) -> None:
    from ops.agents import job_filter_change_request as jfcr

    base = tmp_path / "joblocator_requests"
    monkeypatch.setattr(jfcr, "_BASE_DIR", base)
    monkeypatch.setattr(jfcr, "_PENDING_DIR", base / "pending")
    monkeypatch.setattr(jfcr, "_CONFIRMED_DIR", base / "confirmed")
    monkeypatch.setattr(jfcr, "_COMPLETED_DIR", base / "completed")
    monkeypatch.setattr(jfcr, "_REJECTED_DIR", base / "rejected")
    monkeypatch.setattr(
        jfcr,
        "_ALL_DIRS",
        (base / "pending", base / "confirmed", base / "completed", base / "rejected"),
    )
    monkeypatch.setattr(listener, "jfcr", jfcr)

    record = jfcr.write_change_request(
        requested_by="111",
        raw_request_text="test",
        understood_summary="Exclude 'electrical' titles",
        proposed_change={"action": "add_title_exclusion", "target": "electrical"},
    )

    summary = listener.current_task_summary()
    assert record.request_id in summary
    assert "Exclude 'electrical' titles" in summary
