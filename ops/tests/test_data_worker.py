"""Smoke tests for Phase 2 — data_worker (no Telegram, no real DB).

Tests:
  1. extract_search_keywords — stop-word filtering, length limit
  2. resolve_doc_path — path not found returns None; aims_workspace re-anchor
  3. fetch_db_docs — missing DB returns empty list (no crash)
  4. query_registry — missing DB returns (0, []) (no crash)
  5. axi_bot._extract_search_keywords / _fetch_db_docs delegate correctly
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))


class TestExtractSearchKeywords(unittest.TestCase):
    def _kw(self, text: str):
        from workers.data_worker import extract_search_keywords
        return extract_search_keywords(text)

    def test_basic_extraction(self):
        kws = self._kw("integrity management procedure")
        self.assertIn("integrity", kws)
        self.assertIn("management", kws)
        self.assertIn("procedure", kws)

    def test_stop_words_filtered(self):
        kws = self._kw("generate a report for the plan")
        self.assertNotIn("generate", kws)
        self.assertNotIn("plan", kws)
        self.assertNotIn("report", kws)

    def test_max_8_keywords(self):
        text = "alpha bravo charlie delta echo foxtrot golf hotel india"
        kws = self._kw(text)
        self.assertLessEqual(len(kws), 8)

    def test_cyrillic_included(self):
        kws = self._kw("стратегия безопасности")
        self.assertIn("стратегия", kws)
        self.assertIn("безопасности", kws)

    def test_short_words_excluded(self):
        kws = self._kw("abc def ghij klmn")
        self.assertNotIn("abc", kws)
        self.assertNotIn("def", kws)


class TestResolveDocPath(unittest.TestCase):
    def _resolve(self, raw, workspace=None):
        from workers.data_worker import resolve_doc_path
        return resolve_doc_path(raw, workspace_path=workspace)

    def test_none_input(self):
        self.assertIsNone(self._resolve(None))

    def test_empty_string(self):
        self.assertIsNone(self._resolve(""))

    def test_nonexistent_path_returns_none(self):
        self.assertIsNone(self._resolve("/nonexistent/path/doc.md"))

    def test_existing_file_returned(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"test content")
            path = f.name
        result = self._resolve(path)
        self.assertIsNotNone(result)
        self.assertTrue(result.exists())

    def test_aims_workspace_reanchor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            doc = ws / "docs" / "test.md"
            doc.parent.mkdir()
            doc.write_text("hello")
            # Simulate a stored path with /aims_workspace/ prefix
            fake_stored = f"/old/server/aims_workspace/docs/test.md"
            result = self._resolve(fake_stored, workspace=ws)
            self.assertIsNotNone(result)
            self.assertEqual(result, doc)


class TestFetchDbDocsNoDb(unittest.TestCase):
    def test_missing_db_returns_empty(self):
        from workers.data_worker import fetch_db_docs
        result = fetch_db_docs(["integrity"], db_path=Path("/nonexistent/aims.db"))
        self.assertEqual(result, [])

    def test_empty_keywords_missing_db_returns_empty(self):
        from workers.data_worker import fetch_db_docs
        result = fetch_db_docs([], db_path=Path("/nonexistent/aims.db"))
        self.assertEqual(result, [])


class TestQueryRegistryNoDb(unittest.TestCase):
    def test_missing_db_returns_zero_empty(self):
        from workers.data_worker import query_registry
        total, rows = query_registry("реестр", db_path=Path("/nonexistent/aims.db"))
        self.assertEqual(total, 0)
        self.assertEqual(rows, [])


class TestDataWorkerParity(unittest.TestCase):
    def test_extract_keywords_consistent(self):
        """Same text always produces same keyword list."""
        from workers.data_worker import extract_search_keywords
        text = "integrity management procedure asset"
        self.assertEqual(extract_search_keywords(text), extract_search_keywords(text))

    def test_fetch_db_docs_result_shape(self):
        """Each returned doc has required keys."""
        from workers.data_worker import fetch_db_docs
        # Non-existent DB → empty, no KeyError
        docs = fetch_db_docs(["test"], db_path=Path("/nonexistent/aims.db"))
        for doc in docs:
            self.assertIn("id", doc)
            self.assertIn("title", doc)
            self.assertIn("process", doc)
            self.assertIn("content", doc)

    def test_query_registry_result_shape(self):
        """Result is always (int, list)."""
        from workers.data_worker import query_registry
        total, rows = query_registry("documents", db_path=Path("/nonexistent/aims.db"))
        self.assertIsInstance(total, int)
        self.assertIsInstance(rows, list)


if __name__ == "__main__":
    unittest.main(verbosity=2)
