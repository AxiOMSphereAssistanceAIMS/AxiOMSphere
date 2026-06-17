"""Проверка разбора ответа Ollama /api/generate (без сети) + опционально живой вызов.

Без pytest (stdlib):
  cd aims-workspace && PYTHONPATH=ops python3 -m unittest ops.tests.test_qwen_pc_warm -v

С pytest (если установлен):
  PYTHONPATH=ops pytest ops/tests/test_qwen_pc_warm.py -q

Интеграция с живым ПК:
  QWEN_PC_INTEGRATION_TEST=1 PYTHONPATH=ops python3 -m unittest ops.tests.test_qwen_pc_warm.TestIntegration.test_live_generate -v
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))

from qwen_pc_smoke import parse_generate_response, run_smoke_report, summarize_generate

_SAMPLE = (
    '{"model":"qwen3.5:27b","created_at":"2026-04-06T12:00:00Z",'
    '"response":"OK","done":true}'
)


class TestParse(unittest.TestCase):
    def test_parse_sample(self):
        d = parse_generate_response(_SAMPLE)
        self.assertEqual(d.get("model"), "qwen3.5:27b")
        self.assertEqual(d.get("response"), "OK")

    def test_summarize(self):
        d = parse_generate_response(_SAMPLE)
        s = summarize_generate(d)
        self.assertTrue(s["has_response"])
        self.assertEqual(s["response_len"], 2)
        self.assertIn("OK", s["response_preview"])


@unittest.skipUnless(
    os.environ.get("QWEN_PC_INTEGRATION_TEST", "").strip(),
    "set QWEN_PC_INTEGRATION_TEST=1 for live Ollama",
)
class TestIntegration(unittest.TestCase):
    def test_live_generate(self):
        root = Path(__file__).resolve().parents[2]
        env_p = root / ".env"
        if env_p.is_file():
            for line in env_p.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if k and k not in os.environ:
                    os.environ[k] = v.strip().strip('"').strip("'")

        base = (os.environ.get("PC_ANDREY_OLLAMA_URL") or "").strip().rstrip("/")
        if not base:
            self.skipTest("PC_ANDREY_OLLAMA_URL not set")
        model = (os.environ.get("QWEN_PC_WARM_MODEL") or "qwen3.5:27b").strip()
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            rep = Path(td) / "qwen_smoke.json"
            out = run_smoke_report(base, model, timeout_sec=300.0, report_path=str(rep))
            self.assertEqual(out.get("http_code"), 200, msg=str(out))
            self.assertTrue(out.get("ok"), msg=str(out))
            self.assertTrue(rep.is_file())
            data = json.loads(rep.read_text(encoding="utf-8"))
            self.assertTrue(data.get("summary", {}).get("has_response"))


if __name__ == "__main__":
    unittest.main()
