"""Tests for the real SLOT32 chat wiring (network mocked)."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from ops.agents import logi_llm_chat as chat


def _fake_response(content: str):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"choices": [{"message": {"content": content}}]}
    ).encode()
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


def test_slot32_chat_returns_model_content():
    with patch("urllib.request.urlopen", return_value=_fake_response("привет от slot32")):
        assert chat.slot32_chat("тест") == "привет от slot32"


def test_slot32_chat_raises_typed_error_when_all_candidates_fail():
    import urllib.error
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
        with pytest.raises(chat.Slot32Unavailable):
            chat.slot32_chat("тест")


def test_slot32_chat_raises_on_malformed_response_from_all_candidates():
    mock_resp = MagicMock()
    mock_resp.read.return_value = b"not json"
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(chat.Slot32Unavailable):
            chat.slot32_chat("тест")


def test_slot32_chat_falls_through_to_working_candidate():
    import urllib.error
    calls = {"n": 0}

    def side_effect(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 2:
            raise urllib.error.URLError("connection refused (container-local)")
        return _fake_response("ответ через прокси")

    with patch("urllib.request.urlopen", side_effect=side_effect):
        assert chat.slot32_chat("тест") == "ответ через прокси"
    assert calls["n"] >= 2


def test_proxy_candidate_sends_bearer_token():
    captured = {}

    def side_effect(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.headers.get("Authorization")
        if "18081" in req.full_url or (chat._DIRECT_CANDIDATES[0][0] and
                                        chat._DIRECT_CANDIDATES[0][0] in req.full_url):
            import urllib.error
            raise urllib.error.URLError("down")
        return _fake_response("ok")

    with patch("urllib.request.urlopen", side_effect=side_effect):
        chat.slot32_chat("тест")
    assert captured.get("auth") == f"Bearer {chat.SLOT32_PROXY_TOKEN}"


def test_build_chat_context_prompt_includes_history_and_case():
    prompt = chat.build_chat_context_prompt(
        "Опиши суть",
        history=["первое сообщение", "второе сообщение"],
        skill_context="STRATEGY_PACK",
        recent_case={"title": "Lesson 1.3", "source": "logi_task_queue",
                     "outcome": "completed", "human_report_ru": "файл существует"},
    )
    assert "Опиши суть" in prompt
    assert "второе сообщение" in prompt
    assert "Lesson 1.3" in prompt
    assert "файл существует" in prompt
    assert "STRATEGY_PACK" in prompt


def test_build_chat_context_prompt_without_case_or_history():
    prompt = chat.build_chat_context_prompt("привет", history=[], skill_context="")
    assert "привет" in prompt
    assert "ПОСЛЕДНИЙ РАЗОБРАННЫЙ КЕЙС" not in prompt
