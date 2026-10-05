"""Tests for OpenBagus Local Language Intelligence and Intent Routing."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from openbagus.domains.crypto.quant import QuantDecisionResult, ValidationScenario
from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.intelligence.local_language import (
    SYSTEM_PROFILE,
    LocalLanguageEngine,
)


class TestLocalLanguageIntelligence(unittest.TestCase):
    def setUp(self) -> None:
        self.router = IntentRouter()
        self.session = SessionState()
        self.engine = LocalLanguageEngine()

    def test_section_20_targeted_intent_regressions(self) -> None:
        """Verify the exact 9 regression queries plus fallback without live network."""
        # 1. "herness" -> HARNESS, NOT an asset
        r1 = self.router.parse("herness", self.session)
        self.assertEqual(r1.request_type, "HARNESS")
        self.assertIsNone(r1.asset)

        # 2. "mana hernesnyaaaaaa????" -> HARNESS
        r2 = self.router.parse("mana hernesnyaaaaaa????", self.session)
        self.assertEqual(r2.request_type, "HARNESS")
        self.assertIsNone(r2.asset)

        # 3. "about sistem?" -> SYSTEM_INFO
        r3 = self.router.parse("about sistem?", self.session)
        self.assertEqual(r3.request_type, "SYSTEM_INFO")
        self.assertIsNone(r3.asset)

        # 4. "tolol nih" -> FEEDBACK
        r4 = self.router.parse("tolol nih", self.session)
        self.assertEqual(r4.request_type, "FEEDBACK")
        self.assertIsNone(r4.asset)

        # 5. "wkwk kok no trade semua" -> FEEDBACK
        r5 = self.router.parse("wkwk kok no trade semua", self.session)
        self.assertEqual(r5.request_type, "FEEDBACK")
        self.assertIsNone(r5.asset)

        # 6. "kasih LLM aja deh untuk speknya dibawah 1 GB" -> SETUP_CONFIG/SYSTEM_INFO, NOT PARAMETER token
        r6 = self.router.parse("kasih LLM aja deh untuk speknya dibawah 1 GB", self.session)
        self.assertIn(r6.request_type, ("SETUP_CONFIG", "SYSTEM_INFO"))
        self.assertIsNone(r6.asset)

        # 7. "ohh iya nanti jangan pakai ollama" -> PREFERENCE/SYSTEM_INFO, NOT OHH token
        r7 = self.router.parse("ohh iya nanti jangan pakai ollama", self.session)
        self.assertIn(r7.request_type, ("PREFERENCE", "SYSTEM_INFO"))
        self.assertIsNone(r7.asset)

        # 8. "zcash" -> ZEC analysis
        r8 = self.router.parse("zcash", self.session)
        self.assertEqual(r8.request_type, "ASSET_ANALYSIS")
        self.assertEqual(r8.asset, "ZEC")

        # 9. "near" -> NEAR analysis
        r9 = self.router.parse("near", self.session)
        self.assertEqual(r9.request_type, "ASSET_ANALYSIS")
        self.assertEqual(r9.asset, "NEAR")

    def test_section_20_fallback_when_local_model_unavailable(self) -> None:
        """When local model is offline/unavailable, fallback remains fully operational."""
        with patch.object(self.engine, "is_available", return_value=False):
            self.assertFalse(self.engine.is_available())
            self.assertIsNone(self.engine.interpret_intent("gimana BTC h1?"))
            self.assertIsNone(self.engine.generate_narrative(MagicMock()))

        # Router still correctly handles user input via deterministic rules
        r = self.router.parse("gimana BTC h1?", self.session)
        self.assertEqual(r.asset, "BTC")
        self.assertEqual(r.timeframe, "H1")
        self.assertEqual(r.market, "all")

    def test_local_language_mock_interpreter_and_asset_safety(self) -> None:
        """Verifies JSON schema parsing, asset verification, and non-asset safety."""
        mock_engine = LocalLanguageEngine()

        # Mock LLM returning valid JSON intent
        valid_json = (
            '{"request_type": "POSITION", "asset": "ETH", "market": "perpetual", '
            '"timeframe": "H4", "confidence": "high"}'
        )
        with patch.object(mock_engine, "is_available", return_value=True):
            with patch.object(mock_engine, "_run_llama", return_value=valid_json):
                res = mock_engine.interpret_intent("kalau eth gimana open posisinya")
                self.assertIsNotNone(res)
                self.assertEqual(res["request_type"], "POSITION")
                self.assertEqual(res["asset"], "ETH")
                self.assertEqual(res["timeframe"], "H4")

        # Asset safety: FEEDBACK must strip asset to None
        feedback_json = '{"request_type": "FEEDBACK", "asset": "TOLOL", "confidence": "high"}'
        with patch.object(mock_engine, "is_available", return_value=True):
            with patch.object(mock_engine, "_run_llama", return_value=feedback_json):
                res_fb = mock_engine.interpret_intent("tolol nih")
                self.assertIsNotNone(res_fb)
                self.assertEqual(res_fb["request_type"], "FEEDBACK")
                self.assertIsNone(res_fb["asset"])

    def test_section_21_narrative_quant_invariance(self) -> None:
        """Verifies QuantEngine results remain strictly authoritative in narrative."""
        # Fixed Quant result fixture
        bullish = ValidationScenario(
            direction="LONG",
            trigger_condition="H1 close above $85,500.00",
            volume_condition="Volume > 1.2x avg",
            order_flow_condition="Taker delta > +0.10",
            derivatives_condition="Rising open interest",
            entry_zone="$85,500.00",
            stop_price=85187.50,
            tp1=86000.00,
            tp2=86500.00,
            reward_risk=1.60,
            reward_risk_str="1:1.60",
        )
        bearish = ValidationScenario(
            direction="SHORT",
            trigger_condition="H1 breakdown below $84,500.00",
            volume_condition="Volume expansion",
            order_flow_condition="Sell delta < -0.10",
            derivatives_condition="Rising sell flow",
            entry_zone="$84,500.00",
            stop_price=84812.50,
            tp1=84000.00,
            tp2=83500.00,
            reward_risk=1.60,
            reward_risk_str="1:1.60",
        )

        quant_res = QuantDecisionResult(
            asset="BTC",
            market="perpetual",
            decision="NO_TRADE",
            regime="Compressed",
            confidence="MODERATE",
            price=85000.0,
            entry_zone="Breakout $85,500.00 or Breakdown $84,500.00",
            stop_price=85187.50,
            tp1=86000.00,
            tp2=86500.00,
            reward_risk=1.60,
            reward_risk_str="1:1.60",
            leverage_ceiling="3x",
            leverage_num=3,
            why={"Trend": "Neutral", "Microstructure": "Balanced"},
            sources=["Binance Vision"],
            evidence_count=4,
            composite_score=0.10,
            composite_quality=0.85,
            rr_gate_passed=False,
            quality_gate_passed=True,
            decision_reason="Reward-to-risk at current price does not meet 1:1.50 minimum gate.",
            timeframe="H1",
            bullish_validation=bullish,
            bearish_validation=bearish,
            narrative="BTC masih konsolidasi pada timeframe H1. Disarankan menahan diri (NO_TRADE).",
        )

        mock_llm = LocalLanguageEngine()
        consultant_text = (
            "Untuk H1 saya belum mengejar BTC di harga sekarang ($85,000.00). "
            "Struktur masih Compressed dan rasio risk:reward saat ini belum memadai. "
            "Skenario baru valid jika breakout di atas $85,500.00 atau breakdown di bawah $84,500.00."
        )

        with patch.object(mock_llm, "is_available", return_value=True):
            with patch.object(mock_llm, "_run_llama", return_value=consultant_text):
                narr = mock_llm.generate_narrative(quant_res, language="id")
                self.assertIsNotNone(narr)
                self.assertIn("BTC", narr)
                self.assertIn("$85,000.00", narr)
                self.assertEqual(quant_res.decision, "NO_TRADE")
                self.assertEqual(quant_res.price, 85000.0)

            # Invalidation guard test: LLM falsely recommending BUY when quant is NO_TRADE
            bad_llm_text = "Pasar sangat bagus, SEGERA BELI BTC sekarang juga!"
            with patch.object(mock_llm, "_run_llama", return_value=bad_llm_text):
                invalidated = mock_llm.generate_narrative(quant_res, language="id")
                self.assertIsNone(invalidated)  # Must reject contradictory advice

    def test_canonical_system_profile(self) -> None:
        """Verifies system profile facts are accurate and strictly non-hallucinated."""
        self.assertEqual(SYSTEM_PROFILE["name"], "OpenBagus")
        self.assertEqual(SYSTEM_PROFILE["creator"], "Ahmad Bagus Idkholus Surur")
        self.assertEqual(SYSTEM_PROFILE["active_domain"], "Crypto (Equities disabled)")
        self.assertEqual(SYSTEM_PROFILE["trading_execution"], "Not implemented (research and risk analysis only)")

        resp_id = self.engine.answer_system_question("siapa pembuat OpenBagus?", language="id")
        self.assertIn("Ahmad Bagus Idkholus Surur", resp_id)
        self.assertIn("OpenBagus", resp_id)

        resp_en = self.engine.answer_system_question("about system?", language="en")
        self.assertIn("Ahmad Bagus Idkholus Surur", resp_en)
        self.assertIn("Crypto", resp_en)


if __name__ == "__main__":
    unittest.main()
