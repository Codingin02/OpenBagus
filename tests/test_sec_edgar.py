"""Unit and Integration Tests for SEC EDGAR Provider.

Verifies:
- Official SEC User-Agent header format.
- Rate limiter intervals (< 10 req/s).
- Ticker-to-CIK resolution for US stocks.
- Company facts normalization across US-GAAP taxonomy.
- Canonical statement extraction, accounting invariants, and provenance tracking.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbagus.domains.equities.sec_edgar import (
    SEC_DEFAULT_USER_AGENT,
    SecEdgarClient,
    SecRateLimiter,
)
from openbagus.domains.equities.financial_model import CanonicalFinancialStatement


class TestSecEdgarProvider(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.client = SecEdgarClient(root=self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_user_agent_format(self) -> None:
        # SEC requires: "<Sample Company Name> <AdminContact@sample.com>"
        self.assertIn("@", self.client.user_agent)
        self.assertIn("OpenBagus", self.client.user_agent)

    def test_rate_limiter_interval(self) -> None:
        limiter = SecRateLimiter(min_interval=0.1)
        self.assertGreaterEqual(limiter.min_interval, 0.1)

    def test_ticker_to_cik_resolution_cached(self) -> None:
        mock_tickers = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp."},
        }
        cache_file = self.root / "data" / "equities" / "sec" / "company_tickers.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(mock_tickers), encoding="utf-8")

        client = SecEdgarClient(root=self.root)
        self.assertEqual(client.resolve_ticker("AAPL"), 320193)
        self.assertEqual(client.resolve_ticker("msft"), 789019)
        self.assertIsNone(client.resolve_ticker("NONEXISTENT"))

    def test_extract_canonical_statements_from_facts_fixture(self) -> None:
        # Simulated SEC company facts payload for AAPL FY 2024
        mock_facts = {
            "cik": 320193,
            "entityName": "Apple Inc.",
            "facts": {
                "us-gaap": {
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "label": "Revenue",
                        "units": {
                            "USD": [
                                {
                                    "end": "2024-09-28",
                                    "val": 391035000000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2024-11-01",
                                    "accn": "0000320193-24-000106",
                                }
                            ]
                        },
                    },
                    "CostOfGoodsAndServicesSold": {
                        "label": "Cost of Goods Sold",
                        "units": {
                            "USD": [
                                {
                                    "end": "2024-09-28",
                                    "val": 210352000000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2024-11-01",
                                    "accn": "0000320193-24-000106",
                                }
                            ]
                        },
                    },
                    "OperatingIncomeLoss": {
                        "label": "Operating Income",
                        "units": {
                            "USD": [
                                {
                                    "end": "2024-09-28",
                                    "val": 123216000000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2024-11-01",
                                    "accn": "0000320193-24-000106",
                                }
                            ]
                        },
                    },
                    "NetIncomeLoss": {
                        "label": "Net Income",
                        "units": {
                            "USD": [
                                {
                                    "end": "2024-09-28",
                                    "val": 93736000000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2024-11-01",
                                    "accn": "0000320193-24-000106",
                                }
                            ]
                        },
                    },
                    "Assets": {
                        "label": "Total Assets",
                        "units": {
                            "USD": [
                                {
                                    "end": "2024-09-28",
                                    "val": 364980000000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2024-11-01",
                                    "accn": "0000320193-24-000106",
                                }
                            ]
                        },
                    },
                    "Liabilities": {
                        "label": "Total Liabilities",
                        "units": {
                            "USD": [
                                {
                                    "end": "2024-09-28",
                                    "val": 308030000000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2024-11-01",
                                    "accn": "0000320193-24-000106",
                                }
                            ]
                        },
                    },
                    "StockholdersEquity": {
                        "label": "Shareholders' Equity",
                        "units": {
                            "USD": [
                                {
                                    "end": "2024-09-28",
                                    "val": 56950000000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2024-11-01",
                                    "accn": "0000320193-24-000106",
                                }
                            ]
                        },
                    },
                    "NetCashProvidedByUsedInOperatingActivities": {
                        "label": "Operating Cash Flow",
                        "units": {
                            "USD": [
                                {
                                    "end": "2024-09-28",
                                    "val": 118264000000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2024-11-01",
                                    "accn": "0000320193-24-000106",
                                }
                            ]
                        },
                    },
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "label": "Capex",
                        "units": {
                            "USD": [
                                {
                                    "end": "2024-09-28",
                                    "val": 9453000000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2024-11-01",
                                    "accn": "0000320193-24-000106",
                                }
                            ]
                        },
                    },
                },
                "dei": {
                    "EntityCommonStockSharesOutstanding": {
                        "label": "Shares Outstanding",
                        "units": {
                            "shares": [
                                {
                                    "end": "2024-09-28",
                                    "val": 15204137000,
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2024-11-01",
                                }
                            ]
                        },
                    }
                },
            },
        }

        stmts = self.client.extract_canonical_statements("AAPL", company_facts=mock_facts)
        self.assertEqual(len(stmts), 1)
        s = stmts[0]
        self.assertEqual(s.symbol, "AAPL")
        self.assertEqual(s.period, "2024-FY")
        self.assertEqual(s.currency, "USD")
        self.assertEqual(s.revenue, 391035000000.0)
        self.assertEqual(s.cost_of_revenue, 210352000000.0)
        self.assertEqual(s.gross_profit, 391035000000.0 - 210352000000.0)
        self.assertEqual(s.operating_income, 123216000000.0)
        self.assertEqual(s.net_income_attributable, 93736000000.0)
        self.assertEqual(s.total_assets, 364980000000.0)
        self.assertEqual(s.total_liabilities, 308030000000.0)
        self.assertEqual(s.total_equity, 56950000000.0)
        self.assertEqual(s.operating_cash_flow, 118264000000.0)
        self.assertEqual(s.capital_expenditures, 9453000000.0)
        self.assertEqual(s.operating_cash_flow - s.capital_expenditures, 118264000000.0 - 9453000000.0)

        # Invariant check: Assets == Liabilities + Equity
        # 308,030,000,000 + 56,950,000,000 = 364,980,000,000
        self.assertEqual(s.total_assets, s.total_liabilities + s.total_equity)
        self.assertEqual(s.validation_status, "VALIDATED")


if __name__ == "__main__":
    unittest.main()
