import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from openbagus.core.env import get_repo_root
from openbagus.domains.crypto.research import ResearchPacket
from openbagus.domains.crypto.quant import QuantDecisionResult
from openbagus.intelligence.evidence import (
    FactCategory,
    IndependenceGroup,
    EvidenceMetric,
    EvidencePacket,
    DerivedSetupMetrics,
    build_evidence_packet_from_research,
)
from openbagus.intelligence.local_language import (
    NarrativeFacts,
    LocalLanguageEngine,
    classify_user_style,
)
from openbagus.intelligence.news.registry import NewsSourceRegistry, DEFAULT_SOURCES
from openbagus.intelligence.news.runtime import NewsIntelligenceRuntime
from openbagus.cli import OpenBagusShell


class TestEvidenceFirstQuantIntelligence(unittest.TestCase):

    def setUp(self):
        self.root = get_repo_root()

    def test_derived_setup_metrics_calculation(self):
        """Validates exact geometric risk/reward distances and fee deductions."""
        ds = DerivedSetupMetrics.calculate(
            entry=65000.0,
            stop=64500.0,
            target=66250.0,
            roundtrip_fee_pct=0.0012,
            trigger_level=65400.0,
            trigger_state="UNCONFIRMED",
        )
        self.assertEqual(ds.risk_distance, 500.0)
        self.assertEqual(ds.reward_distance, 1250.0)
        self.assertEqual(ds.gross_rr, 2.50)
        # Cost: 65,000 * 0.0012 = 78.0
        self.assertEqual(ds.estimated_cost, 78.0)
        # Net Risk: 500 + 78 = 578.0
        self.assertEqual(ds.net_risk, 578.0)
        # Net Reward: 1250 - 78 = 1172.0
        self.assertEqual(ds.net_reward, 1172.0)
        # Net RR: 1172 / 578 = 2.03
        self.assertEqual(ds.net_rr, 2.03)

    def test_evidence_packet_and_valid_numbers(self):
        """Ensures EvidencePacket collects typed metrics and valid numbers for grounding."""
        ep = EvidencePacket(
            asset="BTC",
            market="PERPETUAL",
            timeframe="H1",
            currency="USD",
            decision="NO_TRADE",
        )
        ep.add_metric(EvidenceMetric(
            metric_id="BTC_PRICE",
            asset_id="BTC",
            metric_type="PRICE",
            numeric_value=65000.0,
            unit="USD",
            market="PERPETUAL",
            timeframe="H1",
            observation_time="2026-10-10T12:00:00Z",
            retrieval_time="2026-10-10T12:00:00Z",
            source_id="BINANCE",
            category=FactCategory.OBSERVED,
            independence_group=IndependenceGroup.PRICE_STRUCTURE,
        ))
        ep.derived_setup = DerivedSetupMetrics.calculate(
            entry=65400.0,
            stop=64950.0,
            target=66300.0,
            roundtrip_fee_pct=0.0012,
        )
        valid_nums = ep.get_valid_numbers()
        self.assertIn(Decimal("65000"), valid_nums)
        self.assertIn(Decimal("65400"), valid_nums)
        self.assertIn(Decimal("64950"), valid_nums)
        self.assertIn(Decimal("66300"), valid_nums)
        self.assertIn(Decimal("450"), valid_nums)   # risk distance: 65400 - 64950
        self.assertIn(Decimal("900"), valid_nums)   # reward distance: 66300 - 65400
        self.assertIn(Decimal("2"), valid_nums)     # gross RR 2.0

    def test_grounding_accepts_valid_derived_metrics(self):
        """Validates that legitimate derived numbers (risk, reward, net RR) pass numeric guard."""
        ds = DerivedSetupMetrics.calculate(
            entry=65400.0,
            stop=64950.0,
            target=66300.0,
            roundtrip_fee_pct=0.0012,
            trigger_level=65400.0,
            trigger_state="UNCONFIRMED",
        )
        facts = NarrativeFacts(
            asset="BTC",
            price=65000.0,
            decision="NO_TRADE",
            timeframe="H1",
            regime="Compressed",
            reason="Menunggu konfirmasi breakout H1",
            currency="USD",
            asset_type="CRYPTO",
            bullish_trigger_state="UNCONFIRMED",
            derived_metrics={
                "entry": ds.entry,
                "stop": ds.stop,
                "target": ds.target,
                "risk_distance": ds.risk_distance,
                "reward_distance": ds.reward_distance,
                "gross_rr": ds.gross_rr,
                "estimated_cost": ds.estimated_cost,
                "net_risk": ds.net_risk,
                "net_reward": ds.net_reward,
                "net_rr": ds.net_rr,
            },
        )
        # Indonesian narrative with derived numbers and comma decimals
        narrative = (
            "Belum saya ambil long di harga sekarang. BTC masih di $65.000, "
            "sementara konfirmasi yang ditunggu adalah penutupan H1 di atas $65.400. "
            "Skenario ini punya entry $65.400, stop $64.950, dan target $66.300. "
            "R:R sebelum biaya 1:2, tetapi setelah estimasi biaya turun menjadi sekitar 1:1,55."
        )
        self.assertTrue(LocalLanguageEngine._narrative_is_grounded(facts, narrative))

    def test_grounding_rejects_invented_prices(self):
        """Ensures completely fabricated prices outside packet/derived levels are rejected."""
        facts = NarrativeFacts(
            asset="BTC",
            price=65000.0,
            decision="NO_TRADE",
            timeframe="H1",
            regime="Compressed",
            reason="Menunggu konfirmasi",
            currency="USD",
            asset_type="CRYPTO",
            derived_metrics={"entry": 65400.0, "stop": 64950.0, "target": 66300.0},
        )
        invented_narrative = (
            "Bisa beli di $72.500 dengan target $85.000 dan stop loss $61.200."
        )
        self.assertFalse(LocalLanguageEngine._narrative_is_grounded(facts, invented_narrative))

    def test_grounding_rejects_decision_contradiction(self):
        """Ensures Quant decision NO_TRADE cannot be contradicted by narrative."""
        facts = NarrativeFacts(
            asset="BTC",
            price=65000.0,
            decision="NO_TRADE",
            timeframe="H1",
            currency="USD",
            asset_type="CRYPTO",
        )
        contradictory = "BTC di harga $65.000 adalah setup bagus, BUY NOW segera!"
        self.assertFalse(LocalLanguageEngine._narrative_is_grounded(facts, contradictory))

    def test_grounding_rejects_unconfirmed_trigger_as_confirmed(self):
        """Ensures unconfirmed trigger is never described as already broken out."""
        facts = NarrativeFacts(
            asset="BTC",
            price=65000.0,
            decision="NO_TRADE",
            timeframe="H1",
            bullish_trigger_state="UNCONFIRMED",
            currency="USD",
            asset_type="CRYPTO",
        )
        false_breakout = "Harga BTC sudah breakout dan menembus resistance $65.400."
        self.assertFalse(LocalLanguageEngine._narrative_is_grounded(facts, false_breakout))

    def test_classify_user_style(self):
        """Tests user communication style classification."""
        self.assertEqual(classify_user_style("BTC sekarang long enak nggak?"), "CASUAL_DIRECT")
        self.assertEqual(classify_user_style("wkwk kenapa no trade lagi"), "CASUAL_DIRECT")
        self.assertEqual(classify_user_style("bedah BTC H1 lengkap dari derivatives sampai risk"), "QUANT_DETAILED")
        self.assertEqual(classify_user_style("berikan laporan makro untuk BBCA"), "INSTITUTIONAL_RESEARCH")
        self.assertEqual(classify_user_style("BTC vs ETH"), "COMPARATIVE")
        self.assertEqual(classify_user_style("nfp malam ini jam berapa dan dampaknya ke crypto?"), "EVENT_BRIEF")
        self.assertEqual(classify_user_style("ini maksudnya apa?"), "FOLLOW_UP")
        self.assertEqual(classify_user_style("analisis teknikal BTC"), "PROFESSIONAL_DIRECT")

    def test_news_registry_contains_official_sources(self):
        """Verifies registry contains core official sources and publishers."""
        source_ids = {s["id"] for s in DEFAULT_SOURCES}
        self.assertIn("antara_ekonomi", source_ids)
        self.assertIn("antara_terkini", source_ids)
        self.assertIn("bls_news", source_ids)
        self.assertIn("us_treasury_press", source_ids)
        self.assertIn("bank_indonesia_official", source_ids)
        self.assertIn("boj_press", source_ids)
        self.assertIn("cnbc_indonesia", source_ids)
        self.assertIn("blockworks", source_ids)

    def test_news_runtime_citations_assignment(self):
        """Verifies deterministic citation numbering and real URL retention."""
        runtime = NewsIntelligenceRuntime(self.root)
        result = runtime.get_relevant_news_with_citations("crypto", limit=2)
        self.assertIn("items", result)
        self.assertIn("citations_text", result)
        if result["items"]:
            first = result["items"][0]
            self.assertEqual(first["citation_id"], "[1]")
            self.assertTrue(first["article_url"].startswith("http"))
            self.assertIn("[1]", result["citations_text"])

    def test_contextual_cli_help(self):
        """Verifies that contextual help runs without error and covers requested topics."""
        import io
        import sys
        shell = OpenBagusShell()
        buf = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = buf
            shell.do_help("news")
            out_news = buf.getvalue()

            buf = io.StringIO()
            sys.stdout = buf
            shell.do_help("idx")
            out_idx = buf.getvalue()

            buf = io.StringIO()
            sys.stdout = buf
            shell.do_help("quant")
            out_quant = buf.getvalue()

            buf = io.StringIO()
            sys.stdout = buf
            shell.do_help("arbitrage")
            out_arb = buf.getvalue()

            buf = io.StringIO()
            sys.stdout = buf
            shell.do_help("")
            out_full = buf.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("News Intelligence", out_news)
        self.assertIn("Indonesian Equities (IDX)", out_idx)
        self.assertIn("Quant Strategies", out_quant)
        self.assertIn("Arbitrage", out_arb)
        self.assertIn("OPENBAGUS FINANCIAL INTELLIGENCE HELP", out_full)

    def test_reproducibility_of_evidence_packet(self):
        """Given same research inputs, evidence packet outputs identical numbers."""
        packet = ResearchPacket(
            asset="ETH",
            market="PERPETUAL",
            timeframe="H1",
            price=3500.0,
            decision="BUY",
            data_quality="HIGH",
            setup_quality="HIGH",
            stop_price=3400.0,
            tp1=3700.0,
        )
        ep1 = build_evidence_packet_from_research(packet)
        ep2 = build_evidence_packet_from_research(packet)
        self.assertEqual(ep1.get_valid_numbers(), ep2.get_valid_numbers())
        self.assertIsNotNone(ep1.derived_setup)
        self.assertEqual(ep1.derived_setup.net_rr, ep2.derived_setup.net_rr)


if __name__ == "__main__":
    unittest.main()
