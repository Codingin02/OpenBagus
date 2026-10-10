"""OpenBagus Autonomous Intelligence & Native Delivery Acceptance Test Suite (Section M).

Tests:
M1: Financial Data Freshness & Historical Snapshot Retention
M2: Cache Isolation & Credential Partitioning
M3: Bounded L1 LRU Eviction & Memory Tracking
M4: HTTP Standards Compliance (no-store, private, 304 revalidation)
M5: Safe Deletion, Boundary Verification & Windows DPAPI Encryption
M6: Persistent Harness Multi-Turn Context Continuity
M7: Official Gmail OAuth Desktop Flow & Automatic Token Refresh
M8: Gmail RFC 2822 Base64url Delivery
M9: Personal WhatsApp Native Compose & Honest Status Semantics
M10: Experimental Multi-Device QR (Baileys) Safety Disclosures & Default Disabled State
M11: Controlled Autonomous Monitoring & Closed-Candle Alert Deduplication
M12: Monitor Error Recovery & Quiet-Hours Suppression
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbagus.data.cache import MarketDataCache, make_cache_key
from openbagus.delivery.gmail import (
    GMAIL_SEND_SCOPE,
    GmailOAuthConfig,
    GmailOAuthTransport,
    GmailTokenStore,
)
from openbagus.delivery.whatsapp_personal import (
    STATUS_COMPOSE_OPENED,
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    BaileysExperimentalTransport,
    PersonalWhatsAppConfig,
    PersonalWhatsAppTransport,
)
from openbagus.domains.crypto.quant import QuantDecisionResult
from openbagus.domains.crypto.research import ResearchPacket
from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.monitoring.autonomous import (
    AlertEvent,
    AutonomousMonitorStore,
    AutonomousMonitoringRuntime,
    MonitoringRule,
)
from openbagus.storage.data_control import (
    _safe_remove,
    clear_privacy_data,
    decrypt_secret_dpapi,
    encrypt_secret_dpapi,
    execute_full_reset,
)


class TestAutonomousAndDelivery(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.appdata = self.root / "AppData/Local/OpenBagus"
        self.appdata.mkdir(parents=True, exist_ok=True)
        self.reports = self.root / "reports/runtime"
        self.reports.mkdir(parents=True, exist_ok=True)

        self.env_patcher = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "AppData/Local")})
        self.env_patcher.start()

    def tearDown(self) -> None:
        self.env_patcher.stop()
        try:
            self.tmp.cleanup()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # M1: Financial Data Freshness & Historical Snapshot Retention
    # -------------------------------------------------------------------------
    def test_m1_data_freshness_and_historical_snapshot(self) -> None:
        s1 = SessionState()
        s1.set_persistence_enabled(True)
        s1.last_asset = "BTC"
        s1.timeframe = "H1"
        s1.last_research_at = "2026-10-10T12:00:00Z"
        s1.last_research_packet = ResearchPacket(
            asset="BTC",
            market="SPOT",
            timeframe="H1",
            price=68000.0,
            decision="BUY",
            data_quality="HIGH",
            setup_quality="STRONG",
            data_freshness="FRESH",
            price_as_of="2026-10-10T12:00:00Z",
        )
        s1.last_quant_result = QuantDecisionResult(
            asset="BTC",
            market="spot",
            decision="BUY",
            regime="Markup",
            confidence="HIGH",
            price=68000.0,
            entry_zone="68000",
            stop_price=66000.0,
            tp1=72000.0,
            tp2=75000.0,
            reward_risk=2.5,
            reward_risk_str="1:2.5",
            leverage_ceiling="2x",
            leverage_num=2,
            why={"Trend": "Bullish"},
            sources=["Binance"],
            evidence_count=3,
            composite_score=0.85,
            composite_quality=0.80,
            rr_gate_passed=True,
            quality_gate_passed=True,
            data_freshness="FRESH",
        )

        # Save session
        save_path = self.appdata / "harness/session_context.json"
        s1.save_persistent(save_path)

        # Simulate new application session startup
        s2 = SessionState()
        s2.load_persistent(save_path)

        # Verified requirement: Restored packet is explicitly HISTORICAL_SNAPSHOT
        self.assertEqual(s2.last_research_packet.data_freshness, "HISTORICAL_SNAPSHOT")
        self.assertEqual(s2.last_quant_result.data_freshness, "HISTORICAL_SNAPSHOT")
        self.assertEqual(s2.last_research_packet.price, 68000.0)

        # Actionable freshness gate: Historical snapshot cannot be used as fresh evidence
        self.assertFalse(s2.is_actionable_fresh(max_age_seconds=300.0))

    # -------------------------------------------------------------------------
    # M2: Cache Isolation & Credential Partitioning
    # -------------------------------------------------------------------------
    def test_m2_cache_isolation_and_credential_partitioning(self) -> None:
        url = "https://api.exchange.com/v1/user/balances"

        # Different credentials produce completely distinct cache keys
        key_user_a = make_cache_key(url, auth_identity="account_alpha_key_111")
        key_user_b = make_cache_key(url, auth_identity="account_beta_key_222")
        key_public = make_cache_key(url)

        self.assertNotEqual(key_user_a, key_user_b)
        self.assertNotEqual(key_user_a, key_public)

        # Secrets in query params are stripped and never appear in keys
        url_with_secret = f"{url}?apiKey=SUPER_SECRET_TOKEN_XYZ&account=alpha"
        clean_key = make_cache_key(f"{url}?account=alpha")
        sanitized_key = make_cache_key(url_with_secret)
        self.assertEqual(sanitized_key, clean_key)
        self.assertNotIn("SUPER_SECRET_TOKEN_XYZ", sanitized_key)

    # -------------------------------------------------------------------------
    # M3: Bounded L1 LRU Eviction & Memory Tracking
    # -------------------------------------------------------------------------
    def test_m3_bounded_l1_lru_eviction(self) -> None:
        db_path = self.appdata / "cache/market_cache.db"
        cache = MarketDataCache(db_path=db_path, max_l1_entries=3, max_l1_bytes=5000)

        try:
            # Insert 3 entries
            for i in range(1, 4):
                cache.get_json(
                    f"https://api.data.com/item{i}",
                    ttl=60,
                    network_fetcher=lambda u, h: (json.dumps({"id": i, "val": "x" * 50}), 200, 10.0, {}),
                )
            self.assertEqual(len(cache._memory_cache), 3)

            # Insert 4th entry -> forces eviction of oldest entry (item1)
            cache.get_json(
                "https://api.data.com/item4",
                ttl=60,
                network_fetcher=lambda u, h: (json.dumps({"id": 4, "val": "x" * 50}), 200, 10.0, {}),
            )
            self.assertEqual(len(cache._memory_cache), 3)
            k1 = make_cache_key("https://api.data.com/item1")
            k4 = make_cache_key("https://api.data.com/item4")
            self.assertNotIn(k1, cache._memory_cache, "Oldest entry item1 must be evicted from L1")
            self.assertIn(k4, cache._memory_cache, "Newest entry item4 must be present in L1")
        finally:
            cache.close()

    # -------------------------------------------------------------------------
    # M4: HTTP Standards Compliance (no-store, private, 304 revalidation)
    # -------------------------------------------------------------------------
    def test_m4_http_standards_compliance(self) -> None:
        db_path = self.appdata / "cache/market_cache.db"
        cache = MarketDataCache(db_path=db_path)

        try:
            # 1. Cache-Control: no-store skips caching
            url_no_store = "https://api.data.com/realtime-stream"
            res1 = cache.get_json(
                url_no_store,
                network_fetcher=lambda u, h: (
                    json.dumps({"price": 100.0}),
                    200,
                    5.0,
                    {"Cache-Control": "no-store, no-cache"},
                ),
            )
            self.assertIsNotNone(res1)
            # Second call must re-fetch because no-store was not stored
            fetch_count: list[int] = []
            cache.get_json(
                url_no_store,
                network_fetcher=lambda u, h: (fetch_count.append(1), json.dumps({"price": 101.0}), 200, 5.0, {})[1:],
            )
            self.assertEqual(len(fetch_count), 1)

            # 2. HTTP 304 Revalidation preserves original payload
            url_reval = "https://api.data.com/etag-test"
            cache.get_json(
                url_reval,
                ttl=1,  # 1 second TTL
                network_fetcher=lambda u, h: (json.dumps({"ticker": "ETH", "price": 2500.0}), 200, 10.0, {"ETag": '"v1"'}),
            )
            time.sleep(1.1)  # Expire entry

            # Revalidate via 304 Not Modified
            res_304 = cache.get_json(
                url_reval,
                ttl=60,
                network_fetcher=lambda u, h: ("", 304, 5.0, {"ETag": '"v1"'}),
            )
            self.assertIsNotNone(res_304)
            self.assertEqual(res_304.get("price"), 2500.0)
        finally:
            cache.close()

    # -------------------------------------------------------------------------
    # M5: Safe Deletion, Boundary Verification & Windows DPAPI Encryption
    # -------------------------------------------------------------------------
    def test_m5_safe_deletion_and_dpapi_encryption(self) -> None:
        # 1. DPAPI Encryption / Decryption
        secret = "MySuperSecretOAuthRefreshToken_12345"
        encrypted = encrypt_secret_dpapi(secret)
        self.assertNotEqual(encrypted, secret)
        decrypted = decrypt_secret_dpapi(encrypted)
        self.assertEqual(decrypted, secret)

        # 2. Directory Boundary Protection
        outside_file = self.root.parent / "system_file_outside.txt"
        outside_file.write_text("critical data", encoding="utf-8")
        try:
            result = _safe_remove(outside_file, self.appdata, self.root)
            self.assertEqual(result.status, "BOUNDARY_VIOLATION")
            self.assertFalse(bool(result))
            self.assertTrue(outside_file.exists())
        finally:
            outside_file.unlink(missing_ok=True)

        # 3. Inside file deletion
        inside_file = self.appdata / "temp_file.txt"
        inside_file.write_text("ok to delete", encoding="utf-8")
        del_result = _safe_remove(inside_file, self.appdata, self.root)
        self.assertEqual(del_result.status, "DELETED")
        self.assertTrue(bool(del_result))
        self.assertFalse(inside_file.exists())

    # -------------------------------------------------------------------------
    # M6: Persistent Harness Multi-Turn Context Continuity
    # -------------------------------------------------------------------------
    def test_m6_persistent_harness_continuity(self) -> None:
        save_path = self.appdata / "harness/session_context.json"

        s1 = SessionState()
        s1.set_persistence_enabled(True)
        s1.last_asset = "SOL"
        s1.timeframe = "H4"
        s1.market_type = "PERPETUAL"
        s1.add_turn("review SOL", "SOL is in bullish markup above 180 USD.")
        s1.save_persistent(save_path)

        s2 = SessionState()
        self.assertTrue(s2.load_persistent(save_path))
        self.assertEqual(s2.last_asset, "SOL")
        self.assertEqual(s2.timeframe, "H4")
        self.assertEqual(len(s2.conversational_turns), 1)
        self.assertIn("SOL", s2.conversational_turns[0]["assistant"])

    # -------------------------------------------------------------------------
    # M7: Official Gmail OAuth Desktop Flow & Automatic Token Refresh
    # -------------------------------------------------------------------------
    def test_m7_gmail_oauth_token_refresh(self) -> None:
        token_path = self.appdata / "config/gmail_token.json"
        store = GmailTokenStore(token_path)

        now = time.time()
        # Save expired token with refresh token
        store.save({
            "access_token": "expired_access_token_123",
            "refresh_token": "valid_refresh_token_456",
            "expires_at": now - 100.0,  # Expired
            "email": "trader@example.com",
            "scope": GMAIL_SEND_SCOPE,
        })

        # Mock token refresh network call
        def mock_fetcher(method: str, url: str, data: dict, headers: dict) -> tuple[int, dict]:
            if "token" in url and data.get("grant_type") == "refresh_token":
                return 200, {
                    "access_token": "fresh_new_access_token_789",
                    "expires_in": 3600,
                    "scope": GMAIL_SEND_SCOPE,
                }
            return 404, {}

        config = GmailOAuthConfig(client_id="test_client_id", client_secret="test_secret", configured=True)
        transport = GmailOAuthTransport(config=config, token_store=store, http_fetcher=mock_fetcher)

        fresh_token = transport.ensure_access_token()
        self.assertEqual(fresh_token, "fresh_new_access_token_789")

        status = transport.get_status()
        self.assertEqual(status["status"], "CONNECTED")
        self.assertEqual(status["email"], "trader@example.com")

    # -------------------------------------------------------------------------
    # M8: Gmail RFC 2822 Base64url Delivery
    # -------------------------------------------------------------------------
    def test_m8_gmail_message_send_format(self) -> None:
        token_path = self.appdata / "config/gmail_token.json"
        store = GmailTokenStore(token_path)
        store.save({
            "access_token": "active_token_123",
            "refresh_token": "valid_refresh_token_456",
            "expires_at": time.time() + 3600.0,
            "email": "user@gmail.com",
            "scope": GMAIL_SEND_SCOPE,
        })

        captured_requests = []

        def mock_fetcher(method: str, url: str, data: dict, headers: dict) -> tuple[int, dict]:
            captured_requests.append((method, url, data, headers))
            if "messages/send" in url:
                return 200, {"id": "msg_abc123", "threadId": "th_xyz789"}
            return 404, {}

        config = GmailOAuthConfig(client_id="test_client_id", client_secret="test_secret", configured=True)
        transport = GmailOAuthTransport(config=config, token_store=store, http_fetcher=mock_fetcher)

        send_res = transport.send_message(
            recipient="client@example.com",
            subject="BTC Research Summary",
            text_body="Bitcoin breakout confirmed above 68,000 USD.",
        )
        self.assertEqual(send_res["status"], "SENT")
        self.assertEqual(send_res["message_id"], "msg_abc123")

        # Verify sent payload structure
        self.assertTrue(len(captured_requests) > 0)
        _, url, data, headers = captured_requests[0]
        self.assertIn("users/me/messages/send", url)
        self.assertIn("Bearer active_token_123", headers.get("Authorization", ""))
        self.assertIn("raw", data)

        # Decode base64url message
        raw_b64 = data["raw"]
        raw_bytes = base64.urlsafe_b64decode(raw_b64 + "==")
        raw_text = raw_bytes.decode("utf-8", errors="ignore")
        self.assertIn("Subject: BTC Research Summary", raw_text)
        self.assertIn("To: client@example.com", raw_text)
        self.assertIn("Bitcoin breakout confirmed", raw_text)

    # -------------------------------------------------------------------------
    # M9: Personal WhatsApp Native Compose & Honest Status Semantics
    # -------------------------------------------------------------------------
    def test_m9_personal_whatsapp_compose_status(self) -> None:
        cfg = PersonalWhatsAppConfig(self.appdata / "config/whatsapp_personal.json")
        transport = PersonalWhatsAppTransport(cfg)

        connect_res = transport.connect("+62 812-3456-7890")
        self.assertEqual(connect_res["status"], STATUS_CONNECTED)
        self.assertEqual(connect_res["phone"], "6281234567890")

        # Compose must return COMPOSE_OPENED without opening real browser in tests
        compose_res = transport.compose("OpenBagus Daily Market Digest", open_browser=False)
        self.assertEqual(compose_res["status"], STATUS_COMPOSE_OPENED)
        self.assertEqual(compose_res["recipient"], "6281234567890")
        self.assertIn("whatsapp://send", compose_res["app_uri"])
        self.assertIn("web.whatsapp.com/send", compose_res["web_uri"])
        self.assertIn("User must click Send", compose_res["detail"])

    # -------------------------------------------------------------------------
    # M10: Experimental Multi-Device QR (Baileys) Safety Disclosures
    # -------------------------------------------------------------------------
    def test_m10_baileys_safety_and_default_disabled(self) -> None:
        transport = BaileysExperimentalTransport(self.appdata / "whatsapp_session")
        status = transport.get_status()

        self.assertEqual(status["status"], STATUS_DISCONNECTED)
        self.assertFalse(status["enabled"])
        self.assertFalse(status["risk_acknowledged"])
        self.assertEqual(status["classification"], "UNOFFICIAL_EXPERIMENTAL")
        self.assertIn("High risk of account restriction", status["warning"])
        self.assertIn("Disabled by default", status["warning"])

    # -------------------------------------------------------------------------
    # M11: Controlled Autonomous Monitoring & Closed-Candle Alert Deduplication
    # -------------------------------------------------------------------------
    def test_m11_autonomous_monitoring_deduplication(self) -> None:
        db_path = self.appdata / "monitoring/monitor.db"
        store = AutonomousMonitorStore(db_path)
        runtime = AutonomousMonitoringRuntime(store=store)

        # Default state is OFF
        status_init = runtime.get_status()
        self.assertEqual(status_init["status"], "DISABLED")
        self.assertFalse(status_init["global_enabled"])

        # Enable monitoring
        runtime.enable()
        self.assertTrue(runtime.store.is_global_enabled())

        # Add rule
        rule = runtime.add_alert_rule(asset="BTC", timeframe="H1", condition="BREAKOUT")

        fixed_time = datetime(2026, 10, 10, 14, 0, 0, tzinfo=timezone.utc)
        candle_ts = 1760094000

        # Mock signal evaluator
        mock_evaluator = MagicMock(return_value={
            "qualifies": True,
            "decision": "BUY",
            "price": 68500.0,
            "headline": "BTC H1 Breakout confirmed above 68,000",
            "summary": "Volume expansion and clean close.",
            "candle_timestamp": candle_ts,
            "condition_hash": "hash_breakout_68k",
        })

        # Tick 1: Alert triggers
        alerts_tick1 = runtime.evaluate_tick(quant_evaluator=mock_evaluator, now_dt=fixed_time)
        self.assertEqual(len(alerts_tick1), 1)
        self.assertEqual(alerts_tick1[0].asset, "BTC")
        self.assertEqual(alerts_tick1[0].decision, "BUY")

        # Tick 2: Same closed candle & identical condition -> Deduplication suppresses repeat
        alerts_tick2 = runtime.evaluate_tick(quant_evaluator=mock_evaluator, now_dt=fixed_time)
        self.assertEqual(len(alerts_tick2), 0, "Unchanged candle and condition must not re-trigger alert")

        # Tick 3: New condition or new candle -> Alert triggers
        mock_evaluator.return_value["candle_timestamp"] = candle_ts + 3600
        mock_evaluator.return_value["condition_hash"] = "hash_breakout_70k"
        later_time = datetime(2026, 10, 10, 16, 0, 0, tzinfo=timezone.utc)
        alerts_tick3 = runtime.evaluate_tick(quant_evaluator=mock_evaluator, now_dt=later_time)
        self.assertEqual(len(alerts_tick3), 1)
        runtime.close()

    # -------------------------------------------------------------------------
    # M12: Monitor Error Recovery & Quiet-Hours Suppression
    # -------------------------------------------------------------------------
    def test_m12_monitor_quiet_hours(self) -> None:
        db_path = self.appdata / "monitoring/monitor.db"
        store = AutonomousMonitorStore(db_path)
        runtime = AutonomousMonitoringRuntime(store=store)
        runtime.enable()
        runtime.add_alert_rule(asset="ETH", timeframe="H1", condition="BREAKOUT", channels=["gmail"], destination="trader@gmail.com")

        # 23:00 UTC is inside Quiet Hours (22:00 - 06:00)
        quiet_time = datetime(2026, 10, 10, 23, 0, 0, tzinfo=timezone.utc)
        dispatched_channels: list[str] = []

        def mock_dispatcher(event: AlertEvent, channel: str) -> bool:
            dispatched_channels.append(channel)
            return True

        mock_evaluator = MagicMock(return_value={
            "qualifies": True,
            "decision": "BUY",
            "price": 2600.0,
            "headline": "ETH Breakout",
            "summary": "Details",
            "candle_timestamp": 1760098000,
            "condition_hash": "hash_eth",
        })

        events = runtime.evaluate_tick(quant_evaluator=mock_evaluator, dispatcher=mock_dispatcher, now_dt=quiet_time)
        self.assertEqual(len(events), 1)
        # Event is recorded in DB
        self.assertEqual(events[0].asset, "ETH")
        # Gmail push delivery is suppressed during quiet hours (recorded as SUPPRESSED_QUIET_HOURS)
        self.assertEqual(events[0].delivery_status.get("gmail"), "SUPPRESSED_QUIET_HOURS")
        self.assertEqual(len(dispatched_channels), 0)
        runtime.close()


if __name__ == "__main__":
    unittest.main()
