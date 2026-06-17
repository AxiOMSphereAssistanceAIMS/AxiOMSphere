"""Tests for FtCaseStore — SQLite accumulator for quality gap/correction pairs."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))


def _make_store(tmp_dir: str):
    from workers.ft_case_store import FtCaseStore
    return FtCaseStore(db_path=Path(tmp_dir) / "test_ft.db")


class TestFtCaseStoreAddAndCount(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.store = _make_store(self._tmp)

    def test_initial_pending_count_zero(self):
        self.assertEqual(self.store.pending_count(), 0)

    def test_add_case_increments_count(self):
        self.store.add_case(
            doc_name="policy.md",
            requirement="Must define scope",
            original_excerpt="The policy covers...",
            corrected_excerpt="The policy covers all physical assets...",
            gap_description="Scope is too vague",
            score_before=0.6,
            score_after=0.9,
        )
        self.assertEqual(self.store.pending_count(), 1)

    def test_add_multiple_cases(self):
        for i in range(5):
            self.store.add_case(
                doc_name=f"doc{i}.md",
                requirement=f"Requirement {i}",
                original_excerpt="original",
                corrected_excerpt="corrected",
            )
        self.assertEqual(self.store.pending_count(), 5)

    def test_add_case_returns_id(self):
        id1 = self.store.add_case("a.md", "req1", "orig", "corr")
        id2 = self.store.add_case("b.md", "req2", "orig", "corr")
        self.assertIsInstance(id1, int)
        self.assertIsInstance(id2, int)
        self.assertGreater(id2, id1)


class TestFtCaseStoreGetPending(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.store = _make_store(self._tmp)
        for i in range(3):
            self.store.add_case(
                doc_name=f"doc{i}.md",
                requirement=f"req{i}",
                original_excerpt=f"orig{i}",
                corrected_excerpt=f"corr{i}",
                gap_description=f"gap{i}",
                score_before=0.5,
                score_after=0.8,
            )

    def test_get_pending_returns_all(self):
        cases = self.store.get_pending(limit=10)
        self.assertEqual(len(cases), 3)

    def test_get_pending_respects_limit(self):
        cases = self.store.get_pending(limit=2)
        self.assertEqual(len(cases), 2)

    def test_get_pending_includes_expected_fields(self):
        cases = self.store.get_pending()
        c = cases[0]
        self.assertIn("id", c)
        self.assertIn("doc_name", c)
        self.assertIn("requirement", c)
        self.assertIn("original_excerpt", c)
        self.assertIn("corrected_excerpt", c)
        self.assertIn("gap_description", c)
        self.assertIn("score_before", c)
        self.assertIn("score_after", c)
        self.assertIn("created_at", c)

    def test_get_pending_run_id_is_none(self):
        for c in self.store.get_pending():
            self.assertIsNone(c["run_id"])


class TestFtCaseStoreMarkUsed(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.store = _make_store(self._tmp)
        for i in range(4):
            self.store.add_case(f"d{i}.md", f"r{i}", "o", "c")

    def test_mark_used_reduces_pending(self):
        cases = self.store.get_pending(limit=4)
        ids = [c["id"] for c in cases[:2]]
        self.store.mark_used(ids, run_id="run_001")
        self.assertEqual(self.store.pending_count(), 2)

    def test_mark_used_sets_run_id(self):
        cases = self.store.get_pending(limit=4)
        ids = [c["id"] for c in cases]
        self.store.mark_used(ids, run_id="test_run_42")
        used = self.store.all_for_run("test_run_42")
        self.assertEqual(len(used), 4)

    def test_mark_used_empty_list_is_noop(self):
        before = self.store.pending_count()
        self.store.mark_used([], run_id="noop")
        self.assertEqual(self.store.pending_count(), before)

    def test_all_for_run_returns_only_matching(self):
        cases = self.store.get_pending(limit=4)
        ids_a = [cases[0]["id"], cases[1]["id"]]
        ids_b = [cases[2]["id"], cases[3]["id"]]
        self.store.mark_used(ids_a, "run_A")
        self.store.mark_used(ids_b, "run_B")
        self.assertEqual(len(self.store.all_for_run("run_A")), 2)
        self.assertEqual(len(self.store.all_for_run("run_B")), 2)
        self.assertEqual(len(self.store.all_for_run("run_X")), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
