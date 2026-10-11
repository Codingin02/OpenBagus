"""Tests for OpenBagus Dynamic Financial Intelligence, Grounded Responses, and Follow-up Flow."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openbagus.domains.crypto.research import ResearchPacket
from openbagus.domains.equities.catalog import EquityCatalog
from openbagus.domains.equities.policy import EquityMarketPolicy
from openbagus.domains.equities.research import (
    equity_context,
    render_equity,
    run_equity_research,
    _render_equity_followup,
)
from openbagus.domains.crypto.quant import QuantEngine
from openbagus.intelligence.intent import IntentRequest, SessionState


class TestDynamicFinancialResponses(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = EquityCatalog(REPO_ROOT)
        self.policy = EquityMarketPolicy(REPO_ROOT)

    def test_equity_context_is_issuer_specific(self) -> None:
        klbf = self.catalog.resolve("KLBF")
        self.assertIsNotNone(klbf)
        ctx = equity_context(klbf, "prospek KLBF")
        self.assertIn("KLBF", ctx)
        self.assertIn("kesehatan", ctx.lower())
        self.assertNotIn("Untuk kesehatan/farmasi/rumah sakit, driver mencakup Bed Occupancy Rate", ctx)

        bbca = self.catalog.resolve("BBCA")
        self.assertIsNotNone(bbca)
        ctx_b = equity_context(bbca, "suku bunga BBCA")
        self.assertIn("BBCA", ctx_b)
        self.assertIn("BI-Rate", ctx_b)

    def test_followup_margin_query_returns_direct_financial_ratios(self) -> None:
        asset = self.catalog.resolve("ICBP")
        quant = MagicMock()
        quant.symbol = "ICBP"
        quant.decision = "BUY"
        quant.decision_status = "EVALUATED"
        quant.decision_reason = "Setup valid"
        quant.timeframe = "D1"
        quant.data_freshness = "CACHE_VALID"
        quant.bullish_validation = None

        data = {
            "period": "2025 FY",
            "basis": "konsolidasi",
            "ratios": {
                "Operating_Margin_pct": 21.0,
                "Net_Margin_pct": 12.5,
                "ROE_pct": 19.3,
                "Debt_to_Equity": 0.75,
            },
        }
        packet = ResearchPacket(
            "ICBP", "IDX CASH EQUITY", "D1", 10000.0, "BUY", "HIGH", "A",
            fundamentals=data, sources=["IDX Financial Statements"],
        )

        session = SessionState()
        session.language = "ID"
        runner = MagicMock()
        runner.local_llm.is_available.return_value = False

        ans = _render_equity_followup(runner, session, asset, packet, quant, "berapa margin nya?")
        self.assertIn("Operating Margin: 21.00%", ans)
        self.assertIn("Net Margin: 12.50%", ans)
        self.assertNotIn("ICBP | IDX | D1 | BUY", ans)

    def test_followup_why_query_returns_direct_causal_reasoning(self) -> None:
        asset = self.catalog.resolve("BMRI")
        quant = MagicMock()
        quant.symbol = "BMRI"
        quant.decision = "WAIT"
        quant.decision_status = "EVALUATED"
        quant.decision_reason = "Menunggu breakout konfirmasi di atas level resisten Rp7,200"
        quant.timeframe = "D1"
        quant.data_freshness = "CACHE_VALID"
        quant.bullish_validation = MagicMock(
            trigger_condition="Breakout di atas Rp7,200",
            entry_zone="Rp7,225 - Rp7,250",
            stop_price=6950.0,
            tp1=7600.0,
            reward_risk_str="1:1.6",
        )

        packet = ResearchPacket(
            "BMRI", "IDX CASH EQUITY", "D1", 7100.0, "WAIT", "HIGH", "B",
            sources=["IDX"],
        )

        session = SessionState()
        session.language = "ID"
        runner = MagicMock()
        runner.local_llm.is_available.return_value = False

        ans = _render_equity_followup(runner, session, asset, packet, quant, "kenapa wait?")
        self.assertIn("Alasan keputusan WAIT pada BMRI", ans)
        self.assertIn("Menunggu breakout konfirmasi di atas level resisten Rp7,200", ans)
        self.assertIn("Breakout di atas Rp7,200", ans)
        self.assertNotIn("BMRI | IDX | D1 | WAIT", ans)

    def test_followup_sources_query(self) -> None:
        asset = self.catalog.resolve("TLKM")
        quant = MagicMock()
        quant.timeframe = "D1"
        quant.decision_reason = "Konsolidasi"
        quant.data_freshness = "CACHE_VALID"

        packet = ResearchPacket(
            "TLKM", "IDX CASH EQUITY", "D1", 3200.0, "WAIT", "HIGH", "B",
            sources=["Yahoo Finance", "IDX Official Disclosures"],
            price_as_of="2026-01-10T16:00:00+07:00",
            data_freshness="CACHE_VALID",
        )

        session = SessionState()
        session.language = "ID"
        runner = MagicMock()
        runner.local_llm.is_available.return_value = False

        ans = _render_equity_followup(runner, session, asset, packet, quant, "darimana datanya?")
        self.assertIn("Data TLKM bersumber dari: Yahoo Finance, IDX Official Disclosures", ans)
        self.assertIn("Freshness: CACHE_VALID", ans)
        self.assertIn("2026-01-10T16:00:00+07:00", ans)


if __name__ == "__main__":
    unittest.main()
