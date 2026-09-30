"""Test Quant Engine Math and Risk Calculations."""

import unittest

from openbagus.core.market_structure import (
    calculate_volume_profile,
    calculate_vwap,
    detect_support_resistance,
)
from openbagus.risk.metrics import (
    calculate_max_drawdown,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_var_cvar,
)


class TestQuantEngine(unittest.TestCase):
    def test_market_structure_math(self):
        prices = [100.0, 102.0, 101.0, 105.0, 104.0, 108.0]
        volumes = [10.0, 15.0, 20.0, 25.0, 10.0, 30.0]

        vwap = calculate_vwap(prices, volumes)
        self.assertIsNotNone(vwap)
        self.assertTrue(100.0 <= vwap <= 108.0)

        profile = calculate_volume_profile(prices, volumes, bins=5)
        self.assertIn("poc", profile)
        self.assertIn("vah", profile)
        self.assertIn("val", profile)

        sr = detect_support_resistance(prices)
        self.assertIn("support", sr)
        self.assertIn("resistance", sr)
        self.assertLessEqual(sr["support"], sr["resistance"])

    def test_risk_metrics(self):
        returns = [0.01, -0.02, 0.015, 0.03, -0.01, 0.02, -0.005]
        sharpe = calculate_sharpe_ratio(returns)
        self.assertIsInstance(sharpe, float)

        sortino = calculate_sortino_ratio(returns)
        self.assertIsInstance(sortino, float)

        prices = [100.0, 105.0, 95.0, 90.0, 110.0]
        mdd = calculate_max_drawdown(prices)
        self.assertTrue(0.0 <= mdd <= 1.0)

        var, cvar = calculate_var_cvar(returns)
        self.assertIsNotNone(var)
        self.assertIsNotNone(cvar)


if __name__ == "__main__":
    unittest.main()
