"""Проверка задержки перед выгрузкой малой после окончания фонового warm тяжёлой.

Запуск: cd aims-workspace && python3 ops/tests/test_schedule_unload_after_warm.py
"""

from __future__ import annotations

import importlib
import os
import sys

_ops_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ops_dir not in sys.path:
    sys.path.insert(0, _ops_dir)
import time
import unittest
from unittest.mock import patch


class TestScheduleUnloadAfterWarm(unittest.TestCase):
    def test_schedule_waits_about_one_second(self) -> None:
        os.environ["DGX_QWEN_UNLOAD_AFTER_HEAVY_WARM"] = "1"
        os.environ["DGX_QWEN_UNLOAD_SMALL_AFTER_HEAVY_WARM_END_SEC"] = "1"
        import ollama_resolve

        importlib.reload(ollama_resolve)

        called_at: list[float] = []

        def _capture(*_a, **_k) -> None:
            called_at.append(time.monotonic())

        with patch.object(ollama_resolve, "ollama_after_heavy_loaded_unload_small", side_effect=_capture):
            t0 = time.monotonic()
            ollama_resolve._schedule_unload_small_after_warm_end(
                "axi_omi_sphere", "http://127.0.0.1:11434"
            )
            deadline = time.monotonic() + 3.0
            while len(called_at) == 0 and time.monotonic() < deadline:
                time.sleep(0.05)

        self.assertEqual(len(called_at), 1)
        self.assertGreaterEqual(called_at[0] - t0, 0.9, "expected ~1s delay")

    def test_skips_when_unload_after_warm_disabled(self) -> None:
        os.environ["DGX_QWEN_UNLOAD_AFTER_HEAVY_WARM"] = "0"
        os.environ["DGX_QWEN_UNLOAD_SMALL_AFTER_HEAVY_WARM_END_SEC"] = "1"
        import ollama_resolve

        importlib.reload(ollama_resolve)

        with patch.object(ollama_resolve, "ollama_after_heavy_loaded_unload_small") as mock_unload:
            ollama_resolve._schedule_unload_small_after_warm_end(
                "axi_omi_sphere", "http://127.0.0.1:11434"
            )
            time.sleep(0.3)
        mock_unload.assert_not_called()

    def test_delay_zero_calls_unload_inline(self) -> None:
        os.environ["DGX_QWEN_UNLOAD_AFTER_HEAVY_WARM"] = "1"
        os.environ["DGX_QWEN_UNLOAD_SMALL_AFTER_HEAVY_WARM_END_SEC"] = "0"
        import ollama_resolve

        importlib.reload(ollama_resolve)

        order: list[str] = []

        def _capture(*_a, **_k) -> None:
            order.append("unload")

        with patch.object(ollama_resolve, "ollama_after_heavy_loaded_unload_small", side_effect=_capture):
            order.append("before")
            ollama_resolve._schedule_unload_small_after_warm_end(
                "axi_omi_sphere", "http://127.0.0.1:11434"
            )
            order.append("after")

        self.assertEqual(order, ["before", "unload", "after"])


if __name__ == "__main__":
    unittest.main()
