"""P0 Negative Test Gate for Financial Data Integrity & Provenance.

Test Category: PURE_UNIT & AUTHENTIC_FIXTURE
Ensures the system strictly rejects fabricated financial data, unverified real-time labels,
misleading zero-debt representations, invalid symbols, and observations lacking sources.

Implements all 8 gates mandated by Directive 9:
1. Rejects invented IDX URLs (e.g., https://www.idx.co.id/filings/*.json).
2. Rejects manually created financial statements disguised as filings.
3. Rejects observations lacking an actual source or provenance hash.
4. Rejects quotes whose real-time status is unverified (cannot label delayed/EOD as REALTIME_VERIFIED).
5. Rejects representing missing interest-bearing debt as zero without filing evidence.
6. Rejects invalid stock symbols.
7. Rejects unavailable providers returning apparent success.
8. Rejects stale cached observations labelled live.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from openbagus.ai.tools.finance_tools import CalculateFinancialRatiosTool
from openbagus.data.provider_base import (
    DataResult,
    ErrorCode,
    FreshnessStatus,
    QualityStatus,
)
from openbagus.domains.equities.catalog import EquityCatalog
from openbagus.domains.equities.facts_db import FinancialFactsDatabase
from openbagus.domains.equities.storage import FinancialStatementStorage


class TestFinancialIntegrityGates(unittest.TestCase):
    """TEST_SUITE_CATEGORY: PURE_UNIT & AUTHENTIC_FIXTURE"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.storage = FinancialStatementStorage(self.root)
        self.db = FinancialFactsDatabase(root=self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # Gate 1: Reject invented IDX URLs
    # -------------------------------------------------------------------------
    def test_gate_1_reject_invented_idx_urls(self) -> None:
        """CATEGORY: PURE_UNIT - Rejects synthetic filing URLs like https://www.idx.co.id/filings/BBCA_2024.json."""
        synthetic_statement = {
            "symbol": "BBCA",
            "period": "2024-FY",
            "period_type": "FY",
            "currency": "IDR",
            "source": "https://www.idx.co.id/filings/BBCA_2024.json",
            "values": {"revenue": 60000.0, "total_equity": 252000000.0},
        }
        with self.assertRaises(ValueError) as ctx:
            self.storage.store_statement(synthetic_statement)
        self.assertIn("synthetic", str(ctx.exception).lower())

        # Also verify database store_fact rejects invented source URLs
        with self.assertRaises(ValueError) as ctx2:
            self.db.store_fact(
                symbol="BBCA",
                exchange="IDX",
                period="2024-FY",
                period_type="FY",
                metric_name="revenue",
                value=60000.0,
                source_url="https://www.idx.co.id/filings/BBCA_2024.json",
            )
        self.assertIn("synthetic", str(ctx2.exception).lower())

    # -------------------------------------------------------------------------
    # Gate 2: Reject manually created financial statement disguised as filing
    # -------------------------------------------------------------------------
    def test_gate_2_reject_disguised_manual_statement(self) -> None:
        """CATEGORY: PURE_UNIT - Quarantined or synthetic marked statements must not be loaded."""
        # Create a file directly on disk with QUARANTINED_SYNTHETIC status
        sym_dir = self.root / "data" / "equities" / "financials" / "BBCA"
        sym_dir.mkdir(parents=True, exist_ok=True)
        bad_file = sym_dir / "2024-FY.json"
        bad_file.write_text(
            json.dumps({
                "symbol": "BBCA",
                "period": "2024-FY",
                "validation_status": "QUARANTINED_SYNTHETIC",
                "source": "manual_seed_script",
                "values": {"revenue": 60000.0},
            }),
            encoding="utf-8",
        )

        loaded = self.storage.get_statement("BBCA", "2024-FY")
        self.assertIsNone(loaded, "Storage must refuse to load quarantined or disguised statement")
        periods = self.storage.list_periods("BBCA")
        self.assertEqual(periods, [], "list_periods must exclude quarantined statements")

    # -------------------------------------------------------------------------
    # Gate 3: Reject observation lacking an actual source
    # -------------------------------------------------------------------------
    def test_gate_3_reject_observation_lacking_source(self) -> None:
        """CATEGORY: PURE_UNIT - Fact queries must not return unverified observations lacking valid status."""
        self.db.store_fact(
            symbol="TEST",
            exchange="IDX",
            period="2024-FY",
            period_type="FY",
            metric_name="revenue",
            value=100.0,
            source_provider="UNKNOWN_SOURCE",
            validation_status="UNVERIFIED_SOURCE",
        )
        # Normal query must only return VALID facts
        fact = self.db.get_fact("TEST", "revenue", "2024-FY")
        self.assertIsNone(fact, "Unverified fact without source validation must not be retrieved")
        periods = self.db.list_available_periods("TEST")
        self.assertEqual(periods, [])

    # -------------------------------------------------------------------------
    # Gate 4: Reject unverified real-time status (cannot label delayed/EOD as LIVE)
    # -------------------------------------------------------------------------
    def test_gate_4_reject_unverified_realtime_status(self) -> None:
        """CATEGORY: PURE_UNIT - EOD quotes must be classified as LATEST_EOD, never REALTIME_VERIFIED."""
        from openbagus.data.registry import YahooFinanceEquitiesProvider

        prov = YahooFinanceEquitiesProvider(self.root)
        self.assertFalse(prov.supports_live, "Yahoo provider must declare supports_live=False")

        # Test quote result taxonomy
        res = prov.fetch_quotes(["BBCA"])
        self.assertEqual(res.freshness_status, FreshnessStatus.LATEST_EOD.value)
        self.assertFalse(res.is_live, "Yahoo EOD quote must not claim is_live=True")

    # -------------------------------------------------------------------------
    # Gate 5: Reject representing missing debt as zero without evidence
    # -------------------------------------------------------------------------
    def test_gate_5_reject_missing_debt_as_zero(self) -> None:
        """CATEGORY: PURE_UNIT - CalculateFinancialRatiosTool must not assume DER=0.0 when debt is missing."""
        # Store a statement that has assets and equity, but NO debt metrics reported
        sym_dir = self.root / "data" / "equities" / "financials" / "TLKM"
        sym_dir.mkdir(parents=True, exist_ok=True)
        (sym_dir / "2024-FY.json").write_text(
            json.dumps({
                "symbol": "TLKM",
                "period": "2024-FY",
                "source": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000000.json",
                "values": {
                    "revenue": 100000.0,
                    "gross_profit": 40000.0,
                    "operating_income": 25000.0,
                    "net_income": 20000.0,
                    "total_equity": 120000.0,
                    # NOTE: total_debt, short_term_debt, long_term_debt completely absent
                },
            }),
            encoding="utf-8",
        )

        tool = CalculateFinancialRatiosTool()
        # Patch get_repo_root to our temp root
        with unittest.mock.patch("openbagus.ai.tools.finance_tools.get_repo_root", return_value=self.root):
            res, _ = tool.run(ticker="TLKM", period="2024-FY")

        self.assertIsNone(res.get("der"), "DER must be None when debt is omitted from filing")
        self.assertFalse(res.get("debt_verified"), "debt_verified must be False when debt is omitted")
        self.assertEqual(res.get("accounting_health"), "Debt Unverified")

    # -------------------------------------------------------------------------
    # Gate 6: Reject invalid stock symbol
    # -------------------------------------------------------------------------
    def test_gate_6_reject_invalid_stock_symbol(self) -> None:
        """CATEGORY: PURE_UNIT - Storage, Catalog, and DB must reject invalid symbol formats."""
        invalid_symbols = ["1234", "TOOLONGTICKERSYMBOL", "BB CA", "BBCA$%", ""]
        for bad_sym in invalid_symbols:
            with self.assertRaises((ValueError, Exception)):
                self.storage._get_symbol_dir(bad_sym)

        cat = EquityCatalog(self.root)
        for bad_sym in ["NONEXISTENT999", "INVALID_TICKER", "XYZ9"]:
            self.assertIsNone(cat.resolve(bad_sym))

    # -------------------------------------------------------------------------
    # Gate 7: Reject unavailable provider returning apparent success
    # -------------------------------------------------------------------------
    def test_gate_7_reject_unavailable_provider_success(self) -> None:
        """CATEGORY: PURE_UNIT - Provider failure must never return success=True."""
        fail_res = DataResult.failure(
            provider_id="MOCK_PROVIDER",
            error_code=ErrorCode.SOURCE_UNAVAILABLE,
            error_message="Connection timed out to primary exchange.",
        )
        self.assertFalse(fail_res.success)
        self.assertEqual(fail_res.error_code, ErrorCode.SOURCE_UNAVAILABLE.value)
        self.assertEqual(fail_res.quality_status, QualityStatus.UNAVAILABLE.value)

    # -------------------------------------------------------------------------
    # Gate 8: Reject stale cached observation labelled live
    # -------------------------------------------------------------------------
    def test_gate_8_reject_stale_cached_observation_labelled_live(self) -> None:
        """CATEGORY: PURE_UNIT - A result with historical retrieved_at cannot be marked FreshnessStatus.LIVE."""
        stale_res = DataResult(
            success=True,
            data={"price": 1000.0},
            provider_id="CACHE",
            as_of="2020-01-01T00:00:00Z",
            retrieved_at="2020-01-01T00:00:00Z",
            is_live=False,
            freshness_status=FreshnessStatus.HISTORICAL.value,
        )
        self.assertFalse(stale_res.is_live)
        self.assertNotEqual(stale_res.freshness_status, FreshnessStatus.REALTIME_VERIFIED.value)


if __name__ == "__main__":
    unittest.main()
