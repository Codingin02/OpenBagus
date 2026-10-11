"""Unit and integration tests for OpenBagus open-source charting and MCP integrations.

Validates:
- CanonicalChartData strict integrity and validation (rejecting NaN, Inf, out-of-bounds, negative vol)
- Static charts rendering (Matplotlib + mplfinance headless Agg)
- Interactive charting with graceful headless/fallback handling
- TradingView MCP client safety, status, and tool allowlisting
- PDF report generation via matplotlib Agg backend
- Intent routing for reports, exports, integrations, and natural queries
"""

from __future__ import annotations

import math
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from openbagus.domains.crypto.quant import QuantDecisionResult
from openbagus.domains.equities.ownership import (
    OwnershipStructure,
    ShareholderRecord,
    get_synthetic_test_ownership,
)
from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.integrations.tradingview_mcp import (
    ALLOWED_TOOLS,
    MCPStatus,
    TradingViewMCPClient,
    format_integrations_view,
)
from openbagus.reporting.canonical import CanonicalChartData, MalformedCandleError
from openbagus.reporting.interactive_chart import launch_interactive_chart
from openbagus.reporting.pdf import generate_pdf_report
from openbagus.reporting.static_charts import (
    render_candlestick_png,
    render_equity_curve_png,
    render_macro_line_png,
    render_ownership_pie_png,
    render_peer_bar_png,
)


class TestChartAndMCPIntegrations(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.router = IntentRouter(repo_root=self.root)

        self.sample_candles = [
            {"open_at": "2026-10-01T00:00:00Z", "open": 10000.0, "high": 10200.0, "low": 9950.0, "close": 10150.0, "volume": 50000.0},
            {"open_at": "2026-10-02T00:00:00Z", "open": 10150.0, "high": 10300.0, "low": 10100.0, "close": 10250.0, "volume": 60000.0},
            {"open_at": "2026-10-03T00:00:00Z", "open": 10250.0, "high": 10400.0, "low": 10200.0, "close": 10350.0, "volume": 55000.0},
            {"open_at": "2026-10-04T00:00:00Z", "open": 10350.0, "high": 10500.0, "low": 10300.0, "close": 10450.0, "volume": 70000.0},
        ]

        self.quant = QuantDecisionResult(
            asset="BBCA",
            market="idx",
            decision="BUY",
            regime="Markup",
            confidence="HIGH",
            price=10450.0,
            entry_zone="10350.0 - 10450.0",
            stop_price=10100.0,
            tp1=10900.0,
            tp2=11200.0,
            reward_risk=1.85,
            reward_risk_str="1:1.85",
            leverage_ceiling="1x",
            leverage_num=1,
            why={"Trend": "Bullish", "Breakout": "Confirmed"},
            sources=["IDX Verified"],
            evidence_count=4,
            composite_score=0.82,
            composite_quality=0.90,
            rr_gate_passed=True,
            quality_gate_passed=True,
            decision_reason="Confirmed breakout with volume expansion",
            timeframe="D1",
        )

        self.sample_ownership = get_synthetic_test_ownership("BBCA")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # --- T01-T06: CanonicalChartData Integrity ---

    def test_canonical_chart_data_valid(self) -> None:
        data = CanonicalChartData(asset="BBCA", candles=self.sample_candles)
        data.validate_candles()
        self.assertEqual(len(data.candles), 4)

    def test_canonical_chart_data_rejects_nan_inf(self) -> None:
        bad_candles = [{"open": float("nan"), "high": 100.0, "low": 90.0, "close": 95.0, "volume": 10.0}]
        data = CanonicalChartData(asset="TEST", candles=bad_candles)
        with self.assertRaises(MalformedCandleError):
            data.validate_candles()

        bad_inf = [{"open": 100.0, "high": float("inf"), "low": 90.0, "close": 95.0, "volume": 10.0}]
        data_inf = CanonicalChartData(asset="TEST", candles=bad_inf)
        with self.assertRaises(MalformedCandleError):
            data_inf.validate_candles()

    def test_canonical_chart_data_rejects_high_less_than_low(self) -> None:
        bad = [{"open": 100.0, "high": 90.0, "low": 95.0, "close": 92.0, "volume": 10.0}]
        data = CanonicalChartData(asset="TEST", candles=bad)
        with self.assertRaises(MalformedCandleError):
            data.validate_candles()

    def test_canonical_chart_data_rejects_open_outside_bounds(self) -> None:
        bad = [{"open": 110.0, "high": 105.0, "low": 90.0, "close": 95.0, "volume": 10.0}]
        data = CanonicalChartData(asset="TEST", candles=bad)
        with self.assertRaises(MalformedCandleError):
            data.validate_candles()

    def test_canonical_chart_data_rejects_close_outside_bounds(self) -> None:
        bad = [{"open": 95.0, "high": 105.0, "low": 90.0, "close": 85.0, "volume": 10.0}]
        data = CanonicalChartData(asset="TEST", candles=bad)
        with self.assertRaises(MalformedCandleError):
            data.validate_candles()

    def test_canonical_chart_data_rejects_negative_volume(self) -> None:
        bad = [{"open": 95.0, "high": 105.0, "low": 90.0, "close": 100.0, "volume": -5.0}]
        data = CanonicalChartData(asset="TEST", candles=bad)
        with self.assertRaises(MalformedCandleError):
            data.validate_candles()

    # --- T07-T11: Static Charts (Matplotlib & mplfinance Headless Agg) ---

    def test_render_candlestick_png_creates_file(self) -> None:
        out = self.root / "test_candlestick.png"
        res = render_candlestick_png(
            symbol="BBCA",
            candles=self.sample_candles,
            output_path=out,
            quant_result=self.quant,
        )
        self.assertTrue(res.exists())
        self.assertGreater(res.stat().st_size, 1000)

    def test_render_ownership_pie_png(self) -> None:
        out = self.root / "test_ownership.png"
        res = render_ownership_pie_png(self.sample_ownership, symbol="BBCA", output_path=out)
        self.assertTrue(res.exists())
        self.assertGreater(res.stat().st_size, 1000)

    def test_render_ownership_pie_rejects_empty(self) -> None:
        empty_own = OwnershipStructure(
            ticker="EMPTY",
            issuer="Empty Corp",
            reporting_date="",
            publication_date="",
            source="",
            shares_outstanding=1000.0,
            denominator_type="shares_outstanding",
            top_shareholders=[],
            public_shareholders_pct=0.0,
        )
        with self.assertRaises(ValueError):
            render_ownership_pie_png(empty_own, symbol="EMPTY")

    def test_render_equity_curve_png(self) -> None:
        class MockBacktestResult:
            initial_capital = 100_000_000.0
            total_return_pct = 15.5
            max_drawdown_pct = 4.2
            equity_curve = [
                {"date": "2026-10-01", "equity": 100_000_000.0, "drawdown_pct": 0.0},
                {"date": "2026-10-02", "equity": 105_000_000.0, "drawdown_pct": 0.0},
                {"date": "2026-10-03", "equity": 103_000_000.0, "drawdown_pct": -1.9},
                {"date": "2026-10-04", "equity": 115_500_000.0, "drawdown_pct": 0.0},
            ]

        out = self.root / "test_equity_curve.png"
        res = render_equity_curve_png(MockBacktestResult(), symbol="BBCA", output_path=out)
        self.assertTrue(res.exists())
        self.assertGreater(res.stat().st_size, 1000)

    def test_render_macro_line_png(self) -> None:
        points = [
            {"date": "2026-09-01", "value": 15800.0},
            {"date": "2026-09-02", "value": 15850.0},
            {"date": "2026-09-03", "value": 15790.0},
            {"date": "2026-09-04", "value": 15920.0},
        ]
        out = self.root / "test_macro.png"
        res = render_macro_line_png(points=points, title="USD/IDR", series_label="IDR per USD", output_path=out)
        self.assertTrue(res.exists())
        self.assertGreater(res.stat().st_size, 1000)

    def test_render_macro_line_rejects_single_point(self) -> None:
        points = [{"date": "2026-09-01", "value": 15800.0}]
        with self.assertRaises(ValueError):
            render_macro_line_png(points=points, title="USD/IDR")

    def test_render_peer_bar_png(self) -> None:
        peers = {
            "BBCA": {"per": 22.5, "pbv": 4.8},
            "BMRI": {"per": 11.2, "pbv": 2.1},
            "BBRI": {"per": 12.0, "pbv": 2.4},
        }
        out = self.root / "test_peers.png"
        res = render_peer_bar_png(peers, metric_name="pbv", title="Perbandingan PBV Perbankan", output_path=out)
        self.assertTrue(res.exists())
        self.assertGreater(res.stat().st_size, 1000)

    # --- T12: Vector PDF Report Generation ---

    def test_generate_pdf_report(self) -> None:
        out = self.root / "bbca_test_report.pdf"
        res = generate_pdf_report(
            symbol="BBCA",
            quant_result=self.quant,
            ownership=self.sample_ownership,
            root=self.root,
            timeframe="D1",
        )
        self.assertTrue(res.exists())
        self.assertEqual(res.suffix.lower(), ".pdf")
        self.assertGreater(res.stat().st_size, 2000)

    # --- T13-T15: TradingView MCP Client & Tool Allowlist ---

    def test_tradingview_mcp_status_safe(self) -> None:
        client = TradingViewMCPClient(root=self.root)
        st = client.status()
        self.assertIsInstance(st, MCPStatus)
        self.assertIn("Node.js", st.runtime) if st.runtime != "unavailable" else self.assertFalse(st.available)

    def test_tradingview_mcp_rejects_unapproved_tools(self) -> None:
        client = TradingViewMCPClient(root=self.root)
        res = client.execute_tool("delete_files", {"path": "/etc"})
        self.assertFalse(res["success"])
        self.assertIn("tidak diizinkan", res["error"])

    def test_tradingview_mcp_format_view(self) -> None:
        view = format_integrations_view()
        self.assertIn("Matplotlib & mplfinance", view)
        self.assertIn("TradingView Lightweight Charts", view)
        self.assertIn("TradingView MCP Adapter", view)

    # --- T16: Interactive Chart Graceful Fallback ---

    def test_interactive_chart_fallback(self) -> None:
        res = launch_interactive_chart(
            symbol="BBCA",
            candles=self.sample_candles,
            timeframe="D1",
            quant_result=self.quant,
            root=self.root,
            blocking=False,
        )
        self.assertIn("status", res)
        self.assertIn(res["status"], ("desktop_window", "WINDOW_OPENED", "offline_html", "FALLBACK_HTML", "terminal_fallback", "FALLBACK_TERMINAL"))

    # --- T17-T20: Intent Routing for All New Presentation Options ---

    def test_intent_routing_report_pdf(self) -> None:
        req = self.router.parse("/report pdf BBCA")
        self.assertEqual(req.request_type, "REPORT_PDF")
        self.assertEqual(req.asset, "BBCA")

    def test_intent_routing_export_png(self) -> None:
        req = self.router.parse("/export png BTC")
        self.assertEqual(req.request_type, "EXPORT_PNG")
        self.assertEqual(req.asset, "BTC")

    def test_intent_routing_integrations(self) -> None:
        req = self.router.parse("/integrations")
        self.assertEqual(req.request_type, "INTEGRATIONS")

    def test_intent_routing_chart_terminal(self) -> None:
        req = self.router.parse("/chart BBCA terminal")
        self.assertEqual(req.request_type, "CHART")
        self.assertEqual(req.focus, "terminal")

    def test_intent_routing_natural_ownership_chart(self) -> None:
        req = self.router.parse("grafik kepemilikan BBCA")
        self.assertEqual(req.request_type, "EQUITY_OWNERSHIP")
        self.assertEqual(req.focus, "chart")

    def test_intent_routing_natural_equity_curve(self) -> None:
        req = self.router.parse("grafik equity curve BBCA")
        self.assertEqual(req.request_type, "BACKTEST")
        self.assertEqual(req.focus, "equity_curve")

    def test_intent_routing_natural_usd_idr(self) -> None:
        req = self.router.parse("grafik usd idr 1 tahun")
        self.assertEqual(req.request_type, "FIAT_FX")
        self.assertEqual(req.focus, "USD/IDR")
        self.assertEqual(req.topic, "fx")


if __name__ == "__main__":
    unittest.main()
