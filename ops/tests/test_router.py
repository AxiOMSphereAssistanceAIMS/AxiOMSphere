"""Smoke tests for Phase 1 — intent router (no Ollama, no Anthropic).

Tests:
  1. local_router._parse_response — JSON and plain-text fallback
  2. fallback_router._keyword_fast_path — docx patterns, edit keywords
  3. fallback_router.classify_file_intent — uses mock local + anthropic callables
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))


class TestLocalRouterParse(unittest.TestCase):
    def _parse(self, raw: str):
        from router.local_router import _parse_response
        return _parse_response(raw)

    def test_valid_json(self):
        intent, conf = self._parse('{"intent": "docx", "confidence": 0.92}')
        self.assertEqual(intent, "docx")
        self.assertAlmostEqual(conf, 0.92)

    def test_json_in_markdown_fence(self):
        raw = '```json\n{"intent": "edit", "confidence": 0.85}\n```'
        intent, conf = self._parse(raw)
        self.assertEqual(intent, "edit")
        self.assertAlmostEqual(conf, 0.85)

    def test_plain_text_fallback(self):
        intent, conf = self._parse("chat")
        self.assertEqual(intent, "chat")
        self.assertEqual(conf, 0.5)

    def test_unknown_label_returns_ask(self):
        intent, conf = self._parse('{"intent": "unknown_label", "confidence": 0.99}')
        self.assertEqual(intent, "ask")
        self.assertEqual(conf, 0.0)

    def test_empty_returns_ask(self):
        intent, conf = self._parse("")
        self.assertEqual(intent, "ask")
        self.assertEqual(conf, 0.0)

    def test_confidence_clamped(self):
        intent, conf = self._parse('{"intent": "chat", "confidence": 1.5}')
        self.assertEqual(intent, "chat")
        self.assertLessEqual(conf, 1.0)


class TestKeywordFastPath(unittest.TestCase):
    def _kfp(self, prompt: str, file_names: str = ""):
        from router.fallback_router import _keyword_fast_path
        return _keyword_fast_path(prompt, file_names)

    def test_docx_word_keyword(self):
        self.assertEqual(self._kfp("send me a word report"), "docx")

    def test_docx_ru_keyword(self):
        self.assertEqual(self._kfp("пришли в ворд"), "docx")

    def test_docx_generate_report(self):
        self.assertEqual(self._kfp("generate a report"), "docx")

    def test_edit_xlsx_update(self):
        result = self._kfp("update the table", "data.xlsx")
        self.assertEqual(result, "edit")

    def test_edit_no_xlsx_returns_none(self):
        result = self._kfp("update the table", "doc.pdf")
        self.assertIsNone(result)

    def test_plain_chat_returns_none(self):
        self.assertIsNone(self._kfp("what is the status?"))

    def test_docx_takes_priority_over_edit(self):
        result = self._kfp("generate a report, update the word file", "data.xlsx")
        self.assertEqual(result, "docx")


class TestFallbackRouterPipeline(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_keyword_fast_path_skips_local(self):
        """Keyword match should never call local or Anthropic."""
        calls = []

        async def fake_anthropic(prompt, file_names):
            calls.append("anthropic")
            return "chat"

        from router.fallback_router import classify_file_intent
        result = self._run(
            classify_file_intent(
                "generate a word report",
                "analysis.xlsx",
                anthropic_fallback_fn=fake_anthropic,
            )
        )
        self.assertEqual(result, "docx")
        self.assertEqual(calls, [])

    def test_high_confidence_local_skips_anthropic(self):
        """Local confidence ≥ 0.7 should not call Anthropic."""
        import router.local_router as _lr
        _orig = _lr.classify_file_intent

        def fake_local(prompt, file_names):
            return ("chat", 0.9)

        _lr.classify_file_intent = fake_local
        calls = []

        async def fake_anthropic(prompt, file_names):
            calls.append("anthropic")
            return "docx"

        try:
            from router.fallback_router import classify_file_intent
            result = self._run(
                classify_file_intent(
                    "what is in this file?",
                    "report.pdf",
                    anthropic_fallback_fn=fake_anthropic,
                )
            )
            self.assertEqual(result, "chat")
            self.assertEqual(calls, [])
        finally:
            _lr.classify_file_intent = _orig

    def test_low_confidence_calls_anthropic(self):
        """Local confidence < 0.7 should call Anthropic and use its result."""
        import router.local_router as _lr
        _orig = _lr.classify_file_intent

        def fake_local(prompt, file_names):
            return ("ask", 0.4)

        _lr.classify_file_intent = fake_local

        async def fake_anthropic(prompt, file_names):
            return "docx"

        try:
            from router.fallback_router import classify_file_intent
            result = self._run(
                classify_file_intent(
                    "can you check this?",
                    "report.pdf",
                    anthropic_fallback_fn=fake_anthropic,
                )
            )
            self.assertEqual(result, "docx")
        finally:
            _lr.classify_file_intent = _orig

    def test_anthropic_error_falls_back_to_local(self):
        """If Anthropic raises, local intent is returned."""
        import router.local_router as _lr
        _orig = _lr.classify_file_intent

        def fake_local(prompt, file_names):
            return ("edit", 0.55)

        _lr.classify_file_intent = fake_local

        async def boom(prompt, file_names):
            raise RuntimeError("network error")

        try:
            from router.fallback_router import classify_file_intent
            result = self._run(
                classify_file_intent(
                    "modify the table",
                    "data.xlsx",
                    anthropic_fallback_fn=boom,
                )
            )
            self.assertEqual(result, "edit")
        finally:
            _lr.classify_file_intent = _orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
