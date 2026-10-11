"""Comprehensive test suite for Native Conversational Intelligence,
Decision-First Financial Reasoning, and Persistent SQLite Harness.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.domains.crypto.research import CryptoResearchRunner, ResearchPacket
from openbagus.domains.crypto.quant import QuantDecisionResult
from openbagus.storage.harness_db import HarnessStorage


class TestConversationalIntelligenceAndHarness(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.root = Path(self.temp_dir)
        self.router = IntentRouter(repo_root=self.root)
        self.runner = CryptoResearchRunner(repo_root=self.root)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_greeting_and_casual_exploration(self):
        session = SessionState()
        # Informal greetings
        for q in ["halo apa kabar", "selamat pagi", "hai bro", "pagi min", "halo"]:
            req = self.router.parse(q, session=session)
            self.assertEqual(req.request_type, "CONVERSATION", f"Failed for {q}")
            self.assertEqual(req.focus, "greeting")

        # Casual statements
        req_casual = self.router.parse("wkwk capek juga nunggu BTC", session=session)
        self.assertEqual(req_casual.request_type, "CONVERSATION")
        self.assertEqual(req_casual.focus, "casual")

    def test_sector_and_market_exploration(self):
        session = SessionState()
        # Healthcare sector exploration
        req1 = self.router.parse("aku lagi lihat saham kesehatan", session=session)
        self.assertEqual(req1.request_type, "CONVERSATION")
        self.assertEqual(req1.focus, "sector_exploration")
        self.assertEqual(req1.category, "F")

        # Consumer sector exploration
        req2 = self.router.parse("mulai dari consumer aja", session=session)
        self.assertEqual(req2.request_type, "CONVERSATION")
        self.assertEqual(req2.focus, "sector_exploration")
        self.assertEqual(req2.category, "D")

        # Market exploration
        req3 = self.router.parse("lagi pengen lihat market indonesia", session=session)
        self.assertEqual(req3.request_type, "CONVERSATION")
        self.assertEqual(req3.focus, "market_exploration")

    def test_user_topic_correction_and_referent_resolution(self):
        session = SessionState()
        session.last_asset = "BMRI"
        session.record_topic("BMRI", "equity")

        # User correction: "bukan BMRI tapi BBRI"
        req_corr = self.router.parse("bukan BMRI tapi BBRI", session=session)
        self.assertEqual(req_corr.asset, "BBRI")
        self.assertEqual(req_corr.relation_to_context, "CORRECT")
        self.assertEqual(session.last_equity_asset, "BBRI")

        # Switch to crypto
        session.record_topic("BTC", "crypto")
        session.last_asset = "BTC"

        # Resume equity: "balik yang saham tadi"
        req_resume = self.router.parse("balik yang saham tadi", session=session)
        self.assertEqual(req_resume.asset, "BBRI")
        self.assertEqual(req_resume.relation_to_context, "RESUME")

    def test_scenario_deterministic_simulation(self):
        session = SessionState()
        session.last_asset = "BTC"
        mock_packet = ResearchPacket(
            asset="BTC",
            market="PERPETUAL",
            timeframe="H1",
            price=60000.0,
            decision="WAIT",
            data_quality="HIGH",
            setup_quality="NEUTRAL",
            currency="USD",
            stop_price=57000.0,
            decision_reason="RR 1.2 below gate",
        )
        session.last_research_packet = mock_packet
        mock_quant = MagicMock()
        mock_quant.asset = "BTC"
        mock_quant.market = "perpetual"
        mock_quant.timeframe = "H1"
        mock_quant.decision = "WAIT"
        mock_quant.price = 60000.0
        mock_quant.stop_price = 57000.0
        mock_quant.decision_reason = "RR 1.2 below gate"
        mock_quant.data_quality = "HIGH"
        mock_quant.setup_quality = "NEUTRAL"
        session.last_quant_result = mock_quant

        req_scen = self.router.parse("kalau harga turun 3 persen?", session=session)
        self.assertEqual(req_scen.request_type, "SCENARIO")

        resp = self.runner.execute(req_scen, session=session)
        self.assertIn("Simulasi skenario deterministik untuk BTC", resp)
        self.assertIn("58,200.00", resp)  # 60,000 * 0.97 = 58,200
        self.assertNotIn("ramalan", resp.split("(")[0])

    def test_discrepancy_and_numeric_challenge_reasoning(self):
        from openbagus.domains.equities.research import _render_equity_followup
        from openbagus.domains.equities.catalog import EquityAsset

        asset = EquityAsset(symbol="KLBF", name="Kalbe Farma Tbk", sector_code="F", source="IDX")
        session = SessionState()
        session.last_asset = "KLBF"
        mock_packet = MagicMock()
        mock_packet.fundamentals = {
            "period": "2024-FY",
            "basis": "konsolidasian",
            "ratios": {"Net_Margin_pct": 11.2, "Operating_Margin_pct": 15.1, "PER": 22.4, "PBV": 3.5, "ROE_pct": 15.6},
        }
        mock_packet.sources = ["IDX Official", "Company Filing"]
        mock_quant = MagicMock()
        mock_quant.decision = "WAIT"
        mock_quant.decision_status = "HOLD"
        mock_quant.decision_reason = "Valuasi wajar, tunggu konfirmasi volume"
        mock_quant.timeframe = "D1"
        mock_quant.price = 1600.0

        # Query: "tapi aku lihat labanya kok beda ya"
        resp_disc = _render_equity_followup(self.runner, session, asset, mock_packet, mock_quant, "tapi aku lihat labanya kok beda ya")
        self.assertTrue("Tinjauan perbedaan" in resp_disc or "perbedaan" in resp_disc.lower())
        self.assertTrue("laba" in resp_disc.lower() or "sumber" in resp_disc.lower() or "margin" in resp_disc.lower())

        # Query: "yang valuasinya aja dulu"
        resp_val = _render_equity_followup(self.runner, session, asset, mock_packet, mock_quant, "yang valuasinya aja dulu")
        self.assertIn("Valuasi KLBF", resp_val)
        self.assertIn("Price to Earnings (PER): 22.40x", resp_val)
        self.assertIn("Price to Book Value (PBV): 3.50x", resp_val)

        # Query: "terus kalau buat jangka panjang?"
        resp_lt = _render_equity_followup(self.runner, session, asset, mock_packet, mock_quant, "terus kalau buat jangka panjang?")
        self.assertIn("Perspektif Jangka Panjang KLBF", resp_lt)
        self.assertIn("Profitabilitas Modal (ROE): 15.60%", resp_lt)

    def test_harness_unlimited_retention_and_indexed_recall(self):
        db_path = self.root / "test_harness.db"
        storage = HarnessStorage(db_path)

        # Populate with synthetic turns
        for i in range(100):
            storage.save_turn(
                session_id="session_01",
                user_text=f"Analisa aset nomor {i} saham perbankan",
                assistant_text=f"Hasil analisis emiten {i} OPM 20% NIM 5.2%",
                asset="BBRI" if i % 2 == 0 else "BMRI",
                market="idx",
                intent="ANALYZE",
            )

        # Verify retention policy
        stats = storage.get_stats()
        self.assertEqual(stats["total_turns"], 100)
        self.assertEqual(stats["retention_policy"], "UNLIMITED")

        # Indexed query recall
        results = storage.recall_by_query("saham perbankan BBRI", limit=5)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["asset"], "BBRI")

    def test_persistence_opt_out_privacy_guard(self):
        harness_dir = self.root / "harness"
        harness_dir.mkdir(parents=True, exist_ok=True)
        consent_path = harness_dir / "consent.json"
        consent_path.write_text('{"persistent_harness_enabled": false}', encoding="utf-8")

        with patch.object(SessionState, "get_harness_dir", return_value=harness_dir):
            session = SessionState()
            self.assertFalse(session.is_persistence_enabled())

            session.last_asset = "BTC"
            session.last_query = "BTC H1"
            # save_persistent should not write to disk when persistence is disabled
            saved = session.save_persistent()
            self.assertFalse(saved)
            self.assertFalse((harness_dir / "session_context.json").exists())

    def test_granular_harness_clear_verification(self):
        db_path = self.root / "test_clear.db"
        storage = HarnessStorage(db_path)

        # Create two sessions with turns
        storage.save_turn("session_A", "Halo A", "Jawab A", asset="BTC")
        storage.save_turn("session_B", "Halo B", "Jawab B", asset="ETH")

        self.assertEqual(storage.get_stats()["total_turns"], 2)

        # 1. Clear session_A only
        cleared_session = storage.clear(all_history=False, session_id="session_A")
        self.assertTrue(cleared_session)
        self.assertEqual(storage.get_stats()["total_turns"], 1)

        # 2. Clear all
        cleared_all = storage.clear(all_history=True)
        self.assertTrue(cleared_all)
        self.assertEqual(storage.get_stats()["total_turns"], 0)


if __name__ == "__main__":
    unittest.main()
