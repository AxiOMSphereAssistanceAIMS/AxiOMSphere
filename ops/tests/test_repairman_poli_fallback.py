"""Test Repairman degrades gracefully when Poli is unavailable."""
from __future__ import annotations

import unittest


class TestPoliGracefulDegradation(unittest.TestCase):
    def test_low_risk_repair_proceeds_without_poli(self):
        """Low-risk repairs should proceed with logged warning when Poli is down."""
        from repairman.repair_executor import can_proceed_without_poli

        assert can_proceed_without_poli(risk_level="low") is True
        assert can_proceed_without_poli(risk_level="medium") is False
        assert can_proceed_without_poli(risk_level="high") is False

    def test_critical_risk_blocked_without_poli(self):
        """Critical-risk repairs should be blocked when Poli is unavailable."""
        from repairman.repair_executor import can_proceed_without_poli

        assert can_proceed_without_poli(risk_level="critical") is False


if __name__ == "__main__":
    unittest.main()
