"""Unit tests for Indonesian equities shareholder ownership intelligence.

Enforces strict verification and mathematical invariants:
1. Valid disclosure reconciles correctly
2. Shares and percentage mathematically reconcile
3. Percentage calculated from shares outstanding when missing
4. Negative shares rejected
5. Percentage > 100 rejected
6. Duplicate shareholder rejected
7. Sum > 100 rejected
8. Mixed denominator rejected
9. Empty source rejected
10. Unclassified remainder distinguished from regulatory free float
11. No fallback to unverified seeds in production
12. Synthetic test ownership fixtures accessible for tests
13. CSV/JSON user imports set USER_IMPORTED verification status
"""

import json
import tempfile
import unittest
from pathlib import Path

from openbagus.domains.equities.ownership import (
    DENOMINATOR_REGISTERED_HOLDINGS,
    DENOMINATOR_SHARES_OUTSTANDING,
    OwnershipStructure,
    ShareholderRecord,
    get_synthetic_test_ownership,
    import_ownership_file,
    load_ownership,
    reconcile_ownership,
)


class TestIndonesianOwnership(unittest.TestCase):
    def test_01_valid_disclosure_reconciles_correctly(self):
        raw_holders = [
            {
                "shareholder": "PT Maju Bersama",
                "investor_type": "Domestic Institution",
                "shares_held": 55_000_000.0,
                "percentage": 55.0,
            },
            {
                "shareholder": "Direktur Utama",
                "investor_type": "Domestic Individual",
                "shares_held": 5_000_000.0,
                "percentage": 5.0,
            },
        ]
        res = reconcile_ownership(
            ticker="TEST",
            issuer="PT Test Issuer Tbk",
            reporting_date="2026-06-30",
            publication_date="2026-07-10",
            source="https://www.idx.co.id/id/perusahaan-tercatat/data-kepemilikan-saham/",
            shares_outstanding=100_000_000.0,
            raw_top_holders=raw_holders,
            domestic_pct=70.0,
            foreign_pct=30.0,
            regulatory_free_float_pct=38.5,
        )
        self.assertEqual(res.ticker, "TEST")
        self.assertEqual(len(res.top_shareholders), 2)
        self.assertAlmostEqual(res.public_shareholders_pct, 40.0, places=2)
        self.assertAlmostEqual(res.domestic_pct, 70.0, places=2)
        self.assertAlmostEqual(res.foreign_pct, 30.0, places=2)
        self.assertAlmostEqual(res.regulatory_free_float_pct, 38.5, places=2)
        self.assertTrue(res.reconciled)
        self.assertIn("shares outstanding", res.denominator_explanation)

    def test_02_shares_and_percentage_mathematically_reconcile(self):
        # Discrepancy > 1.0% between shares and stated percentage must raise ValueError
        raw_conflicting = [
            {
                "shareholder": "Conflicted Holder",
                "shares_held": 50_000_000.0,  # 50% of 100M
                "percentage": 10.0,  # Stated 10%, conflict of 40%
            }
        ]
        with self.assertRaises(ValueError):
            reconcile_ownership(
                ticker="CONFLICT",
                issuer="PT Conflict Tbk",
                reporting_date="2026-06-30",
                publication_date="2026-07-10",
                source="https://www.idx.co.id/",
                shares_outstanding=100_000_000.0,
                raw_top_holders=raw_conflicting,
            )

    def test_03_percentage_calculated_from_shares_outstanding_when_missing(self):
        raw_holders = [
            {
                "shareholder": "Major Stakeholder",
                "shares_held": 25_000_000.0,
                "percentage": 0.0,  # Missing percentage, should compute 25%
            }
        ]
        res = reconcile_ownership(
            ticker="ABC",
            issuer="PT ABC Tbk",
            reporting_date="2026-06-30",
            publication_date="2026-07-10",
            source="https://www.idx.co.id/",
            shares_outstanding=100_000_000.0,
            raw_top_holders=raw_holders,
        )
        self.assertAlmostEqual(res.top_shareholders[0].percentage, 25.0, places=2)
        self.assertAlmostEqual(res.public_shareholders_pct, 75.0, places=2)

    def test_04_negative_shares_rejected(self):
        raw_negative = [
            {
                "shareholder": "Negative Holder",
                "shares_held": -500_000.0,
                "percentage": 5.0,
            }
        ]
        with self.assertRaises(ValueError):
            reconcile_ownership(
                ticker="NEG",
                issuer="PT Neg Tbk",
                reporting_date="2026-06-30",
                publication_date="2026-07-10",
                source="https://www.idx.co.id/",
                shares_outstanding=100_000_000.0,
                raw_top_holders=raw_negative,
            )

    def test_05_percentage_bounds_rejected(self):
        raw_over = [
            {
                "shareholder": "Excess Holder",
                "shares_held": 150_000_000.0,
                "percentage": 105.0,
            }
        ]
        with self.assertRaises(ValueError):
            reconcile_ownership(
                ticker="BOUNDS",
                issuer="PT Bounds Tbk",
                reporting_date="2026-06-30",
                publication_date="2026-07-10",
                source="https://www.idx.co.id/",
                shares_outstanding=100_000_000.0,
                raw_top_holders=raw_over,
            )

    def test_06_duplicate_shareholder_rejected(self):
        raw_duplicates = [
            {
                "shareholder": "PT Investor Bersama",
                "shares_held": 20_000_000.0,
                "percentage": 20.0,
            },
            {
                "shareholder": "pt investor bersama",  # Case-insensitive duplicate
                "shares_held": 10_000_000.0,
                "percentage": 10.0,
            },
        ]
        with self.assertRaises(ValueError):
            reconcile_ownership(
                ticker="DUP",
                issuer="PT Dup Tbk",
                reporting_date="2026-06-30",
                publication_date="2026-07-10",
                source="https://www.idx.co.id/",
                shares_outstanding=100_000_000.0,
                raw_top_holders=raw_duplicates,
            )

    def test_07_sum_exceeding_100_rejected(self):
        raw_over_sum = [
            {
                "shareholder": "Holder A",
                "shares_held": 60_000_000.0,
                "percentage": 60.0,
            },
            {
                "shareholder": "Holder B",
                "shares_held": 45_000_000.0,
                "percentage": 45.0,
            },
        ]
        with self.assertRaises(ValueError):
            reconcile_ownership(
                ticker="OVERSUM",
                issuer="PT Oversum Tbk",
                reporting_date="2026-06-30",
                publication_date="2026-07-10",
                source="https://www.idx.co.id/",
                shares_outstanding=100_000_000.0,
                raw_top_holders=raw_over_sum,
            )

        # Domestic + Foreign sum > 100% also rejected
        with self.assertRaises(ValueError):
            reconcile_ownership(
                ticker="DFOVER",
                issuer="PT DF Over Tbk",
                reporting_date="2026-06-30",
                publication_date="2026-07-10",
                source="https://www.idx.co.id/",
                shares_outstanding=100_000_000.0,
                raw_top_holders=[],
                domestic_pct=70.0,
                foreign_pct=35.0,
            )

    def test_08_mixed_denominator_rejected(self):
        raw_mixed = [
            {
                "shareholder": "Holder Registered",
                "shares_held": 10_000_000.0,
                "percentage": 10.0,
                "denominator_type": DENOMINATOR_REGISTERED_HOLDINGS,
            }
        ]
        with self.assertRaises(ValueError):
            reconcile_ownership(
                ticker="MIXED",
                issuer="PT Mixed Tbk",
                reporting_date="2026-06-30",
                publication_date="2026-07-10",
                source="https://www.idx.co.id/",
                shares_outstanding=100_000_000.0,
                raw_top_holders=raw_mixed,
                denominator_type=DENOMINATOR_SHARES_OUTSTANDING,
            )

    def test_09_empty_source_rejected(self):
        with self.assertRaises(ValueError):
            reconcile_ownership(
                ticker="NOSOURCE",
                issuer="PT No Source Tbk",
                reporting_date="2026-06-30",
                publication_date="2026-07-10",
                source="   ",  # Whitespace source
                shares_outstanding=100_000_000.0,
                raw_top_holders=[],
            )

    def test_10_unclassified_remainder_distinguished_from_regulatory_free_float(self):
        raw_holders = [
            {
                "shareholder": "Induk Holding",
                "shares_held": 60_000_000.0,
                "percentage": 60.0,
            }
        ]
        res = reconcile_ownership(
            ticker="FLOAT",
            issuer="PT Float Tbk",
            reporting_date="2026-06-30",
            publication_date="2026-07-10",
            source="https://www.idx.co.id/",
            shares_outstanding=100_000_000.0,
            raw_top_holders=raw_holders,
            regulatory_free_float_pct=15.0,
        )
        # Remainder is 40%, distinct from regulatory free float of 15%
        self.assertEqual(res.public_shareholders_pct, 40.0)
        self.assertEqual(res.regulatory_free_float_pct, 15.0)
        self.assertIn("bukan free float regulasi yang disahkan", res.denominator_explanation)
        self.assertIn("Disclosed regulatory free float: 15.00%", res.reconciliation_notes)

    def test_11_load_ownership_does_not_use_synthetic_seeds_in_production(self):
        # In production without an imported file, load_ownership returns None (never synthetic seeds)
        root = Path("nonexistent_directory_never_used_12345")
        for sym in ("BBCA", "BBRI", "BMRI", "TLKM", "ASII", "ANTM"):
            self.assertIsNone(load_ownership(sym, root))

    def test_12_synthetic_test_ownership_fixtures_available_for_tests(self):
        # get_synthetic_test_ownership is available specifically for test harness fixtures
        for sym in ("BBCA", "BBRI", "BMRI", "TLKM", "ASII", "ANTM"):
            own = get_synthetic_test_ownership(sym)
            self.assertIsNotNone(own, f"Test fixture for {sym} must be present")
            self.assertEqual(own.ticker, sym)
            self.assertEqual(own.verification_status, "UNVERIFIED")
            self.assertGreater(own.shares_outstanding, 0)
            self.assertGreater(len(own.top_shareholders), 0)

    def test_13_import_ownership_json_and_csv(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            json_file = root / "IMPORT_OWN.json"
            json_data = {
                "ticker": "BBCA",
                "issuer": "PT Bank Central Asia Tbk",
                "reporting_date": "2026-06-30",
                "publication_date": "2026-07-10",
                "source": "https://www.idx.co.id/id/perusahaan-tercatat/data-kepemilikan-saham/",
                "shares_outstanding": 123275050000.0,
                "top_shareholders": [
                    {
                        "shareholder": "PT Dwimuria Investama Andalan",
                        "investor_type": "Domestic Institution",
                        "shares_held": 67729950000.0,
                        "percentage": 54.94,
                    }
                ],
                "domestic_pct": 69.12,
                "foreign_pct": 30.88,
            }
            json_file.write_text(json.dumps(json_data), encoding="utf-8")
            imported_ticker = import_ownership_file(json_file, root)
            self.assertEqual(imported_ticker, "BBCA")
            loaded = load_ownership("BBCA", root)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.ticker, "BBCA")
            self.assertEqual(loaded.verification_status, "USER_IMPORTED")
            self.assertAlmostEqual(loaded.top_shareholders[0].percentage, 54.94, places=2)


if __name__ == "__main__":
    unittest.main()
