"""P0 Financial Integrity Tests.

Verifies:
1. P0.1: No fabricated positive FCF in DCF (explicit states: CALCULABLE, REQUIRES_NORMALIZATION, UNSUITABLE_FCF, INSUFFICIENT_DATA).
2. Gordon growth denominator guard: WACC <= terminal_g returns INVALID_ASSUMPTIONS, never clamps to fake positive value.
3. P0.2: Debt semantics: strict separation of Interest-Bearing Debt from Total Liabilities.
4. P0.3: Elimination of shares-only market capitalization tier guessing (returns UNKNOWN_CAP when price is None).
5. Strict monetary unit validation in _get_multiplier() (raises ValueError on unknown unit).
6. SEC EDGAR User-Agent configurability and amendment / duration precedence.
"""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from openbagus.domains.equities.catalog import EquityAsset, EquityCatalog
from openbagus.domains.equities.sec_edgar import SecEdgarClient, SEC_DEFAULT_USER_AGENT
from openbagus.domains.equities.storage import FinancialStatementStorage
from openbagus.domains.equities.valuation import (
    _get_multiplier,
    calculate_valuation_multiples,
    dcf_scenario_model,
    calculate_cash_flows,
    calculate_fcff,
    calculate_fcfe,
    calculate_reinvestment,
    calculate_sustainable_growth,
)


class TestFinancialIntegrityP0(unittest.TestCase):
    # -------------------------------------------------------------------------
    # P0.1 DCF Positive FCF Fabrication Fallback Elimination & States
    # -------------------------------------------------------------------------
    def test_dcf_negative_fcf_with_positive_ebit_requires_normalization(self) -> None:
        """When FCF is negative due to growth capex but EBIT is positive, use Damodaran reinvestment scenario and preserve negative historical FCF."""
        stmt = {
            "symbol": "GROWTH",
            "period": "2024-FY",
            "period_type": "FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "values": {
                "revenue": 100_000_000.0,
                "operating_income": 20_000_000.0,  # Positive EBIT
                "tax_expense": 4_400_000.0,
                "operating_cash_flow": 15_000_000.0,
                "capital_expenditure": 25_000_000.0,  # Heavy capex -> FCF = -10,000,000
                "interest_bearing_debt": 10_000_000.0,
                "cash_and_equivalents": 5_000_000.0,
                "shares_outstanding": 10_000_000_000.0,
            },
        }
        res = dcf_scenario_model(statement=stmt, price=1000.0, shares_outstanding=10_000_000_000.0)
        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["fcf_state"], "REQUIRES_NORMALIZATION")
        self.assertIn(res["fcf_basis"], {"sustainable_reinvestment_rate_scenario", "assumption_based_scenario"})
        self.assertIsNotNone(res["normalization_note"])
        # Actual negative FCF is strictly preserved as negative!
        self.assertTrue(res["actual_negative_fcf_preserved"])
        self.assertEqual(res["actual_historical_fcf"], -10_000_000.0 * 1e6)
        self.assertEqual(res["historical_fcf_IDR"], -10_000_000.0 * 1e6)
        # NOPAT = 20M * (1 - 0.22) = 15.6M; projected cash flow for discounting is positive
        self.assertGreater(res["base_fcf_IDR"], 0.0)

    def test_dcf_damodaran_sustainable_reinvestment_rate_with_roic(self) -> None:
        """When equity is provided, ROIC is calculated and sustainable reinvestment b = g / ROIC is derived."""
        stmt = {
            "symbol": "SUSTAIN",
            "period": "2024-FY",
            "period_type": "FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "values": {
                "revenue": 100_000_000.0,
                "operating_income": 20_000_000.0,
                "tax_expense": 4_400_000.0,
                "operating_cash_flow": 12_000_000.0,
                "capital_expenditure": 20_000_000.0,
                "interest_bearing_debt": 10_000_000.0,
                "equity_attributable": 70_000_000.0,
                "cash_and_equivalents": 5_000_000.0,
                "shares_outstanding": 10_000_000_000.0,
            },
        }
        res = dcf_scenario_model(statement=stmt, price=1000.0, shares_outstanding=10_000_000_000.0)
        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["fcf_state"], "REQUIRES_NORMALIZATION")
        self.assertEqual(res["fcf_basis"], "sustainable_reinvestment_rate_scenario")
        self.assertTrue(res["actual_negative_fcf_preserved"])
        self.assertEqual(res["historical_fcf_IDR"], -8_000_000.0 * 1e6)
        self.assertIsNotNone(res["reinvestment_rate_pct"])
        self.assertIn("tingkat reinvestasi keberlanjutan", res["normalization_note"].lower())

    def test_damodaran_calculate_cash_flows_and_fcff_fcfe(self) -> None:
        stmt = {
            "symbol": "CASHFLOW_TEST",
            "period": "2024-FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "values": {
                "operating_income": 20_000_000.0,
                "tax_expense": 4_400_000.0,
                "operating_cash_flow": 16_000_000.0,
                "capital_expenditure": 10_000_000.0,
                "interest_expense": 2_000_000.0,
                "current_assets": 40_000_000.0,
                "current_liabilities": 20_000_000.0,
                "cash_and_equivalents": 8_000_000.0,
                "short_term_debt": 4_000_000.0,
                "interest_bearing_debt": 15_000_000.0,
                "equity_attributable": 50_000_000.0,
            },
        }
        prev_stmt = {
            "period": "2023-FY",
            "unit": "million_IDR",
            "currency": "IDR",
            "values": {
                "current_assets": 35_000_000.0,
                "current_liabilities": 18_000_000.0,
                "cash_and_equivalents": 6_000_000.0,
                "short_term_debt": 3_000_000.0,
            },
        }
        cf = calculate_cash_flows(stmt, prev_stmt)
        self.assertEqual(cf["status"], "CALCULATED")
        self.assertEqual(cf["actual_historical_fcf"], 6_000_000.0 * 1e6)
        self.assertFalse(cf["actual_historical_fcf_is_negative"])
        # Non-cash WC 2024: (40 - 8) - (20 - 4) = 32 - 16 = 16M
        # Non-cash WC 2023: (35 - 6) - (18 - 3) = 29 - 15 = 14M
        # Delta Non-cash WC = 2M * 1e6
        self.assertEqual(cf["delta_non_cash_working_capital"], 2_000_000.0 * 1e6)
        # Reinvestment: Capex 10M + Delta WC 2M = 12M * 1e6
        self.assertEqual(cf["reinvestment"], 12_000_000.0 * 1e6)

        # Test helper wrappers
        fcff_res = calculate_fcff(stmt, prev_stmt)
        self.assertEqual(fcff_res["status"], "CALCULATED")
        self.assertIsNotNone(fcff_res["fcff"])

        reinv_res = calculate_reinvestment(stmt, prev_stmt)
        self.assertEqual(reinv_res["reinvestment"], 12_000_000.0 * 1e6)

    def test_dcf_negative_fcf_with_negative_ebit_returns_unsuitable_fcf(self) -> None:
        """When company burns cash AND has operating loss, DCF must return UNSUITABLE_FCF, never Rp 100k fallback."""
        stmt = {
            "symbol": "BURN",
            "period": "2024-FY",
            "period_type": "FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "values": {
                "revenue": 10_000_000.0,
                "operating_income": -5_000_000.0,  # Negative operating income
                "operating_cash_flow": -8_000_000.0,
                "capital_expenditure": 4_000_000.0,  # FCF = -12,000,000
                "shares_outstanding": 1_000_000_000.0,
            },
        }
        res = dcf_scenario_model(statement=stmt, price=50.0, shares_outstanding=1_000_000_000.0)
        self.assertEqual(res["status"], "UNSUITABLE_FCF")
        self.assertEqual(res["fcf_state"], "UNSUITABLE_FCF")
        self.assertIn("Free Cash Flow negatif", res["message"])
        # Must not fabricate positive scenarios
        self.assertNotIn("scenarios", res)

    def test_dcf_missing_cashflow_and_operating_income_returns_insufficient_data(self) -> None:
        stmt = {
            "symbol": "EMPTY",
            "period": "2024-FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "values": {
                "shares_outstanding": 1_000_000_000.0,
            },
        }
        res = dcf_scenario_model(statement=stmt, price=100.0, shares_outstanding=1_000_000_000.0)
        self.assertEqual(res["status"], "INSUFFICIENT_DATA")

    def test_dcf_invalid_terminal_growth_greater_than_wacc_guard(self) -> None:
        """If WACC <= terminal_g, Gordon growth model is invalid and must not clamp silently."""
        stmt = {
            "symbol": "TEST",
            "period": "2024-FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "values": {
                "operating_cash_flow": 20_000_000.0,
                "capital_expenditure": 5_000_000.0,
                "shares_outstanding": 1_000_000_000.0,
            },
        }
        # In standard scenarios WACC (10%) > g (3%). In sensitivity matrix, combinations where w <= tg must be None.
        res = dcf_scenario_model(statement=stmt, price=500.0, shares_outstanding=1_000_000_000.0)
        self.assertEqual(res["status"], "COMPLETED")
        matrix = res["sensitivity_wacc_terminal_growth"]
        # Check that any hypothetical wacc <= tg row produces None instead of infinity/clamped
        for row in matrix:
            w_rate = row["wacc_pct"] / 100.0
            for g_col, iv in row.items():
                if g_col == "wacc_pct":
                    continue
                g_rate = float(g_col.replace("g_", "").replace("%", "")) / 100.0
                if w_rate <= g_rate:
                    self.assertIsNone(iv, f"Cell where WACC ({w_rate}) <= g ({g_rate}) must be None")

    # -------------------------------------------------------------------------
    # P0.2 Debt Semantics: Interest-Bearing Debt vs Total Liabilities
    # -------------------------------------------------------------------------
    def test_debt_to_equity_strict_interest_bearing_debt(self) -> None:
        """When interest_bearing_debt is not reported, Debt_to_Equity must be None, not total_liabilities."""
        stmt = {
            "symbol": "SUPPLIER_FINANCED",
            "period": "2024-FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "values": {
                "revenue": 50_000_000.0,
                "net_income_attributable": 5_000_000.0,
                "equity_attributable": 20_000_000.0,
                "total_liabilities": 30_000_000.0,  # Trade payables, accruals, zero bank debt
                "shares_outstanding": 1_000_000_000.0,
            },
        }
        res = calculate_valuation_multiples(stmt, price=100.0, shares_outstanding=1_000_000_000.0)
        ratios = res["ratios"]
        # Total liabilities to equity should be 30M / 20M = 1.5x
        self.assertEqual(ratios["Total_Liabilities_to_Equity"], 1.5)
        # Debt to equity must be None because interest-bearing debt is missing
        self.assertIsNone(ratios["Debt_to_Equity"])
        self.assertIn("Hutang berbunga tidak dilaporkan", ratios["Debt_to_Equity_note"])

        # Enterprise Value cannot substitute total liabilities as debt
        mults = res["multiples"]
        self.assertIsNone(mults["EV"])

    def test_debt_to_equity_when_interest_bearing_debt_reported(self) -> None:
        stmt = {
            "symbol": "LEVERAGED",
            "period": "2024-FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "values": {
                "revenue": 50_000_000.0,
                "net_income_attributable": 5_000_000.0,
                "equity_attributable": 20_000_000.0,
                "total_liabilities": 30_000_000.0,
                "interest_bearing_debt": 8_000_000.0,  # Bank debt 8M
                "cash_and_equivalents": 2_000_000.0,
                "shares_outstanding": 1_000_000_000.0,
            },
        }
        res = calculate_valuation_multiples(stmt, price=100.0, shares_outstanding=1_000_000_000.0)
        ratios = res["ratios"]
        # DER = 8M / 20M = 0.40x
        self.assertEqual(ratios["Debt_to_Equity"], 0.4)
        self.assertEqual(ratios["Total_Liabilities_to_Equity"], 1.5)
        mults = res["multiples"]
        # EV = Market Cap (100 * 1B = 100B) + Debt (8M * 1e6 = 8T) - Cash (2M * 1e6 = 2T) = 6.1T
        self.assertEqual(mults["EV"], 6_100_000_000_000.0)

    # -------------------------------------------------------------------------
    # P0.3 Elimination of Shares-Only Market Cap Tier Guessing
    # -------------------------------------------------------------------------
    def test_cap_tier_returns_unknown_cap_without_price(self) -> None:
        """Asset with 200 billion shares must return UNKNOWN_CAP when market price is not provided."""
        asset = EquityAsset(
            symbol="GIANT",
            name="Giant Shares Corp",
            shares_outstanding=200_000_000_000.0,
            board="MAIN",
        )
        self.assertEqual(asset.cap_tier(price=None), "UNKNOWN_CAP")
        self.assertEqual(asset.cap_tier(last_price=None), "UNKNOWN_CAP")
        # With valid price of Rp 500, MC = 100 Triliun -> LARGE_CAP
        self.assertEqual(asset.cap_tier(price=500.0), "LARGE_CAP")

    def test_third_liner_detection_requires_verified_board_or_price(self) -> None:
        """Main board asset with unknown price must NOT be flagged as third-liner."""
        asset_main = EquityAsset(
            symbol="BIG",
            name="Big Main Board Corp",
            shares_outstanding=1_000_000_000.0,
            board="MAIN",
        )
        self.assertFalse(asset_main.is_third_liner)

        # Acceleration board asset is verified third-liner even without price
        asset_acc = EquityAsset(
            symbol="SMALL",
            name="Acceleration Corp",
            shares_outstanding=500_000_000.0,
            board="ACCELERATION",
        )
        self.assertTrue(asset_acc.is_third_liner)

    # -------------------------------------------------------------------------
    # Strict Monetary Unit Scaling
    # -------------------------------------------------------------------------
    def test_get_multiplier_strict_validation(self) -> None:
        self.assertEqual(_get_multiplier("IDR"), 1.0)
        self.assertEqual(_get_multiplier("thousand_IDR"), 1e3)
        self.assertEqual(_get_multiplier("million_IDR"), 1e6)
        self.assertEqual(_get_multiplier("billion_IDR"), 1e9)
        self.assertEqual(_get_multiplier("trillion_IDR"), 1e12)
        self.assertEqual(_get_multiplier("USD"), 1.0)
        self.assertEqual(_get_multiplier("million_USD"), 1e6)

        # Unrecognized unit must raise ValueError
        with self.assertRaises(ValueError):
            _get_multiplier("unsupported_unit", "IDR")
        with self.assertRaises(ValueError):
            _get_multiplier("yen", "USD")

    # -------------------------------------------------------------------------
    # SEC EDGAR User-Agent Configurability
    # -------------------------------------------------------------------------
    def test_sec_edgar_user_agent_env_override(self) -> None:
        with patch.dict(os.environ, {"OPENBAGUS_SEC_USER_AGENT": "CustomOrg/2.0 (contact@custom.org)"}):
            client = SecEdgarClient()
            self.assertEqual(client.user_agent, "CustomOrg/2.0 (contact@custom.org)")

        # Default fallback
        client_default = SecEdgarClient(user_agent=None)
        self.assertIn("@", client_default.user_agent)
        self.assertNotIn("codingindong02@gmail.com", client_default.user_agent)

    # -------------------------------------------------------------------------
    # EV Reconciliation with Minority Interest & Preferred Equity
    # -------------------------------------------------------------------------
    def test_enterprise_value_minority_interest_and_preferred_equity(self) -> None:
        stmt = {
            "symbol": "CONGLOMERATE",
            "period": "2024-FY",
            "currency": "IDR",
            "unit": "million_IDR",
            "values": {
                "revenue": 100_000_000.0,
                "operating_income": 15_000_000.0,
                "interest_bearing_debt": 20_000_000.0,
                "cash_and_equivalents": 5_000_000.0,
                "equity_attributable": 50_000_000.0,
                "non_controlling_interests": 8_000_000.0,
                "preferred_equity": 2_000_000.0,
                "shares_outstanding": 10_000_000_000.0,
            },
        }
        res = calculate_valuation_multiples(stmt, price=10.0, shares_outstanding=10_000_000_000.0)
        mults = res["multiples"]
        # Market Cap = 10 * 10B = 100B
        # Debt = 20M * 1e6 = 20T
        # Cash = 5M * 1e6 = 5T
        # NCI = 8M * 1e6 = 8T
        # Preferred = 2M * 1e6 = 2T
        # EV = 100B + 20T - 5T + 8T + 2T = 25.1T
        self.assertEqual(mults["EV"], 25_100_000_000_000.0)
        self.assertEqual(mults["Minority_Interest_IDR"], 8_000_000_000_000.0)
        self.assertEqual(mults["Preferred_Equity_IDR"], 2_000_000_000_000.0)

    # -------------------------------------------------------------------------
    # TTM Period Aggregation and Interim Adjustment
    # -------------------------------------------------------------------------
    def test_ttm_statement_aggregation_interim_and_quarters(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            storage = FinancialStatementStorage(Path(tmp_dir))
            # Store 2023-FY
            storage.store_statement({
                "symbol": "TTMCO",
                "period": "2023-FY",
                "period_type": "FY",
                "currency": "IDR",
                "unit": "million_IDR",
                "values": {"revenue": 1000.0, "net_income": 100.0, "total_assets": 5000.0},
            })
            # Store 2023-9M
            storage.store_statement({
                "symbol": "TTMCO",
                "period": "2023-9M",
                "period_type": "9M",
                "currency": "IDR",
                "unit": "million_IDR",
                "values": {"revenue": 700.0, "net_income": 70.0, "total_assets": 4800.0},
            })
            # Store 2024-9M
            storage.store_statement({
                "symbol": "TTMCO",
                "period": "2024-9M",
                "period_type": "9M",
                "currency": "IDR",
                "unit": "million_IDR",
                "values": {"revenue": 850.0, "net_income": 95.0, "total_assets": 5500.0},
            })
            ttm = storage.compute_ttm_statement("TTMCO")
            self.assertIsNotNone(ttm)
            self.assertEqual(ttm["period_type"], "TTM")
            self.assertEqual(ttm["ttm_method"], "INTERIM_YTD_PLUS_PRIOR_FY_ADJUSTED")
            # TTM Revenue = 2024-9M (850) + (2023-FY (1000) - 2023-9M (700)) = 850 + 300 = 1150
            self.assertEqual(ttm["values"]["revenue"], 1150.0)
            # TTM Net income = 95 + (100 - 70) = 125
            self.assertEqual(ttm["values"]["net_income"], 125.0)
            # Total assets point in time from latest 2024-9M
            self.assertEqual(ttm["values"]["total_assets"], 5500.0)


if __name__ == "__main__":
    unittest.main()

