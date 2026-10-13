"""End-to-end tests for financial intelligence, statement reading, and automated valuation engine.

Verifies:
1. US Equities valuation multiples & DCF scenario model in USD (e.g. AAPL, MSFT).
2. Banking valuation (Excess Return model) with NIM, CAR, NPL, BVPS, and corporate FCF marked NOT_APPLICABLE.
3. Non-financial corporate DCF with dual 2D sensitivity matrices and DuPont 3-stage / 5-stage analysis.
4. Mathematical guards for negative earnings (PER marked NOT_MEANINGFUL).
5. Natural language fundamental breakdowns (DCF intrinsic value, solvency check, earnings quality).
6. Side-by-side multi-stock fundamental comparison table generation.
"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from openbagus.domains.equities.catalog import EquityCatalog
from openbagus.domains.equities.data import CanonicalFinancialStatement, EquityData
from openbagus.domains.equities.storage import FinancialStatementStorage
from openbagus.domains.equities.valuation import (
    calculate_valuation_multiples,
    dupont_analysis,
    evaluate_earnings_quality,
    dcf_scenario_model,
)
from openbagus.domains.equities.research import (
    run_equity_research,
    _render_equity_followup,
)


class TestFinancialValuationE2E(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.storage = FinancialStatementStorage(self.root)
        self.catalog = EquityCatalog(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. US Equities Valuation Multiples & DCF (USD)
    # -------------------------------------------------------------------------
    def test_us_equity_valuation_multiples_and_dcf(self) -> None:
        stmt = {
            "symbol": "AAPL",
            "period": "2024-FY",
            "period_type": "FY",
            "currency": "USD",
            "unit": "USD",
            "basis": "consolidated",
            "values": {
                "revenue": 391_035_000_000.0,
                "cost_of_revenue": 210_352_000_000.0,
                "gross_profit": 180_683_000_000.0,
                "operating_income": 123_216_000_000.0,
                "net_income": 93_736_000_000.0,
                "net_income_attributable": 93_736_000_000.0,
                "total_assets": 364_980_000_000.0,
                "total_liabilities": 308_030_000_000.0,
                "interest_bearing_debt": 106_629_000_000.0,
                "equity": 56_950_000_000.0,
                "operating_cash_flow": 118_264_000_000.0,
                "capital_expenditure": 9_453_000_000.0,
                "cash_and_equivalents": 29_942_000_000.0,
                "shares_outstanding": 15_204_137_000.0,
            },
            "reported_ratios_pct": {},
        }

        price = 225.0
        multiples_res = calculate_valuation_multiples(
            statement=stmt,
            price=price,
            shares_outstanding=15_204_137_000.0,
            sector="Technology",
        )

        self.assertEqual(multiples_res["currency"], "USD")
        mults = multiples_res["multiples"]
        ratios = multiples_res["ratios"]

        # Market Cap & Multiples
        expected_mcap = price * 15_204_137_000.0
        self.assertAlmostEqual(mults["Market_Cap"], expected_mcap, delta=1000.0)
        expected_per = expected_mcap / 93_736_000_000.0
        self.assertAlmostEqual(mults["PER"], expected_per, places=2)
        expected_pbv = expected_mcap / 56_950_000_000.0
        self.assertAlmostEqual(mults["PBV"], expected_pbv, places=2)

        # FCF Yield = (118,264M - 9,453M) / Market Cap
        fcf = 118_264_000_000.0 - 9_453_000_000.0
        expected_fcf_yield = (fcf / expected_mcap) * 100.0
        self.assertAlmostEqual(mults["FCF_Yield_pct"], expected_fcf_yield, places=2)

        # DCF Model in USD
        dcf_res = dcf_scenario_model(
            statement=stmt,
            price=price,
            shares_outstanding=15_204_137_000.0,
            sector="Technology",
        )
        self.assertEqual(dcf_res["status"], "COMPLETED")
        self.assertEqual(dcf_res["currency"], "USD")
        self.assertEqual(dcf_res["model_type"], "FCF_DISCOUNTED_CASH_FLOW")
        self.assertIn("Base", dcf_res["scenarios"])
        self.assertIn("Bull", dcf_res["scenarios"])
        self.assertIn("Bear", dcf_res["scenarios"])
        self.assertGreater(dcf_res["scenarios"]["Base"]["intrinsic_value_per_share"], 0.0)
        self.assertIn("sensitivity_wacc_terminal_growth", dcf_res)
        self.assertIn("sensitivity_margin_revenue_growth", dcf_res)

    # -------------------------------------------------------------------------
    # 2. Banking Valuation: Excess Return Model (BBCA / BBRI)
    # -------------------------------------------------------------------------
    def test_banking_valuation_excess_return_and_fcf_exclusion(self) -> None:
        bank_stmt = {
            "symbol": "BBCA",
            "period": "2024-FY",
            "period_type": "FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "basis": "consolidated",
            "values": {
                "revenue": 100_000_000.0,
                "net_income": 53_000_000.0,
                "net_income_attributable": 53_000_000.0,
                "total_assets": 1_400_000_000.0,
                "total_liabilities": 1_150_000_000.0,
                "equity": 250_000_000.0,
                "equity_attributable": 250_000_000.0,
                "shares_outstanding": 123_275_050_000.0,
            },
            "reported_ratios_pct": {
                "NIM": 5.8,
                "CAR": 29.4,
                "NPL_gross": 1.8,
            },
        }

        price = 10_000.0
        multiples_res = calculate_valuation_multiples(
            statement=bank_stmt,
            price=price,
            shares_outstanding=123_275_050_000.0,
            sector="Financials",
        )

        # Corporate FCF multiples should be NOT_APPLICABLE for banks
        self.assertEqual(multiples_res["multiples"]["P_FCF_note"], "NOT_APPLICABLE (Sektor Perbankan/Keuangan)")
        self.assertEqual(multiples_res["multiples"]["FCF_Yield_note"], "NOT_APPLICABLE (Sektor Perbankan/Keuangan)")

        # Excess Return Valuation
        dcf_res = dcf_scenario_model(
            statement=bank_stmt,
            price=price,
            shares_outstanding=123_275_050_000.0,
            sector="Financials",
        )
        self.assertEqual(dcf_res["status"], "COMPLETED")
        self.assertEqual(dcf_res["model_type"], "EXCESS_RETURN_BANK_MODEL")
        self.assertIn("Base", dcf_res["scenarios"])
        self.assertGreater(dcf_res["bvps"], 0.0)

    # -------------------------------------------------------------------------
    # 3. Non-Financial Corporate DCF & DuPont (TLKM / ASII)
    # -------------------------------------------------------------------------
    def test_non_financial_dcf_and_dupont(self) -> None:
        stmt = {
            "symbol": "TLKM",
            "period": "2024-FY",
            "period_type": "FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "basis": "consolidated",
            "values": {
                "revenue": 150_000_000.0,
                "cost_of_revenue": 75_000_000.0,
                "gross_profit": 75_000_000.0,
                "operating_income": 45_000_000.0,
                "profit_before_tax": 38_000_000.0,
                "net_income": 25_000_000.0,
                "net_income_attributable": 25_000_000.0,
                "total_assets": 280_000_000.0,
                "total_liabilities": 130_000_000.0,
                "interest_bearing_debt": 60_000_000.0,
                "equity": 150_000_000.0,
                "equity_attributable": 150_000_000.0,
                "operating_cash_flow": 55_000_000.0,
                "capital_expenditure": 30_000_000.0,
                "cash_and_equivalents": 25_000_000.0,
                "shares_outstanding": 99_062_216_600.0,
            },
            "reported_ratios_pct": {},
        }

        # DuPont Analysis
        dupont_res = dupont_analysis(stmt)
        self.assertEqual(dupont_res["status"], "COMPLETED")
        self.assertIsNotNone(dupont_res["three_stage"])
        self.assertIsNotNone(dupont_res["five_stage"])
        self.assertAlmostEqual(
            dupont_res["three_stage"]["net_profit_margin_pct"],
            (25_000_000.0 / 150_000_000.0) * 100.0,
            places=1,
        )

        # DCF Dual Sensitivity Matrices
        dcf_res = dcf_scenario_model(
            statement=stmt,
            price=3000.0,
            shares_outstanding=99_062_216_600.0,
            sector="Infrastruktur",
        )
        self.assertEqual(dcf_res["status"], "COMPLETED")
        self.assertEqual(dcf_res["model_type"], "FCF_DISCOUNTED_CASH_FLOW")

        # Verify dual sensitivity matrices
        wacc_tg = dcf_res["sensitivity_wacc_terminal_growth"]
        self.assertEqual(len(wacc_tg), 5)
        self.assertIn("g_2.0%", wacc_tg[0])
        self.assertIn("g_3.0%", wacc_tg[0])

        margin_rev = dcf_res["sensitivity_margin_revenue_growth"]
        self.assertEqual(len(margin_rev), 3)
        self.assertIn("rev_g_5.0%", margin_rev[0])
        self.assertIn("rev_g_10.0%", margin_rev[0])

    # -------------------------------------------------------------------------
    # 4. Negative Earnings Guards
    # -------------------------------------------------------------------------
    def test_negative_earnings_guard(self) -> None:
        loss_stmt = {
            "symbol": "GOTO",
            "period": "2024-FY",
            "period_type": "FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "basis": "consolidated",
            "values": {
                "revenue": 15_000_000.0,
                "gross_profit": 5_000_000.0,
                "operating_income": -3_000_000.0,
                "net_income": -4_500_000.0,
                "net_income_attributable": -4_500_000.0,
                "total_assets": 40_000_000.0,
                "total_liabilities": 10_000_000.0,
                "interest_bearing_debt": 2_000_000.0,
                "equity": 30_000_000.0,
                "shares_outstanding": 1_200_000_000_000.0,
            },
            "reported_ratios_pct": {},
        }

        multiples_res = calculate_valuation_multiples(
            statement=loss_stmt,
            price=60.0,
            shares_outstanding=1_200_000_000_000.0,
            sector="Teknologi",
        )

        mults = multiples_res["multiples"]
        ratios = multiples_res["ratios"]

        # PER must be None with explanation note
        self.assertIsNone(mults["PER"])
        self.assertIn("N/M", mults["PER_note"])

        # Fundamental non-price ratios must still calculate accurately
        self.assertAlmostEqual(ratios["Gross_Margin_pct"], (5_000_000.0 / 15_000_000.0) * 100.0, places=1)
        self.assertAlmostEqual(ratios["Debt_to_Equity"], 2_000_000.0 / 30_000_000.0, places=2)

    # -------------------------------------------------------------------------
    # 5. Natural Language Fundamental Breakdowns
    # -------------------------------------------------------------------------
    def test_natural_language_valuation_followup(self) -> None:
        stmt = {
            "symbol": "ASII",
            "period": "2024-FY",
            "period_type": "FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "basis": "konsolidasian",
            "values": {
                "revenue": 300_000_000.0,
                "gross_profit": 60_000_000.0,
                "operating_income": 40_000_000.0,
                "net_income": 30_000_000.0,
                "net_income_attributable": 30_000_000.0,
                "total_assets": 400_000_000.0,
                "total_liabilities": 180_000_000.0,
                "interest_bearing_debt": 70_000_000.0,
                "equity": 220_000_000.0,
                "equity_attributable": 220_000_000.0,
                "operating_cash_flow": 45_000_000.0,
                "capital_expenditure": 20_000_000.0,
                "cash_and_equivalents": 50_000_000.0,
                "shares_outstanding": 40_483_553_140.0,
            },
            "reported_ratios_pct": {},
        }
        self.storage.store_statement(stmt)

        asset = self.catalog.resolve("ASII")
        runner = SimpleNamespace(root=self.root)
        quant = SimpleNamespace(price=5000.0, timeframe="D1", decision="WAIT", decision_reason="P/E fair")
        packet = SimpleNamespace(fundamentals=stmt, sources=["https://idx.co.id/ASII.pdf"])

        # Test: Intrinsic Value / DCF query
        resp_dcf = _render_equity_followup(runner, None, asset, packet, quant, "Berapa intrinsic value ASII?")
        self.assertIn("Valuasi Intrinsik ASII", resp_dcf)
        self.assertIn("Skenario Proyeksi", resp_dcf)
        self.assertIn("Matriks Sensitivitas", resp_dcf)

        # Test: Debt safety / Solvency query
        resp_debt = _render_equity_followup(runner, None, asset, packet, quant, "Apakah utang ASII aman?")
        self.assertIn("Analisis Keamanan Utang & Solvabilitas ASII", resp_debt)
        self.assertIn("Debt to Equity (DER)", resp_debt)

        # Test: Earnings Quality / OCF conversion query
        resp_eq = _render_equity_followup(runner, None, asset, packet, quant, "Kenapa laba naik tetapi arus kas turun?")
        self.assertIn("Evaluasi Kualitas Laba & Divergensi Kas ASII", resp_eq)
        self.assertIn("Rasio Konversi Kas", resp_eq)

    # -------------------------------------------------------------------------
    # 6. Side-by-Side Multi-Stock Comparison Table
    # -------------------------------------------------------------------------
    def test_side_by_side_comparison_table(self) -> None:
        runner = SimpleNamespace(
            root=self.root,
            assets=SimpleNamespace(equities=self.catalog),
        )
        req = SimpleNamespace(
            request_type="COMPARE",
            target_assets=["BBCA", "BBRI"],
            raw_query="compare BBCA BBRI",
            asset="",
            asset_type="EQUITY_ID",
        )

        res = run_equity_research(runner, req)
        self.assertIn("Perbandingan Fundamental Saham (BBCA, BBRI)", res)
        self.assertIn("BBCA", res)
        self.assertIn("BBRI", res)
        self.assertIn("Catatan Integritas", res)


if __name__ == "__main__":
    unittest.main()
