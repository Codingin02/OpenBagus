"""Test suite for Advanced Backtesting Framework, Multi-Timeframe Strategy Builder,
Parameter Sensitivity Sweep, and Equity Curve Visualization.
"""

import math
import tempfile
import unittest
from pathlib import Path

from openbagus.domains.quant.backtesting import BacktestResult, BacktestRunner
from openbagus.domains.quant.optimization import ParameterSweepResult, ParameterSweepRunner
from openbagus.domains.quant.strategies import (
    DonchianBreakoutStrategy,
    EMATrendPullbackStrategy,
    MultiTimeframeStrategy,
    RSIReversionStrategy,
)
from openbagus.domains.quant.visualization import (
    format_visual_backtest_summary,
    render_ascii_drawdown_chart,
    render_ascii_equity_curve,
)
from openbagus.intelligence.intent import IntentRouter, SessionState


def _generate_synthetic_candles(n: int = 120, trend: float = 0.002, volatility: float = 0.015) -> list[dict]:
    """Generates deterministic synthetic price action with strictly monotonic timestamps."""
    candles = []
    price = 5000.0
    for i in range(n):
        # Deterministic cyclic price movement
        cycle = math.sin(i / 6.0) * volatility * price
        drift = trend * price * i
        c_open = price + drift + cycle
        c_high = c_open * 1.015
        c_low = c_open * 0.985
        c_close = (c_open + c_high + c_low) / 3.0
        # Format ISO timestamp
        day = (i % 28) + 1
        month = ((i // 28) % 12) + 1
        year = 2024 + (i // (28 * 12))
        iso_str = f"{year:04d}-{month:02d}-{day:02d}T09:00:00Z"
        candles.append({
            "open_at": iso_str,
            "open": round(c_open, 2),
            "high": round(c_high, 2),
            "low": round(c_low, 2),
            "close": round(c_close, 2),
            "volume": 10000.0 + (i * 100),
            "is_closed": True,
        })
    return candles


class TestAdvancedBacktestingFramework(unittest.TestCase):
    def setUp(self):
        self.candles = _generate_synthetic_candles(100)
        self.temp_dir = tempfile.mkdtemp()
        self.router = IntentRouter(repo_root=Path(self.temp_dir))

    def test_ema_trend_pullback_strategy(self):
        strat = EMATrendPullbackStrategy(fast_ema=8, slow_ema=21)
        self.assertEqual(strat.name, "EMA_Trend_Pullback")
        self.assertEqual(strat.warmup_bars, 21)

        runner = BacktestRunner(initial_capital=10_000_000.0, asset_type="EQUITY_ID", strategy=strat)
        res = runner.run("TEST_EQUITY", self.candles, timeframe="D1")
        self.assertIsInstance(res, BacktestResult)
        self.assertEqual(res.strategy_name, "EMA_Trend_Pullback")
        self.assertGreaterEqual(res.final_equity, 0)
        self.assertIn("=== Backtest Results:", res.summary_table())

    def test_donchian_breakout_strategy(self):
        strat = DonchianBreakoutStrategy(lookback=15, stop_atr_mult=1.5, tp_atr_mult=3.0)
        self.assertEqual(strat.name, "Donchian_Breakout")
        self.assertGreaterEqual(strat.warmup_bars, 15)

        runner = BacktestRunner(initial_capital=10_000.0, asset_type="CRYPTO", strategy=strat)
        res = runner.run("BTC", self.candles, timeframe="H1")
        self.assertIsInstance(res, BacktestResult)
        self.assertEqual(res.strategy_name, "Donchian_Breakout")
        self.assertTrue(len(res.equity_curve) > 0)

    def test_rsi_mean_reversion_strategy(self):
        strat = RSIReversionStrategy(rsi_period=10, oversold=35.0, overbought=65.0)
        self.assertEqual(strat.name, "RSI_Mean_Reversion")

        runner = BacktestRunner(initial_capital=10_000.0, asset_type="CRYPTO", strategy=strat)
        res = runner.run("ETH", self.candles, timeframe="H1")
        self.assertIsInstance(res, BacktestResult)
        self.assertEqual(res.strategy_name, "RSI_Mean_Reversion")

    def test_multi_timeframe_strategy(self):
        strat = MultiTimeframeStrategy(htf_ratio=4, htf_ema_fast=10, htf_ema_slow=20)
        self.assertEqual(strat.name, "Multi_Timeframe_Confluence")

        runner = BacktestRunner(initial_capital=10_000.0, asset_type="CRYPTO", strategy=strat)
        res = runner.run("SOL", self.candles, timeframe="H1")
        self.assertIsInstance(res, BacktestResult)
        self.assertEqual(res.strategy_name, "Multi_Timeframe_Confluence")

    def test_parameter_sensitivity_sweep(self):
        param_grid = {
            "fast_ema": [5, 8],
            "slow_ema": [20, 30],
            "stop_atr_mult": [1.5, 2.0],
        }
        sweep_runner = ParameterSweepRunner()
        sweep_res = sweep_runner.run_sweep(
            symbol="BBCA",
            candles=self.candles,
            strategy_cls=EMATrendPullbackStrategy,
            param_grid=param_grid,
            initial_capital=50_000_000.0,
            asset_type="EQUITY_ID",
            timeframe="D1",
        )

        self.assertIsInstance(sweep_res, ParameterSweepResult)
        self.assertEqual(sweep_res.total_combinations, 8)
        self.assertIsNotNone(sweep_res.best_trial)
        self.assertIsNotNone(sweep_res.best_backtest)
        self.assertGreaterEqual(sweep_res.robustness_score, 0.0)
        self.assertLessEqual(sweep_res.robustness_score, 1.0)

        # Check summary table rendering
        table = sweep_res.summary_table()
        self.assertIn("Parameter Sensitivity Sweep", table)
        self.assertIn("Top Ranked Configurations", table)
        self.assertIn("Robustness Score", table)

    def test_ascii_equity_curve_and_drawdown_visualization(self):
        equity_series = [100.0, 102.0, 105.0, 103.0, 108.0, 112.0, 110.0, 115.0]
        dd_series = [0.0, 0.0, 0.0, 1.9, 0.0, 0.0, 1.78, 0.0]

        ascii_curve = render_ascii_equity_curve(equity_series, height=6, width=40, title="Test Curve", currency="USD")
        self.assertIn("Test Curve", ascii_curve)
        self.assertIn("Net Return: +15.00%", ascii_curve)
        self.assertIn("|", ascii_curve)

        ascii_dd = render_ascii_drawdown_chart(dd_series, height=4, width=40)
        self.assertIn("Underwater Drawdown", ascii_dd)

        # Full summary
        strat = EMATrendPullbackStrategy()
        runner = BacktestRunner(initial_capital=10_000_000.0, strategy=strat)
        res = runner.run("BBRI", self.candles)
        vis_summary = format_visual_backtest_summary(res)
        self.assertIn("=== Backtest Results:", vis_summary)
        self.assertIn("Equity Curve: BBRI", vis_summary)

    def test_intent_parsing_for_advanced_backtest(self):
        session = SessionState()

        # Command /backtest sweep
        req1 = self.router.parse("/backtest sweep BBCA", session=session)
        self.assertEqual(req1.request_type, "BACKTEST")
        self.assertEqual(req1.asset, "BBCA")
        self.assertEqual(req1.focus, "sweep")

        # Command /backtest mtf
        req2 = self.router.parse("/backtest mtf BTC", session=session)
        self.assertEqual(req2.request_type, "BACKTEST")
        self.assertEqual(req2.asset, "BTC")
        self.assertEqual(req2.focus, "mtf")

        # Command /backtest curve
        req3 = self.router.parse("/backtest curve ETH", session=session)
        self.assertEqual(req3.request_type, "BACKTEST")
        self.assertEqual(req3.asset, "ETH")
        self.assertEqual(req3.focus, "equity_curve")

        # Natural language sweep query
        req4 = self.router.parse("optimasi parameter backtest strategi BBRI", session=session)
        self.assertEqual(req4.request_type, "BACKTEST")
        self.assertEqual(req4.focus, "sweep")

        # Natural language equity curve
        req5 = self.router.parse("tampilkan grafik kurva ekuitas backtest KLBF", session=session)
        self.assertEqual(req5.request_type, "BACKTEST")
        self.assertEqual(req5.focus, "equity_curve")


if __name__ == "__main__":
    unittest.main()
