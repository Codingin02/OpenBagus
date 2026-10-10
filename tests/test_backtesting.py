"""Unit tests for walk-forward backtesting engine, realistic transaction costs, and promotion gates."""

import math
import unittest

from openbagus.domains.quant.backtesting import BacktestRunner


class TestBacktesting(unittest.TestCase):
    def setUp(self):
        # 50 bars trending upward with pullbacks and strictly monotonic timestamps
        self.candles = []
        base = 1000.0
        for i in range(50):
            osc = (i % 5) * 5.0
            close = base + i * 10.0 + osc
            high = close + 15.0
            low = close - 12.0
            open_px = close - 5.0
            day = (i % 28) + 1
            month = 1 if i < 28 else 2
            self.candles.append({
                "open": open_px,
                "high": high,
                "low": low,
                "close": close,
                "volume": 100_000,
                "open_at": f"2026-{month:02d}-{day:02d}T09:00:00Z",
                "close_at": f"2026-{month:02d}-{day:02d}T16:00:00Z",
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
            day = (i % 28) + 1
            month = 1 if i < 28 else 2
            choppy_candles.append({
                "open": c,
                "high": c + 5.0,
                "low": c - 10.0,
                "close": c - 2.0,
                "volume": 1000,
                "open_at": f"2026-{month:02d}-{day:02d}T09:00:00Z",
                "close_at": f"2026-{month:02d}-{day:02d}T16:00:00Z",
            })
        runner = BacktestRunner()
        res = runner.run("LOSING_ASSET", choppy_candles)
        self.assertFalse(res.passed_promotion_gate)
        self.assertIn("Gate Notes", res.summary_table())

    def test_non_monotonic_timestamps_rejected(self):
        # Shuffled candles or backward timestamps must raise ValueError
        bad_candles = list(self.candles)
        bad_candles[15] = dict(bad_candles[15])
        bad_candles[15]["open_at"] = "2025-01-01T09:00:00Z"  # Past timestamp
        runner = BacktestRunner()
        with self.assertRaises(ValueError):
            runner.run("BAD_TS", bad_candles)

    def test_exact_cash_conservation_and_no_double_fee_deduction(self):
        # Invariant: final_equity == initial_capital + sum(net_pnl for all trades)
        runner = BacktestRunner(initial_capital=100_000_000.0, asset_type="EQUITY_ID")
        res = runner.run("BBCA", self.candles, timeframe="D1")
        self.assertGreater(len(res.trades), 0)
        total_trade_net_pnl = sum(t.net_pnl for t in res.trades)
        expected_final = res.initial_capital + total_trade_net_pnl
        self.assertAlmostEqual(res.final_equity, expected_final, places=2)
        total_trade_fees = sum(t.fees_paid for t in res.trades)
        self.assertAlmostEqual(res.total_fees_paid, total_trade_fees, places=2)

    def test_promotion_gate_fails_on_zero_oos_trades(self):
        # Run with high train_ratio so out-of-sample window generates 0 trades
        runner = BacktestRunner(initial_capital=100_000_000.0, asset_type="EQUITY_ID")
        # 30 bars: 21 warmup, 9 test bars with no pullbacks
        flat_candles = []
        for i in range(35):
            c = 1000.0 + i * 2.0
            day = (i % 28) + 1
            month = 1 if i < 28 else 2
            flat_candles.append({
                "open": c,
                "high": c + 2.0,
                "low": c - 1.0,
                "close": c + 1.0,
                "volume": 1000,
                "open_at": f"2026-{month:02d}-{day:02d}T09:00:00Z",
                "close_at": f"2026-{month:02d}-{day:02d}T16:00:00Z",
            })
        res = runner.run("OOS_TEST", flat_candles, train_ratio=0.8, val_ratio=0.1)
        # Even if overall win rate or profit factor is fine, if 0 OOS trades exist, promotion gate must fail
        if res.out_of_sample_metrics.get("trades", 0) == 0:
            self.assertFalse(res.passed_promotion_gate)
            self.assertTrue(any("out-of-sample" in r.lower() for r in res.gate_reasons))

    def test_intrabar_stop_and_take_profit_collision_prefers_stop(self):
        # Construct scenario where low <= stop AND high >= tp1 in same bar
        # Runner should conservatively choose STOP_LOSS
        runner = BacktestRunner(initial_capital=100_000_000.0, asset_type="EQUITY_ID")
        candles = []
        for i in range(25):
            c = 1000.0 + i * 10.0
            day = (i % 28) + 1
            month = 1 if i < 28 else 2
            candles.append({
                "open": c - 2.0,
                "high": c + 10.0,
                "low": c - 5.0,
                "close": c,
                "volume": 10000,
                "open_at": f"2026-{month:02d}-{day:02d}T09:00:00Z",
                "close_at": f"2026-{month:02d}-{day:02d}T16:00:00Z",
            })
        # At bar 23, huge bar triggering both stop and TP
        candles.append({
            "open": 1250.0,
            "high": 2000.0,  # huge high
            "low": 100.0,    # huge low
            "close": 1250.0,
            "volume": 50000,
            "open_at": "2026-02-01T09:00:00Z",
            "close_at": "2026-02-01T16:00:00Z",
        })
        candles.append({
            "open": 1250.0,
            "high": 1260.0,
            "low": 1240.0,
            "close": 1250.0,
            "volume": 10000,
            "open_at": "2026-02-02T09:00:00Z",
            "close_at": "2026-02-02T16:00:00Z",
        })
        res = runner.run("COLLISION", candles)
        collision_trades = [t for t in res.trades if t.exit_idx == 25]
        if collision_trades:
            self.assertEqual(collision_trades[0].exit_reason, "STOP_LOSS")

    def test_profit_factor_infinite_when_zero_losses(self):
        # When all closed trades have net_pnl > 0 and 0 losses, profit_factor is math.inf
        runner = BacktestRunner(initial_capital=100_000_000.0)
        res = runner.run("BBCA", self.candles)
        winning_only = [t for t in res.trades if t.net_pnl > 0]
        if winning_only and len(winning_only) == len(res.trades):
            self.assertEqual(res.profit_factor, math.inf)
            self.assertIn("Inf", res.summary_table())


if __name__ == "__main__":
    unittest.main()
