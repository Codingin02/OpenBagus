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


if __name__ == "__main__":
    unittest.main()
