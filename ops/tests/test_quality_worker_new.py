"""Tests for new quality_worker.py features: correction_pass, mode="thorough", FtCaseStore registration."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))


class TestCorrectionPass(unittest.TestCase):
    """correction_pass returns original content when no gaps or model fails."""

    def test_empty_gaps_returns_content_unchanged(self):
        from workers.quality_worker import correction_pass
        result = correction_pass("some content", gaps=[])
        self.assertEqual(result, "some content")

    def test_model_error_returns_original(self):
        from workers.quality_worker import correction_pass
        with mock.patch("workers.quality_worker._ollama_generate", side_effect=Exception("timeout")):
            result = correction_pass("original text", gaps=["gap 1"])
        self.assertEqual(result, "original text")

    def test_model_returns_corrected(self):
        from workers.quality_worker import correction_pass
        with mock.patch("workers.quality_worker._ollama_generate", return_value="CORRECTED"):
            result = correction_pass("original", gaps=["missing scope"])
        self.assertEqual(result, "CORRECTED")

    def test_model_empty_response_returns_original(self):
        from workers.quality_worker import correction_pass
        with mock.patch("workers.quality_worker._ollama_generate", return_value="   "):
            result = correction_pass("original", gaps=["gap"])
        self.assertEqual(result, "original")


class TestRegisterCases(unittest.TestCase):
    def test_writes_json_files_to_quality_dir(self):
        from workers import quality_worker
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = quality_worker._QUALITY_PAIRS_DIR
            quality_worker._QUALITY_PAIRS_DIR = Path(tmp)
            try:
                saved = quality_worker._register_cases(
                    store=None,
                    doc_name="policy.md",
                    gaps=["Missing risk register", "No RACI matrix"],
                    original="original content",
                    corrected="corrected content",
                    score_before=0.5,
                    score_after=0.9,
                )
                files = list(Path(tmp).glob("qloop_*.json"))
                self.assertEqual(saved, 2)
                self.assertEqual(len(files), 2)
            finally:
                quality_worker._QUALITY_PAIRS_DIR = original_dir

    def test_training_pair_format(self):
        from workers import quality_worker
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = quality_worker._QUALITY_PAIRS_DIR
            quality_worker._QUALITY_PAIRS_DIR = Path(tmp)
            try:
                quality_worker._register_cases(
                    store=None,
                    doc_name="doc.md",
                    gaps=["gap1"],
                    original="orig",
                    corrected="corr",
                    score_before=0.4,
                    score_after=0.8,
                )
                files = list(Path(tmp).glob("*.json"))
                data = json.loads(files[0].read_text())
                self.assertIn("messages", data)
                roles = [m["role"] for m in data["messages"]]
                self.assertEqual(roles, ["system", "user", "assistant"])
            finally:
                quality_worker._QUALITY_PAIRS_DIR = original_dir

    def test_calls_store_add_case(self):
        from workers import quality_worker
        store = mock.MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = quality_worker._QUALITY_PAIRS_DIR
            quality_worker._QUALITY_PAIRS_DIR = Path(tmp)
            try:
                quality_worker._register_cases(
                    store=store,
                    doc_name="x.md",
                    gaps=["gap A", "gap B"],
                    original="o",
                    corrected="c",
                    score_before=0.3,
                    score_after=0.7,
                )
                self.assertEqual(store.add_case.call_count, 2)
            finally:
                quality_worker._QUALITY_PAIRS_DIR = original_dir

    def test_store_exception_does_not_crash(self):
        from workers import quality_worker
        store = mock.MagicMock()
        store.add_case.side_effect = Exception("DB error")
        with tempfile.TemporaryDirectory() as tmp:
            original_dir = quality_worker._QUALITY_PAIRS_DIR
            quality_worker._QUALITY_PAIRS_DIR = Path(tmp)
            try:
                saved = quality_worker._register_cases(
                    store=store,
                    doc_name="x.md",
                    gaps=["gap"],
                    original="o",
                    corrected="c",
                    score_before=0.3,
                    score_after=0.7,
                )
                # JSON file still written even if store fails
                self.assertEqual(saved, 1)
            finally:
                quality_worker._QUALITY_PAIRS_DIR = original_dir


class TestCheckDocumentModeFast(unittest.TestCase):
    """mode='fast' — no correction, gaps saved to store."""

    def _write_doc(self, tmp_dir: str, content: str) -> Path:
        p = Path(tmp_dir) / "test_doc.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_fast_mode_does_not_call_correction_pass(self):
        from workers.quality_worker import check_document
        reqs = ["Has scope", "Has objectives"]
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._write_doc(tmp, "# Policy\n## Scope\nCovers all assets.\n")
            with mock.patch("workers.quality_worker.fetch_standard_requirements", return_value=reqs), \
                 mock.patch("workers.quality_worker.compare_doc_to_requirements",
                            return_value=(0.5, ["Missing objectives"])), \
                 mock.patch("workers.quality_worker.correction_pass") as mock_corr:
                result = check_document(doc, mode="fast")
                mock_corr.assert_not_called()

    def test_fast_mode_returns_result_with_score(self):
        from workers.quality_worker import check_document
        reqs = ["Has scope"]
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._write_doc(tmp, "# Policy\n## Scope\nContent.\n")
            with mock.patch("workers.quality_worker.fetch_standard_requirements", return_value=reqs), \
                 mock.patch("workers.quality_worker.compare_doc_to_requirements",
                            return_value=(0.7, ["gap1"])):
                result = check_document(doc, mode="fast")
                self.assertAlmostEqual(result.score, 0.7)
                self.assertEqual(result.passes, 0)

    def test_fast_mode_saves_gaps_to_store(self):
        from workers.quality_worker import check_document
        store = mock.MagicMock()
        reqs = ["Has scope"]
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as pairs_tmp:
            doc = self._write_doc(tmp, "# Policy\nContent.")
            from workers import quality_worker
            original_dir = quality_worker._QUALITY_PAIRS_DIR
            quality_worker._QUALITY_PAIRS_DIR = Path(pairs_tmp)
            try:
                with mock.patch("workers.quality_worker.fetch_standard_requirements", return_value=reqs), \
                     mock.patch("workers.quality_worker.compare_doc_to_requirements",
                                return_value=(0.5, ["missing scope"])):
                    result = check_document(doc, mode="fast", store=store)
                store.add_case.assert_called_once()
                self.assertEqual(result.pairs_saved, 1)
            finally:
                quality_worker._QUALITY_PAIRS_DIR = original_dir

    def test_fast_approved_doc_does_not_save_pairs(self):
        from workers.quality_worker import check_document
        store = mock.MagicMock()
        reqs = ["Has scope"]
        with tempfile.TemporaryDirectory() as tmp:
            doc = self._write_doc(tmp, "# Policy\nContent.")
            with mock.patch("workers.quality_worker.fetch_standard_requirements", return_value=reqs), \
                 mock.patch("workers.quality_worker.compare_doc_to_requirements",
                            return_value=(0.95, [])):
                result = check_document(doc, mode="fast", store=store)
            store.add_case.assert_not_called()
            self.assertTrue(result.approved)


class TestCheckDocumentModeThorough(unittest.TestCase):
    """mode='thorough' — correction loop runs up to MAX_PASSES."""

    def _write_doc(self, tmp_dir: str, content: str) -> Path:
        p = Path(tmp_dir) / "test_doc.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_thorough_calls_correction_pass(self):
        from workers.quality_worker import check_document
        reqs = ["Has scope"]
        compare_results = [
            (0.5, ["missing scope"]),    # initial
            (0.9, []),                   # after correction
        ]
        compare_iter = iter(compare_results)
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as pairs_tmp:
            doc = self._write_doc(tmp, "# Policy\nContent.")
            from workers import quality_worker
            original_dir = quality_worker._QUALITY_PAIRS_DIR
            quality_worker._QUALITY_PAIRS_DIR = Path(pairs_tmp)
            try:
                with mock.patch("workers.quality_worker.fetch_standard_requirements", return_value=reqs), \
                     mock.patch("workers.quality_worker.compare_doc_to_requirements",
                                side_effect=lambda *a, **kw: next(compare_iter)), \
                     mock.patch("workers.quality_worker.correction_pass", return_value="corrected text") as mock_corr:
                    result = check_document(doc, mode="thorough")
                mock_corr.assert_called_once()
                self.assertEqual(result.passes, 1)
            finally:
                quality_worker._QUALITY_PAIRS_DIR = original_dir

    def test_thorough_stops_when_approved(self):
        from workers.quality_worker import check_document
        reqs = ["Has scope", "Has objectives"]
        # After first correction → already above threshold → loop stops
        compare_results = [
            (0.4, ["gap1", "gap2"]),  # initial
            (0.92, []),               # after first correction
        ]
        compare_iter = iter(compare_results)
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as pairs_tmp:
            doc = self._write_doc(tmp, "# Policy\nContent.")
            from workers import quality_worker
            original_dir = quality_worker._QUALITY_PAIRS_DIR
            quality_worker._QUALITY_PAIRS_DIR = Path(pairs_tmp)
            try:
                with mock.patch("workers.quality_worker.fetch_standard_requirements", return_value=reqs), \
                     mock.patch("workers.quality_worker.compare_doc_to_requirements",
                                side_effect=lambda *a, **kw: next(compare_iter)), \
                     mock.patch("workers.quality_worker.correction_pass", return_value="corrected"):
                    result = check_document(doc, mode="thorough")
                self.assertEqual(result.passes, 1)
                self.assertTrue(result.approved)
            finally:
                quality_worker._QUALITY_PAIRS_DIR = original_dir

    def test_thorough_saves_pairs_per_gap(self):
        from workers.quality_worker import check_document
        reqs = ["req1", "req2"]
        compare_results = [
            (0.3, ["gap1", "gap2"]),
            (0.9, []),
        ]
        compare_iter = iter(compare_results)
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as pairs_tmp:
            doc = self._write_doc(tmp, "# Doc\nContent.")
            from workers import quality_worker
            original_dir = quality_worker._QUALITY_PAIRS_DIR
            quality_worker._QUALITY_PAIRS_DIR = Path(pairs_tmp)
            try:
                with mock.patch("workers.quality_worker.fetch_standard_requirements", return_value=reqs), \
                     mock.patch("workers.quality_worker.compare_doc_to_requirements",
                                side_effect=lambda *a, **kw: next(compare_iter)), \
                     mock.patch("workers.quality_worker.correction_pass", return_value="corrected"):
                    result = check_document(doc, mode="thorough")
                # 2 gaps → 2 training pairs
                self.assertEqual(result.pairs_saved, 2)
                files = list(Path(pairs_tmp).glob("*.json"))
                self.assertEqual(len(files), 2)
            finally:
                quality_worker._QUALITY_PAIRS_DIR = original_dir

    def test_thorough_writes_corrected_content_to_file(self):
        from workers.quality_worker import check_document
        reqs = ["req1"]
        compare_results = [(0.5, ["gap"]), (0.9, [])]
        compare_iter = iter(compare_results)
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as pairs_tmp:
            doc = self._write_doc(tmp, "# Doc\nOriginal content.")
            from workers import quality_worker
            original_dir = quality_worker._QUALITY_PAIRS_DIR
            quality_worker._QUALITY_PAIRS_DIR = Path(pairs_tmp)
            try:
                with mock.patch("workers.quality_worker.fetch_standard_requirements", return_value=reqs), \
                     mock.patch("workers.quality_worker.compare_doc_to_requirements",
                                side_effect=lambda *a, **kw: next(compare_iter)), \
                     mock.patch("workers.quality_worker.correction_pass", return_value="IMPROVED CONTENT"):
                    check_document(doc, mode="thorough")
                self.assertEqual(doc.read_text(), "IMPROVED CONTENT")
            finally:
                quality_worker._QUALITY_PAIRS_DIR = original_dir

    def test_thorough_score_before_reflects_initial(self):
        from workers.quality_worker import check_document
        reqs = ["req1"]
        compare_results = [(0.3, ["gap"]), (0.9, [])]
        compare_iter = iter(compare_results)
        with tempfile.TemporaryDirectory() as tmp, \
             tempfile.TemporaryDirectory() as pairs_tmp:
            doc = self._write_doc(tmp, "# Doc\nContent.")
            from workers import quality_worker
            original_dir = quality_worker._QUALITY_PAIRS_DIR
            quality_worker._QUALITY_PAIRS_DIR = Path(pairs_tmp)
            try:
                with mock.patch("workers.quality_worker.fetch_standard_requirements", return_value=reqs), \
                     mock.patch("workers.quality_worker.compare_doc_to_requirements",
                                side_effect=lambda *a, **kw: next(compare_iter)), \
                     mock.patch("workers.quality_worker.correction_pass", return_value="improved"):
                    result = check_document(doc, mode="thorough")
                self.assertAlmostEqual(result.score_before, 0.3)
                self.assertAlmostEqual(result.score, 0.9)
            finally:
                quality_worker._QUALITY_PAIRS_DIR = original_dir


class TestQualityResultFields(unittest.TestCase):
    """QualityResult has all required fields."""

    def test_dataclass_fields_exist(self):
        from workers.quality_worker import QualityResult
        r = QualityResult(score=0.8, gaps=[], approved=True, requirements=[])
        self.assertEqual(r.passes, 0)
        self.assertEqual(r.pairs_saved, 0)
        self.assertEqual(r.score_before, 0.0)
        self.assertFalse(r.needs_review)
        self.assertEqual(r.error, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
