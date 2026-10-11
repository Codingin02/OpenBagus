"""Comprehensive tests for evidence-grounded financial reasoning, adaptive ontology,
dynamic query hooks, and harness consent privacy.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbagus.core.env import get_repo_root
from openbagus.data.indonesia_official import KemendagAdapter, OJKPublicAdapter
from openbagus.domains.crypto.quant import QuantDecisionResult
from openbagus.domains.crypto.research import ResearchPacket
from openbagus.domains.equities.catalog import EquityCatalog
from openbagus.domains.equities.research import (
    equity_context,
    _render_equity_followup,
    render_equity,
)
from openbagus.intelligence.evidence import (
    EvidencePacket,
    EvidenceMetric,
    FactCategory,
    IndependenceGroup,
    build_evidence_packet_from_research,
)
from openbagus.intelligence.intent import IntentRequest, SessionState
from openbagus.intelligence.local_language import (
    LocalLanguageEngine,
    NarrativeFacts,
)

REPO_ROOT = get_repo_root()


class TestEvidenceReasoningAndDialogue(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = EquityCatalog(REPO_ROOT)

    # ------------------------------------------------------------------
    # Fix 2.6: Coverage Flags Integrity
    # ------------------------------------------------------------------
    def test_coverage_flags_reflect_actual_data_presence(self) -> None:
        packet_no_macro = ResearchPacket(
            "BBCA", "IDX CASH EQUITY", "D1", 10000.0, "WAIT", "HIGH", "A",
            sector_statistics_available=False,
            macro_context_available=False,
            corporate_actions_available=False,
        )
        self.assertFalse(packet_no_macro.sector_statistics_available)
        self.assertFalse(packet_no_macro.macro_context_available)
        self.assertFalse(packet_no_macro.corporate_actions_available)

    # ------------------------------------------------------------------
    # Fix 2.7: Static Government Benchmark Transparency
    # ------------------------------------------------------------------
    def test_government_benchmarks_flagged_as_hardcoded(self) -> None:
        ojk = OJKPublicAdapter.get_benchmark_banking_metrics()
        self.assertTrue(ojk.get("is_hardcoded"))
        self.assertIn("HARDCODED", ojk.get("note", ""))
        self.assertEqual(ojk.get("data_category"), "AGGREGATE_INDUSTRY_STATISTICS")

        kemendag = KemendagAdapter.get_staple_and_export_benchmarks()
        self.assertTrue(kemendag.get("is_hardcoded"))
        self.assertIn("HARDCODED", kemendag.get("note", ""))
        self.assertEqual(kemendag.get("category"), "COMMODITY_AND_TRADE_EVIDENCE")

    # ------------------------------------------------------------------
    # Fix 2.8: Harness Privacy and Consent Guard
    # ------------------------------------------------------------------
    def test_add_turn_respects_disabled_persistence_consent(self) -> None:
        session = SessionState()
        session.set_persistence_enabled(False)

        with patch("openbagus.storage.harness_db.HarnessStorage.save_turn") as mock_save:
            session.add_turn("pertanyaan pengguna", "jawaban asisten")
            mock_save.assert_not_called()

        # In-memory working turns are still maintained
        self.assertEqual(len(session.conversational_turns), 1)

    def test_add_turn_writes_to_sqlite_when_consent_given(self) -> None:
        session = SessionState()
        session.set_persistence_enabled(True)

        with patch("openbagus.storage.harness_db.HarnessStorage.save_turn") as mock_save, \
             patch.object(session, "save_persistent"):
            session.add_turn("pertanyaan berizin", "jawaban berizin")
            mock_save.assert_called_once()

    # ------------------------------------------------------------------
    # Fix 2.2: Dynamic Equity Context with Actual Reported Fundamentals
    # ------------------------------------------------------------------
    def test_equity_context_incorporates_actual_reported_ratios(self) -> None:
        bbca = self.catalog.resolve("BBCA")
        self.assertIsNotNone(bbca)

        fund_data = {
            "period": "2024 FY",
            "basis": "konsolidasi",
            "ratios": {
                "NIM_pct": 5.45,
                "NPL_gross_pct": 1.82,
                "CAR_pct": 28.70,
            },
        }
        packet = ResearchPacket(
            "BBCA", "IDX CASH EQUITY", "D1", 10200.0, "WAIT", "HIGH", "A",
            fundamentals=fund_data,
        )

        ctx = equity_context(bbca, "suku bunga BBCA", packet=packet)
        self.assertIn("BBCA", ctx)
        self.assertIn("BI-Rate", ctx)
        self.assertIn("NIM 5.45%", ctx)
        self.assertIn("NPL Gross 1.82%", ctx)
        self.assertIn("CAR 28.70%", ctx)

    def test_equity_context_consumer_margin_inclusion(self) -> None:
        icbp = self.catalog.resolve("ICBP")
        self.assertIsNotNone(icbp)

        fund_data = {
            "period": "2024 Q3",
            "ratios": {
                "Operating_Margin_pct": 21.40,
            },
        }
        packet = ResearchPacket(
            "ICBP", "IDX CASH EQUITY", "D1", 11500.0, "BUY", "HIGH", "A",
            fundamentals=fund_data,
        )

        ctx = equity_context(icbp, "ketahanan margin ICBP", packet=packet)
        self.assertIn("Operating Margin 21.40%", ctx)

    # ------------------------------------------------------------------
    # Fix 2.5: Follow-Up Semantics and Causal Reasoning
    # ------------------------------------------------------------------
    def test_render_equity_followup_prioritizes_why_over_generic_keywords(self) -> None:
        asset = self.catalog.resolve("BBCA")
        quant = MagicMock()
        quant.symbol = "BBCA"
        quant.decision = "WAIT"
        quant.decision_status = "EVALUATED"
        quant.decision_reason = "Menunggu konfirmasi reversal volume"
        quant.timeframe = "D1"
        quant.bullish_validation = None
        quant.data_freshness = "FRESH"

        packet = ResearchPacket(
            "BBCA", "IDX CASH EQUITY", "D1", 10000.0, "WAIT", "HIGH", "A",
            fundamentals={"ratios": {"Operating_Margin_pct": 20.0}},
            sources=["IDX"],
        )

        runner = MagicMock()
        runner.local_llm.is_available.return_value = False
        session = SessionState()

        # Query has both "kenapa" and "margin"
        ans = _render_equity_followup(runner, session, asset, packet, quant, "kenapa wait padahal margin bagus?")
        self.assertIn("Alasan keputusan WAIT pada BBCA", ans)
        self.assertIn("Menunggu konfirmasi reversal volume", ans)

    def test_render_equity_followup_rate_question_answered_during_source_gap(self) -> None:
        asset = self.catalog.resolve("BBCA")
        quant = MagicMock()
        quant.price = None
        quant.decision_status = "INSUFFICIENT_DATA_FOR_DECISION"

        packet = ResearchPacket("BBCA", "IDX CASH EQUITY", "D1", None, "WAIT", "LOW", "NEUTRAL")
        runner = MagicMock()
        runner.local_llm.is_available.return_value = False
        session = SessionState()

        ans = _render_equity_followup(runner, session, asset, packet, quant, "pengaruh BI rate ke BBCA?")
        self.assertIn("Transmisi BI-Rate", ans)
        self.assertIn("BBCA", ans)

    # ------------------------------------------------------------------
    # Fix 2.1, 2.3, 2.4: Local Language Narrative Prompt Integrity
    # ------------------------------------------------------------------
    def test_equity_narrative_prompt_uses_cash_equity_ontology(self) -> None:
        engine = LocalLanguageEngine()
        facts = NarrativeFacts(
            asset="BBCA",
            price=10100.0,
            decision="WAIT",
            reason="Volume belum konfirmasi",
            currency="IDR",
            asset_type="EQUITY_ID",
            fundamentals={"PBV": 4.8, "PER": 22.5, "ROE_pct": 21.0},
        )

        captured_prompt = None

        def mock_complete(prompt: str, **kwargs) -> str:
            nonlocal captured_prompt
            captured_prompt = prompt
            return "BBCA saat ini berada dalam posisi WAIT pada harga Rp10,100 menunggu konfirmasi volume."

        with patch.object(engine, "is_available", return_value=True), \
             patch.object(engine, "_complete", side_effect=mock_complete):
            engine.generate_narrative(facts, user_query="bagaimana valuasi BBCA?")

        self.assertIsNotNone(captured_prompt)
        # Ontology must be equity-focused
        self.assertIn("cash equities, IDX, IHSG, valuation", captured_prompt)
        self.assertIn("NEVER mention perpetual contracts, leverage", captured_prompt)
        # Hook directive responds to valuation query
        self.assertIn("Directly address the fundamental valuation", captured_prompt)

    def test_crypto_narrative_prompt_uses_crypto_ontology(self) -> None:
        engine = LocalLanguageEngine()
        facts = NarrativeFacts(
            asset="BTC",
            price=88000.0,
            decision="BUY",
            reason="Breakout di atas resisten $87,500",
            currency="USD",
            asset_type="CRYPTO",
        )

        captured_prompt = None

        def mock_complete(prompt: str, **kwargs) -> str:
            nonlocal captured_prompt
            captured_prompt = prompt
            return "BTC berada dalam setup BUY pada harga $88,000 setelah breakout."

        with patch.object(engine, "is_available", return_value=True), \
             patch.object(engine, "_complete", side_effect=mock_complete):
            engine.generate_narrative(facts, user_query="kenapa buy BTC?")

        self.assertIsNotNone(captured_prompt)
        self.assertIn("spot, perpetual, long, short", captured_prompt)
        self.assertIn("Directly explain why the quant decision is BUY", captured_prompt)

    def test_evidence_packet_metrics_included_in_prompt(self) -> None:
        engine = LocalLanguageEngine()
        ep = EvidencePacket(
            asset="ETH", market="PERPETUAL", timeframe="H1",
            currency="USD", asset_type="CRYPTO",
        )
        ep.add_metric(EvidenceMetric(
            metric_id="ETH_PRICE", asset_id="ETH", metric_type="PRICE",
            numeric_value=2750.0, unit="USD", market="PERPETUAL", timeframe="H1",
            observation_time="2026-01-01T00:00:00Z", retrieval_time="2026-01-01T00:00:00Z",
            source_id="BINANCE", category=FactCategory.OBSERVED,
            independence_group=IndependenceGroup.PRICE_STRUCTURE,
        ))

        facts = NarrativeFacts(
            asset="ETH",
            price=2750.0,
            decision="WAIT",
            reason="Menunggu trigger konfirmasi",
            currency="USD",
            asset_type="CRYPTO",
            evidence_packet=ep,
        )

        captured_prompt = None

        def mock_complete(prompt: str, **kwargs) -> str:
            nonlocal captured_prompt
            captured_prompt = prompt
            return "ETH pada harga $2,750 masih menunggu konfirmasi."

        with patch.object(engine, "is_available", return_value=True), \
             patch.object(engine, "_complete", side_effect=mock_complete):
            engine.generate_narrative(facts, user_query="kondisi ETH")

        self.assertIsNotNone(captured_prompt)
        self.assertIn("Validated Evidence Metrics:", captured_prompt)
        self.assertIn("PRICE: $2,750.00 [OBSERVED] (source: BINANCE)", captured_prompt)


if __name__ == "__main__":
    unittest.main()
