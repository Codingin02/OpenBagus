"""Unit and integration test suite for OpenBagus Multi-Asset Portfolio & Risk Management Engine.

Tests:
1. Position sizing for Indonesian equities (lot constraints) and Cryptocurrencies.
2. Kelly criterion and ATR volatility adjustments.
3. Multi-asset portfolio Value at Risk (Parametric, Historical, CVaR, Component VaR).
4. Cross-asset correlation matrix (IHSG vs Crypto) and diversification benefits.
5. Intent routing and CLI runner execution.
"""

import unittest
from pathlib import Path

from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.domains.crypto.research import CryptoResearchRunner
from openbagus.risk.multi_asset import (
    calculate_position_size,
    calculate_portfolio_var,
    calculate_correlation_matrix,
    format_position_size_summary,
    format_portfolio_var_summary,
    format_correlation_matrix_table,
)


class TestPortfolioRiskEngine(unittest.TestCase):
    def setUp(self):
        self.router = IntentRouter()
        self.runner = CryptoResearchRunner()

    def test_position_sizing_equity_lots(self):
        # Rp 10.000.000 modal, 2% risk (Rp 200.000), entry Rp 5.000, stop Rp 4.700
        res = calculate_position_size(
            capital=10000000.0,
            entry_price=5000.0,
            stop_loss=4700.0,
            risk_pct=2.0,
            asset_type="EQUITY_ID",
            currency="IDR",
            lot_size=100,
        )
        self.assertEqual(res.capital, 10000000.0)
        self.assertEqual(res.risk_amount, 200000.0)
        self.assertEqual(res.risk_per_unit, 300.0)
        # 200,000 / 300 = 666.67 shares -> 6 lots = 600 shares
        self.assertEqual(res.lots, 6)
        self.assertEqual(res.units, 600.0)
        self.assertEqual(res.position_value, 3000000.0)
        self.assertEqual(res.allocation_pct, 30.0)
        self.assertLessEqual(res.max_loss, 200000.0)

        summary = format_position_size_summary(res)
        self.assertIn("6 Lot", summary)
        self.assertIn("600 lembar saham", summary)
        self.assertIn("EQUITY_ID", summary)

    def test_position_sizing_crypto_fractional(self):
        # $10,000 capital, 2% risk ($200), entry $60,000, stop $58,000
        res = calculate_position_size(
            capital=10000.0,
            entry_price=60000.0,
            stop_loss=58000.0,
            risk_pct=2.0,
            asset_type="CRYPTO",
            currency="USD",
            lot_size=0,
        )
        self.assertEqual(res.capital, 10000.0)
        self.assertEqual(res.risk_amount, 200.0)
        self.assertEqual(res.risk_per_unit, 2000.0)
        # $200 / $2,000 = 0.1 BTC
        self.assertEqual(res.units, 0.1)
        self.assertIsNone(res.lots)
        self.assertEqual(res.position_value, 6000.0)
        self.assertEqual(res.max_loss, 200.0)

        summary = format_position_size_summary(res)
        self.assertIn("0.1 Unit", summary)
        self.assertIn("USD", summary)

    def test_position_sizing_kelly_and_atr(self):
        # Kelly criterion: 60% win rate, 2.0 reward:risk
        # Full Kelly = (0.6*2 - 0.4)/2 = 0.40 (40%), Half Kelly = 20%
        res_kelly = calculate_position_size(
            capital=10000000.0,
            entry_price=5000.0,
            stop_loss=4800.0,
            risk_pct=2.0,
            win_rate=0.60,
            reward_risk=2.0,
        )
        self.assertIn("half_kelly_pct", res_kelly.details)
        self.assertEqual(res_kelly.details["half_kelly_pct"], 20.0)

        # ATR volatility spacing
        res_atr = calculate_position_size(
            capital=10000000.0,
            entry_price=5000.0,
            stop_loss=4800.0,
            risk_pct=2.0,
            atr=150.0,
            atr_multiplier=2.0,
        )
        self.assertEqual(res_atr.risk_per_unit, 300.0)
        self.assertEqual(res_atr.method, "ATR_VOLATILITY")

    def test_multi_asset_portfolio_var(self):
        import random
        rng = random.Random(42)
        # Synthetic daily returns for 2 assets over 100 days
        rets_bbca = [rng.gauss(0.0005, 0.012) for _ in range(100)]
        rets_btc = [rng.gauss(0.0015, 0.035) for _ in range(100)]

        weights = {"BBCA": 0.6, "BTC": 0.4}
        returns_dict = {"BBCA": rets_bbca, "BTC": rets_btc}

        res = calculate_portfolio_var(
            weights=weights,
            returns_by_asset=returns_dict,
            portfolio_value=50000000.0,
            confidence=0.95,
            horizon_days=1,
            currency="IDR",
        )

        self.assertEqual(res.portfolio_value, 50000000.0)
        self.assertGreater(res.parametric_var, 0.0)
        self.assertGreater(res.historical_var, 0.0)
        self.assertGreater(res.cvar_expected_shortfall, res.historical_var)
        self.assertGreater(res.diversification_benefit_pct, 0.0)
        self.assertEqual(len(res.component_var), 2)
        # Component VaR sum roughly equals total parametric VaR
        total_comp = sum(res.component_var.values())
        self.assertAlmostEqual(total_comp, res.parametric_var, delta=100.0)

        summary = format_portfolio_var_summary(res)
        self.assertIn("Parametric VaR (95%)", summary)
        self.assertIn("Expected Shortfall", summary)
        self.assertIn("Efek Diversifikasi", summary)

    def test_cross_asset_correlation_matrix(self):
        import random
        rng = random.Random(123)
        returns = {
            "BBCA": [rng.gauss(0.0005, 0.01) for _ in range(50)],
            "BBRI": [rng.gauss(0.0006, 0.011) for _ in range(50)],
            "BTC": [rng.gauss(0.001, 0.03) for _ in range(50)],
            "ETH": [rng.gauss(0.0012, 0.035) for _ in range(50)],
        }

        res = calculate_correlation_matrix(
            returns,
            idx_symbols=["BBCA", "BBRI"],
            crypto_symbols=["BTC", "ETH"],
        )

        self.assertEqual(len(res.assets), 4)
        for a in res.assets:
            self.assertEqual(res.matrix[a][a], 1.0)
        self.assertGreaterEqual(res.diversification_score, 0.0)
        self.assertLessEqual(res.diversification_score, 1.0)
        self.assertTrue(len(res.cross_asset_correlations) > 0)

        table = format_correlation_matrix_table(res)
        self.assertIn("Matriks Korelasi IHSG & Kripto", table)
        self.assertIn("Skor Diversifikasi", table)

    def test_intent_router_portfolio_parsing(self):
        session = SessionState()

        # 1. Overview
        r1 = self.router.parse("/portfolio", session=session)
        self.assertEqual(r1.request_type, "PORTFOLIO_RISK")
        self.assertEqual(r1.focus, "overview")

        # 2. Position sizing natural query
        r2 = self.router.parse("posisi modal 10jt risiko 2% entry 5000 stop 4700", session=session)
        self.assertEqual(r2.request_type, "PORTFOLIO_RISK")
        self.assertEqual(r2.focus, "position_sizing")

        # 3. Correlation query
        r3 = self.router.parse("korelasi BBCA dan BTC", session=session)
        self.assertEqual(r3.request_type, "PORTFOLIO_RISK")
        self.assertEqual(r3.focus, "correlation")
        self.assertIn("BBCA", r3.target_assets)
        self.assertIn("BTC", r3.target_assets)

        # 4. VaR query
        r4 = self.router.parse("kalkulator var portofolio", session=session)
        self.assertEqual(r4.request_type, "PORTFOLIO_RISK")
        self.assertEqual(r4.focus, "var")

    def test_crypto_runner_execute_portfolio_risk(self):
        session = SessionState()

        # 1. Execute Position Sizing
        req_size = self.router.parse("posisi modal 10jt risiko 2% entry 5000 sl 4700", session=session)
        out_size = self.runner.execute(req_size, session=session)
        self.assertIn("Position Sizing", out_size)
        self.assertIn("Rekomendasi Alokasi", out_size)

        # 2. Execute Correlation Matrix
        req_corr = self.router.parse("/portfolio corr BBCA BBRI BTC ETH", session=session)
        out_corr = self.runner.execute(req_corr, session=session)
        self.assertIn("Matriks Korelasi IHSG & Kripto", out_corr)
        self.assertIn("BBCA", out_corr)
        self.assertIn("BTC", out_corr)

        # 3. Execute VaR
        req_var = self.router.parse("/portfolio var BBCA BTC", session=session)
        out_var = self.runner.execute(req_var, session=session)
        self.assertIn("Value at Risk", out_var)
        self.assertIn("Expected Shortfall", out_var)

    def test_mandatory_risk_budget_violation_rejection(self):
        # Section 8.4: Capital Rp 10M, Risk 0.1% (Rp 10k), Entry Rp 5000, Stop Rp 4500
        # Risk per unit = Rp 500 -> 20 shares. 1 lot = 100 shares -> 1 lot risks Rp 50,000 > Rp 10,000
        res = calculate_position_size(
            capital=10000000.0,
            entry_price=5000.0,
            stop_loss=4500.0,
            risk_pct=0.1,
            asset_type="EQUITY_ID",
            currency="IDR",
            lot_size=100,
        )
        self.assertEqual(res.lots, 0)
        self.assertEqual(res.units, 0.0)
        self.assertEqual(res.max_loss, 0.0)
        self.assertFalse(res.trade_eligible)
        self.assertIn("melebihi batas anggaran risiko", res.rejection_reason)
        self.assertEqual(res.details["min_lot_loss"], 50000.0)
        self.assertEqual(res.details["excess_risk"], 40000.0)

    def test_invalid_stop_loss_geometry(self):
        res = calculate_position_size(
            capital=10000000.0,
            entry_price=5000.0,
            stop_loss=5200.0,  # Stop higher than entry for long
            risk_pct=1.0,
            asset_type="EQUITY_ID",
        )
        self.assertFalse(res.trade_eligible)
        self.assertEqual(res.lots, 0)
        self.assertEqual(res.method, "INVALID_STOP")
        self.assertIn("Stop loss harus berada di bawah", res.rejection_reason)

    def test_kelly_zero_or_negative_edge(self):
        res = calculate_position_size(
            capital=10000000.0,
            entry_price=5000.0,
            stop_loss=4800.0,
            risk_pct=2.0,
            win_rate=0.30,
            reward_risk=1.0,  # Negative Kelly edge: 0.3 * 1 - 0.7 = -0.4
        )
        self.assertFalse(res.trade_eligible)
        self.assertEqual(res.method, "KELLY_ZERO_EDGE")
        self.assertEqual(res.lots, 0)
        self.assertIn("tidak memiliki edge", res.rejection_reason)

    def test_date_aligned_correlation_with_crypto_and_idx(self):
        # BTC trades 7 days (including weekend Oct 3 & Oct 4)
        # BBCA trades 5 weekdays only (Oct 1, Oct 2, Oct 5, Oct 6, Oct 7)
        btc_dates = ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07"]
        btc_returns = [0.01, -0.02, 0.015, -0.005, 0.03, -0.01, 0.02]

        bbca_dates = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]
        bbca_returns = [0.005, -0.01, 0.02, -0.005, 0.015]

        res = calculate_correlation_matrix(
            returns_by_asset={"BTC": btc_returns, "BBCA": bbca_returns},
            dates_by_asset={"BTC": btc_dates, "BBCA": bbca_dates},
        )
        # Should strictly align on the 5 common business days!
        self.assertEqual(res.observations_used, 5)
        self.assertTrue(res.alignment_metadata["date_aligned"])
        self.assertIn("BTC", res.matrix)
        self.assertIn("BBCA", res.matrix)

    def test_hedging_component_var_negative_contribution(self):
        # Asset A and Asset B are negatively correlated (hedge)
        rets_a = [0.02, -0.01, 0.03, -0.02, 0.04, -0.03]
        rets_b = [-0.02, 0.01, -0.03, 0.02, -0.04, 0.03]
        res = calculate_portfolio_var(
            weights={"A": 0.5, "B": 0.5},
            returns_by_asset={"A": rets_a, "B": rets_b},
            portfolio_value=100000000.0,
            confidence=0.95,
        )
        # Perfectly offsetting hedge should produce zero or near-zero portfolio volatility and VaR
        self.assertAlmostEqual(res.portfolio_daily_volatility, 0.0, places=4)
        self.assertAlmostEqual(res.parametric_var, 0.0, places=1)


if __name__ == "__main__":
    unittest.main()
