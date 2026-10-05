"""Test Quant Engine Math, Security, Microstructure, and Risk Calculations."""

import unittest
from unittest.mock import MagicMock, patch

from openbagus.core.market_structure import (
    calculate_volume_profile,
    calculate_vwap,
    detect_support_resistance,
)
from openbagus.data.http import (
    ALLOWED_PROVIDER_HOSTS,
    DisallowedHostError,
    InsecureSchemeError,
    SafeRedirectHandler,
    SecureHttpClient,
    sanitize_url,
)
from openbagus.data.zerokey import ZeroKeyMarketData
from openbagus.domains.crypto.quant import QuantEngine
from openbagus.domains.crypto.research import CryptoResearchRunner
from openbagus.intelligence.intent import IntentRequest
from openbagus.risk.metrics import (
    calculate_max_drawdown,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_var_cvar,
)


class TestMarketStructureMath(unittest.TestCase):
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


class TestNetworkSecurity(unittest.TestCase):
    def setUp(self):
        self.client = SecureHttpClient(timeout=1.0, max_response_bytes=1024)

    def test_1_disallowed_host_rejected(self):
        with self.assertRaises(DisallowedHostError):
            self.client.validate_target_url("https://malicious-site.com/api")

        with self.assertRaises(DisallowedHostError):
            self.client.validate_target_url("https://127.0.0.1:8080/api")

        _, status, _ = self.client.fetch_raw("https://arbitrary-user-domain.org/data")
        self.assertEqual(status, "DISALLOWED_HOST")

    def test_2_non_https_url_rejected(self):
        with self.assertRaises(InsecureSchemeError):
            self.client.validate_target_url("http://data-api.binance.vision/api/v3/ping")

        with self.assertRaises(InsecureSchemeError):
            self.client.validate_target_url("file:///etc/passwd")

        _, status, _ = self.client.fetch_raw("http://api.gateio.ws/api/v4/spot/tickers")
        self.assertEqual(status, "DISALLOWED_HOST")

    def test_3_provider_timeout_fallback(self):
        zk = ZeroKeyMarketData(timeout=0.001)
        # With an impossible timeout, fetcher degrades gracefully to None
        res = zk._get_json("https://data-api.binance.vision/api/v3/ping")
        # Should not raise an unhandled exception
        self.assertIsNone(res)

    def test_4_malformed_json_returns_none(self):
        with patch.object(self.client, "fetch_raw", return_value=("{not:valid:json}", "REACHABLE", 10.0)):
            res = self.client.get_json("https://data-api.binance.vision/api/v3/ping")
            self.assertIsNone(res)

    def test_5_oversized_response_rejected(self):
        client = SecureHttpClient(timeout=1.0, max_response_bytes=64)
        mock_resp = MagicMock()
        mock_resp.read.side_effect = [b"A" * 50, b"B" * 50, b""]
        mock_opener = MagicMock()
        mock_opener.open.return_value.__enter__.return_value = mock_resp

        with patch.object(client, "opener", mock_opener):
            raw, status, _ = client.fetch_raw("https://data-api.binance.vision/api/v3/ping")
            self.assertEqual(status, "PAYLOAD_TOO_LARGE")
            self.assertIsNone(raw)

    def test_6_cross_host_redirect_rejected(self):
        handler = SafeRedirectHandler()
        mock_req = MagicMock()
        # Redirect to unauthorized host must return None (refuse redirect)
        refused = handler.redirect_request(mock_req, None, 302, "Found", {}, "https://evil.com/redirect")
        self.assertIsNone(refused)

        # Redirect to insecure http must return None
        refused_http = handler.redirect_request(mock_req, None, 302, "Found", {}, "http://api.gateio.ws/api/v4/ping")
        self.assertIsNone(refused_http)

    def test_7_outlier_price_cannot_control_consensus(self):
        zk = ZeroKeyMarketData()
        # Mock candidate tickers where one is a corrupted outlier
        mock_binance = {"lastPrice": "85000.0", "volume": "1000", "quoteVolume": "85000000"}
        mock_gate = [{"last": "85100.0", "base_volume": "1000", "quote_volume": "85100000"}]
        mock_bybit = {"result": {"list": [{"lastPrice": "999999.0", "volume24h": "100", "turnover24h": "99999900"}]}}

        def mock_get(url, ttl_seconds=15.0):
            if "binance.vision" in url:
                return mock_binance
            if "gateio.ws" in url:
                return mock_gate
            if "bybit.com" in url:
                return mock_bybit
            return None

        with patch.object(zk, "_get_json", side_effect=mock_get):
            ticker = zk.get_spot_ticker("BTC")
            self.assertIsNotNone(ticker)
            # Consensus must use ~85000-85100, not the 999999 outlier
            self.assertLess(ticker["price"], 86000.0)
            self.assertGreater(ticker["price"], 84000.0)

    def test_8_gate_blocked_other_providers_continue(self):
        zk = ZeroKeyMarketData()

        def mock_get(url, ttl_seconds=15.0):
            if "gateio.ws" in url:
                return None  # Blocked by firewall
            if "binance.vision" in url and "ticker/24hr" in url:
                return {"lastPrice": "85200.0", "volume": "500", "quoteVolume": "42600000"}
            if "alternative.me" in url:
                return {"data": [{"value": "60", "value_classification": "Greed"}]}
            return None

        with patch.object(zk, "_get_json", side_effect=mock_get):
            ticker = zk.get_spot_ticker("BTC")
            self.assertIsNotNone(ticker)
            self.assertEqual(ticker["price"], 85200.0)
            self.assertIn("Binance", ticker["provider"])

    def test_9_no_secret_appears_in_provider_error(self):
        secret_url = "https://api.stlouisfed.org/fred/series?series_id=GNPCA&api_key=SECRET_TOKEN_12345&file_type=json"
        clean = sanitize_url(secret_url)
        self.assertNotIn("SECRET_TOKEN_12345", clean)
        self.assertIn("api_key=***", clean)


class TestCanonicalQuantEngine(unittest.TestCase):
    def setUp(self):
        self.engine = QuantEngine(hard_leverage_max=3)

    def test_10_risk_reward_gate_forces_wait_when_rr_below_1_5(self):
        spot_ticker = {
            "symbol": "BTC",
            "price": 89000.0,
            "high": 90000.0,
            "low": 80000.0,
            "volume": 50000000.0,
            "pct_change": 4.5,
            "provider": "Binance Vision",
            "is_cross_confirmed": True,
            "cross_exchange_sources": ["Binance Vision", "Gate.io"],
        }
        sentiment = {"value": 75, "classification": "Greed", "provider": "Alternative.me"}

        res_spot = self.engine.evaluate("BTC", spot_ticker, sentiment=sentiment, market_type="spot")
        self.assertIn(res_spot.decision, ("WAIT", "REDUCE"))
        self.assertNotEqual(res_spot.decision, "BUY")
        self.assertFalse(res_spot.rr_gate_passed)

        res_perp = self.engine.evaluate("BTC", spot_ticker, sentiment=sentiment, market_type="perpetual")
        self.assertIn(res_perp.decision, ("NO_TRADE", "SHORT"))
        self.assertNotEqual(res_perp.decision, "LONG")

    def test_11_order_book_imbalance_alone_cannot_force_trade(self):
        spot_ticker = {
            "symbol": "BTC",
            "price": 85000.0,
            "high": 85500.0,
            "low": 84500.0,
            "volume": 100000.0,
            "pct_change": 0.1,
            "provider": "Test Provider",
        }
        # Huge order book imbalance but no trade flow confirmation
        orderbook = {
            "imbalance": 0.85,
            "mid_price": 85000.0,
            "microprice": 85050.0,
            "microprice_dev_bps": 5.8,
            "spread_bps": 1.0,
        }
        trades = {"status": "DATA_GAP", "trade_flow_imbalance": 0.0}
        res = self.engine.evaluate("BTC", spot_ticker, orderbook=orderbook, trades=trades, market_type="spot")
        # Alone without independent family confirmation and RR setup, cannot produce BUY
        self.assertIn(res.decision, ("WAIT", "NO_TRADE"))
        self.assertNotEqual(res.decision, "BUY")

    def test_12_oi_funding_contradiction_penalizes_longs(self):
        spot_ticker = {
            "symbol": "BTC",
            "price": 85000.0,
            "high": 86000.0,
            "low": 84000.0,
            "volume": 80000000.0,
            "pct_change": 2.0,
            "provider": "Test Provider",
        }
        derivatives = {
            "symbol": "BTC",
            "mark_price": 85100.0,
            "index_price": 85000.0,
            "funding_rate": 0.0008,
            "funding_zscore": 2.5,
            "open_interest": 100000.0,
            "volume_24h": 500000000.0,
            "basis": 100.0,
            "provider": "Gate.io Futures",
        }
        res = self.engine.evaluate("BTC", spot_ticker, derivatives=derivatives, market_type="perpetual")
        self.assertIn("Crowded long", res.why.get("Derivatives", ""))
        self.assertNotEqual(res.decision, "LONG")

    def test_13_single_source_evidence_lowers_quality(self):
        spot_ticker = {
            "symbol": "BTC",
            "price": 85000.0,
            "high": 86000.0,
            "low": 84000.0,
            "volume": 10000000.0,
            "pct_change": 0.5,
            "provider": "Single Exchange",
            "is_cross_confirmed": False,
            "cross_exchange_sources": ["Single Exchange"],
        }
        res_single = self.engine.evaluate("BTC", spot_ticker)

        spot_ticker_multi = dict(spot_ticker)
        spot_ticker_multi["is_cross_confirmed"] = True
        spot_ticker_multi["cross_exchange_sources"] = ["Exchange A", "Exchange B"]
        res_multi = self.engine.evaluate("BTC", spot_ticker_multi)

        self.assertGreater(res_multi.composite_quality, res_single.composite_quality)

    def test_14_two_healthy_venues_confirm_signal(self):
        spot_ticker = {
            "symbol": "ETH",
            "price": 2700.0,
            "high": 2750.0,
            "low": 2650.0,
            "volume": 600000000.0,
            "quote_volume": 600000000.0,
            "pct_change": 1.5,
            "is_cross_confirmed": True,
            "cross_exchange_sources": ["Binance Vision (Public)", "Gate.io (Public)"],
            "price_dispersion_bps": 2.5,
        }
        trades = {"status": "OK", "trade_flow_imbalance": 0.45}
        orderbook = {"imbalance": 0.40, "microprice_dev_bps": 3.0}
        sentiment = {"value": 65, "classification": "Greed"}

        res = self.engine.evaluate("ETH", spot_ticker, trades=trades, orderbook=orderbook, sentiment=sentiment)
        self.assertEqual(res.confidence, "HIGH")
        self.assertGreaterEqual(res.composite_quality, 0.70)

    def test_conservative_leverage_ceiling_policy(self):
        self.assertEqual(self.engine.hard_leverage_max, 3)
        spot_ticker = {
            "symbol": "SOL",
            "price": 200.0,
            "high": 230.0,
            "low": 170.0,
            "volume": 20000000.0,
            "pct_change": -8.0,
            "provider": "Test Provider",
        }
        res = self.engine.evaluate("SOL", spot_ticker, market_type="perpetual")
        self.assertLessEqual(res.leverage_num, 3)
        if res.leverage_num > 0:
            self.assertIn("3x policy", res.leverage_ceiling)

    def test_categorical_confidence(self):
        spot_ticker = {
            "symbol": "BTC",
            "price": 85000.0,
            "high": 86000.0,
            "low": 84000.0,
            "volume": 50000000.0,
            "pct_change": 1.0,
            "provider": "Test Provider",
        }
        res = self.engine.evaluate("BTC", spot_ticker)
        self.assertIn(res.confidence, ("LOW", "MODERATE", "HIGH"))
        self.assertNotIn("%", res.confidence)

    def test_deterministic_capital_sizing(self):
        runner = CryptoResearchRunner()
        req = IntentRequest(
            intent="POSITION",
            asset="BTC",
            focus="capital",
            equity=1000.0,
            risk_pct=2.0,
            raw_query="position size btc equity 1000 risk 2%",
        )
        output = runner.execute(req)
        self.assertIn("CAPITAL & POSITION SIZING", output)
        self.assertIn("Account Equity         $1,000.00", output)
        self.assertIn("Risk Percentage        2.00%", output)
        self.assertIn("Max Risk Budget        $20.00", output)
        self.assertIn("Position Notional", output)
        self.assertIn("Margin Required", output)

    def test_session_followup_and_stop_words(self):
        from openbagus.intelligence.intent import IntentRouter, SessionState

        router = IntentRouter()
        session = SessionState()

        # 1. Five ini apa?
        r1 = router.parse("Five ini apa?", session)
        self.assertEqual(r1.asset, "FIVE")
        self.assertEqual(r1.request_type, "ASSET_ANALYSIS")
        session.last_asset = r1.asset

        # 2. Follow-up: kok risk dan TPnya nggk ada sih
        r2 = router.parse("kok risk dan TPnya nggk ada sih", session)
        self.assertEqual(r2.asset, "FIVE")
        self.assertEqual(r2.request_type, "EXPLAIN_LEVELS")

        # 3. Preference: jangan kasih sources
        r3 = router.parse("jangan kasih sources", session)
        self.assertEqual(r3.request_type, "PREFERENCE")
        self.assertEqual(r3.preference_action, "hide_sources")

        # 4. System Info: anda dijalankan di mana?
        r4 = router.parse("anda dijalankan di mana?", session)
        self.assertEqual(r4.request_type, "SYSTEM_INFO")

        # 5. Market Outlook: gimana prospek crypto
        r5 = router.parse("gimana prospek crypto", session)
        self.assertEqual(r5.request_type, "MARKET_OUTLOOK")

        # 6. Stop words protection: koin yang high 1 kuartal terakhir
        r6 = router.parse("koin yang high 1 kuartal terakhir", session)
        self.assertEqual(r6.request_type, "SCREEN")
        self.assertIsNone(r6.asset)  # Must NOT resolve "yang" or "high" to coin

        # 7. BUY btc?
        r7 = router.parse("BUY btc?", session)
        self.assertEqual(r7.asset, "BTC")
        self.assertEqual(r7.request_type, "POSITION")

    def test_candidate_long_short_and_quality_separation(self):
        spot_ticker = {
            "symbol": "BTC",
            "price": 85000.0,
            "high": 86000.0,
            "low": 84000.0,
            "volume": 60000000.0,
            "pct_change": 0.5,
            "provider": "Binance Vision",
            "is_cross_confirmed": True,
            "cross_exchange_sources": ["Binance Vision", "Gate.io"],
        }
        res = self.engine.evaluate("BTC", spot_ticker, market_type="perpetual")

        # Must have candidate long and candidate short evaluated
        self.assertIsNotNone(res.candidate_long)
        self.assertIsNotNone(res.candidate_short)
        self.assertEqual(res.candidate_long.direction, "LONG")
        self.assertEqual(res.candidate_short.direction, "SHORT")

        # Must separate Data Quality from Setup Quality
        self.assertIn(res.data_quality, ("HIGH", "MODERATE", "LOW"))
        self.assertIn(res.setup_quality, ("STRONG", "MODERATE", "INSUFFICIENT"))

        # Narrative must be a coherent multi-sentence string
        self.assertIsInstance(res.narrative, str)
        self.assertIn("BTC", res.narrative)
        self.assertGreater(len(res.narrative), 30)

    def test_no_trade_formatting_omits_empty_levels(self):
        spot_ticker = {
            "symbol": "BTC",
            "price": 85000.0,
            "high": 85500.0,
            "low": 84500.0,
            "volume": 200000.0,
            "pct_change": 0.05,
            "provider": "Binance Vision",
        }
        res = self.engine.evaluate("BTC", spot_ticker, market_type="perpetual")
        self.assertEqual(res.decision, "NO_TRADE")

        runner = CryptoResearchRunner()
        view = runner._render_section_25_view(res, market_type="perpetual", show_sources=False)

        # Must NOT contain empty level lines
        self.assertNotIn("Entry          -", view)
        self.assertNotIn("Stop           -", view)
        self.assertNotIn("TP1            -", view)
        self.assertNotIn("Reward:Risk    -", view)
        self.assertNotIn("Leverage       -", view)

        # Must contain Conditional setup and quality metrics without template headers
        self.assertIn("Conditional setup", view)
        self.assertIn("Data Quality", view)
        self.assertIn("Setup Quality", view)

        # Sources must be omitted when show_sources is False
        self.assertNotIn("Sources", view)

    def test_section_23_targeted_regression_cases(self):
        from openbagus.intelligence.intent import IntentRouter, SessionState

        router = IntentRouter()
        session = SessionState()

        # Timeframe alone does not select derivatives as the primary market.
        r1 = router.parse("gimana BTC h1?", session)
        self.assertEqual(r1.asset, "BTC")
        self.assertEqual(r1.market, "all")
        self.assertEqual(r1.timeframe, "H1")
        self.assertEqual(r1.request_type, "POSITION")

        # 2. kalau eth gimana open posisinya -> ETH position analysis
        r2 = router.parse("kalau eth gimana open posisinya", session)
        self.assertEqual(r2.asset, "ETH")
        self.assertEqual(r2.request_type, "POSITION")

        # 3. wkwk kok no trade semua -> FEEDBACK / follow-up, NOT an asset
        r3 = router.parse("wkwk kok no trade semua", session)
        self.assertEqual(r3.request_type, "FEEDBACK")
        self.assertIsNone(r3.asset)

        # 4. tolol nih -> FEEDBACK, NOT TOLOL token
        r4 = router.parse("tolol nih", session)
        self.assertEqual(r4.request_type, "FEEDBACK")
        self.assertIsNone(r4.asset)

        # 5. Long sentence containing "AI lokal" -> NOT AI category
        long_query = "Saya ingin tahu apakah sistem ini menggunakan model AI lokal atau cloud provider?"
        r5 = router.parse(long_query, session)
        self.assertNotEqual(r5.request_type, "CATEGORY")
        self.assertIsNone(r5.category)

        # 6. near -> NEAR asset
        r6 = router.parse("near", session)
        self.assertEqual(r6.asset, "NEAR")

        # 7. mana hernesnyaaaaaa???? -> HARNESS / SYSTEM_INFO
        r7 = router.parse("mana hernesnyaaaaaa????", session)
        self.assertEqual(r7.request_type, "HARNESS")
        self.assertEqual(r7.intent, "SYSTEM_INFO")

        # 8. Privacy -> category only when appropriate
        r8 = router.parse("Privacy", session)
        self.assertEqual(r8.request_type, "CATEGORY")
        self.assertEqual(r8.category, "Privacy")

    def test_section_24_decision_quality_and_validation_scenarios(self):
        spot_ticker = {
            "symbol": "BTC",
            "price": 85000.0,
            "high": 86000.0,
            "low": 84000.0,
            "volume": 60000000.0,
            "pct_change": 0.5,
            "provider": "Binance Vision",
            "is_cross_confirmed": True,
            "cross_exchange_sources": ["Binance Vision", "Gate.io"],
            "cross_venue_quotes": {"Binance Vision": {"price": 85010.0}, "Gate.io": {"price": 85030.0}},
        }
        klines = [
            {"time": i, "open": 84500.0 + i * 10, "high": 85200.0 + i * 10, "low": 84300.0 + i * 10, "close": 85000.0 + i * 10, "volume": 1000.0}
            for i in range(30)
        ]
        res = self.engine.evaluate("BTC", spot_ticker, klines=klines, market_type="perpetual", timeframe="H1")

        # Requested timeframe is honored
        self.assertEqual(res.timeframe, "H1")

        # Current decision generated
        self.assertIn(res.decision, ("LONG", "SHORT", "NO_TRADE"))

        # Both bullish and bearish validation scenarios generated with real conditions
        self.assertIsNotNone(res.bullish_validation)
        self.assertIsNotNone(res.bearish_validation)
        self.assertEqual(res.bullish_validation.direction, "LONG")
        self.assertEqual(res.bearish_validation.direction, "SHORT")
        self.assertGreaterEqual(res.bullish_validation.reward_risk, 1.5)
        self.assertGreaterEqual(res.bearish_validation.reward_risk, 1.5)
        self.assertIn("H1", res.bullish_validation.trigger_condition)
        self.assertIn("H1", res.bearish_validation.trigger_condition)

        # Factor contributions calculated
        self.assertIsInstance(res.factor_contributions, dict)
        self.assertIn("Trend / Momentum", res.factor_contributions)
        self.assertIn("Microstructure", res.factor_contributions)
        self.assertIn("Cross-Venue", res.factor_contributions)

        # Narrative uses actual evidence (trader note style)
        self.assertIn("BTC", res.narrative)
        self.assertIn("H1", res.narrative)
        self.assertNotIn("menurut AI", res.narrative)
        self.assertNotIn("as an AI", res.narrative)

        # Test ETH on H4
        eth_ticker = dict(spot_ticker, symbol="ETH", price=2700.0, high=2750.0, low=2650.0)
        res_eth = self.engine.evaluate("ETH", eth_ticker, market_type="perpetual", timeframe="H4")
        self.assertEqual(res_eth.timeframe, "H4")
        self.assertIn("H4", res_eth.bullish_validation.trigger_condition)

    def test_section_25_arbitrage_cross_venue_dislocation(self):
        # 1. Healthy venues with normal dispersion
        spot_ticker = {
            "symbol": "BTC",
            "price": 85000.0,
            "cross_venue_quotes": {
                "Binance Vision": {"price": 85000.0, "bid": 84990.0, "ask": 85010.0},
                "Gate.io": {"price": 85020.0, "bid": 85010.0, "ask": 85030.0},
            },
        }
        res = self.engine.evaluate("BTC", spot_ticker)
        cv = res.cross_venue_dislocation
        self.assertTrue(cv.get("available"))
        self.assertEqual(cv.get("dislocation_status"), "NORMAL")
        self.assertLess(cv.get("dispersion_pct"), 0.15)
        self.assertLess(cv.get("estimated_net_spread_pct"), 0.0)  # Costs prevent false profit claim

        # 2. Elevated / Dislocated venues
        spot_ticker_stress = {
            "symbol": "BTC",
            "price": 85000.0,
            "cross_venue_quotes": {
                "Binance Vision": {"price": 85000.0},
                "Gate.io": {"price": 85600.0},
            },
        }
        res_stress = self.engine.evaluate("BTC", spot_ticker_stress)
        cv_stress = res_stress.cross_venue_dislocation
        self.assertEqual(cv_stress.get("dislocation_status"), "HIGH")
        self.assertGreaterEqual(cv_stress.get("dispersion_pct"), 0.50)

        # 3. Dislocation alone never creates LONG or SHORT
        ev_disloc, _ = self.engine._eval_cross_exchange_dislocation(spot_ticker_stress, 85000.0)
        self.assertEqual(ev_disloc.direction_score, 0.0)

    def test_section_26_patterns_and_fibonacci_evidence(self):
        # 1. Bullish Engulfing pattern
        klines_engulf = [
            {"open": 100.0, "high": 101.0, "low": 98.0, "close": 98.5, "volume": 100.0},
            {"open": 98.5, "high": 99.0, "low": 93.0, "close": 94.0, "volume": 120.0},  # red
            {"open": 93.5, "high": 103.0, "low": 93.0, "close": 102.5, "volume": 350.0},  # green engulfs
        ]
        ev_pat, pats = self.engine._eval_chart_patterns(klines_engulf, 102.5, 98.0, 93.0, 103.0, 5.0)
        self.assertTrue(any(p["pattern"] == "Bullish Engulfing" for p in pats))
        self.assertGreater(ev_pat.direction_score, 0.20)

        # 2. Hammer pattern
        klines_hammer = [
            {"open": 100.0, "high": 101.0, "low": 95.0, "close": 96.0, "volume": 100.0},
            {"open": 95.5, "high": 96.0, "low": 88.0, "close": 95.8, "volume": 300.0},  # long lower shadow
        ]
        ev_ham, ham_pats = self.engine._eval_chart_patterns(klines_hammer, 95.8, 95.0, 90.0, 100.0, 5.0)
        self.assertTrue(any(p["pattern"] == "Hammer" for p in ham_pats))
        self.assertGreater(ev_ham.direction_score, 0.15)

        # 3. Random bars do not falsely produce strong pattern signal
        klines_flat = [
            {"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.1, "volume": 50.0}
            for _ in range(10)
        ]
        ev_flat, flat_pats = self.engine._eval_chart_patterns(klines_flat, 100.1, 100.0, 95.0, 105.0, 2.0)
        self.assertEqual(len(flat_pats), 0)
        self.assertEqual(ev_flat.direction_score, 0.0)

        # 4. Fibonacci confluence
        # Swing from 50 to 100 (span 50). Fib 0.618 is 100 - 0.618*50 = 69.1. Price at 69.15.
        klines_fib = [
            {"high": 50.0 + (i * 2.0), "low": 50.0 + (i * 2.0), "close": 50.0 + (i * 2.0)}
            for i in range(26)
        ]
        ev_fib, fib_d = self.engine._eval_fibonacci_confluence(klines_fib, 69.15, 75.0, 60.0, 90.0)
        self.assertIn("0.618", fib_d.get("confluence", ""))
        self.assertGreater(ev_fib.direction_score, 0.0)

        # Fibonacci alone cannot create a trade
        fib_only_ticker = {"symbol": "SOL", "price": 69.2, "high": 72.0, "low": 66.0, "volume": 1000.0}
        res_fib = self.engine.evaluate("SOL", fib_only_ticker, klines=klines_fib, market_type="perpetual")
        self.assertIn(res_fib.decision, ("WAIT", "NO_TRADE"))

    def test_harness_session_state_and_clear(self):
        from openbagus.intelligence.intent import SessionState

        session = SessionState()
        session.last_asset = "NEAR"
        session.timeframe = "H4"
        session.market_type = "SPOT"
        session.show_sources = True

        display = session.status_display()
        self.assertIn("OpenBagus Harness", display)
        self.assertIn("Current Asset   NEAR", display)
        self.assertIn("Timeframe       H4", display)
        self.assertIn("Market          SPOT", display)
        self.assertIn("Sources         ON", display)
        self.assertIn("Clear on Exit   YES", display)

        # Test clear
        session.clear()
        self.assertIsNone(session.last_asset)
        self.assertEqual(session.timeframe, "H1")
        self.assertEqual(session.market_type, "PERPETUAL")


if __name__ == "__main__":
    unittest.main()
