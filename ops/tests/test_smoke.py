"""Phase 0 smoke tests — no network, no GPU, no Telegram.

Covers:
  1. FailureDetector — init, record, from_* hooks
  2. SysPolic — safe/dangerous/unknown actions
  3. SysMR — policy gate enforced before execution
  4. Registry access — aims_registry.db readable
  5. DocAgent import — no crash on import
  6. OCR pipeline — pytesseract importable (skipped if absent)
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))


class TestFailureDetector(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        import os
        os.environ["AIMS_FAILURES_DB"] = str(Path(self._tmp.name) / "test_failures.db")

    def tearDown(self):
        import os
        os.environ.pop("AIMS_FAILURES_DB", None)
        self._tmp.cleanup()

    def _fresh(self):
        import importlib
        import failure_detector as fd
        importlib.reload(fd)
        fd._detector = None
        return fd.FailureDetector()

    def test_init_creates_db(self):
        d = self._fresh()
        import os
        db = os.environ["AIMS_FAILURES_DB"]
        self.assertTrue(Path(db).exists())

    def test_record_stored(self):
        d = self._fresh()
        import os
        d.record("semantic_fail", "medium", "test", {"msg": "bad response"})
        rows = d.recent(5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "semantic_fail")

    def test_from_axi_ok_no_record(self):
        d = self._fresh()
        d.from_axi({"ok": True, "text": "hello"})
        self.assertEqual(len(d.recent()), 0)

    def test_from_axi_fail_records(self):
        d = self._fresh()
        d.from_axi({"ok": False, "error": "timeout"})
        rows = d.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "axi")

    def test_from_eval_below_threshold(self):
        d = self._fresh()
        d.from_eval(0.7, {"model": "omi-ft-14b-v15"})
        rows = d.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], "eval_fail")

    def test_from_eval_above_threshold_no_record(self):
        d = self._fresh()
        d.from_eval(0.9, {"model": "omi-ft-14b-v15"})
        self.assertEqual(len(d.recent()), 0)

    def test_recent_limit(self):
        d = self._fresh()
        for i in range(5):
            d.record("test", "low", "test", {"i": i})
        self.assertEqual(len(d.recent(3)), 3)


class TestSysPolic(unittest.TestCase):

    def setUp(self):
        from self_healing.policy_gate import SysPolic
        self.gate = SysPolic()

    def test_restart_known_container_allowed(self):
        self.assertTrue(self.gate.allow({"type": "restart_container", "target": "axi-bot"}))

    def test_restart_unknown_container_denied(self):
        from self_healing.policy_gate import PolicyDenied
        with self.assertRaises(PolicyDenied):
            self.gate.allow({"type": "restart_container", "target": "postgres"})

    def test_switch_model_allowed(self):
        self.assertTrue(self.gate.allow({"type": "switch_model", "model": "qwen2.5:14b"}))

    def test_switch_model_no_model_denied(self):
        from self_healing.policy_gate import PolicyDenied
        with self.assertRaises(PolicyDenied):
            self.gate.allow({"type": "switch_model"})

    def test_delete_db_denied(self):
        from self_healing.policy_gate import PolicyDenied
        with self.assertRaises(PolicyDenied):
            self.gate.allow({"type": "delete_db", "target": "aims_registry.db"})

    def test_exec_shell_denied(self):
        from self_healing.policy_gate import PolicyDenied
        with self.assertRaises(PolicyDenied):
            self.gate.allow({"type": "exec_shell", "cmd": "rm -rf /"})

    def test_unknown_action_denied(self):
        from self_healing.policy_gate import PolicyDenied
        with self.assertRaises(PolicyDenied):
            self.gate.allow({"type": "do_something_new"})

    def test_clear_queue_allowed(self):
        self.assertTrue(self.gate.allow({"type": "clear_queue"}))


class TestSysMRPolicyEnforced(unittest.TestCase):

    def test_dangerous_action_blocked(self):
        from self_healing.repair_executor import RepairExecutor
        ex = RepairExecutor()
        result = ex.execute({"type": "delete_db", "target": "aims_registry.db"})
        self.assertFalse(result["ok"])
        self.assertIn("policy denied", result["detail"])

    def test_unknown_action_blocked(self):
        from self_healing.repair_executor import RepairExecutor
        ex = RepairExecutor()
        result = ex.execute({"type": "teleport_server"})
        self.assertFalse(result["ok"])


class TestRegistryAccess(unittest.TestCase):

    def test_aims_registry_readable(self):
        import os
        db_path = os.environ.get(
            "OMI_DB_PATH",
            "/home/axi_omi_sphere/aims-workspace/data/aims_registry.db",
        )
        if not Path(db_path).exists():
            self.skipTest(f"registry not found at {db_path}")
        import sqlite3
        conn = sqlite3.connect(db_path)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        conn.close()
        self.assertGreater(len(tables), 0, "registry DB has no tables")

    def test_aims_registry_query_documents(self):
        import os
        db_path = os.environ.get(
            "OMI_DB_PATH",
            "/home/axi_omi_sphere/aims-workspace/data/aims_registry.db",
        )
        if not Path(db_path).exists():
            self.skipTest(f"registry not found at {db_path}")
        import sqlite3
        conn = sqlite3.connect(db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%doc%'"
        )
        doc_tables = [r[0] for r in cur.fetchall()]
        conn.close()
        # Just verify query doesn't crash — tables may or may not exist
        self.assertIsInstance(doc_tables, list)


class TestDocAgentImport(unittest.TestCase):

    def test_doc_agent_importable(self):
        try:
            import doc_agent  # noqa: F401
        except ImportError as e:
            self.skipTest(f"doc_agent optional deps missing: {e}")

    def test_failure_detector_importable(self):
        import failure_detector  # noqa: F401

    def test_claude_orchestrator_importable(self):
        import claude_orchestrator  # noqa: F401


class TestOCRPipeline(unittest.TestCase):

    def test_pytesseract_importable(self):
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            self.skipTest("pytesseract not installed")
        self.assertTrue(True)

    def test_pdf_ocr_nim_importable(self):
        try:
            import pdf_ocr_nim  # noqa: F401
        except ImportError as e:
            self.skipTest(f"pdf_ocr_nim deps missing: {e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
