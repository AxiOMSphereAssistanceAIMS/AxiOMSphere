from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest

from ops import cyclic_doc_generation_pipeline as pipeline


def _make_bedrock_response(verdict: str = "A", score: int = 10) -> dict:
    """Build a boto3 invoke_model response dict matching the expected format."""
    body_content = json.dumps({
        "content": [{"text": json.dumps({"verdict": verdict, "score": score, "rationale": "Correct"})}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 50, "output_tokens": 20},
    })
    return {"body": io.BytesIO(body_content.encode())}


def _make_session_mock(fail_first: bool = False, always_fail: bool = False):
    """Return a boto3.Session mock.

    Args:
        fail_first: First invoke_model call raises an exception, second succeeds.
        always_fail: All invoke_model calls raise exceptions.
    """
    call_count = [0]

    def invoke_model(**kwargs):
        call_count[0] += 1
        if always_fail or (fail_first and call_count[0] == 1):
            raise Exception("Simulated Bedrock connection error")
        return _make_bedrock_response()

    bedrock_client = MagicMock()
    bedrock_client.invoke_model.side_effect = invoke_model

    session_mock = MagicMock()
    session_mock.client.return_value = bedrock_client
    return session_mock


def test_judge_smoke_retries_after_timeout(tmp_path) -> None:
    """First attempt (opus) fails; second attempt (sonnet) succeeds."""
    with patch("boto3.Session", return_value=_make_session_mock(fail_first=True)):
        result = pipeline._claude_judge_smoke(tmp_path)

    assert result["status"] == "PASS"
    assert result["passed_attempt"] == 2
    assert result["model"] == "sonnet"
    assert result["degraded_mode"] is True
    assert result["attempts"][0]["status"] == "ERROR"
    assert not (tmp_path / "DOCUMENT_CYCLE_BLOCKED.json").exists()


def test_judge_smoke_writes_blocked_incident(tmp_path) -> None:
    """Both attempts fail → RuntimeError raised + DOCUMENT_CYCLE_BLOCKED.json written."""
    with patch("boto3.Session", return_value=_make_session_mock(always_fail=True)):
        with pytest.raises(RuntimeError, match="document cycle blocked"):
            pipeline._claude_judge_smoke(tmp_path)

    incident = json.loads(
        (tmp_path / "DOCUMENT_CYCLE_BLOCKED.json").read_text()
    )
    assert incident["generation_started"] is False
    assert len(incident["attempts"]) == 2
