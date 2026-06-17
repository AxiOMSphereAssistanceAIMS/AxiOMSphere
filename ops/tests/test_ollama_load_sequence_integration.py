"""Интеграция с живым Ollama: последовательность малая → большая → выгрузка малой.

Без флага тесты **не** бегают (нет сети/GPU-нагрузки в CI).

Запуск на машине с `ollama serve` и уже скачанными моделями:

  OLLAMA_SEQUENCE_INTEGRATION_TEST=1 \\
  OLLAMA_API=http://127.0.0.1:11434 \\
  SMALL=qwen2.5:14b BIG=axi_omi_sphere:latest \\
  PYTHONPATH=ops python3 -m unittest ops.tests.test_ollama_load_sequence_integration -v

Или:

  OLLAMA_SEQUENCE_INTEGRATION_TEST=1 PYTHONPATH=ops python3 -m pytest \\
    ops/tests/test_ollama_load_sequence_integration.py -v -s

`-s` показывает print-шаги. Полный прогрев большой модели может занять **несколько минут**.
"""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_OPS = Path(__file__).resolve().parents[1]
if str(_OPS) not in sys.path:
    sys.path.insert(0, str(_OPS))


def _base_url() -> str:
    # OLLAMA_API — как в ~/model-manager.sh; OLLAMA_SEQUENCE_URL — явный override для теста
    return (
        os.environ.get("OLLAMA_SEQUENCE_URL")
        or os.environ.get("OLLAMA_API")
        or "http://127.0.0.1:11434"
    ).rstrip("/")


def _get_json(path: str, timeout: float = 30.0) -> dict:
    url = f"{_base_url()}{path}"
    req = Request(url, method="GET")
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _post_generate(payload: dict, timeout: float) -> dict:
    url = f"{_base_url()}/api/generate"
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _ps_model_bases() -> set[str]:
    raw = _get_json("/api/ps", timeout=15.0)
    out: set[str] = set()
    for m in raw.get("models") or []:
        if not isinstance(m, dict):
            continue
        for k in ("name", "model"):
            n = m.get(k)
            if isinstance(n, str) and n.strip():
                out.add(n.split(":", 1)[0].strip().lower())
                break
    return out


def _tags_contain_model(tag_list: dict, want: str) -> bool:
    want_b = want.split(":", 1)[0].strip().lower()
    for e in tag_list.get("models") or []:
        if not isinstance(e, dict):
            continue
        n = e.get("name") or e.get("model")
        if isinstance(n, str) and n.split(":", 1)[0].strip().lower() == want_b:
            return True
    return False


@unittest.skipUnless(
    os.environ.get("OLLAMA_SEQUENCE_INTEGRATION_TEST", "").strip().lower()
    in ("1", "true", "yes", "on"),
    "set OLLAMA_SEQUENCE_INTEGRATION_TEST=1 to run live Ollama sequence (GPU/time)",
)
class TestOllamaLoadSequenceIntegration(unittest.TestCase):
    small: str
    big: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.small = (
            os.environ.get("OLLAMA_SEQUENCE_SMALL") or os.environ.get("SMALL") or "qwen2.5:14b"
        ).strip()
        cls.big = (
            os.environ.get("OLLAMA_SEQUENCE_BIG") or os.environ.get("BIG") or "axi_omi_sphere:latest"
        ).strip()
        try:
            _get_json("/api/tags", timeout=5.0)
        except (URLError, HTTPError, TimeoutError, OSError) as e:
            raise unittest.SkipTest(f"Ollama unreachable at {_base_url()}: {e}") from e

    def test_01_tags_include_required_models(self) -> None:
        tags = _get_json("/api/tags", timeout=15.0)
        self.assertTrue(
            _tags_contain_model(tags, self.small),
            f"Model {self.small!r} not in /api/tags — ollama pull {self.small.split(':')[0]}",
        )
        self.assertTrue(
            _tags_contain_model(tags, self.big),
            f"Model {self.big!r} not in /api/tags — ollama pull …",
        )

    def test_02_sequence_small_big_unload_small(self) -> None:
        """Как ~/model-manager.sh: малый KV → большой KV → keep_alive 0 на малой."""
        print(f"\n[sequence] OLLAMA={_base_url()} SMALL={self.small} BIG={self.big}")

        # 1) Малая — как model-manager.sh фаза 1 (keep_alive 30m, num_ctx 8192)
        print("[sequence] phase 1: load SMALL …")
        r1 = _post_generate(
            {
                "model": self.small,
                "prompt": "warmup",
                "stream": False,
                "keep_alive": "30m",
                "options": {"num_ctx": 8192},
            },
            timeout=600.0,
        )
        self.assertTrue(r1.get("done"), msg=str(r1)[:500])
        ps1 = _ps_model_bases()
        self.assertIn(
            self.small.split(":")[0].lower(),
            ps1,
            msg=f"after small generate, expected small in /api/ps, got {ps1}",
        )
        print(f"[sequence] /api/ps after small: {sorted(ps1)}")

        # 2) Большая — как model-manager.sh фаза 2 (keep_alive 24h, num_ctx 32768)
        print("[sequence] phase 2: load BIG (may take minutes) …")
        r2 = _post_generate(
            {
                "model": self.big,
                "prompt": "warmup",
                "stream": False,
                "keep_alive": "24h",
                "options": {"num_ctx": 32768},
            },
            timeout=7200.0,
        )
        self.assertTrue(r2.get("done"), msg=str(r2)[:500])
        ps2 = _ps_model_bases()
        self.assertIn(
            self.big.split(":")[0].lower(),
            ps2,
            msg=f"after big generate, expected big in /api/ps, got {ps2}",
        )
        print(f"[sequence] /api/ps after big: {sorted(ps2)}")

        # 3) Выгрузка малой — как model-manager.sh фаза 3
        print("[sequence] phase 3: unload SMALL (keep_alive 0) …")
        try:
            _post_generate(
                {
                    "model": self.small,
                    "prompt": ".",
                    "stream": False,
                    "keep_alive": "0",
                    "options": {"num_predict": 1},
                },
                timeout=120.0,
            )
        except (HTTPError, URLError, TimeoutError, OSError):
            pass  # как в bash: || true

        time.sleep(3)
        ps3 = _ps_model_bases()
        print(f"[sequence] /api/ps after unload small: {sorted(ps3)}")
        self.assertNotIn(
            self.small.split(":")[0].lower(),
            ps3,
            msg="small model should be gone from /api/ps after keep_alive 0",
        )


if __name__ == "__main__":
    unittest.main()
