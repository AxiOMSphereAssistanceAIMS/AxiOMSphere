"""Tests for ft_pipeline.py — dataset build, eval parsing, failure notes, version scan."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))


class TestBuildJsonl(unittest.TestCase):
    def _build(self, cases, out_path):
        from workers.ft_pipeline import build_jsonl
        return build_jsonl(cases, out_path)

    def test_writes_one_line_per_case(self):
        cases = [
            {"original_excerpt": "orig1", "requirement": "req1", "corrected_excerpt": "corr1"},
            {"original_excerpt": "orig2", "requirement": "req2", "corrected_excerpt": "corr2"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "train.jsonl"
            self._build(cases, out)
            lines = out.read_text().splitlines()
            self.assertEqual(len(lines), 2)

    def test_each_line_is_valid_json(self):
        cases = [{"original_excerpt": "o", "requirement": "r", "corrected_excerpt": "c"}]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "train.jsonl"
            self._build(cases, out)
            data = json.loads(out.read_text().strip())
            self.assertIn("messages", data)

    def test_message_roles(self):
        cases = [{"original_excerpt": "o", "requirement": "r", "corrected_excerpt": "c"}]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "train.jsonl"
            self._build(cases, out)
            data = json.loads(out.read_text().strip())
            roles = [m["role"] for m in data["messages"]]
            self.assertEqual(roles, ["system", "user", "assistant"])

    def test_assistant_content_is_corrected(self):
        cases = [{"original_excerpt": "o", "requirement": "r", "corrected_excerpt": "CORRECTED TEXT"}]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "train.jsonl"
            self._build(cases, out)
            data = json.loads(out.read_text().strip())
            assistant_msg = next(m for m in data["messages"] if m["role"] == "assistant")
            self.assertEqual(assistant_msg["content"], "CORRECTED TEXT")

    def test_user_content_contains_requirement(self):
        cases = [{"original_excerpt": "o", "requirement": "UNIQUE_REQ_XYZ", "corrected_excerpt": "c"}]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "train.jsonl"
            self._build(cases, out)
            data = json.loads(out.read_text().strip())
            user_msg = next(m for m in data["messages"] if m["role"] == "user")
            self.assertIn("UNIQUE_REQ_XYZ", user_msg["content"])

    def test_creates_parent_directories(self):
        cases = [{"original_excerpt": "o", "requirement": "r", "corrected_excerpt": "c"}]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "deep" / "nested" / "train.jsonl"
            self._build(cases, out)
            self.assertTrue(out.exists())

    def test_empty_cases_produces_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "train.jsonl"
            self._build([], out)
            self.assertEqual(out.read_text().strip(), "")


class TestEvalModel(unittest.TestCase):
    def _write_eval(self, tmp_dir: str, version: int, cases: list) -> None:
        from workers import ft_pipeline
        log_dir = ft_pipeline._LOGS
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"eval_14_v{version}_golden_v2.json"
        path.write_text(json.dumps({"cases": cases}), encoding="utf-8")
        self._written = path

    def tearDown(self):
        if hasattr(self, "_written") and self._written.exists():
            self._written.unlink()

    def test_all_pass(self):
        self._write_eval("", 999, [{"pass": True}, {"pass": True}])
        from workers.ft_pipeline import eval_model
        self.assertAlmostEqual(eval_model(999), 1.0)

    def test_all_fail(self):
        self._write_eval("", 998, [{"pass": False}, {"pass": False}])
        from workers.ft_pipeline import eval_model
        self.assertAlmostEqual(eval_model(998), 0.0)

    def test_partial_pass(self):
        self._write_eval("", 997, [{"pass": True}, {"pass": False}, {"pass": True}])
        from workers.ft_pipeline import eval_model
        score = eval_model(997)
        self.assertAlmostEqual(score, 2 / 3, places=5)

    def test_result_string_pass(self):
        self._write_eval("", 996, [{"result": "pass"}, {"result": "FAIL"}])
        from workers.ft_pipeline import eval_model
        score = eval_model(996)
        self.assertAlmostEqual(score, 0.5)

    def test_missing_eval_file_returns_zero(self):
        from workers.ft_pipeline import eval_model
        self.assertEqual(eval_model(99999), 0.0)

    def test_empty_cases_returns_zero(self):
        self._write_eval("", 995, [])
        from workers.ft_pipeline import eval_model
        self.assertEqual(eval_model(995), 0.0)


class TestRegisterFailure(unittest.TestCase):
    def test_writes_to_ft_notes(self):
        from workers import ft_pipeline
        notes_path = ft_pipeline._FT_NOTES
        notes_path.parent.mkdir(parents=True, exist_ok=True)
        # Save original content
        original = notes_path.read_text(encoding="utf-8") if notes_path.exists() else None
        try:
            ft_pipeline.register_failure(
                model_name="omi-ft-14b-v99",
                score=0.72,
                failure_details=["score=72% on golden_v2"],
                run_id="test_run_99",
            )
            content = notes_path.read_text(encoding="utf-8")
            self.assertIn("omi-ft-14b-v99", content)
            self.assertIn("72%", content)
            self.assertIn("test_run_99", content)
        finally:
            if original is not None:
                notes_path.write_text(original, encoding="utf-8")
            else:
                notes_path.unlink(missing_ok=True)

    def test_read_pending_notes_returns_empty_when_no_file(self):
        from workers import ft_pipeline
        notes_path = ft_pipeline._FT_NOTES
        if notes_path.exists():
            self.skipTest("ft_notes.md exists, skipping absence test")
        result = ft_pipeline.read_pending_notes()
        self.assertEqual(result, "")


class TestNextVersion(unittest.TestCase):
    def test_returns_at_least_16(self):
        from workers.ft_pipeline import _next_version
        v = _next_version()
        self.assertGreaterEqual(v, 16)

    def test_returns_integer(self):
        from workers.ft_pipeline import _next_version
        self.assertIsInstance(_next_version(), int)


if __name__ == "__main__":
    unittest.main(verbosity=2)
