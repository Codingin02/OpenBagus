"""Unit and acceptance tests for Advanced Market Intelligence, Global Events & Compute Acceleration."""

import unittest
from datetime import datetime, timezone, timedelta

from openbagus.domains.crypto.arbitrage import ArbitrageEngine, DepthWalkResult
from openbagus.intelligence.macro.events import MacroEventEngine, MacroEvent
from openbagus.domains.equities.asian_preopen import AsianPreOpenIntelligence, WIB
from openbagus.intelligence.astro import LunarCycleResearch
from openbagus.domains.quant.acceleration import HybridComputeEngine
from openbagus.intelligence.macro.scenario import build_scenario_thesis, build_macro_overlay
from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.domains.crypto.research import CryptoResearchRunner


class TestArbitrageEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ArbitrageEngine()

    def test_depth_walk_asks(self):
        # Asks: 10 @ $100 ($1,000), 10 @ $105 ($1,050)
        asks = [[100.0, 10.0], [105.0, 10.0]]
        res = self.engine.walk_orderbook_asks(asks, target_notional_usd=1500.0)
        self.assertTrue(res.is_fully_filled)
        self.assertEqual(res.levels_traversed, 2)
        # $1,000 at $100 (10 qty) + $500 at $105 (4.7619 qty)
        expected_qty = 10.0 + (500.0 / 105.0)
        expected_vwap = 1500.0 / expected_qty
        self.assertAlmostEqual(res.vwap, expected_vwap, places=2)
        self.assertGreater(res.slippage_pct, 0.0)

    def test_depth_walk_bids(self):
        # Bids: 10 @ $100 ($1,000), 10 @ $95 ($950)
        bids = [[100.0, 10.0], [95.0, 10.0]]
        res = self.engine.walk_orderbook_bids(bids, target_notional_usd=1500.0)
        self.assertTrue(res.is_fully_filled)
        expected_qty = 10.0 + (500.0 / 95.0)
        expected_vwap = 1500.0 / expected_qty
        self.assertAlmostEqual(res.vwap, expected_vwap, places=2)

    def test_cross_venue_arbitrage_fees_and_status(self):
        # Venue A: ask $60,000; Venue B: bid $60,300 (raw spread +0.50%)
        venues = {
            "Binance": {"asks": [[60000.0, 1.0]], "observed_at_ts": 1000.0},
            "Gate.io": {"bids": [[60300.0, 1.0]], "observed_at_ts": 1000.0},
        }
        opp = self.engine.evaluate_cross_venue_arbitrage(
            symbol="BTC",
            venues=venues,
            declared_notional=1000.0,
            taker_fee_pct=0.10,
            transfer_fee_usd=1.0,
            now_ts=1005.0,
        )
        self.assertEqual(opp.buy_venue, "Binance")
        self.assertEqual(opp.sell_venue, "Gate.io")
        self.assertAlmostEqual(opp.gross_spread_pct, 0.50, places=2)
        # Costs: 0.20% taker + 0.10% transfer ($1 on $1000) = 0.30%
        # Net spread: ~0.20% > 0.05% -> POTENTIAL_AFTER_COSTS
        self.assertEqual(opp.status, "POTENTIAL_AFTER_COSTS")
        self.assertGreater(opp.net_profit_usd, 0.0)

    def test_cross_venue_observed_spread_not_profitable(self):
        # Raw spread +0.10%, but costs are ~0.30% -> OBSERVED_SPREAD
        venues = {
            "Binance": {"asks": [[60000.0, 1.0]], "observed_at_ts": 1000.0},
            "Gate.io": {"bids": [[60060.0, 1.0]], "observed_at_ts": 1000.0},
        }
        opp = self.engine.evaluate_cross_venue_arbitrage(
            symbol="BTC",
            venues=venues,
            declared_notional=1000.0,
            taker_fee_pct=0.10,
            now_ts=1005.0,
        )
        self.assertEqual(opp.status, "OBSERVED_SPREAD")
        self.assertLess(opp.net_spread_pct, 0.0)

    def test_cross_venue_stale_quotes(self):
        venues = {
            "Binance": {"asks": [[60000.0, 1.0]], "observed_at_ts": 100.0},
            "Gate.io": {"bids": [[60500.0, 1.0]], "observed_at_ts": 100.0},
        }
        opp = self.engine.evaluate_cross_venue_arbitrage(
            symbol="BTC",
            venues=venues,
            now_ts=200.0,  # 100 seconds later -> stale (>30s)
        )
        self.assertEqual(opp.status, "STALE_QUOTES")

    def test_triangular_arbitrage(self):
        rates = {"BTC/USDT": 60000.0, "ETH/BTC": 0.05, "ETH/USDT": 3000.0}
        res = self.engine.evaluate_triangular_arbitrage(
            rates=rates,
            route=["USDT", "BTC", "ETH", "USDT"],
            initial_notional=1000.0,
            fee_per_leg_pct=0.10,
        )
        # 1000 USDT -> 0.01666 BTC * 0.999 -> 0.333 ETH * 0.999 -> 997 USDT
        self.assertEqual(res.status, "NOT_EXECUTABLE")
        self.assertLess(res.net_return_pct, 0.0)

    def test_basis_dislocation(self):
        res = self.engine.evaluate_basis_dislocation(
            symbol="BTC",
            spot_price=60000.0,
            perp_price=60600.0,  # +1.0% premium
            funding_rate_8h=0.0001,  # 0.01%
        )
        self.assertEqual(res.status, "ELEVATED")
        self.assertAlmostEqual(res.basis_pct, 1.0, places=2)
        self.assertIsNotNone(res.funding_annualized_pct)


class TestMacroEventEngine(unittest.TestCase):
    def setUp(self):
        self.engine = MacroEventEngine()

    def test_point_in_time_redaction(self):
        # Event scheduled at 2026-10-14T12:30:00Z
        # As of 2026-10-10, actual must be None (unreleased)
        events = self.engine.get_events(as_of="2026-10-10T00:00:00Z")
        cpi_oct = next(e for e in events if e.event_id == "US_CPI_2026_10")
        self.assertIsNone(cpi_oct.actual)
        self.assertEqual(cpi_oct.lifecycle_state, "UPCOMING")

    def test_historical_event_surprise(self):
        # Event scheduled at 2026-09-11
        # As of 2026-09-12, actual is released
        events = self.engine.get_events(as_of="2026-09-12T00:00:00Z")
        cpi_sep = next(e for e in events if e.event_id == "US_CPI_2026_09")
        self.assertIsNotNone(cpi_sep.actual)
        self.assertEqual(cpi_sep.lifecycle_state, "HISTORICAL")
        self.assertEqual(cpi_sep.surprise_type, "STANDARDIZED_ZSCORE")
        # Actual 0.32, forecast 0.20, std 0.05 -> surprise (0.32-0.20)/0.05 = 2.40
        self.assertAlmostEqual(cpi_sep.surprise_standardized, 2.40, places=2)

    def test_imminent_lifecycle(self):
        # Event at 2026-10-14T12:30:00Z
        # As of 2026-10-14T00:00:00Z (12.5h prior) -> IMMINENT
        events = self.engine.get_events(as_of="2026-10-14T00:00:00Z")
        cpi_oct = next(e for e in events if e.event_id == "US_CPI_2026_10")
        self.assertEqual(cpi_oct.lifecycle_state, "IMMINENT")


class TestAsianPreOpenIntelligence(unittest.TestCase):
    def setUp(self):
        self.engine = AsianPreOpenIntelligence()

    def test_session_clocks_at_0840_wib(self):
        # Tuesday at 08:40 WIB
        dt = datetime(2026, 10, 13, 8, 40, tzinfo=WIB)
        clocks = self.engine.get_session_clocks(dt)
        krx = next(c for c in clocks if c.market_code == "KRX")
        tse = next(c for c in clocks if c.market_code == "TSE")
        sse = next(c for c in clocks if c.market_code == "SSE")
        hkex = next(c for c in clocks if c.market_code == "HKEX")
        idx = next(c for c in clocks if c.market_code == "IDX")

        # KRX & TSE open at 07:00 -> 100 minutes open
        self.assertEqual(krx.status, "OPEN")
        self.assertEqual(krx.minutes_open, 100)
        self.assertEqual(tse.status, "OPEN")
        self.assertEqual(tse.minutes_open, 100)

        # SSE & HKEX open at 08:30 -> 10 minutes open
        self.assertEqual(sse.status, "OPEN")
        self.assertEqual(sse.minutes_open, 10)
        self.assertEqual(hkex.status, "OPEN")
        self.assertEqual(hkex.minutes_open, 10)

        # IDX opens at 09:00 -> CLOSED at 08:40
        self.assertEqual(idx.status, "CLOSED")

    def test_preopen_briefing_sector_impacts(self):
        dt = datetime(2026, 10, 13, 8, 40, tzinfo=WIB)
        quotes = {
            "N225_pct": 0.80,
            "KS11_pct": 0.65,
            "HSI_pct": 0.20,
            "SSEC_pct": 0.35,
            "USD_IDR": 15600.0,
            "USD_IDR_pct": -0.05,
            "NICKEL_pct": 1.50,
            "COAL_pct": 0.10,
        }
        briefing = self.engine.build_preopen_briefing(dt, quotes)
        self.assertEqual(briefing.regional_sentiment, "RISK_ON")
        self.assertEqual(briefing.idx_market_state, "PRE_OPEN_IMMINENT")

        # Check basic materials sector impact
        b_sec = next(s for s in briefing.sector_impacts if s.sector_code == "B")
        self.assertEqual(b_sec.sentiment_bias, "POSITIVE")
        self.assertIn("ANTM", b_sec.representative_tickers)


class TestLunarCycleResearch(unittest.TestCase):
    def test_lunar_phase_and_zero_decision_weight(self):
        phase = LunarCycleResearch.get_lunar_phase()
        self.assertEqual(phase.status, "EXPERIMENTAL")
        self.assertEqual(phase.decision_weight, "0%")
        self.assertTrue(0.0 <= phase.phase_ratio <= 1.0)
        self.assertTrue(0.0 <= phase.illumination_pct <= 100.0)

    def test_lunar_hypothesis_test(self):
        # Synthetic candles
        candles = [{"time": 1704067200000 + i * 86400000, "close": 40000.0 + i * 10.0} for i in range(60)]
        res = LunarCycleResearch.test_lunar_effect_on_returns("BTC", candles)
        self.assertEqual(res.asset_symbol, "BTC")
        self.assertEqual(res.sample_size_candles, 60)
        self.assertTrue(hasattr(res, "p_value"))
        self.assertIn("0%", res.conclusion)


class TestHybridComputeEngine(unittest.TestCase):
    def setUp(self):
        self.engine = HybridComputeEngine()

    def test_hardware_profiler(self):
        prof = self.engine.profile
        self.assertGreaterEqual(prof.cpu_count, 1)
        self.assertIn(prof.recommended_backend, ("CUDA", "NUMBA_JIT", "NUMPY_VECTORIZED", "PURE_PYTHON"))

    def test_monte_carlo_pure_python(self):
        res = self.engine.simulate_monte_carlo_pure_python(100.0, 0.02, 0.05, num_paths=500, steps=10)
        self.assertEqual(res.backend_used, "PURE_PYTHON")
        self.assertEqual(res.num_paths, 500)
        self.assertGreater(res.mean_ending_price, 0.0)
        self.assertGreaterEqual(res.var_95_pct, 0.0)

    def test_benchmark_system(self):
        rep = self.engine.benchmark_system(num_paths=1000, steps=10)
        self.assertGreater(rep.speedup_ratio, 0.0)
        self.assertGreater(rep.paths_per_second, 0.0)
        self.assertIn("Benchmark Quantum OpenBagus", rep.summary)


class TestScenarioProbabilityLabeling(unittest.TestCase):
    def test_heuristic_weights_labeling(self):
        macro_overlay = build_macro_overlay({}, {})
        res = build_scenario_thesis(
            symbol="BTC",
            market_row={"price": 60000.0},
            analysis_status="OK",
            market_structure={"support_resistance": {"support": 58000.0, "resistance": 62000.0, "range_position": 0.5}},
            risk_metrics={"status": "OK", "latest_bar_return": 0.01},
            macro_overlay=macro_overlay,
        )
        self.assertEqual(res["probability_calibration"], "HEURISTIC_WEIGHTS_UNCALIBRATED")
        self.assertEqual(res["probability_type"], "heuristic_weight")
        self.assertIn("heuristic_weights", res)
        self.assertIn("scenario_probability", res)  # Backwards compatibility preserved


class TestIntentAcceptanceQueries(unittest.TestCase):
    def setUp(self):
        self.router = IntentRouter()
        self.runner = CryptoResearchRunner()

    def test_arbitrage_intent(self):
        req = self.router.parse("ada arbitrase btc antar exchange sekarang?")
        self.assertEqual(req.intent, "ARBITRAGE")
        self.assertEqual(req.asset, "BTC")
        out = self.runner.execute(req)
        self.assertIn("Analisis Arbitrase & Dislokasi Bursa: BTC", out)

    def test_macro_event_intent(self):
        req = self.router.parse("nfp malam ini jam berapa dan dampaknya ke crypto?")
        self.assertEqual(req.intent, "MACRO_EVENT")
        out = self.runner.execute(req)
        self.assertIn("Kalender & Intelijen Peristiwa Makro Global", out)

    def test_cpi_intent(self):
        req = self.router.parse("cpi rilis kapan")
        self.assertEqual(req.intent, "MACRO_EVENT")
        out = self.runner.execute(req)
        self.assertIn("Kalender & Intelijen Peristiwa Makro Global", out)

    def test_asian_preopen_intent(self):
        req = self.router.parse("bagaimana pasar asia pagi ini sebelum ihsg buka?")
        self.assertEqual(req.intent, "ASIAN_PREOPEN")
        out = self.runner.execute(req)
        self.assertIn("Intelijen Pre-Opening Pasar Asia", out)

    def test_sector_impact_intent(self):
        req = self.router.parse("dampak china manufacturing data ke sektor tambang idx antm")
        self.assertEqual(req.intent, "SECTOR_IMPACT")
        self.assertEqual(req.asset, "ANTM")
        out = self.runner.execute(req)
        self.assertIn("Analisis Transmisi Makro & Dampak Sektoral", out)
        self.assertIn("ANTM", out)

    def test_lunar_cycle_intent(self):
        req = self.router.parse("apakah fase bulan mempengaruhi pergerakan btc?")
        self.assertEqual(req.intent, "LUNAR_CYCLE")
        self.assertEqual(req.asset, "BTC")
        out = self.runner.execute(req)
        self.assertIn("Riset Eksperimental Siklus Astronomi & Fase Bulan: BTC", out)
        self.assertIn("0%", out)

    def test_benchmark_intent(self):
        req = self.router.parse("benchmark quantum openbagus")
        self.assertEqual(req.intent, "BENCHMARK")
        out = self.runner.execute(req)
        self.assertIn("Benchmark Quantum OpenBagus", out)


if __name__ == "__main__":
    unittest.main()
