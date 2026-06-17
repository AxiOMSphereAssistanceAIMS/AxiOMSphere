"""Stage 1: DocAgent isolated unit tests.

Tests each component in isolation — no real Ollama or NIM calls.
Mock boundary: _call_llm() and nvidia_nim.score() are patched.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

OPS = Path(__file__).resolve().parents[1]
if str(OPS) not in sys.path:
    sys.path.insert(0, str(OPS))

from doc_agent import DocAgent, DocGenerationRequest, _render_docx, _strip_think_tags


_FAKE_DOC = """\
# Confined Space Entry Procedure

## 1. Scope
This procedure applies to all confined space entry operations at the facility.

## 2. Definitions
Confined space: a space large enough for a worker to enter and perform work.

## 3. Requirements
All entrants must hold a valid permit. A supervisor must be present.
Atmospheric testing required before entry: O2 19.5–23.5%, LEL < 10%.

## 4. Emergency
Rescue team on standby. Emergency number: local emergency response.
"""


class TestDocAgentSingle:
    """Single-model pipeline (no NIM, no dual)."""

    def test_generate_returns_docx(self, tmp_path):
        req = DocGenerationRequest(
            user_request="Write a confined space entry procedure",
            dual_pipeline=False,
            out_dir=tmp_path,
        )
        with patch("doc_agent._call_llm", return_value=_FAKE_DOC):
            agent = DocAgent()
            result = agent.generate(req)

        path, preview, score, feedback = result
        assert path.exists(), "DOCX output file must exist"
        assert path.suffix == ".docx"
        assert len(preview) > 0, "Preview text must be non-empty"
        assert score == 0.0, "Single pipeline: NIM not called, score stays 0.0"

    def test_generate_title_in_filename(self, tmp_path):
        req = DocGenerationRequest(
            user_request="JSA for hot work",
            title="Hot Work JSA",
            dual_pipeline=False,
            out_dir=tmp_path,
        )
        with patch("doc_agent._call_llm", return_value=_FAKE_DOC):
            agent = DocAgent()
            path, *_ = agent.generate(req)

        assert "Hot_Work_JSA" in path.name

    def test_generate_creates_output_dir(self, tmp_path):
        out_dir = tmp_path / "nested" / "output"
        req = DocGenerationRequest(
            user_request="procedure",
            dual_pipeline=False,
            out_dir=out_dir,
        )
        with patch("doc_agent._call_llm", return_value=_FAKE_DOC):
            DocAgent().generate(req)
        assert out_dir.exists()


class TestDocAgentDual:
    """Dual-model pipeline: R1 draft → rewrite → NIM score."""

    def test_dual_passes_quality_gate(self, tmp_path):
        req = DocGenerationRequest(
            user_request="Write a JSA for confined space entry",
            dual_pipeline=True,
            out_dir=tmp_path,
        )
        with (
            patch("doc_agent._call_llm", return_value=_FAKE_DOC),
            patch("doc_agent._vram_unload"),
            patch("doc_agent._nim_score", return_value=(0.92, "meets ISO 45001")),
        ):
            path, preview, score, feedback = DocAgent().generate(req)

        assert path.exists()
        assert score == pytest.approx(0.92)
        assert "ISO" in feedback

    def test_dual_score_below_threshold_retries(self, tmp_path):
        """Score < _QUALITY_THRESHOLD triggers retry; second attempt passes."""
        call_count = {"n": 0}

        def _mock_nim(req_text, doc_text):
            call_count["n"] += 1
            return (0.4, "insufficient") if call_count["n"] == 1 else (0.75, "improved")

        req = DocGenerationRequest(
            user_request="Write a procedure",
            dual_pipeline=True,
            out_dir=tmp_path,
        )
        with (
            patch("doc_agent._call_llm", return_value=_FAKE_DOC),
            patch("doc_agent._vram_unload"),
            patch("doc_agent._nim_score", side_effect=_mock_nim),
        ):
            path, _, score, _ = DocAgent().generate(req)

        assert path.exists()
        assert call_count["n"] >= 2, "Must retry when score < threshold"

    def test_nim_unavailable_skips_quality_gate(self, tmp_path):
        """NIM unavailable (nim_unavailable: prefix) → accept document, no retry."""
        req = DocGenerationRequest(
            user_request="Write a safety procedure",
            dual_pipeline=True,
            out_dir=tmp_path,
        )
        nim_calls = {"n": 0}

        def _mock_nim(req_text, doc_text):
            nim_calls["n"] += 1
            return 0.0, "nim_unavailable: NVIDIA_API_KEY not configured"

        with (
            patch("doc_agent._call_llm", return_value=_FAKE_DOC),
            patch("doc_agent._vram_unload"),
            patch("doc_agent._nim_score", side_effect=_mock_nim),
        ):
            path, _, score, feedback = DocAgent().generate(req)

        assert path.exists(), "Document must be generated even when NIM unavailable"
        assert nim_calls["n"] == 1, "Must not retry when NIM unavailable"


class TestStripThinkTags:
    def test_removes_think_block(self):
        text = "<think>reasoning here</think>\nFinal answer."
        assert _strip_think_tags(text) == "Final answer."

    def test_no_think_block(self):
        text = "Plain text, no think tags."
        assert _strip_think_tags(text) == text

    def test_nested_think_stripped(self):
        text = "<think>step 1\nstep 2</think>\n\nResult"
        result = _strip_think_tags(text)
        assert "<think>" not in result
        assert "Result" in result


class TestRenderDocx:
    def test_renders_valid_docx(self, tmp_path):
        out = tmp_path / "test_doc.docx"
        _render_docx("Test Title", _FAKE_DOC, [], out)
        assert out.exists()
        assert out.stat().st_size > 1000, "DOCX should have real content"

    def test_renders_with_source_docs(self, tmp_path):
        out = tmp_path / "with_sources.docx"
        sources = [{"title": "ISO 45001", "excerpt": "Clause 8.1 requirements..."}]
        _render_docx("Procedure", _FAKE_DOC, sources, out)
        assert out.exists()
