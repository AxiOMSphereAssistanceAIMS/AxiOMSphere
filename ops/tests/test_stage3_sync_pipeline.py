"""Stage 3: Sync pipeline — classify intent → dispatch to agent.

Tests the full sync dispatch chain with all external calls mocked:
  prompt + files → _classify_sync → dispatch → agent → result

Steps validated:
  Step A  keyword fast-path  (_classify_sync)
  Step B  local model path   (_classify_sync — high/low confidence)
  Step C  docx dispatch      (dispatch → DocAgentClient)
  Step D  chat dispatch      (dispatch → ModelRouter)
  Step E  ask / clarify      (dispatch → no agent call)
  Step F  ModelRouter fallback  (primary fail → fallback succeeds)
  Step G  error propagation  (agent failure → success=False)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

OPS = Path(__file__).resolve().parents[1]
WORKSPACE = OPS.parent
for _p in (str(OPS), str(WORKSPACE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── Step A/B: _classify_sync ──────────────────────────────────────────────────

class TestClassifySync:
    """_classify_sync: keyword fast-path and local model branch."""

    def test_keyword_docx_bypasses_local(self):
        from sync_pipeline import _classify_sync
        with patch("router.local_router.classify_file_intent") as mock_local:
            intent = _classify_sync("generate a word report", "analysis.pdf")
        assert intent == "docx"
        mock_local.assert_not_called()

    def test_keyword_edit_bypasses_local(self):
        from sync_pipeline import _classify_sync
        with patch("router.local_router.classify_file_intent") as mock_local:
            intent = _classify_sync("update the table", "data.xlsx")
        assert intent == "edit"
        mock_local.assert_not_called()

    def test_local_high_confidence_used(self):
        from sync_pipeline import _classify_sync
        with patch("router.local_router.classify_file_intent", return_value=("chat", 0.9)):
            intent = _classify_sync("what is in this file?", "report.pdf")
        assert intent == "chat"

    def test_local_low_confidence_returns_ask(self):
        """Low local confidence → ask (no cloud call in sync mode)."""
        from sync_pipeline import _classify_sync
        with patch("router.local_router.classify_file_intent", return_value=("chat", 0.4)):
            intent = _classify_sync("hmm interesting stuff here", "report.pdf")
        assert intent == "ask"

    def test_local_ollama_unavailable_returns_ask(self):
        """Ollama not configured → local_router returns ('ask', 0.0) → ask."""
        from sync_pipeline import _classify_sync
        with patch("router.local_router.classify_file_intent", return_value=("ask", 0.0)):
            intent = _classify_sync("check this doc", "safety.pdf")
        assert intent == "ask"

    def test_confidence_exactly_at_threshold_accepted(self):
        from sync_pipeline import _classify_sync
        with patch("router.local_router.classify_file_intent", return_value=("docx", 0.7)):
            intent = _classify_sync("make a document", "data.pdf")
        assert intent == "docx"

    def test_confidence_just_below_threshold_rejected(self):
        from sync_pipeline import _classify_sync
        with patch("router.local_router.classify_file_intent", return_value=("docx", 0.69)):
            intent = _classify_sync("make a document", "data.pdf")
        assert intent == "ask"


# ── Step C: docx dispatch ──────────────────────────────────────────────────────

class TestDispatchDocx:
    """dispatch → DocAgentClient.generate on docx intent."""

    def _mock_doc_agent(self, return_value):
        mock_client = MagicMock()
        mock_client.generate.return_value = return_value
        mock_cls = MagicMock(return_value=mock_client)
        return mock_cls, mock_client

    def test_docx_calls_doc_agent(self):
        from sync_pipeline import dispatch
        mock_cls, mock_client = self._mock_doc_agent({"ok": True, "path": "/out/doc.docx"})

        with patch("router.fallback_router._keyword_fast_path", return_value="docx"), \
             patch("doc_agent_api.DocAgentClient", mock_cls):
            result = dispatch(
                "generate a safety report",
                [{"name": "procedure.pdf", "excerpt": "1. Scope\n2. Hazards"}],
            )

        assert result["success"] is True
        assert result["intent"] == "docx"
        assert result["agent"] == "doc_agent"
        assert result["result"] == "/out/doc.docx"
        mock_client.generate.assert_called_once()

    def test_docx_passes_source_docs(self):
        """source_docs should carry excerpts from uploaded files."""
        from sync_pipeline import dispatch
        mock_cls, mock_client = self._mock_doc_agent({"ok": True, "path": "/out/doc.docx"})
        files = [
            {"name": "proc_a.pdf", "excerpt": "Safety content A"},
            {"name": "proc_b.pdf", "excerpt": "Safety content B"},
            {"name": "image.png"},  # no excerpt — must be omitted
        ]

        with patch("router.fallback_router._keyword_fast_path", return_value="docx"), \
             patch("doc_agent_api.DocAgentClient", mock_cls):
            dispatch("compare and generate report", files)

        _, kwargs = mock_client.generate.call_args
        src = kwargs.get("source_docs") or []
        assert len(src) == 2
        assert all(d["text"] for d in src)

    def test_docx_agent_error_returns_failure(self):
        from sync_pipeline import dispatch
        mock_cls, mock_client = self._mock_doc_agent(None)
        mock_client.generate.side_effect = RuntimeError("doc-agent unreachable")

        with patch("router.fallback_router._keyword_fast_path", return_value="docx"), \
             patch("doc_agent_api.DocAgentClient", mock_cls):
            result = dispatch("generate report", [])

        assert result["success"] is False
        assert result["error"] is not None
        assert result["intent"] == "docx"

    def test_docx_agent_ok_false_returns_failure(self):
        from sync_pipeline import dispatch
        mock_cls, mock_client = self._mock_doc_agent({"ok": False, "error": "template missing"})

        with patch("router.fallback_router._keyword_fast_path", return_value="docx"), \
             patch("doc_agent_api.DocAgentClient", mock_cls):
            result = dispatch("generate report", [])

        assert result["success"] is False
        assert "template missing" in (result["error"] or "")


# ── Step D: chat dispatch ──────────────────────────────────────────────────────

class TestDispatchChat:
    """dispatch → ModelRouter.generate on chat intent."""

    def _make_router(self, return_value: dict):
        router = MagicMock()
        router.generate.return_value = return_value
        return router

    def test_chat_calls_model_router(self):
        from sync_pipeline import dispatch
        router = self._make_router({"success": True, "result": "Analysis complete.", "provider": "nim"})

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.9)):
            result = dispatch(
                "analyze this document",
                [{"name": "doc.pdf", "excerpt": "Procedure content"}],
                model_router=router,
            )

        assert result["success"] is True
        assert result["intent"] == "chat"
        assert result["result"] == "Analysis complete."
        router.generate.assert_called_once()

    def test_chat_prompt_includes_file_context(self):
        """File excerpts must be appended to the prompt sent to ModelRouter."""
        from sync_pipeline import dispatch
        router = self._make_router({"success": True, "result": "ok", "provider": "local"})

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.85)):
            dispatch(
                "summarize these files",
                [{"name": "a.txt", "excerpt": "Content of A"}, {"name": "b.txt", "excerpt": "Content of B"}],
                model_router=router,
            )

        _, kwargs = router.generate.call_args
        sent_prompt = kwargs["prompt"]
        assert "Content of A" in sent_prompt
        assert "Content of B" in sent_prompt

    def test_chat_model_router_failure_returned(self):
        from sync_pipeline import dispatch
        router = self._make_router({"success": False, "error": "both providers failed"})

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.95)):
            result = dispatch("analyze this", [], model_router=router)

        assert result["success"] is False
        assert "failed" in (result["error"] or "")


# ── Step E: ask / clarify ─────────────────────────────────────────────────────

class TestDispatchAsk:
    """Low-confidence or ambiguous → clarify signal returned without agent call."""

    def test_ask_returns_clarify_no_agent_call(self):
        from sync_pipeline import dispatch
        doc_agent_called = []

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("ask", 0.2)), \
             patch("doc_agent_api.DocAgentClient", side_effect=lambda *a, **kw: doc_agent_called.append(1)):
            result = dispatch("...", [{"name": "mystery.bin"}])

        assert result["intent"] == "ask"
        assert result["agent"] == "clarify"
        assert result["success"] is True
        assert result["result"] is None
        assert doc_agent_called == []

    def test_edit_intent_returns_clarify(self):
        """'edit' from keyword fast-path — sync pipeline defers to caller."""
        from sync_pipeline import dispatch
        with patch("router.fallback_router._keyword_fast_path", return_value="edit"):
            result = dispatch("update the table", [{"name": "data.xlsx"}])
        assert result["intent"] == "edit"
        assert result["agent"] == "clarify"


# ── Step F: ModelRouter internal fallback ─────────────────────────────────────

class TestModelRouterFallback:
    """ModelRouter primary (nim) fails → fallback (local) succeeds."""

    def test_primary_fail_triggers_fallback(self):
        from sync_pipeline import dispatch
        from core.router.model_router import ModelRouter

        mock_nim = MagicMock()
        mock_nim.generate.side_effect = RuntimeError("NIM timeout")
        mock_local = MagicMock()
        mock_local.generate.return_value = "Local fallback answer"

        router = ModelRouter.__new__(ModelRouter)
        router.clients = {
            "local": mock_local,
            "nim": mock_nim,
            "claude": MagicMock(),
        }
        router.task_map = {"analysis": "nim", "cheap": "local"}
        router.fallbacks = {"nim": "local", "local": "nim", "claude": "nim"}

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.9)):
            result = dispatch("analyze this", [], model_router=router)

        assert result["success"] is True
        assert result["agent"] == "local"
        mock_nim.generate.assert_called_once()
        mock_local.generate.assert_called_once()

    def test_both_fail_returns_error(self):
        from sync_pipeline import dispatch
        from core.router.model_router import ModelRouter

        mock_nim = MagicMock()
        mock_nim.generate.side_effect = RuntimeError("NIM down")
        mock_local = MagicMock()
        mock_local.generate.side_effect = RuntimeError("Ollama down")

        router = ModelRouter.__new__(ModelRouter)
        router.clients = {
            "local": mock_local,
            "nim": mock_nim,
            "claude": MagicMock(),
        }
        router.task_map = {"analysis": "nim", "cheap": "local"}
        router.fallbacks = {"nim": "local", "local": "nim", "claude": "nim"}

        with patch("router.fallback_router._keyword_fast_path", return_value=None), \
             patch("router.local_router.classify_file_intent", return_value=("chat", 0.9)):
            result = dispatch("analyze this", [], model_router=router)

        assert result["success"] is False
        assert result["error"] is not None

    def test_nim_unavailable_signal_not_retried(self):
        """nim_unavailable: prefix → SafeNIMClient skips retry."""
        from core.router.model_router import SafeNIMClient
        client = SafeNIMClient.__new__(SafeNIMClient)
        client.api_key = ""  # no key → unavailable signal
        result = client.generate("test prompt")
        assert result.startswith("nim_unavailable:")
