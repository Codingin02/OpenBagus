"""Comprehensive mathematical and sector-integrity tests for financial calculations.

Verifies:
- True beginning/ending balance averages for ROE/ROA.
- Interest-bearing debt distinction from total liabilities.
- Non-financial corporate FCF (OCF - Capex) vs banking sector NOT_MEANINGFUL exclusion.
- Multiples with negative earnings/equity guards.
- DuPont 3-stage and 5-stage models.
- Earnings quality & cash conversion ratio.
- Multi-scenario DCF and banking Excess Return models.
- Cross-sector validation across all 11 IDX-IC sectors.
"""

import unittest

from openbagus.domains.equities.catalog import SECTORS
from openbagus.domains.equities.data import fundamentals, validate_statement
from openbagus.domains.equities.valuation import (
    calculate_valuation_multiples,
    dupont_analysis,
    evaluate_earnings_quality,
    dcf_scenario_model,
)


class TestFinancialCalculations(unittest.TestCase):
    def test_beginning_ending_balance_averages(self):
        # 2024 statement
        stmt_2024 = {
            "symbol": "ICBP",
            "source": "https://www.idx.co.id/filings/ICBP_2024.json",
            "published_at": "2025-03-25T09:00:00+07:00",
            "currency": "IDR",
            "unit": "million_IDR",
            "period": "2024-FY",
            "period_type": "FY",
            "basis": "consolidated",
            "values": {
                "revenue": 70000,
                "net_income_attributable": 9000,
                "equity_attributable": 45000, # Ending 2024
                "total_assets": 125000,        # Ending 2024
                "shares_outstanding": 11661908000,
                "weighted_average_shares": 11661908000,
            },
            "reported_ratios_pct": {},
        }

        # 2023 statement (prior period)
        stmt_2023 = {
            "symbol": "ICBP",
            "source": "https://www.idx.co.id/filings/ICBP_2023.json",
            "published_at": "2024-03-25T09:00:00+07:00",
            "currency": "IDR",
            "unit": "million_IDR",
            "period": "2023-FY",
            "period_type": "FY",
            "basis": "consolidated",
            "values": {
                "revenue": 65000,
                "net_income_attributable": 7500,
                "equity_attributable": 35000, # Ending 2023 (Beginning 2024)
                "total_assets": 115000,        # Ending 2023 (Beginning 2024)
            },
            "reported_ratios_pct": {},
        }

        # Without previous statement: basis is point_in_time ending
        res_standalone = fundamentals(stmt_2024, price=10500)
        # ROE = 9,000 / 45,000 = 20.0%
        self.assertAlmostEqual(res_standalone["ratios"]["ROE_pct"], 20.0, places=2)
        self.assertEqual(res_standalone["ratios"]["average_equity_basis"], "ending_balance_point_in_time")

        # With previous statement: true average = (45,000 + 35,000) / 2 = 40,000
        # ROE = 9,000 / 40,000 = 22.5%
        res_with_prev = fundamentals(stmt_2024, price=10500, previous=stmt_2023)
        self.assertAlmostEqual(res_with_prev["ratios"]["ROE_pct"], 22.5, places=2)
        self.assertEqual(res_with_prev["ratios"]["average_equity_basis"], "two_point_average")
        # Average assets = (125,000 + 115,000) / 2 = 120,000
        # ROA = 9,000 / 120,000 = 7.5%
        self.assertAlmostEqual(res_with_prev["ratios"]["ROA_pct"], 7.5, places=2)
        self.assertEqual(res_with_prev["ratios"]["average_assets_basis"], "two_point_average")

    def test_debt_to_equity_vs_total_liabilities_distinction(self):
        # Case A: Interest-bearing debt is known
        stmt_with_debt = {
            "source": "https://www.idx.co.id/test.json",
            "published_at": "2025-01-01T00:00:00+00:00",
            "currency": "IDR",
            "unit": "million_IDR",
            "period": "2024-FY",
            "period_type": "FY",
            "basis": "consolidated",
            "values": {
                "total_liabilities": 50000,
                "interest_bearing_debt": 15000, # Only bank debt/bonds
                "equity": 30000,
            },
            "reported_ratios_pct": {},
        }
        res_a = fundamentals(stmt_with_debt, None)
        # DER = 15,000 / 30,000 = 0.50x
        self.assertAlmostEqual(res_a["ratios"]["Debt_to_Equity"], 0.50, places=2)
        self.assertNotIn("Total_Liabilities_to_Equity", res_a["ratios"])

        # Case B: Interest-bearing debt is missing (only total liabilities reported)
        stmt_no_debt = {
            "source": "https://www.idx.co.id/test.json",
            "published_at": "2025-01-01T00:00:00+00:00",
            "currency": "IDR",
            "unit": "million_IDR",
            "period": "2024-FY",
            "period_type": "FY",
            "basis": "consolidated",
            "values": {
                "total_liabilities": 50000,
                "equity": 30000,
            },
            "reported_ratios_pct": {},
        }
        res_b = fundamentals(stmt_no_debt, None)
        # Total liabilities fallback
        self.assertIn("Total_Liabilities_to_Equity", res_b["ratios"])
        self.assertAlmostEqual(res_b["ratios"]["Total_Liabilities_to_Equity"], 1.667, places=2)
        self.assertEqual(res_b["ratios"]["Debt_to_Equity"], res_b["ratios"]["Total_Liabilities_to_Equity"])

    def test_banking_fcf_exclusion_and_metrics(self):
        bank_stmt = {
            "symbol": "BBCA",
            "sector": "Financials",
            "source": "https://www.idx.co.id/filings/BBCA.json",
            "published_at": "2025-02-01T00:00:00+00:00",
            "currency": "IDR",
            "unit": "million_IDR",
            "period": "2024-FY",
            "period_type": "FY",
            "basis": "consolidated",
            "values": {
                "operating_cash_flow": 45000000, # Includes customer deposit swings
                "capital_expenditure": 5000000,
                "net_income_attributable": 48000000,
                "equity_attributable": 240000000,
                "shares_outstanding": 123275000000,
            },
            "reported_ratios_pct": {
                "NIM": 5.5,
                "CAR": 27.0,
                "NPL_gross": 1.8,
                "CASA": 80.5,
                "LDR": 72.0,
            },
        }

        # 1. In fundamentals()
        res = fundamentals(bank_stmt, price=10000)
        self.assertIsNone(res["ratios"]["FCF_IDR"])
        self.assertEqual(res["ratios"]["FCF_status"], "NOT_MEANINGFUL")
        self.assertIn("Perbankan", res["ratios"]["FCF_note"])
        self.assertEqual(res["ratios"]["NIM_pct"], 5.5)
        self.assertEqual(res["ratios"]["CAR_pct"], 27.0)

        # 2. In calculate_valuation_multiples()
        mults = calculate_valuation_multiples(bank_stmt, price=10000, sector="Financials")
        self.assertIsNone(mults["multiples"]["FCF_IDR"])
        self.assertEqual(mults["multiples"]["FCF_status"], "NOT_APPLICABLE")
        self.assertNotIn("FCF_Yield_pct", mults["multiples"])

        # 3. Bank DCF -> Excess Return Model
        dcf_bank = dcf_scenario_model(bank_stmt, price=10000, sector="Financials")
        self.assertEqual(dcf_bank["model_type"], "EXCESS_RETURN_BANK_MODEL")
        self.assertIn("Base", dcf_bank["scenarios"])
        self.assertGreater(dcf_bank["scenarios"]["Base"]["intrinsic_value_per_share"], 0)

    def test_non_financial_corporate_fcf(self):
        corp_stmt = {
            "symbol": "KLBF",
            "sector": "Healthcare",
            "source": "https://www.idx.co.id/filings/KLBF.json",
            "published_at": "2025-03-01T00:00:00+00:00",
            "currency": "IDR",
            "unit": "million_IDR",
            "period": "2024-FY",
            "period_type": "FY",
            "basis": "consolidated",
            "values": {
                "operating_cash_flow": 3500000,
                "capital_expenditure": 1000000, # PPE & Intangibles capex
                "net_income_attributable": 3000000,
                "equity_attributable": 20000000,
                "shares_outstanding": 46875000000,
            },
            "reported_ratios_pct": {},
        }

        # fundamentals() FCF = 3,500,000 - 1,000,000 = 2,500,000 million IDR = 2.5T IDR
        res = fundamentals(corp_stmt, price=1600)
        self.assertEqual(res["ratios"]["FCF_IDR"], 2_500_000 * 1e6)
        self.assertEqual(res["ratios"]["FCF_status"], "CALCULATED")

        # Valuation multiples FCF yield
        mults = calculate_valuation_multiples(corp_stmt, price=1600, sector="Healthcare")
        self.assertEqual(mults["multiples"]["FCF_IDR"], 2_500_000 * 1e6)
        # Market Cap = 1600 * 46,875,000,000 = 75,000,000,000,000 (75T)
        # FCF Yield = 2.5T / 75T = 3.33%
        self.assertAlmostEqual(mults["multiples"]["FCF_Yield_pct"], 3.33, places=1)

        # Corporate DCF scenario & 2D sensitivity
        dcf_corp = dcf_scenario_model(corp_stmt, price=1600, sector="Healthcare")
        self.assertEqual(dcf_corp["model_type"], "FCF_DISCOUNTED_CASH_FLOW")
        self.assertIn("sensitivity_matrix", dcf_corp)
        self.assertEqual(len(dcf_corp["sensitivity_matrix"]), 5) # 5 WACC rows

    def test_valuation_negative_guards(self):
        loss_stmt = {
            "symbol": "BUKA",
            "source": "https://www.idx.co.id/test.json",
            "published_at": "2025-01-01T00:00:00+00:00",
            "currency": "IDR",
            "unit": "million_IDR",
            "period": "2024-FY",
            "period_type": "FY",
            "basis": "consolidated",
            "values": {
                "revenue": 5000,
                "net_income_attributable": -1200, # Net loss
                "equity_attributable": 10000,
                "shares_outstanding": 1000000,
            },
            "reported_ratios_pct": {},
        }
        mults = calculate_valuation_multiples(loss_stmt, price=120)
        self.assertIsNone(mults["multiples"]["PER"])
        self.assertIn("Laba Bersih Negatif", mults["multiples"]["PER_note"])

        # Deficit equity
        deficit_stmt = {
            "symbol": "DEFI",
            "source": "https://www.idx.co.id/test.json",
            "published_at": "2025-01-01T00:00:00+00:00",
            "currency": "IDR",
            "unit": "million_IDR",
            "period": "2024-FY",
            "period_type": "FY",
            "basis": "consolidated",
            "values": {
                "revenue": 5000,
                "net_income_attributable": 500,
                "equity_attributable": -2000, # Negative equity
                "shares_outstanding": 1000000,
            },
            "reported_ratios_pct": {},
        }
        mults_def = calculate_valuation_multiples(deficit_stmt, price=120)
        self.assertIsNone(mults_def["multiples"]["PBV"])
        self.assertIn("Ekuitas Negatif", mults_def["multiples"]["PBV_note"])

    def test_dupont_and_earnings_quality(self):
        stmt = {
            "symbol": "TLKM",
            "source": "https://www.idx.co.id/filings/TLKM.json",
            "published_at": "2025-03-01T00:00:00+00:00",
            "currency": "IDR",
            "unit": "million_IDR",
            "period": "2024-FY",
            "period_type": "FY",
            "basis": "consolidated",
            "values": {
                "revenue": 150000,
                "operating_income": 45000,
                "profit_before_tax": 40000,
                "net_income_attributable": 25000,
                "total_assets": 280000,
                "equity_attributable": 140000,
                "operating_cash_flow": 30000,
            },
            "reported_ratios_pct": {},
        }

        dupont = dupont_analysis(stmt)
        self.assertEqual(dupont["status"], "COMPLETED")
        three = dupont["three_stage"]
        # NPM = 25,000 / 150,000 = 16.67%
        self.assertAlmostEqual(three["net_profit_margin_pct"], 16.67, places=1)
        # Asset Turnover = 150,000 / 280,000 = 0.536x
        self.assertAlmostEqual(three["asset_turnover_x"], 0.536, places=2)
        # Equity Multiplier = 280,000 / 140,000 = 2.0x
        self.assertAlmostEqual(three["equity_multiplier_x"], 2.0, places=1)
        # ROE = 25,000 / 140,000 = 17.86%
        self.assertAlmostEqual(three["roe_pct"], 17.86, places=1)

        # 5-stage DuPont
        self.assertIsNotNone(dupont["five_stage"])
        five = dupont["five_stage"]
        # Operating Margin = 45,000 / 150,000 = 30.0%
        self.assertAlmostEqual(five["operating_margin_pct"], 30.0, places=1)

        # Earnings Quality
        eq = evaluate_earnings_quality(stmt)
        self.assertEqual(eq["status"], "EVALUATED")
        # OCF / Net Income = 30,000 / 25,000 = 1.20x (> 1.0 -> PRIMA)
        self.assertAlmostEqual(eq["cash_conversion_ratio"], 1.20, places=2)
        self.assertIn("PRIMA", eq["assessment"])

    def test_cross_sector_statements_validation(self):
        # Validate that statements from all 11 IDX sectors pass validation and calculate ratios
        sector_samples = {
            "A": "ADRO",  # Energy
            "B": "ANTM",  # Basic Materials
            "C": "ASII",  # Industrials
            "D": "ICBP",  # Consumer Non-Cyclicals
            "E": "ACES",  # Consumer Cyclicals
            "F": "KLBF",  # Healthcare
            "G": "BBCA",  # Financials
            "H": "BSDE",  # Properties
            "I": "GOTO",  # Technology
            "J": "TLKM",  # Infrastructures
            "K": "BIRD",  # Transportation
        }

        for code, sym in sector_samples.items():
            sec_name = SECTORS[code][0]
            stmt = {
                "symbol": sym,
                "sector": sec_name,
                "source": f"https://www.idx.co.id/filings/{sym}_2024.json",
                "published_at": "2025-03-15T09:00:00+07:00",
                "currency": "IDR",
                "unit": "million_IDR",
                "period": "2024-FY",
                "period_type": "FY",
                "basis": "consolidated",
                "values": {
                    "revenue": 10000,
                    "operating_income": 2000,
                    "net_income_attributable": 1500,
                    "total_assets": 25000,
                    "total_liabilities": 10000,
                    "interest_bearing_debt": 4000,
                    "equity_attributable": 15000,
                    "operating_cash_flow": 2200,
                    "capital_expenditure": 700,
                    "shares_outstanding": 10000000,
                },
                "reported_ratios_pct": {"NIM": 5.0} if code == "G" else {},
            }
            validate_statement(stmt)
            calc = fundamentals(stmt, price=1500)
            self.assertIn("Operating_Margin_pct", calc["ratios"])
            if code == "G":
                self.assertEqual(calc["ratios"]["FCF_status"], "NOT_MEANINGFUL")
            else:
                self.assertEqual(calc["ratios"]["FCF_status"], "CALCULATED")


if __name__ == "__main__":
    unittest.main()
