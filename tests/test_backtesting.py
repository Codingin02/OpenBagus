"""Unit tests for walk-forward backtesting engine, realistic transaction costs, and promotion gates."""

import unittest

from openbagus.domains.quant.backtesting import BacktestRunner


class TestBacktesting(unittest.TestCase):
    def setUp(self):
        # 50 bars trending upward with pullbacks
        self.candles = []
        base = 1000.0
        for i in range(50):
            # Gentle uptrend with oscillations
            osc = (i % 5) * 5.0
            close = base + i * 10.0 + osc
            high = close + 15.0
            low = close - 12.0
            open_px = close - 5.0
            self.candles.append({
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100_000,
                "open_at": f"2026-01-{(i%28)+1:02d}T09:00:00Z",
                "close_at": f"2026-01-{(i%28)+1:02d}T16:00:00Z",
            })

    def test_backtest_execution_and_metrics(self):
        runner = BacktestRunner(initial_capital=100_000_000.0, asset_type="EQUITY_ID")
        res = runner.run("BBCA", self.candles, timeframe="D1")
        self.assertEqual(res.asset, "BBCA")
        self.assertEqual(res.total_bars, 50)
        self.assertGreater(res.total_trades, 0)
        self.assertGreater(res.final_equity, 0.0)
        self.assertGreaterEqual(res.win_rate, 0.0)
        self.assertLessEqual(res.win_rate, 100.0)
        self.assertGreater(res.total_fees_paid, 0.0)
        self.assertEqual(len(res.equity_curve), 50 - 21 + 1)
        self.assertIn("Walk-Forward Split", res.summary_table())

    def test_insufficient_sample_rejection(self):
        runner = BacktestRunner()
        short_candles = self.candles[:20]
        with self.assertRaises(ValueError):
            runner.run("BBCA", short_candles)

    def test_idx_lot_size_constraint(self):
        runner = BacktestRunner(initial_capital=50_000_000.0, asset_type="EQUITY_ID", lot_size=100)
        res = runner.run("BBCA", self.candles)
        for t in res.trades:
            self.assertEqual(t.shares % 100, 0, "IDX shares must be multiples of 100-share round lots")

    def test_crypto_mode_fees_and_sizing(self):
        runner = BacktestRunner(initial_capital=10_000.0, asset_type="CRYPTO", buy_fee=0.0005, sell_fee=0.0005, lot_size=1)
        res = runner.run("BTC", self.candles, timeframe="H1")
        self.assertEqual(res.asset_type, "CRYPTO")
        self.assertGreater(res.total_trades, 0)

    def test_promotion_gate_evaluation(self):
        # Degraded/choppy candles where strategy does not win
        choppy_candles = []
        for i in range(50):
            c = 1000.0 - (i * 5.0)  # downtrend
            choppy_candles.append({
                "open": c,
                "high": c + 5.0,
                "low": c - 10.0,
                "close": c - 2.0,
                "volume": 1000,
            })
        runner = BacktestRunner()
        res = runner.run("LOSING_ASSET", choppy_candles)
        self.assertFalse(res.passed_promotion_gate)
        self.assertIn("Gate Notes", res.summary_table())


if __name__ == "__main__":
    unittest.main()
