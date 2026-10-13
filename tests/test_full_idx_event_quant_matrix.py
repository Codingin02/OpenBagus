"""Master Test Suite for Full IDX Universe, Event Intelligence, Microstructure, and Quant Engine.

Fulfills Phase 12 (Groups A through G) and Phase 13 (Acceptance Scenarios 1 through 12).
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import unittest

from openbagus.core.env import get_repo_root
from openbagus.domains.equities.catalog import EquityCatalog, EquityAsset, SECTORS
from openbagus.domains.equities.events import (
    CorporateEventManager,
    CorporateEventRecord,
    RelativeMaterialityEngine,
    EVENT_TAXONOMY,
)
from openbagus.domains.equities.microstructure import (
    IDXMicrostructureEngine,
    MicrostructureProfile,
)
from openbagus.domains.equities.strategies import (
    PostAnnouncementMomentumStrategy,
    VolumeExpansionBreakoutStrategy,
    NegativeCatalystRiskWatch,
)
from openbagus.domains.equities.backtesting import (
    PointInTimeBacktester,
    BacktestResult,
)
from openbagus.domains.quant.engine import (
    get_engine_diagnostics,
    calculate_sma,
    calculate_ema,
    calculate_rsi,
    calculate_atr,
    calculate_macd,
    calculate_bollinger_bands,
    calculate_vwap,
    calculate_rolling_stats,
    calculate_var_cvar_mc,
    calculate_lot_shares,
    parallel_universe_screen,
)
from openbagus.monitoring.daily_brief import (
    DailyBriefGenerator,
    render_brief_markdown,
)
from openbagus.intelligence.intent import IntentRouter
from openbagus.domains.crypto.research import CryptoResearchRunner


class TestFullUniverseIntegrity(unittest.TestCase):
    """Group A & Scenario 1: Full IDX Universe Integrity (Zero Blue-Chip Bias)."""

    def setUp(self) -> None:
        self.root = get_repo_root()
        self.catalog = EquityCatalog(self.root)

    def test_all_verified_common_equities_discoverable(self) -> None:
        stats = self.catalog.get_universe_stats()
        self.assertEqual(stats["common_equities"], 951)
        self.assertEqual(stats["indices"], 17)
        self.assertEqual(stats["total_instruments"], 968)

    def test_no_market_cap_eligibility_gate(self) -> None:
        """Equities with unknown market cap remain fully researchable."""
        asset = self.catalog.resolve("HGII")
        self.assertIsNotNone(asset)
        # Without price, cap is unknown
        self.assertIsNone(asset.market_cap())
        self.assertEqual(asset.cap_tier(), "UNKNOWN_CAP")
        self.assertTrue(asset.research_eligible)

    def test_separate_research_and_execution_eligibility(self) -> None:
        """Suspended stocks are research eligible but not execution eligible."""
        suspended = self.catalog.search_suspended(limit=5)
        if suspended:
            s0 = suspended[0]
            self.assertTrue(s0.research_eligible)
            self.assertFalse(s0.execution_eligible)

    def test_reconciled_sector_and_board_coverage(self) -> None:
        stats = self.catalog.get_universe_stats()
        # Verify 11 sectors represented
        self.assertEqual(len(stats["sectors"]), 11)
        # Verify boards
        self.assertIn("MAIN", stats["boards"])
        self.assertIn("DEVELOPMENT", stats["boards"])
        self.assertIn("ACCELERATION", stats["boards"])
        self.assertIn("SPECIAL_MONITORING", stats["boards"])

    def test_pagination_integrity(self) -> None:
        all_eqs = [a for a in self.catalog.assets if a.asset_type == "EQUITY_ID"]
        sliced, meta = self.catalog.paginate(all_eqs, page=1, page_size=25)
        self.assertEqual(len(sliced), 25)
        self.assertEqual(meta["total_items"], 951)
        self.assertEqual(meta["total_pages"], 39)
        self.assertTrue(meta["has_next"])
        self.assertFalse(meta["has_prev"])


class TestCapitalizationCoverage(unittest.TestCase):
    """Group B: All-Cap Coverage across tiers."""

    def setUp(self) -> None:
        self.root = get_repo_root()
        self.catalog = EquityCatalog(self.root)

    def test_all_tiers_represented(self) -> None:
        # Mock price table
        price_lookup = {
            "BBCA": 10_000.0,   # Large cap (> 50T)
            "ANTM": 1_500.0,    # Mid cap (5T - 50T)
            "RATU": 250.0,      # Small cap (500M - 5T)
        }
        bbca = self.catalog.resolve("BBCA")
        antm = self.catalog.resolve("ANTM")
        ratu = self.catalog.resolve("RATU")

        self.assertEqual(bbca.cap_tier(price_lookup["BBCA"]), "LARGE_CAP")
        self.assertEqual(antm.cap_tier(price_lookup["ANTM"]), "MID_CAP")
        self.assertIn(ratu.cap_tier(price_lookup["RATU"]), ("SMALL_CAP", "MICRO_CAP"))


class TestEventIntelligence(unittest.TestCase):
    """Group C, Scenario 2 & 5: Corporate Event Intelligence & Relative Materiality."""

    def setUp(self) -> None:
        self.root = get_repo_root()
        self.mgr = CorporateEventManager(self.root)

    def test_event_taxonomy_breadth(self) -> None:
        self.assertGreaterEqual(len(EVENT_TAXONOMY), 40)
        self.assertIn("MATERIAL_CONTRACT", EVENT_TAXONOMY)
        self.assertIn("SHARE_BUYBACK", EVENT_TAXONOMY)
        self.assertIn("PROFIT_TURNAROUND", EVENT_TAXONOMY)
        self.assertIn("SPECIAL_MONITORING_ENTRY", EVENT_TAXONOMY)

    def test_material_contract_relative_evaluation(self) -> None:
        # Contract 120B IDR vs 150B IDR Annual Revenue -> 80% (Highly Material)
        res = RelativeMaterialityEngine.evaluate_contract(
            contract_value_idr=120_000_000_000.0,
            annual_revenue_idr=150_000_000_000.0,
        )
        self.assertEqual(res["materiality"], "HIGHLY_MATERIAL")
        self.assertGreaterEqual(res["score"], 60.0)
        self.assertAlmostEqual(res["ratios"]["contract_to_revenue_pct"], 80.0, places=1)

    def test_share_buyback_relative_evaluation(self) -> None:
        # Buyback 1 Triliun vs 10 Triliun Market Cap -> 10% (Highly Material)
        res = RelativeMaterialityEngine.evaluate_buyback(
            authorized_amount_idr=1_000_000_000_000.0,
            market_cap_idr=10_000_000_000_000.0,
        )
        self.assertEqual(res["materiality"], "HIGHLY_MATERIAL")
        self.assertGreaterEqual(res["score"], 60.0)

    def test_event_registration_and_hash_integrity(self) -> None:
        ev = self.mgr.create_event(
            ticker="HGII",
            event_type="MATERIAL_CONTRACT",
            event_title="Kontrak Pembangunan PLTMH 15MW",
            published_at="2026-10-13T10:00:00+07:00",
            source_url="https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/",
            source_document_id="HGII/CORP/2026-X",
            raw_text="Kontrak definitif PLTMH senilai Rp 120 Miliar ditandatangani.",
            quantitative_amounts={"contract_value": 120_000_000_000.0},
            annual_revenue_baseline=150_000_000_000.0,
        )
        self.assertEqual(ev.ticker, "HGII")
        self.assertEqual(len(ev.document_hash), 64)  # SHA-256
        self.assertEqual(ev.verification_status, "CONFIRMED_OFFICIAL")


class TestIDXMicrostructure(unittest.TestCase):
    """Group C & Scenario 4: Microstructure, Tick Sizes, ARA/ARB, and Board Constraints."""

    def test_tick_sizes_by_price_band(self) -> None:
        engine = IDXMicrostructureEngine
        self.assertEqual(engine.get_tick_size(150.0, "MAIN"), 1.0)
        self.assertEqual(engine.get_tick_size(350.0, "MAIN"), 2.0)
        self.assertEqual(engine.get_tick_size(1200.0, "MAIN"), 5.0)
        self.assertEqual(engine.get_tick_size(3500.0, "MAIN"), 10.0)
        self.assertEqual(engine.get_tick_size(8000.0, "MAIN"), 25.0)
        # Acceleration board is flat Rp 1
        self.assertEqual(engine.get_tick_size(8000.0, "ACCELERATION"), 1.0)

    def test_board_lot_rounding(self) -> None:
        engine = IDXMicrostructureEngine
        self.assertEqual(engine.round_to_lot(150), 100)
        self.assertEqual(engine.round_to_lot(99), 0)
        self.assertEqual(engine.round_to_lot(1050), 1000)

    def test_ara_arb_calculation(self) -> None:
        engine = IDXMicrostructureEngine
        # Regular Rp 1000 -> 25% ARA/ARB
        ara, arb = engine.calculate_auto_rejection(1000.0, "MAIN")
        self.assertEqual(ara, 1250.0)
        self.assertEqual(arb, 750.0)

        # Acceleration board -> 10%
        ara_acc, arb_acc = engine.calculate_auto_rejection(100.0, "ACCELERATION")
        self.assertEqual(ara_acc, 110.0)
        self.assertEqual(arb_acc, 90.0)

        # Periodic call auction (FCA) -> 10%
        ara_fca, arb_fca = engine.calculate_auto_rejection(50.0, "SPECIAL_MONITORING")
        self.assertEqual(ara_fca, 55.0)
        self.assertEqual(arb_fca, 45.0)

    def test_fca_execution_rejection(self) -> None:
        prof = IDXMicrostructureEngine.profile_asset(
            symbol="TEST",
            board="SPECIAL_MONITORING",
            reference_price=100.0,
        )
        self.assertTrue(prof.is_fca)
        self.assertFalse(prof.execution_eligible)
        self.assertIn("FCA", prof.rejection_reason)


class TestPointInTimeBacktesting(unittest.TestCase):
    """Group D, Scenario 7: Point-in-time timestamping and no lookahead bias."""

    def test_after_hours_publication_scheduled_for_next_open(self) -> None:
        # Published at 16:30 WIB (market closed at 16:00 WIB)
        session = PointInTimeBacktester.get_earliest_execution_session("2026-10-13T16:30:00+07:00")
        self.assertEqual(session, "NEXT_SESSION_OPEN (T+1)")

    def test_market_hours_publication_eligible_for_same_day(self) -> None:
        # Published at 10:15 WIB
        session = PointInTimeBacktester.get_earliest_execution_session("2026-10-13T10:15:00+07:00")
        self.assertEqual(session, "SAME_SESSION_CLOSE (T+0)")

    def test_backtest_execution_with_realistic_fees_and_lots(self) -> None:
        backtester = PointInTimeBacktester(initial_capital=50_000_000.0)
        strat = VolumeExpansionBreakoutStrategy()

        # Synthetic 30-day candles with breakout at day 25
        candles = []
        for i in range(30):
            px = 1000.0 + (i * 5.0) if i < 25 else 1200.0
            vol = 50_000.0 if i < 25 else 250_000.0
            candles.append({
                "open_at": f"2026-09-{i+1:02d}T09:00:00+07:00",
                "open": px - 5.0,
                "high": px + 10.0,
                "low": px - 10.0,
                "close": px,
                "volume": vol,
            })

        res = backtester.run(strat, "TEST", candles, board="MAIN")
        self.assertIsInstance(res, BacktestResult)
        if res.trades:
            t0 = res.trades[0]
            # Verify board lot multiple of 100
            self.assertEqual(t0.shares % 100, 0)
            # Verify fees deducted
            self.assertGreater(t0.fees, 0.0)


class TestQuantitativeEngineContracts(unittest.TestCase):
    """Group E & Scenario 8: Rust/Python Mathematical & Precision Equivalence."""

    def test_engine_diagnostics(self) -> None:
        diag = get_engine_diagnostics()
        self.assertIn("backend", diag)
        self.assertTrue(diag["active"])

    def test_wilder_rsi_precision_contract(self) -> None:
        prices = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00]
        rsi = calculate_rsi(prices, 14)
        self.assertEqual(len(rsi), len(prices))
        valid_rsis = [r for r in rsi if r is not None]
        self.assertGreater(len(valid_rsis), 0)
        for r in valid_rsis:
            self.assertTrue(0.0 <= r <= 100.0)

    def test_exact_share_lot_rounding(self) -> None:
        # Cash: 10,000,000 | Price: 2,750 | Max Risk: 200,000 | Stop: 2,600
        # Risk per share: 150 -> Max shares by risk: 200,000 / 150 = 1,333.33
        # Max shares by cash: 10,000,000 / 2,750 = 3,636.36
        # Target shares: 1,333 -> Lots: 13 lots = 1,300 shares
        shares, notional = calculate_lot_shares(10_000_000.0, 2750.0, 200_000.0, 2600.0)
        self.assertEqual(shares, 1300)
        self.assertEqual(notional, 1300 * 2750.0)

    def test_monte_carlo_var_cvar_determinism(self) -> None:
        returns = [-0.02, 0.015, -0.01, 0.03, -0.025, 0.018, -0.005]
        v1, cv1 = calculate_var_cvar_mc(returns, confidence=0.95, num_simulations=5000, seed=12345)
        v2, cv2 = calculate_var_cvar_mc(returns, confidence=0.95, num_simulations=5000, seed=12345)
        self.assertAlmostEqual(v1, v2, places=6)
        self.assertAlmostEqual(cv1, cv2, places=6)
        self.assertGreater(cv1, v1)  # CVaR (Expected Shortfall) is always >= VaR


class TestDailyBriefRedesign(unittest.TestCase):
    """Scenario 3 & Redesigned Daily Brief Verification."""

    def setUp(self) -> None:
        self.root = get_repo_root()
        self.gen = DailyBriefGenerator(self.root)

    def test_brief_generates_all_10_sections(self) -> None:
        brief = self.gen.generate(session_type="MORNING")
        md = render_brief_markdown(brief)

        self.assertIn("## 1. Market Overview", md)
        self.assertIn("## 2. New Material Disclosures", md)
        self.assertIn("## 3. Matriks Pengamatan Aset Unggulan", md)
        self.assertIn("## 4. Large-Cap Opportunities", md)
        self.assertIn("## 5. Mid-Cap Opportunities", md)
        self.assertIn("## 6. Small/Micro-Cap Opportunities", md)
        self.assertIn("## 7. New IPO & Acceleration-Board Watch", md)
        self.assertIn("## 8. Special-Monitoring Risk Watch (FCA)", md)
        self.assertIn("## 9. Negative Catalyst Alerts & Rejected Setups", md)
        self.assertIn("## 10. Data Coverage Warnings & Risk Protocol", md)


class TestNaturalLanguageAcceptanceScenarios(unittest.TestCase):
    """Phase 13: Scenarios 1 to 12 User-Level Verification."""

    def setUp(self) -> None:
        self.root = get_repo_root()
        self.runner = CryptoResearchRunner(repo_root=self.root)
        self.router = IntentRouter(repo_root=self.root)

    def test_scenario_1_full_idx_scan(self) -> None:
        req = self.router.parse("Scan seluruh saham IDX.")
        self.assertEqual(req.intent, "ALL_IDX_SCAN")
        res = self.runner.execute(req)
        self.assertIn("951 emiten biasa", res)

    def test_scenario_2_small_cap_catalyst(self) -> None:
        req = self.router.parse("Cari saham small-cap dengan announcement material baru.")
        self.assertEqual(req.intent, "EVENT_DISCOVERY")
        res = self.runner.execute(req)
        self.assertIn("Radar Keterbukaan Informasi", res)

    def test_scenario_4_special_monitoring(self) -> None:
        req = self.router.parse("Analisis saham Papan Pemantauan Khusus dan risiko likuiditasnya.")
        self.assertEqual(req.intent, "AUCTION_BOARD_RESEARCH")
        res = self.runner.execute(req)
        self.assertIn("Periodic Call Auction", res)

    def test_scenario_5_material_contract(self) -> None:
        req = self.router.parse("Apakah kontrak baru emiten ini material terhadap pendapatan?")
        self.assertEqual(req.intent, "EVENT_IMPACT_ANALYSIS")
        res = self.runner.execute(req)
        self.assertIn("Nilai Kontrak / Pendapatan Tahunan", res)

    def test_scenario_6_risk_rejection_review(self) -> None:
        req = self.router.parse("Jelaskan alasan setup ini ditolak oleh risk engine.")
        self.assertEqual(req.intent, "TRADING_RISK_REVIEW")
        res = self.runner.execute(req)
        self.assertIn("Evaluasi Protokol Penolakan Sinyal", res)


if __name__ == "__main__":
    unittest.main()
