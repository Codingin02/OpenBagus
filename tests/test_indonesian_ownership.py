"""Unit tests for Indonesian equities shareholder ownership intelligence."""

import json
import tempfile
import unittest
from pathlib import Path

from openbagus.domains.equities.ownership import (
    DENOMINATOR_REGISTERED_HOLDINGS,
    DENOMINATOR_SHARES_OUTSTANDING,
    OwnershipStructure,
    ShareholderRecord,
    import_ownership_file,
    load_ownership,
    reconcile_ownership,
)


class TestIndonesianOwnership(unittest.TestCase):
    def test_reconcile_ownership_and_public_float(self):
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
        )
        self.assertEqual(res.ticker, "TEST")
        self.assertEqual(len(res.top_shareholders), 2)
        # Public float = 100% - 60% = 40%
        self.assertAlmostEqual(res.public_shareholders_pct, 40.0, places=2)
        self.assertAlmostEqual(res.domestic_pct, 70.0, places=2)
        self.assertAlmostEqual(res.foreign_pct, 30.0, places=2)
        self.assertTrue(res.reconciled)
        self.assertIn("shares outstanding", res.denominator_explanation)

    def test_percentage_calculation_when_missing(self):
        raw_holders = [
            {
                "shareholder": "Major Stakeholder",
                "shares_held": 25_000_000.0,
                "percentage": 0.0,  # Missing percentage, should compute
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

    def test_domestic_foreign_normalization(self):
        # Unnormalized percentages summing to != 100%
        res = reconcile_ownership(
            ticker="XYZ",
            issuer="PT XYZ Tbk",
            reporting_date="2026-06-30",
            publication_date="2026-07-10",
            source="https://www.idx.co.id/",
            shares_outstanding=50_000_000.0,
            raw_top_holders=[],
            domestic_pct=60.0,
            foreign_pct=20.0,  # Sum = 80%, should normalize to 75% / 25%
        )
        self.assertAlmostEqual(res.domestic_pct + res.foreign_pct, 100.0, places=2)
        self.assertAlmostEqual(res.domestic_pct, 75.0, places=2)
        self.assertAlmostEqual(res.foreign_pct, 25.0, places=2)

    def test_denominator_registered_holdings(self):
        res = reconcile_ownership(
            ticker="KSEI_TEST",
            issuer="PT KSEI Test Tbk",
            reporting_date="2026-06-30",
            publication_date="2026-07-10",
            source="https://www.ksei.co.id/",
            shares_outstanding=10_000_000.0,
            raw_top_holders=[],
            denominator_type=DENOMINATOR_REGISTERED_HOLDINGS,
        )
        self.assertEqual(res.denominator_type, DENOMINATOR_REGISTERED_HOLDINGS)
        self.assertIn("KSEI", res.denominator_explanation)

    def test_verified_seed_issuers(self):
        root = Path(".")
        for sym in ("BBCA", "BBRI", "BMRI", "TLKM", "ASII", "ANTM"):
            own = load_ownership(sym, root)
            self.assertIsNotNone(own, f"Seed for {sym} must be present")
            self.assertEqual(own.ticker, sym)
            self.assertGreater(own.shares_outstanding, 0)
            self.assertGreater(len(own.top_shareholders), 0)
            self.assertGreater(own.domestic_pct, 0)
            self.assertGreater(own.foreign_pct, 0)
            self.assertAlmostEqual(own.domestic_pct + own.foreign_pct, 100.0, places=2)
            self.assertGreaterEqual(own.public_shareholders_pct, 0.0)

    def test_import_ownership_json_and_csv(self):
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
            self.assertAlmostEqual(loaded.top_shareholders[0].percentage, 54.94, places=2)


if __name__ == "__main__":
    unittest.main()
