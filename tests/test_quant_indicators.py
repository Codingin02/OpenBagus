"""Unit tests for mathematically verified indicators, chart patterns, and risk metrics."""

import math
import unittest

from openbagus.domains.quant.indicators import (
    adx,
    bollinger_bands,
    conditional_var,
    detect_patterns,
    ema,
    fibonacci_levels,
    macd,
    max_drawdown,
    realized_volatility,
    rsi,
    sharpe_ratio,
    sma,
    sortino_ratio,
    stochastic_oscillator,
    value_at_risk,
    volume_profile,
    vwap,
    wilder_atr,
)


class TestQuantIndicators(unittest.TestCase):
    def setUp(self):
        # 25-period reference data
        self.closes = [
            100.0, 102.0, 101.5, 103.0, 104.5, 106.0, 105.0, 107.5, 109.0, 108.0,
            110.0, 111.5, 110.5, 112.0, 114.0, 113.0, 115.5, 117.0, 116.0, 118.0,
            119.5, 118.5, 120.0, 122.0, 121.0,
        ]
        self.highs = [c + 1.5 for c in self.closes]
        self.lows = [c - 1.5 for c in self.closes]
        self.volumes = [1000.0 + i * 50.0 for i in range(len(self.closes))]

    def test_sma_and_ema(self):
        s5 = sma(self.closes, 5)
        self.assertEqual(len(s5), len(self.closes))
        self.assertTrue(math.isnan(s5[0]))
        self.assertTrue(math.isnan(s5[3]))
        expected_s5_4 = sum(self.closes[:5]) / 5.0
        self.assertAlmostEqual(s5[4], expected_s5_4, places=4)

        e5 = ema(self.closes, 5)
        self.assertEqual(len(e5), len(self.closes))
        self.assertTrue(math.isnan(e5[3]))
        # First valid EMA is seeded with SMA
        self.assertAlmostEqual(e5[4], expected_s5_4, places=4)
        # Check next EMA step: alpha = 2/(5+1) = 1/3
        alpha = 2.0 / 6.0
        expected_e5_5 = alpha * self.closes[5] + (1.0 - alpha) * e5[4]
        self.assertAlmostEqual(e5[5], expected_e5_5, places=4)

    def test_wilder_atr(self):
        atr14 = wilder_atr(self.highs, self.lows, self.closes, 14)
        self.assertEqual(len(atr14), len(self.closes))
        self.assertTrue(math.isnan(atr14[12]))
        self.assertFalse(math.isnan(atr14[13]))
        self.assertGreater(atr14[-1], 0.0)

    def test_rsi_calculation_and_edge_cases(self):
        r14 = rsi(self.closes, 14)
        self.assertEqual(len(r14), len(self.closes))
        self.assertTrue(math.isnan(r14[13]))
        self.assertFalse(math.isnan(r14[14]))
        self.assertGreaterEqual(r14[-1], 0.0)
        self.assertLessEqual(r14[-1], 100.0)

        # Monotonically rising: RSI should reach 100
        rising = [10.0 + i * 2.0 for i in range(25)]
        r_rising = rsi(rising, 14)
        self.assertAlmostEqual(r_rising[-1], 100.0, places=2)

        # Constant price: zero division check
        constant = [50.0] * 25
        r_const = rsi(constant, 14)
        self.assertEqual(r_const[-1], 50.0)

    def test_macd(self):
        macd_l, sig_l, hist = macd(self.closes, 5, 10, 3)
        self.assertEqual(len(macd_l), len(self.closes))
        self.assertEqual(len(sig_l), len(self.closes))
        self.assertEqual(len(hist), len(self.closes))
        self.assertFalse(math.isnan(macd_l[-1]))
        self.assertFalse(math.isnan(sig_l[-1]))
        self.assertAlmostEqual(hist[-1], macd_l[-1] - sig_l[-1], places=4)

    def test_bollinger_bands(self):
        up, mid, dn, bw = bollinger_bands(self.closes, 10, 2.0)
        self.assertEqual(len(up), len(self.closes))
        self.assertFalse(math.isnan(up[-1]))
        self.assertGreater(up[-1], mid[-1])
        self.assertLess(dn[-1], mid[-1])
        self.assertGreater(bw[-1], 0.0)

    def test_vwap(self):
        v = vwap(self.highs, self.lows, self.closes, self.volumes)
        self.assertEqual(len(v), len(self.closes))
        self.assertGreater(v[-1], 0.0)
        self.assertGreater(v[-1], min(self.lows))
        self.assertLess(v[-1], max(self.highs))

    def test_stochastic_oscillator(self):
        k, d = stochastic_oscillator(self.highs, self.lows, self.closes, 5, 3)
        self.assertEqual(len(k), len(self.closes))
        self.assertEqual(len(d), len(self.closes))
        self.assertFalse(math.isnan(k[-1]))
        self.assertFalse(math.isnan(d[-1]))
        self.assertGreaterEqual(k[-1], 0.0)
        self.assertLessEqual(k[-1], 100.0)

    def test_volume_profile(self):
        vp = volume_profile(self.highs, self.lows, self.closes, self.volumes, bins=10)
        self.assertIn("poc", vp)
        self.assertIn("vah", vp)
        self.assertIn("val", vp)
        self.assertGreaterEqual(vp["vah"], vp["val"])
        self.assertGreaterEqual(vp["poc"], vp["val"])
        self.assertLessEqual(vp["poc"], vp["vah"])

    def test_fibonacci_levels(self):
        fib = fibonacci_levels(200.0, 100.0)
        self.assertEqual(fib["0.000"], 200.0)
        self.assertEqual(fib["1.000"], 100.0)
        self.assertEqual(fib["0.500"], 150.0)
        self.assertEqual(fib["0.618"], 200.0 - 0.618 * 100.0)
        self.assertEqual(fib["1.618_ext"], 200.0 + 0.618 * 100.0)

    def test_candlestick_patterns(self):
        # 1. Bullish Engulfing pattern
        c_engulf = [
            {"open": 100, "high": 102, "low": 98, "close": 99},   # Bearish
            {"open": 98, "high": 105, "low": 97, "close": 104},   # Bullish engulfing
        ]
        p_engulf = detect_patterns([{"open": 99, "high": 101, "low": 98, "close": 100}] + c_engulf)
        names = [p["name"] for p in p_engulf]
        self.assertIn("Bullish Engulfing", names)

        # 2. Hammer Pin Bar
        c_hammer = [
            {"open": 100, "high": 101, "low": 99, "close": 100},
            {"open": 100, "high": 101, "low": 90, "close": 99},   # Long lower wick
        ]
        p_hammer = detect_patterns([{"open": 100, "high": 101, "low": 99, "close": 100}] + c_hammer)
        names_h = [p["name"] for p in p_hammer]
        self.assertIn("Hammer (Pin Bar)", names_h)

    def test_risk_metrics(self):
        returns = [0.01, -0.005, 0.02, 0.015, -0.01, 0.03, -0.02, 0.01, 0.02]
        s = sharpe_ratio(returns, risk_free_rate=0.0)
        self.assertGreater(s, 0.0)

        so = sortino_ratio(returns, risk_free_rate=0.0)
        self.assertGreater(so, 0.0)

        # Max drawdown
        equity = [100.0, 110.0, 105.0, 95.0, 90.0, 100.0, 120.0]
        dd, peak_idx, trough_idx = max_drawdown(equity)
        # Peak was 110.0, trough was 90.0 -> dd = (110 - 90)/110 = 18.18%
        self.assertAlmostEqual(dd, (20.0 / 110.0) * 100.0, places=2)
        self.assertEqual(peak_idx, 1)
        self.assertEqual(trough_idx, 4)

        # VaR and CVaR
        var95 = value_at_risk(returns, 0.95)
        cvar95 = conditional_var(returns, 0.95)
        self.assertGreaterEqual(cvar95, var95)


if __name__ == "__main__":
    unittest.main()
