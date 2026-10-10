"""Unit tests for offline native interactive visualization layer."""

import tempfile
import unittest
from pathlib import Path

from openbagus.domains.crypto.quant import QuantDecisionResult
from openbagus.domains.equities.ownership import get_synthetic_test_ownership
from openbagus.domains.quant.backtesting import BacktestRunner
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
        self.ownership = get_synthetic_test_ownership("BBCA")

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
            self.assertNotIn(f'src="{external}', content.lower())
            self.assertNotIn(f'href="{external}', content.lower())

        # Essential Canvas and Visualizer IDs
        self.assertIn("candleCanvas", content)
        self.assertIn("sunburstCanvas", content)

        # Asset metadata and verified top shareholder embedded
        self.assertIn("BBCA", content)
        self.assertIn("D1", content)
        self.assertIn("PT Dwimuria", content)

        # Verify no hardcoded 16.6 placeholders
        self.assertNotIn("16.6", content)

    def test_unverified_radar_and_heatmap_omitted_without_data(self):
        # When neither verified ratios (< 3 dimensions) nor multi-asset return series exist:
        # Radar and Heatmap must display explicit omission notices, NOT fabricated values.
        html_file = generate_html_report(
            asset="BBCA",
            candles=self.candles,
            quant_result=None,
            packet=None,
            ownership=None,
            root=self.root,
            timeframe="D1",
        )
        content = html_file.read_text(encoding="utf-8")
        self.assertIn("Radar Omitted", content)
        self.assertIn("Heatmap Omitted", content)
        # Ensure static unverified values are not present
        self.assertNotIn("[65.0, 50.0, 70.0, 60.0, 75.0, 68.0]", content)
        self.assertNotIn("16.6", content)

    def test_heatmap_rendered_when_multi_asset_returns_provided(self):
        # 20 bars for 2 assets
        candles_bbca = [
            {"open_at": f"2026-01-{i+1:02d}T09:00:00Z", "open": 100.0 + i, "high": 105.0 + i, "low": 98.0 + i, "close": 102.0 + i, "volume": 1000}
            for i in range(20)
        ]
        candles_bbri = [
            {"open_at": f"2026-01-{i+1:02d}T09:00:00Z", "open": 50.0 + i * 0.5, "high": 52.0 + i * 0.5, "low": 49.0 + i * 0.5, "close": 51.0 + i * 0.5, "volume": 2000}
            for i in range(20)
        ]
        multi_candles = {"BBCA": candles_bbca, "BBRI": candles_bbri}
        html_file = generate_html_report(
            asset="BBCA",
            candles=candles_bbca,
            root=self.root,
            timeframe="D1",
            multi_asset_candles=multi_candles,
        )
        content = html_file.read_text(encoding="utf-8")
        self.assertIn("heatmapCanvas", content)
        self.assertNotIn("Heatmap Omitted", content)

    def test_backtest_curve_rendering_in_html(self):
        candles = [
            {
                "open_at": f"2026-{1 if i < 28 else 2:02d}-{(i%28)+1:02d}T09:00:00Z",
                "open": 100.0 + i * 5,
                "high": 105.0 + i * 5,
                "low": 98.0 + i * 5,
                "close": 104.0 + i * 5,
                "volume": 1000,
            }
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
        self.assertIn("Walk-Forward Backtesting", content)


if __name__ == "__main__":
    unittest.main()
