"""Permanent Acceptance Tests for OpenBagus Product Intelligence and Interaction.

Covers Section I requirements (I1 through I9):
I1: Harness interactive session context switching (BTC -> ETH confirmation, N keeps BTC, Y switches, Compare bypasses)
I2: System context continuity (BTC -> system info -> follow-up preserved on BTC)
I3: Chart action (TradingView / GeckoTerminal browser action only, no full quant analysis text, no ASCII chart)
I4: BLS CPI-U freshness verification (August 2026 reference month, next release Oct 14, 2026, not stale)
I5: Federal Reserve FOMC schedule verification (Oct 7, 2026 minutes, Oct 27-28, 2026 meeting)
I6: Conditional factor engine materiality (Stochastic, Pattern, Fibonacci only surfaced when material)
I7: Cross-venue arbitrage materiality (Tiny spread suppressed, large net spread surfaced)
I8: Lunar/astrology factor isolation (Zero weight, suppressed by default, isolated to explicit diagnostic)
I9: Narrative consistency and anti-template compliance
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from openbagus.cli import OpenBagusShell
from openbagus.data.zerokey import ZeroKeyMarketData
from openbagus.domains.crypto.quant import (
    EvidenceBlockResult,
    QuantDecisionResult,
    QuantEngine,
    ValidationScenario,
)
from openbagus.domains.crypto.research import CryptoResearchRunner, ResearchPacket
from openbagus.intelligence.intent import IntentRequest, IntentRouter, SessionState
from openbagus.intelligence.local_language import LocalLanguageEngine


class TestProductInteraction(unittest.TestCase):
    def setUp(self) -> None:
        self.router = IntentRouter()
        self.quant = QuantEngine()
        self.zerokey = ZeroKeyMarketData()

    # ============================================================
    # I1. HARNESS TEST
    # ============================================================
    def test_i1_harness_session(self) -> None:
        """Verify strict context switching: BTC -> ETH asks confirmation; N keeps BTC; repeat ETH + Y switches; BTC vs ETH runs COMPARE."""
        shell = OpenBagusShell()
        shell.session.last_asset = "BTC"

        # Mock runner.execute to prevent live network calls during shell interaction
        with patch.object(shell.researcher, "execute", return_value="Executed") as mock_exec:
            # 1. User inputs "ETH" while BTC is active, user enters "N"
            with patch("builtins.input", return_value="N"):
                shell.default("ETH")
                # Context must remain BTC
                self.assertEqual(shell.session.last_asset, "BTC")

            # 2. User repeats "ETH" and confirms with "Y"
            with patch("builtins.input", return_value="Y"):
                shell.default("ETH")
                # Context must switch to ETH
                self.assertEqual(shell.session.last_asset, "ETH")

            # 3. User inputs comparison "BTC vs ETH"
            with patch("builtins.input") as mock_input:
                shell.default("BTC vs ETH")
                # Context switch confirmation must NOT be triggered for COMPARE
                mock_input.assert_not_called()

    # ============================================================
    # I2. SYSTEM CONTEXT TEST
    # ============================================================
    def test_i2_system_context(self) -> None:
        """Verify BTC analysis -> system question ('siapa pembuat OpenBagus?') -> follow-up ('entry tadi dimana?') retains BTC context."""
        session = SessionState()
        session.last_asset = "BTC"

        # 1. System question
        req_sys = self.router.parse("siapa pembuat OpenBagus?", session=session)
        self.assertEqual(req_sys.request_type, "SYSTEM_INFO")
        self.assertIsNone(req_sys.asset)
        # Context remains BTC
        self.assertEqual(session.last_asset, "BTC")

        # 2. Follow-up query
        req_followup = self.router.parse("entry tadi dimana?", session=session)
        self.assertIn(req_followup.request_type, ("POSITION", "EXPLAIN_LEVELS", "FOLLOW_UP"))
        self.assertEqual(req_followup.asset, "BTC")
        self.assertEqual(session.last_asset, "BTC")

    # ============================================================
    # I3. CHART TEST
    # ============================================================
    def test_i3_chart_browser_action(self) -> None:
        """Verify 'chartnya dong' triggers browser chart action only, without full Quant analysis or ASCII candlesticks."""
        session = SessionState()
        session.last_asset = "BTC"
        runner = CryptoResearchRunner()

        req = self.router.parse("chartnya dong", session=session)
        self.assertEqual(req.request_type, "CHART")
        self.assertEqual(req.asset, "BTC")

        # Mock webbrowser.open to prevent browser launching in CI/automated runs
        with patch("webbrowser.open") as mock_open:
            with patch.object(runner.zerokey, "get_spot_ticker", return_value={"price": 85000.0}):
                res = runner.execute(req, session=session)

                # Browser opened with TradingView
                mock_open.assert_called_once()
                opened_url = mock_open.call_args[0][0]
                self.assertIn("tradingview.com", opened_url)
                self.assertIn("BTC", opened_url)

                # Output is concise status only
                self.assertTrue(res.startswith("Opening BTC") or "Opening BTC" in res)
                self.assertNotIn("Quant Decision:", res)
                self.assertNotIn("Reward:Risk", res)
                self.assertNotIn("───", res)

    # ============================================================
    # I4. CPI TEST
    # ============================================================
    def test_i4_cpi_freshness(self) -> None:
        """Verify CPI metadata: August 2026 reference month, next release Oct 14, 2026, is_stale=False."""
        cpi = self.zerokey.get_cpi()
        self.assertEqual(cpi.get("series_id"), "CUUR0000SA0")
        self.assertEqual(cpi.get("reference_month"), "August 2026")
        self.assertEqual(cpi.get("next_release_date"), "2026-10-14")
        self.assertFalse(cpi.get("is_stale"))
        self.assertIn("August 2026", cpi.get("summary", ""))

    # ============================================================
    # I5. FOMC TEST
    # ============================================================
    def test_i5_fomc_schedule(self) -> None:
        """Verify FOMC schedule: Oct 7, 2026 minutes, Oct 27-28, 2026 meeting, and error fallback."""
        fomc = self.zerokey.get_fomc()
        self.assertEqual(fomc.get("next_event"), "2026-10-07 minutes")
        self.assertEqual(fomc.get("next_meeting"), "October 27-28, 2026")
        self.assertIn("2026-10-07 minutes", fomc.get("summary", ""))

        # Error handling when calendar parsing fails
        fomc_err = self.zerokey.get_fomc(html_source="<html>Corrupted HTML without valid dates</html>")
        self.assertEqual(fomc_err.get("error"), "FOMC_CALENDAR_PARSE_ERROR")

    # ============================================================
    # I6. CONDITIONAL FACTOR TEST
    # ============================================================
    def test_i6_conditional_factor_engine(self) -> None:
        """Verify Stochastic, Pattern, and Fibonacci only appear when material confluence criteria are met."""
        # 1. Fibonacci
        klines_fib = [
            {"high": 50.0 + (i * 2.0), "low": 50.0 + (i * 2.0), "close": 50.0 + (i * 2.0)}
            for i in range(26)
        ]
        # Price mid-range (83.0) far from any Fib level -> not material
        fib_mid = self.quant.evaluate_fibonacci(klines_fib, 83.0, 75.0, 60.0, 90.0)
        self.assertFalse(fib_mid.get("material"))

        # Price at 69.15 near Fib 0.618 (69.10) with pivot at 69.0 -> material
        fib_conf = self.quant.evaluate_fibonacci(klines_fib, 69.15, 69.0, 60.0, 90.0)
        self.assertTrue(fib_conf.get("material"))
        self.assertIn("0.618", fib_conf.get("values", {}).get("confluence", ""))

        # 2. Stochastic
        # Flat klines -> neutral %K ~ 50 -> not material
        flat_klines = [{"high": 105.0, "low": 95.0, "close": 100.0} for _ in range(20)]
        stoch_flat = self.quant.evaluate_stochastic(flat_klines, 100.0, 100.0, 95.0, 105.0)
        self.assertFalse(stoch_flat.get("material"))

        # Bearish cross near resistance -> material
        klines_stoch_ob = []
        for _ in range(13):
            klines_stoch_ob.append({"high": 100.0, "low": 50.0, "close": 85.0})
        klines_stoch_ob.append({"high": 100.0, "low": 50.0, "close": 95.0})
        klines_stoch_ob.append({"high": 100.0, "low": 50.0, "close": 98.0})
        klines_stoch_ob.append({"high": 100.0, "low": 50.0, "close": 89.0})
        stoch_bear = self.quant.evaluate_stochastic(klines_stoch_ob, 89.0, 75.0, 60.0, 90.0)
        self.assertTrue(stoch_bear.get("material"))
        self.assertEqual(stoch_bear.get("direction"), "BEARISH")

        # 3. Chart Patterns
        # Flat klines -> no pattern -> not material
        pat_flat = self.quant.evaluate_pattern(flat_klines, 100.0, 100.0, 95.0, 105.0)
        self.assertFalse(pat_flat.get("material"))

        # Confirmed Bearish Engulfing at resistance -> material
        klines_bear_engulf = [
            {"open": 90.0, "high": 92.0, "low": 89.0, "close": 91.0, "volume": 100.0},
            {"open": 91.0, "high": 100.0, "low": 90.5, "close": 99.5, "volume": 120.0},
            {"open": 100.0, "high": 100.5, "low": 89.0, "close": 89.5, "volume": 350.0},
        ]
        pat_bear = self.quant.evaluate_pattern(klines_bear_engulf, 89.5, 95.0, 85.0, 100.0, atr=5.0)
        self.assertTrue(pat_bear.get("material"))
        self.assertEqual(pat_bear.get("values", {}).get("name"), "Bearish Engulfing")

    # ============================================================
    # I7. ARBITRAGE TEST
    # ============================================================
    def test_i7_arbitrage_engine(self) -> None:
        """Verify cross-venue spread materiality: small spreads erased by costs are suppressed; large spreads surfaced."""
        # Tiny gross spread (0.02%) erased by ~0.25% cost -> not material
        ticker_tiny = {"cross_venue_quotes": {"A": {"price": 100.0}, "B": {"price": 100.02}}}
        arb_tiny = self.quant.evaluate_arbitrage(ticker_tiny, 100.0)
        self.assertFalse(arb_tiny.get("material"))

        # Large gross spread (1.50%) surviving ~0.25% cost -> material
        ticker_wide = {"cross_venue_quotes": {"Binance": {"price": 100.0}, "Gate.io": {"price": 101.5}}}
        arb_wide = self.quant.evaluate_arbitrage(ticker_wide, 100.0)
        self.assertTrue(arb_wide.get("material"))
        self.assertGreater(arb_wide.get("values", {}).get("estimated_net_spread_pct", 0.0), 0.10)

    # ============================================================
    # I8. LUNAR TEST
    # ============================================================
    def test_i8_lunar_experimental_astrology(self) -> None:
        """Verify astrology/lunar factor: zero weight, hidden on normal queries, isolated diagnostic only if explicitly asked."""
        runner = CryptoResearchRunner()
        lunar_item = self.quant.evaluate_lunar()
        self.assertTrue(lunar_item.get("available"))
        self.assertFalse(lunar_item.get("material"))
        self.assertEqual(lunar_item.get("values", {}).get("weight"), 0.0)

        # Build mock packet via quant.evaluate
        decision_res = self.quant.evaluate(
            "BTC",
            {"symbol": "BTC", "price": 85000.0, "high": 87000.0, "low": 83000.0, "volume": 1000000.0},
        )

        # 1. Normal BTC query -> no astrology/lunar in report
        with patch.object(runner.local_llm, "is_available", return_value=False):
            rep_normal = runner._render_section_25_view(decision_res, raw_query="analisa BTC")
            self.assertNotIn("Astrology", rep_normal)
            self.assertNotIn("Lunar", rep_normal)

            # 2. Explicit query -> displays experimental diagnostic note
            rep_astro = runner._render_section_25_view(decision_res, raw_query="show experimental lunar factor")
            self.assertIn("Astrology (EXPERIMENTAL / Weight=0)", rep_astro)

        # Decision is unaffected
        self.assertEqual(decision_res.decision, "WAIT")

    # ============================================================
    # I9. NARRATIVE TEST
    # ============================================================
    def test_i9_narrative_consistency_and_anti_template(self) -> None:
        """Verify narrative preserves quantitative decision and numbers while omitting repetitive template headers."""
        runner = CryptoResearchRunner()

        val_bull = ValidationScenario(
            direction="LONG",
            trigger_condition="H1 close above $87,500",
            volume_condition="Volume expansion",
            order_flow_condition="Taker buy > 0.10",
            derivatives_condition="OI expansion",
            entry_zone="$87,500",
            stop_price=86000.0,
            tp1=90000.0,
            tp2=92000.0,
            reward_risk=1.67,
            reward_risk_str="1:1.67",
            summary="Bullish continuation above 87,500",
        )
        val_bear = ValidationScenario(
            direction="SHORT",
            trigger_condition="H1 breakdown below $83,000",
            volume_condition="Sell volume spike",
            order_flow_condition="Taker sell < -0.10",
            derivatives_condition="OI rise on breakdown",
            entry_zone="$83,000",
            stop_price=84500.0,
            tp1=80000.0,
            tp2=78000.0,
            reward_risk=2.0,
            reward_risk_str="1:2.00",
            summary="Bearish continuation below 83,000",
        )

        decision_res = self.quant.evaluate(
            "BTC",
            {"symbol": "BTC", "price": 85000.0, "high": 87000.0, "low": 83000.0, "volume": 1000000.0},
        )
        decision_res.bullish_validation = val_bull
        decision_res.bearish_validation = val_bear

        with patch.object(runner.local_llm, "is_available", return_value=False):
            report = runner._render_section_25_view(decision_res, raw_query="BTC")

        # 1. Quantitative decision preserved
        self.assertIn("WAIT", report)
        self.assertIn("$85,000", report)

        # 2. Conditional actionable setup present with concrete levels
        self.assertIn("Conditional setup:", report)
        self.assertIn("Long valid if : H1 close above $87,500", report)
        self.assertIn("Short valid if: H1 breakdown below $83,000", report)

        # 3. No formulaic template headers
        self.assertNotIn("Reason:", report)
        self.assertNotIn("Watch:", report)
        self.assertNotIn("Summary:", report)
        self.assertNotIn("Why:", report)

        # 4. Irrelevant/non-material factors omitted
        self.assertNotIn("Fibonacci:", report)
        self.assertNotIn("Stochastic:", report)
        self.assertNotIn("Arbitrage:", report)


if __name__ == "__main__":
    unittest.main()
