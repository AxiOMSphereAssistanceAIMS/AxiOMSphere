"""Тест централизованного guard compliance vs file_watch_mode (без Telegram/БД)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))

from compliance_guard import artifact_delivery_language_hints, pending_step_blocks_compliance


class TestComplianceGuard(unittest.TestCase):
    def test_file_watch_blocks(self):
        self.assertTrue(pending_step_blocks_compliance("file_watch_mode"))

    def test_normal_does_not_block(self):
        self.assertFalse(pending_step_blocks_compliance(None))
        self.assertFalse(pending_step_blocks_compliance(""))
        self.assertFalse(pending_step_blocks_compliance("compliance_await_standard"))

    def test_artifact_hints_detect_risky_phrases(self):
        t = "Статус: 100% — результат готов. Файл будет прикреплен в следующем сообщении."
        h = artifact_delivery_language_hints(t)
        self.assertTrue(h)

    def test_artifact_hints_empty_for_benign(self):
        self.assertEqual(artifact_delivery_language_hints(""), ())
        self.assertEqual(artifact_delivery_language_hints("Краткий ответ без обещания файла."), ())


if __name__ == "__main__":
    unittest.main()
