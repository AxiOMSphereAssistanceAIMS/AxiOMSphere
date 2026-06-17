"""
Валидация тренировочного датасета для QLoRA FT.

Запуск: cd aims-workspace && python3 -m unittest ops/tests/test_ft_dataset.py -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

_ops_dir = Path(__file__).resolve().parents[1]
if str(_ops_dir) not in sys.path:
    sys.path.insert(0, str(_ops_dir))

DATASET_PATH = Path(
    os.environ.get(
        "FT_DATASET",
        str(Path(__file__).resolve().parents[2] / "ops/ft/data/v11/train_v11.jsonl"),
    )
)

REQUIRED_ACTIONS = {
    "classify_doc", "create_master", "find_duplicates",
    "generate_report", "reassign_doc",
    "clarify", "handoff_axi", "answer", "search",
}

MIN_EXAMPLES = 750
MIN_PER_ACTION = 5


def _load_rows() -> list[dict]:
    if not DATASET_PATH.is_file():
        return []
    lines = DATASET_PATH.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(l) for l in lines if l.strip()]


def _task_from_row(row: dict) -> str:
    import re
    msgs = row.get("messages", [])
    for m in msgs:
        if m.get("role") == "assistant":
            content = m.get("content", "")
            # JSON action field: {"action": "search", ...}
            hit = re.search(r'"action"\s*:\s*"([^"]+)"', content)
            if hit:
                return hit.group(1)
            # legacy format: {"task": "search", ...}
            hit = re.search(r'"task"\s*:\s*"([^"]+)"', content)
            if hit:
                return hit.group(1)
    return "?"


class TestFtDatasetExists(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(
            DATASET_PATH.is_file(),
            f"Dataset not found: {DATASET_PATH}",
        )


@unittest.skipUnless(DATASET_PATH.is_file(), "dataset file missing")
class TestFtDatasetSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _load_rows()

    def test_minimum_examples(self):
        self.assertGreaterEqual(
            len(self.rows), MIN_EXAMPLES,
            f"Too few examples: {len(self.rows)} < {MIN_EXAMPLES}",
        )

    def test_no_parse_errors(self):
        """Every line must be valid JSON — already parsed in setUpClass."""
        self.assertGreater(len(self.rows), 0)

    def test_messages_field_present(self):
        bad = [i for i, r in enumerate(self.rows, 1) if "messages" not in r]
        self.assertEqual(bad, [], f"Rows missing 'messages': {bad[:10]}")

    def test_messages_is_list(self):
        bad = [i for i, r in enumerate(self.rows, 1)
               if not isinstance(r.get("messages"), list)]
        self.assertEqual(bad, [], f"'messages' not a list at lines: {bad[:10]}")

    def test_each_example_has_assistant_turn(self):
        bad = [
            i for i, r in enumerate(self.rows, 1)
            if not any(m.get("role") == "assistant" for m in r.get("messages", []))
        ]
        self.assertEqual(bad, [], f"Missing assistant turn at lines: {bad[:10]}")

    def test_each_example_has_user_turn(self):
        bad = [
            i for i, r in enumerate(self.rows, 1)
            if not any(m.get("role") == "user" for m in r.get("messages", []))
        ]
        self.assertEqual(bad, [], f"Missing user turn at lines: {bad[:10]}")

    def test_no_empty_content(self):
        bad = []
        for i, r in enumerate(self.rows, 1):
            for m in r.get("messages", []):
                if not (m.get("content") or "").strip():
                    bad.append((i, m.get("role")))
        self.assertEqual(bad, [], f"Empty content in turns: {bad[:10]}")

    def test_roles_valid(self):
        valid = {"system", "user", "assistant"}
        bad = []
        for i, r in enumerate(self.rows, 1):
            for m in r.get("messages", []):
                role = m.get("role", "")
                if role not in valid:
                    bad.append((i, role))
        self.assertEqual(bad, [], f"Invalid roles: {bad[:10]}")


@unittest.skipUnless(DATASET_PATH.is_file(), "dataset file missing")
class TestFtDatasetCoverage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = _load_rows()
        from collections import Counter
        cls.counts: Counter = Counter(_task_from_row(r) for r in rows)
        cls.total = len(rows)

    def test_all_required_actions_present(self):
        missing = [a for a in REQUIRED_ACTIONS if self.counts.get(a, 0) == 0]
        self.assertEqual(missing, [], f"Actions with zero examples: {missing}")

    def test_minimum_per_action(self):
        low = {
            a: self.counts[a]
            for a in REQUIRED_ACTIONS
            if self.counts.get(a, 0) < MIN_PER_ACTION
        }
        self.assertEqual(low, {}, f"Actions below {MIN_PER_ACTION} examples: {low}")

    def test_coverage_report(self):
        """Informational — always passes, prints distribution."""
        lines = [f"Total: {self.total}"]
        for a in sorted(REQUIRED_ACTIONS):
            c = self.counts.get(a, 0)
            bar = "█" * min(c // 5, 20)
            lines.append(f"  {a:<28} {c:4d}  {bar}")
        print("\n" + "\n".join(lines))


if __name__ == "__main__":
    unittest.main(verbosity=2)
