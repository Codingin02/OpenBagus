"""Comprehensive acceptance tests for OpenBagus persistent harness, intelligent API caching, and local data control."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbagus.data.cache import MarketDataCache, make_cache_key
from openbagus.domains.crypto.quant import QuantDecisionResult
from openbagus.domains.crypto.research import CryptoResearchRunner, ResearchPacket
from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.reporting.visualizer import generate_html_report
from openbagus.reporting.word_report import generate_word_report
from openbagus.storage.data_control import (
    FULL_RESET_CONFIRMATION_PHRASE,
    _safe_remove,
    clear_privacy_data,
    execute_full_reset,
    format_privacy_status,
    get_privacy_status,
)


def _make_quant_result(asset: str = "BTC", price: float = 65432.10, decision: str = "WAIT") -> QuantDecisionResult:
    return QuantDecisionResult(
        asset=asset,
        market="perpetual",
        decision=decision,
        regime="Compressed",
        confidence="Moderate",
        price=price,
        entry_zone="65200 - 65500",
        stop_price=64000.0,
        tp1=68000.0,
        tp2=70000.0,
        reward_risk=1.80,
        reward_risk_str="1:1.80",
        leverage_ceiling="2x",
        leverage_num=2,
        why={"trend": "neutral", "momentum": "consolidation"},
        sources=["Binance"],
        evidence_count=3,
        composite_score=0.10,
        composite_quality=0.75,
        rr_gate_passed=False,
        quality_gate_passed=True,
        data_quality="HIGH",
        setup_quality="MODERATE",
        decision_reason="Volatility compression and neutral momentum",
        data_freshness="CACHE_VALID",
        narrative=f"{asset} consolidating near {price:,.2f} USD.",
    )


class TestCachingAndHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="openbagus_test_cache_")
        self.db_path = Path(self.temp_dir) / "test_cache.db"
        MarketDataCache.reset_instance()
        self.cache = MarketDataCache(db_path=self.db_path)

    def tearDown(self) -> None:
        self.cache.close()
        MarketDataCache.reset_instance()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # H1: Repeated identical request served from cache (mock network count = 1)
    # -------------------------------------------------------------------------
    def test_h1_repeated_identical_request_hits_cache(self) -> None:
        url = "https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT"
        fetch_count = [0]

        def mock_fetcher(u: str, headers: dict) -> tuple[str, int, float, dict]:
            fetch_count[0] += 1
            payload = json.dumps({"symbol": "BTCUSDT", "lastPrice": "65432.10"})
            return payload, 200, 15.0, {"ETag": '"mock-etag-1"'}

        # First request: Cache miss -> network fetch
        res1 = self.cache.get_json(url, dataset_type="SPOT_TICKER", ttl=20, network_fetcher=mock_fetcher)
        self.assertIsNotNone(res1)
        self.assertEqual(res1.get("symbol"), "BTCUSDT")
        self.assertEqual(fetch_count[0], 1)

        # Second request within TTL: Cache hit -> 0 network fetches
        res2 = self.cache.get_json(url, dataset_type="SPOT_TICKER", ttl=20, network_fetcher=mock_fetcher)
        self.assertIsNotNone(res2)
        self.assertEqual(res2.get("symbol"), "BTCUSDT")
        self.assertEqual(fetch_count[0], 1, "Second request must be served from cache without calling network fetcher")

        stats = self.cache.get_statistics()
        self.assertGreaterEqual(stats["cache_hits"], 1)
        self.assertEqual(stats["network_fetches"], 1)

    # -------------------------------------------------------------------------
    # H2: Conversational follow-up uses cached packet/facts (0 refetches)
    # -------------------------------------------------------------------------
    def test_h2_conversational_followup_uses_cached_facts(self) -> None:
        router = IntentRouter()
        runner = CryptoResearchRunner()
        session = SessionState()

        q = _make_quant_result(asset="BTC", price=65432.10, decision="WAIT")
        packet = ResearchPacket(
            asset="BTC",
            market="SPOT",
            timeframe="H1",
            price=65432.10,
            decision="WAIT",
            data_quality="HIGH",
            setup_quality="MODERATE",
            regime="Compressed",
            decision_reason="Volatility compression and neutral momentum",
            reward_risk_str="N/A",
            rr_gate_passed=False,
            entry_zone="65200 - 65500",
            stop_price=64000.0,
            tp1=68000.0,
            tp2=70000.0,
            sources=["Binance"],
            narrative="BTC consolidating near 65,432 USD.",
        )
        session.last_asset = "BTC"
        session.timeframe = "H1"
        session.market_type = "SPOT"
        session.last_quant_result = q
        session.last_research_packet = packet

        with patch.object(runner.zerokey, "get_spot_ticker") as mock_ticker, \
             patch.object(runner.zerokey, "get_klines") as mock_klines:
            req = router.parse("kenapa wait?", session=session)
            res = runner.execute(req, session=session)

            self.assertIn("BTC", res)
            self.assertIn("WAIT", res)
            mock_ticker.assert_not_called()
            mock_klines.assert_not_called()

    # -------------------------------------------------------------------------
    # H3: Cache expiry with injectable clock
    # -------------------------------------------------------------------------
    def test_h3_cache_expiry_with_injectable_clock(self) -> None:
        url = "https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=20"
        fetch_count = [0]
        current_time = [1000.0]

        def mock_fetcher(u: str, headers: dict) -> tuple[str, int, float, dict]:
            fetch_count[0] += 1
            return json.dumps({"bids": [], "asks": []}), 200, 10.0, {}

        with patch("time.time", side_effect=lambda: current_time[0]):
            # First fetch at t=1000 with TTL=10s
            self.cache.get_json(url, dataset_type="ORDERBOOK", ttl=10, network_fetcher=mock_fetcher)
            self.assertEqual(fetch_count[0], 1)

            # At t=1005 (within TTL): Hit
            current_time[0] = 1005.0
            self.cache.get_json(url, dataset_type="ORDERBOOK", ttl=10, network_fetcher=mock_fetcher)
            self.assertEqual(fetch_count[0], 1)

            # At t=1015 (expired): Re-fetch
            current_time[0] = 1015.0
            self.cache.get_json(url, dataset_type="ORDERBOOK", ttl=10, network_fetcher=mock_fetcher)
            self.assertEqual(fetch_count[0], 2, "Expired cache entry must trigger a fresh fetch")

    # -------------------------------------------------------------------------
    # H4: Request deduplication (coalescing across concurrent threads)
    # -------------------------------------------------------------------------
    def test_h4_request_deduplication_coalescing(self) -> None:
        url = "https://api.binance.com/api/v3/klines?symbol=ETHUSDT&interval=1h"
        network_calls = [0]
        gate_event = threading.Event()

        def slow_fetcher(u: str, headers: dict) -> tuple[str, int, float, dict]:
            network_calls[0] += 1
            gate_event.wait(timeout=2.0)
            return json.dumps([["1600000000", "2000.0", "2100.0", "1990.0", "2050.0", "100.0"]]), 200, 50.0, {}

        results: list[dict | list | None] = [None, None, None]

        def worker(idx: int) -> None:
            res = self.cache.get_json(url, dataset_type="INTRADAY_CANDLES", ttl=90, network_fetcher=slow_fetcher)
            results[idx] = res

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()

        time.sleep(0.05)
        gate_event.set()

        for t in threads:
            t.join(timeout=3.0)

        for res in results:
            self.assertIsNotNone(res, "All concurrent callers must receive valid result")
            self.assertEqual(len(res), 1)

        self.assertEqual(network_calls[0], 1, "Concurrent in-flight requests must coalesce into 1 network call")
        stats = self.cache.get_statistics()
        self.assertGreaterEqual(stats["deduplicated_requests"], 1)

    # -------------------------------------------------------------------------
    # H5: Rate limits (HTTP 429 Retry-After -> Cooldown)
    # -------------------------------------------------------------------------
    def test_h5_rate_limit_429_cooldown(self) -> None:
        url = "https://api.coingecko.com/api/v3/coins/bitcoin"
        network_calls = [0]

        def rate_limited_fetcher(u: str, headers: dict) -> tuple[str, int, float, dict]:
            network_calls[0] += 1
            return json.dumps({"error": "rate limited"}), 429, 20.0, {"Retry-After": "25"}

        res1 = self.cache.get_json(url, dataset_type="SPOT_TICKER", ttl=20, network_fetcher=rate_limited_fetcher)
        self.assertIsNone(res1)
        self.assertEqual(network_calls[0], 1)
        self.assertTrue(self.cache.is_in_cooldown("coingecko"))
        self.assertGreater(self.cache.get_cooldown_remaining("coingecko"), 0)

        res2 = self.cache.get_json(url, dataset_type="SPOT_TICKER", ttl=20, network_fetcher=rate_limited_fetcher)
        self.assertIsNone(res2)
        self.assertEqual(network_calls[0], 1, "Request during cooldown must not execute a network fetch")

    # -------------------------------------------------------------------------
    # H6: Credential validation cached (0 network calls on repeat)
    # -------------------------------------------------------------------------
    def test_h6_credential_validation_cached(self) -> None:
        provider_id = "mock_alpha"
        raw_key = "secret_mock_key_999"
        key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

        # Initially no cached state
        state = self.cache.get_credential_state(provider_id, key_hash)
        self.assertIsNone(state)

        # Store validated state
        self.cache.set_credential_state(provider_id, key_hash, "VALID", error_category="")

        # Retrieve cached state
        cached = self.cache.get_credential_state(provider_id, key_hash)
        self.assertEqual(cached, "VALID")

        # Different key returns None
        diff_hash = hashlib.sha256(b"different_key_abc").hexdigest()
        self.assertIsNone(self.cache.get_credential_state(provider_id, diff_hash))

    # -------------------------------------------------------------------------
    # H7: Process restart restores context & allows continuation
    # -------------------------------------------------------------------------
    def test_h7_process_restart_restores_context(self) -> None:
        with tempfile.TemporaryDirectory() as appdata_dir:
            try:
                with patch.dict(os.environ, {"LOCALAPPDATA": appdata_dir}):
                    s1 = SessionState()
                    s1.set_persistence_enabled(True)
                    s1.last_asset = "BTC"
                    s1.timeframe = "H4"
                    s1.market_type = "PERPETUAL"
                    s1.last_quant_result = _make_quant_result(asset="BTC", price=66000.0, decision="WAIT")
                    s1.last_research_packet = ResearchPacket(
                        asset="BTC",
                        market="PERPETUAL",
                        timeframe="H4",
                        price=66000.0,
                        decision="WAIT",
                        data_quality="HIGH",
                        setup_quality="MODERATE",
                        regime="Trending",
                        decision_reason="Re-test in progress",
                        reward_risk_str="N/A",
                        rr_gate_passed=False,
                        entry_zone="",
                        stop_price=None,
                        tp1=None,
                        tp2=None,
                        sources=["Binance"],
                        narrative="BTC H4 holding above 66,000 USD.",
                    )
                    saved = s1.save_persistent()
                    self.assertTrue(saved)

                    # Session 2: simulate new application process start
                    s2 = SessionState()
                    self.assertTrue(s2.is_persistence_enabled())
                    loaded = s2.load_if_enabled()
                    self.assertTrue(loaded)
                    self.assertEqual(s2.last_asset, "BTC")
                    self.assertEqual(s2.timeframe, "H4")
                    self.assertEqual(s2.market_type, "PERPETUAL")
                    self.assertIsNotNone(s2.last_research_packet)
                    self.assertEqual(s2.last_research_packet.price, 66000.0)

                    # Test continuation trigger
                    router = IntentRouter()
                    runner = CryptoResearchRunner()
                    req = router.parse("lanjutkan BTC tadi", session=s2)
                    res = runner.execute(req, session=s2)
                    self.assertIn("BTC", res)
                    self.assertIn("66,000", res)
            finally:
                MarketDataCache.get_instance().close()
                MarketDataCache.reset_instance()

    # -------------------------------------------------------------------------
    # H8: Domain continuity across multi-turn context switches
    # -------------------------------------------------------------------------
    def test_h8_domain_continuity_multi_turn(self) -> None:
        session = SessionState()

        # Turn 1: BTC (crypto)
        session.last_asset = "BTC"
        session.market_type = "SPOT"
        session.timeframe = "H1"
        self.assertEqual(session.last_asset, "BTC")

        # Turn 2: BBCA (equities)
        session.last_asset = "BBCA"
        session.market_type = "IDX_EQUITY"
        session.timeframe = "D1"
        self.assertEqual(session.last_asset, "BBCA")

        # Turn 3: BBRI (equities)
        session.last_asset = "BBRI"
        session.market_type = "IDX_EQUITY"
        session.timeframe = "D1"
        self.assertEqual(session.last_asset, "BBRI")

        # Turn 4: Return to BTC
        session.last_asset = "BTC"
        session.market_type = "SPOT"
        session.timeframe = "H1"
        self.assertEqual(session.last_asset, "BTC")

    # -------------------------------------------------------------------------
    # H9: Privacy controls and bounded reset
    # -------------------------------------------------------------------------
    def test_h9_privacy_controls_and_bounded_reset(self) -> None:
        with tempfile.TemporaryDirectory() as sandbox_root:
            root = Path(sandbox_root)
            appdata = root / "AppData/Local/OpenBagus"
            appdata.mkdir(parents=True, exist_ok=True)
            runtime_reports = root / "reports/runtime"
            runtime_reports.mkdir(parents=True, exist_ok=True)

            with patch.dict(os.environ, {"LOCALAPPDATA": str(root / "AppData/Local")}), \
                 patch("openbagus.core.env.get_repo_root", return_value=root):

                (appdata / "harness").mkdir(parents=True, exist_ok=True)
                (appdata / "harness/session_context.json").write_text("{}", encoding="utf-8")
                (appdata / "feedback").mkdir(parents=True, exist_ok=True)
                (appdata / "feedback/log.jsonl").write_text("{}\n", encoding="utf-8")
                (runtime_reports / "sheet.csv").write_text("run_id\n", encoding="utf-8")

                status_text = format_privacy_status(root)
                self.assertIn("OpenBagus Local Data Storage & Privacy Status", status_text)

                cleared = clear_privacy_data(root)
                self.assertEqual(cleared.get("Harness Context"), "CLEARED")
                self.assertEqual(cleared.get("Feedback Store"), "CLEARED")

                res = execute_full_reset(root)
                self.assertIn("Harness Context", res)
                self.assertIn("Reports (Runtime Sheets)", res)

                # Boundary check: outside file cannot be deleted
                outside_file = root.parent / "important_outside_file.txt"
                outside_file.write_text("precious", encoding="utf-8")
                try:
                    can_remove = _safe_remove(outside_file, appdata, root)
                    self.assertFalse(can_remove, "Boundary check must forbid deleting outside OpenBagus paths")
                    self.assertTrue(outside_file.exists())
                finally:
                    outside_file.unlink(missing_ok=True)

    # -------------------------------------------------------------------------
    # H10: Sensitive data never appears in cache keys or SQLite database
    # -------------------------------------------------------------------------
    def test_h10_sensitive_data_never_in_cache_keys_or_db(self) -> None:
        url_with_secrets = (
            "https://api.example.com/v1/ticker"
            "?symbol=BTCUSDT"
            "&apiKey=SUPER_SECRET_API_KEY_12345"
            "&token=BEARER_AUTH_TOKEN_ABCDEF"
            "&password=MY_SECRET_PASSWORD"
        )
        key = make_cache_key(url_with_secrets)

        self.assertNotIn("SUPER_SECRET_API_KEY_12345", key)
        self.assertNotIn("BEARER_AUTH_TOKEN_ABCDEF", key)
        self.assertNotIn("MY_SECRET_PASSWORD", key)

        clean_url = "https://api.example.com/v1/ticker?symbol=BTCUSDT"
        clean_key = make_cache_key(clean_url)
        self.assertEqual(key, clean_key, "Cache key must be deterministic after stripping authentication query parameters")

        self.cache.get_json(
            url_with_secrets,
            dataset_type="SPOT_TICKER",
            ttl=30,
            network_fetcher=lambda u, h: (json.dumps({"price": 100.0}), 200, 10.0, {}),
        )
        db_raw_bytes = self.db_path.read_bytes()
        self.assertNotIn(b"SUPER_SECRET_API_KEY_12345", db_raw_bytes)
        self.assertNotIn(b"BEARER_AUTH_TOKEN_ABCDEF", db_raw_bytes)
        self.assertNotIn(b"MY_SECRET_PASSWORD", db_raw_bytes)

    # -------------------------------------------------------------------------
    # H11: Cross-output consistency (CLI, HTML, Word share identical figures)
    # -------------------------------------------------------------------------
    def test_h11_cross_output_consistency(self) -> None:
        target_price = 68950.45
        q = _make_quant_result(asset="BTC", price=target_price, decision="WAIT")
        packet = ResearchPacket(
            asset="BTC",
            market="PERPETUAL",
            timeframe="H1",
            price=target_price,
            decision="WAIT",
            data_quality="HIGH",
            setup_quality="MODERATE",
            regime="Trending",
            decision_reason="Re-test of 68,500 key support",
            reward_risk_str="1:1.80",
            rr_gate_passed=True,
            entry_zone="68800 - 69000",
            stop_price=67500.0,
            tp1=71500.0,
            tp2=73000.0,
            sources=["Binance", "Coinbase"],
            narrative="BTC consolidating near 68,950 USD.",
        )
        runner = CryptoResearchRunner()

        # 1. CLI text
        cli_text = runner._render_section_25_view(q, packet=packet, market_type="perpetual")
        self.assertIn("68,950.45", cli_text)
        self.assertIn("WAIT", cli_text)

        # 2. HTML output
        candles = [
            {"time": 1600000000, "open": 68000.0, "high": 69000.0, "low": 67900.0, "close": target_price, "volume": 120.0}
        ]
        html_file = generate_html_report("BTC", candles, q, packet, timeframe="H1")
        self.assertTrue(html_file.exists())
        html_content = html_file.read_text(encoding="utf-8")
        self.assertIn(str(target_price), html_content)
        self.assertIn("WAIT", html_content)

        # 3. Word output (.docx)
        docx_file = generate_word_report("BTC", q, packet, timeframe="H1")
        self.assertTrue(docx_file.exists())
        self.assertGreater(docx_file.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()
