"""Smoke tests for Phase 3 — queue.py and quality_worker.py (no Redis, no network).

Tests:
  1. TaskQueue helpers work without Redis (connection error expected)
  2. extract_doc_description — headings extraction
  3. _parse_requirements_json — valid / invalid JSON
  4. _parse_score_json — valid / missing fields / bad JSON
  5. check_document — missing file returns error QualityResult
  6. extract_doc_description — falls back to raw text when no headings
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))


class TestExtractDocDescription(unittest.TestCase):
    def _desc(self, text: str, max_chars: int = 500) -> str:
        from workers.quality_worker import extract_doc_description
        return extract_doc_description(text, max_chars)

    def test_markdown_headings(self):
        text = "# Integrity Management Policy\n## Scope\n## Objectives\nSome body text."
        desc = self._desc(text)
        self.assertIn("Integrity Management Policy", desc)
        self.assertIn("Scope", desc)
        self.assertIn("Objectives", desc)

    def test_numbered_headings(self):
        text = "1. Asset Lifecycle Overview\n2. Risk Assessment\nBody text here."
        desc = self._desc(text)
        self.assertIn("Asset Lifecycle Overview", desc)

    def test_max_chars_respected(self):
        text = "# " + "A" * 600
        desc = self._desc(text, max_chars=50)
        self.assertLessEqual(len(desc), 50)

    def test_fallback_to_raw_text(self):
        text = "plain text without any headings at all, just words"
        desc = self._desc(text)
        self.assertGreater(len(desc), 0)

    def test_empty_content(self):
        desc = self._desc("")
        self.assertEqual(desc, "")


class TestParseRequirementsJson(unittest.TestCase):
    def _parse(self, raw: str):
        from workers.quality_worker import _parse_requirements_json
        return _parse_requirements_json(raw)

    def test_plain_json_array(self):
        raw = '["Req 1", "Req 2", "Req 3"]'
        result = self._parse(raw)
        self.assertEqual(result, ["Req 1", "Req 2", "Req 3"])

    def test_json_in_markdown_fence(self):
        raw = '```json\n["Req A", "Req B"]\n```'
        result = self._parse(raw)
        self.assertIsNotNone(result)
        self.assertIn("Req A", result)

    def test_max_15_items(self):
        items = [f"Req {i}" for i in range(20)]
        raw = repr(items).replace("'", '"')
        result = self._parse(raw)
        self.assertIsNotNone(result)
        self.assertLessEqual(len(result), 15)

    def test_invalid_json_returns_none(self):
        self.assertIsNone(self._parse("not json at all"))

    def test_empty_returns_none(self):
        self.assertIsNone(self._parse(""))

    def test_object_not_array_returns_none(self):
        self.assertIsNone(self._parse('{"key": "value"}'))


class TestParseScoreJson(unittest.TestCase):
    def _parse(self, raw: str):
        from workers.quality_worker import _parse_score_json
        return _parse_score_json(raw)

    def test_valid_response(self):
        raw = '{"score": 0.8, "gaps": ["Missing risk register", "No RACI matrix"]}'
        score, gaps = self._parse(raw)
        self.assertAlmostEqual(score, 0.8)
        self.assertEqual(len(gaps), 2)

    def test_score_clamped_to_one(self):
        raw = '{"score": 1.5, "gaps": []}'
        score, gaps = self._parse(raw)
        self.assertLessEqual(score, 1.0)

    def test_score_clamped_to_zero(self):
        raw = '{"score": -0.3, "gaps": []}'
        score, gaps = self._parse(raw)
        self.assertGreaterEqual(score, 0.0)

    def test_missing_score_defaults_zero(self):
        raw = '{"gaps": ["something"]}'
        score, gaps = self._parse(raw)
        self.assertEqual(score, 0.0)

    def test_invalid_json_returns_error(self):
        score, gaps = self._parse("not json")
        self.assertEqual(score, 0.0)
        self.assertTrue(len(gaps) > 0)

    def test_json_with_prose_prefix(self):
        raw = 'Here is the result:\n{"score": 0.6, "gaps": ["Gap 1"]}'
        score, gaps = self._parse(raw)
        self.assertAlmostEqual(score, 0.6)


class TestCheckDocumentNoFile(unittest.TestCase):
    def test_missing_file_returns_error_result(self):
        from workers.quality_worker import check_document
        result = check_document("/nonexistent/path/doc.md")
        self.assertEqual(result.score, 0.0)
        self.assertFalse(result.approved)
        self.assertIn("not found", result.error)

    def test_existing_file_no_network(self):
        """With no cloud API keys, check_document marks needs_review instead of crashing."""
        import os
        from workers.quality_worker import check_document
        # Temporarily clear API keys
        saved = {k: os.environ.pop(k, None) for k in (
            "GEMINI_API_KEY", "GEMINI_API_KEY_1", "GEMINI_API_KEY_2",
            "GEMINI_API_KEY_3", "GEMINI_API_KEY_4", "ANTHROPIC_API_KEY",
        )}
        try:
            with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
                f.write("# Asset Management Policy\n## Scope\nThis policy covers all assets.\n")
                path = f.name
            result = check_document(path)
            # No API keys → needs_review=True, no crash
            self.assertTrue(result.needs_review)
            self.assertFalse(result.approved)
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v
            Path(path).unlink(missing_ok=True)


class TestTaskQueueNoRedis(unittest.TestCase):
    """Verify TaskQueue raises ConnectionError when Redis is absent."""

    def test_enqueue_raises_without_redis(self):
        import unittest.mock as mock
        from core.queue import TaskQueue
        q = TaskQueue(redis_url="redis://localhost:9999")
        # Inject a broken redis client
        broken = mock.MagicMock()
        broken.lpush.side_effect = Exception("ECONNREFUSED")
        q._r = broken
        with self.assertRaises(Exception):
            q.enqueue("test", {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
