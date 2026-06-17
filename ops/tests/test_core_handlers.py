"""Smoke tests for Phase 0 — core infrastructure (no Telegram, no DB, no Ollama).

Tests:
  1. AIMSError — creation, properties, subclasses
  2. core.metrics — imports without error; no-op stubs callable
  3. cross_bot_handoff — input validation (bad target returns None without DB)
  4. cross_bot_handoff — infer_lang_ru pure string function
  5. cross_bot_handoff — retry constants accessible
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))


class TestAIMSError(unittest.TestCase):
    def test_basic_fields(self):
        from core.errors import AIMSError
        e = AIMSError("test_code", "something broke", recoverable=False)
        self.assertEqual(e.code, "test_code")
        self.assertEqual(str(e), "something broke")
        self.assertFalse(e.recoverable)

    def test_default_recoverable(self):
        from core.errors import AIMSError
        e = AIMSError("x", "msg")
        self.assertTrue(e.recoverable)

    def test_llm_error_subclass(self):
        from core.errors import AIMSError, LLMError
        e = LLMError("timeout", provider="gemini")
        self.assertIsInstance(e, AIMSError)
        self.assertEqual(e.provider, "gemini")
        self.assertIn("gemini", e.code)

    def test_db_error_subclass(self):
        from core.errors import AIMSError, DBError
        e = DBError("write failed")
        self.assertIsInstance(e, AIMSError)
        self.assertEqual(e.code, "db_error")

    def test_handoff_error_subclass(self):
        from core.errors import AIMSError, HandoffError
        e = HandoffError("queue full")
        self.assertIsInstance(e, AIMSError)

    def test_sandbox_error_not_recoverable_by_default(self):
        from core.errors import SandboxError
        e = SandboxError("execution timeout")
        self.assertFalse(e.recoverable)


class TestMetrics(unittest.TestCase):
    def test_import_without_prometheus(self):
        # Should import cleanly even if prometheus_client is not installed
        from core.metrics import (
            handler_calls_total,
            handoff_ops_total,
            llm_calls_total,
            llm_latency_seconds,
            record_llm_call,
        )
        self.assertIsNotNone(llm_calls_total)
        self.assertIsNotNone(llm_latency_seconds)

    def test_noop_counter_callable(self):
        from core.metrics import llm_calls_total
        # Must not raise regardless of whether prometheus is installed
        llm_calls_total.labels(provider="test", model="m", status="ok").inc()

    def test_record_llm_call_context_manager(self):
        from core.metrics import record_llm_call
        # Normal exit — should not raise
        with record_llm_call(provider="local", model="qwen2.5-14b"):
            pass

    def test_record_llm_call_propagates_exception(self):
        from core.metrics import record_llm_call
        with self.assertRaises(ValueError):
            with record_llm_call(provider="local", model="qwen2.5-14b"):
                raise ValueError("llm broke")


class TestCrossBotHandoff(unittest.TestCase):
    def test_bad_target_returns_none(self):
        from cross_bot_handoff import enqueue_handoff
        # Bad target — should return None without touching any DB
        result = enqueue_handoff(
            target="invalid_bot",
            source_bot="axi",
            chat_id=12345,
            user_id=None,
            payload="test",
        )
        self.assertIsNone(result)

    def test_bad_source_returns_none(self):
        from cross_bot_handoff import enqueue_handoff
        result = enqueue_handoff(
            target="axi",
            source_bot="unknown",
            chat_id=12345,
            user_id=None,
            payload="test",
        )
        self.assertIsNone(result)

    def test_empty_payload_returns_none(self):
        from cross_bot_handoff import enqueue_handoff
        result = enqueue_handoff(
            target="axi",
            source_bot="omi",
            chat_id=12345,
            user_id=None,
            payload="   ",
        )
        self.assertIsNone(result)

    def test_infer_lang_ru_detects_cyrillic(self):
        from cross_bot_handoff import infer_lang_ru
        self.assertTrue(infer_lang_ru("Привет, как дела?"))
        self.assertTrue(infer_lang_ru("hello мир"))

    def test_infer_lang_ru_latin_only(self):
        from cross_bot_handoff import infer_lang_ru
        self.assertFalse(infer_lang_ru("hello world"))
        self.assertFalse(infer_lang_ru(""))

    def test_retry_constants(self):
        import cross_bot_handoff
        self.assertGreater(cross_bot_handoff.HANDOFF_MAX_RETRIES, 0)
        self.assertGreater(cross_bot_handoff.HANDOFF_RETRY_BACKOFF_SEC, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
