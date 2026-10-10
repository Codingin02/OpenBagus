"""Unit tests for offline native interactive visualization layer."""

import tempfile
import unittest
from pathlib import Path

from openbagus.domains.crypto.quant import QuantDecisionResult
from openbagus.domains.equities.ownership import OwnershipStructure, ShareholderRecord
from openbagus.domains.quant.backtesting import BacktestResult, BacktestTrade
from openbagus.reporting.visualizer import generate_html_report


class TestVisualization(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.candles = [
            {"open_at": "2026-01-01T09:00:00Z", "open": 100.0, "high": 105.0, "low": 98.0, "close": 104.0, "volume": 1000},
            {"open_at": "2026-01-02T09:00:00Z", "open": 104.0, "high": 110.0, "low": 102.0, "close": 108.0, "volume": 1200},
            {"open_at": "2026-01-03T09:00:00Z", "open": 108.0, "high": 112.0, "low": 106.0, "close": 111.0, "volume": 1500},
        ]
        self.quant = QuantDecisionResult(
            asset="BBCA",
            market="idx",
            decision="BUY",
            regime="Markup",
            confidence="HIGH",
            price=111.0,
            entry_zone="108.0 - 110.0",
            stop_price=102.0,
            tp1=120.0,
            tp2=125.0,
            reward_risk=2.0,
            reward_risk_str="1:2.0",
            leverage_ceiling="1x",
            leverage_num=1,
            why={"Trend": "Bullish"},
            sources=["IDX Market Data"],
            evidence_count=3,
            composite_score=0.75,
            composite_quality=0.85,
            rr_gate_passed=True,
            quality_gate_passed=True,
            decision_reason="Trend confirmation with RSI recovery.",
            timeframe="D1",
        )
        from openbagus.domains.equities.ownership import load_ownership
        self.ownership = load_ownership("BBCA", Path("."))

    def tearDown(self):
        self.tmp.cleanup()

    def test_html_report_generation_and_offline_integrity(self):
        html_file = generate_html_report(
            asset="BBCA",
            candles=self.candles,
            quant_result=self.quant,
            ownership=self.ownership,
            root=self.root,
            timeframe="D1",
        )
        self.assertTrue(html_file.exists())
        self.assertEqual(html_file.suffix, ".html")

        content = html_file.read_text(encoding="utf-8")

        # Zero CDN / external script dependencies (100% offline)
        for external in ["https://cdn", "https://cdnjs", "unpkg.com", "jsdelivr.net", "http://", "https://"]:
            # Note: only allow harmless schema or doctype, no script/link src
            self.assertNotIn(f'src="{external}', content.lower())
            self.assertNotIn(f'href="{external}', content.lower())

        # Essential Canvas and Visualizer IDs
        self.assertIn("candleCanvas", content)
        self.assertIn("radarCanvas", content)
        self.assertIn("sunburstCanvas", content)
        self.assertIn("heatmapCanvas", content)

        # Asset metadata embedded
        self.assertIn("BBCA", content)
        self.assertIn("D1", content)
        self.assertIn("PT Dwimuria", content)

    def test_backtest_curve_rendering_in_html(self):
        from openbagus.domains.quant.backtesting import BacktestRunner
        candles = [
            {"open_at": f"2026-01-{(i%28)+1:02d}T09:00:00Z", "open": 100.0 + i * 5, "high": 105.0 + i * 5, "low": 98.0 + i * 5, "close": 104.0 + i * 5, "volume": 1000}
            for i in range(30)
        ]
        bt = BacktestRunner().run("BBCA", candles, timeframe="D1")
        html_file = generate_html_report(
            asset="BBCA",
            candles=candles,
            quant_result=self.quant,
            backtest_result=bt,
            root=self.root,
            timeframe="D1",
        )
        self.assertTrue(html_file.exists())
        content = html_file.read_text(encoding="utf-8")
        self.assertIn("backtestCanvas", content)
        self.assertIn("Walk-Forward Backtest", content)


if __name__ == "__main__":
    unittest.main()
