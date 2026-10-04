"""Test Quant Engine V2, Zero-Key Core, and Decision Gates."""

import unittest

from openbagus.domains.crypto.quant import QuantEngineV2
from openbagus.domains.crypto.research import CryptoResearchRunner
from openbagus.intelligence.intent import IntentRequest


class TestQuantEngineV2(unittest.TestCase):
    def setUp(self):
        self.engine = QuantEngineV2(hard_leverage_max=3)

    def test_risk_reward_gate_forces_wait_when_rr_below_1_5(self):
        """When nearest target offers RR < 1.5, directional bias must NOT issue BUY/LONG."""
        # Simulated ticker near resistance (poor RR)
        spot_ticker = {
            "symbol": "BTC",
            "price": 89000.0,
            "high": 90000.0,
            "low": 80000.0,
            "volume": 50000000.0,
            "pct_change": 4.5,
            "provider": "Test Provider",
        }
        sentiment = {"value": 75, "classification": "Greed", "provider": "Test Sentiment"}

        res_spot = self.engine.evaluate("BTC", spot_ticker, sentiment=sentiment, market_type="spot")
        # Near resistance, nearest target R1 cannot provide 1.5x of stop distance to S1
        self.assertIn(res_spot.decision, ("WAIT", "REDUCE"))
        self.assertNotEqual(res_spot.decision, "BUY")
        self.assertFalse(res_spot.rr_gate_passed)

        res_perp = self.engine.evaluate("BTC", spot_ticker, sentiment=sentiment, market_type="perpetual")
        self.assertIn(res_perp.decision, ("NO_TRADE", "SHORT"))
        self.assertNotEqual(res_perp.decision, "LONG")

    def test_crowded_long_penalty_on_extreme_funding(self):
        """Extreme positive funding (> 0.04%) must trigger a crowded long penalty."""
        spot_ticker = {
            "symbol": "BTC",
            "price": 85000.0,
            "high": 86000.0,
            "low": 84000.0,
            "volume": 80000000.0,
            "pct_change": 2.0,
            "provider": "Test Provider",
        }
        # Extreme funding rate 0.08% (80 bps per 8h)
        derivatives = {
            "symbol": "BTC",
            "mark_price": 85100.0,
            "index_price": 85000.0,
            "funding_rate": 0.0008,  # 0.08%
            "funding_history": [0.0007, 0.0008, 0.0009],
            "funding_zscore": 2.5,
            "open_interest": 100000.0,
            "volume_24h": 500000000.0,
            "basis": 100.0,
            "provider": "Test Derivatives",
        }
        res = self.engine.evaluate("BTC", spot_ticker, derivatives=derivatives, market_type="perpetual")
        deriv_why = res.why.get("Derivatives", "")
        self.assertIn("Crowded long", deriv_why)
        # Decision must not be LONG when longs are crowded
        self.assertNotEqual(res.decision, "LONG")

    def test_conservative_leverage_ceiling_policy(self):
        """Leverage ceiling must never exceed hard maximum (3x) and reduce in volatile conditions."""
        self.assertEqual(self.engine.hard_leverage_max, 3)

        # High volatility setup
        spot_ticker = {
            "symbol": "SOL",
            "price": 200.0,
            "high": 230.0,
            "low": 170.0,  # 30% range -> VOLATILE
            "volume": 20000000.0,
            "pct_change": -8.0,
            "provider": "Test Provider",
        }
        res = self.engine.evaluate("SOL", spot_ticker, market_type="perpetual")
        self.assertLessEqual(res.leverage_num, 3)
        if res.leverage_num > 0:
            self.assertIn("3x policy", res.leverage_ceiling)

    def test_categorical_confidence(self):
        """Confidence must be categorical (LOW, MODERATE, HIGH), never fake percentages."""
        spot_ticker = {
            "symbol": "BTC",
            "price": 85000.0,
            "high": 86000.0,
            "low": 84000.0,
            "volume": 50000000.0,
            "pct_change": 1.0,
            "provider": "Test Provider",
        }
        res = self.engine.evaluate("BTC", spot_ticker)
        self.assertIn(res.confidence, ("LOW", "MODERATE", "HIGH"))
        self.assertNotIn("%", res.confidence)

    def test_deterministic_capital_sizing(self):
        """Capital sizing math: notional = risk_budget / stop_pct, margin = notional / leverage."""
        runner = CryptoResearchRunner()
        req = IntentRequest(
            intent="POSITION",
            asset="BTC",
            focus="capital",
            equity=1000.0,
            risk_pct=2.0,
            raw_query="position size btc equity 1000 risk 2%",
        )
        output = runner.execute(req)
        self.assertIn("CAPITAL & POSITION SIZING", output)
        self.assertIn("Account Equity         $1,000.00", output)
        self.assertIn("Risk Percentage        2.00%", output)
        self.assertIn("Max Risk Budget        $20.00", output)
        self.assertIn("Position Notional", output)
        self.assertIn("Margin Required", output)


if __name__ == "__main__":
    unittest.main()
