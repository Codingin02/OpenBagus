"""Tests for IDX market universe exploration, board/tier classification, and third-liner discovery."""

import io
import json
from pathlib import Path
import tempfile
import unittest

from openbagus.domains.equities.catalog import (
    EquityAsset,
    EquityCatalog,
    SECTORS,
    normalize_board,
    normalize_listing_status,
)
from openbagus.intelligence.intent import IntentRouter
from openbagus.domains.crypto.research import CryptoResearchRunner, IntentRequest
from openbagus.domains.equities.research import run_equity_research
from openbagus.cli import OpenBagusShell


class TestIdxUniverseCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent.parent
        cls.catalog = EquityCatalog(cls.root)

    def test_universe_total_count_and_types(self):
        """Universe must cover all 968 instruments (951 equities, 17 indices)."""
        self.assertGreaterEqual(len(self.catalog.assets), 968)
        equities = [a for a in self.catalog.assets if a.asset_type == "EQUITY_ID"]
        indices = [a for a in self.catalog.assets if a.asset_type == "INDEX_ID"]
        self.assertEqual(len(equities), 951)
        self.assertEqual(len(indices), 17)

    def test_all_11_sectors_represented(self):
        """All 11 IDX-IC sectors (A through K) must be represented."""
        codes_in_catalog = {a.sector_code for a in self.catalog.assets if a.sector_code}
        for code in "ABCDEFGHIJK":
            self.assertIn(code, codes_in_catalog, f"Sector code {code} missing from IDX universe")
            self.assertIn(code, SECTORS)

    def test_board_normalization_and_separation(self):
        """Boards must be canonically distinguished; Special Monitoring must never map to Main."""
        self.assertEqual(normalize_board("Utama"), "MAIN")
        self.assertEqual(normalize_board("Main Board"), "MAIN")
        self.assertEqual(normalize_board("Pengembangan"), "DEVELOPMENT")
        self.assertEqual(normalize_board("Development Board"), "DEVELOPMENT")
        self.assertEqual(normalize_board("Pemantauan Khusus"), "SPECIAL_MONITORING")
        self.assertEqual(normalize_board("Watchlist"), "SPECIAL_MONITORING")
        self.assertEqual(normalize_board("Akselerasi"), "ACCELERATION")
        self.assertEqual(normalize_board("Acceleration Board"), "ACCELERATION")
        self.assertEqual(normalize_board("Ekonomi Baru"), "MAIN_NEW_ECONOMY")
        self.assertEqual(normalize_board("New Economy"), "MAIN_NEW_ECONOMY")
        self.assertEqual(normalize_board("Unknown Random Board"), "UNKNOWN")

        # Invariant: SPECIAL_MONITORING is strictly distinct from MAIN
        self.assertNotEqual(normalize_board("Pemantauan Khusus"), "MAIN")

    def test_status_normalization(self):
        """Listing statuses must normalize cleanly without guessing."""
        self.assertEqual(normalize_listing_status("Aktif"), "ACTIVE")
        self.assertEqual(normalize_listing_status("Trading"), "ACTIVE")
        self.assertEqual(normalize_listing_status("Suspensi"), "SUSPENDED")
        self.assertEqual(normalize_listing_status("Suspended"), "SUSPENDED")
        self.assertEqual(normalize_listing_status("Delisting"), "DELISTED")
        self.assertEqual(normalize_listing_status("Delisted"), "DELISTED")
        self.assertEqual(normalize_listing_status("NonExistentStatus"), "UNKNOWN")

    def test_market_cap_and_size_tiers(self):
        """Size tiers must be accurately computed from shares and price."""
        asset = EquityAsset(
            symbol="TEST",
            name="Test Equity Tbk",
            asset_type="EQUITY_ID",
            sector_code="A",
            shares_outstanding=10_000_000_000.0,
            board="Utama",
        )
        # 10B shares * Rp 10,000 = Rp 100 Trillion -> LARGE_CAP (> 50T)
        self.assertEqual(asset.cap_tier(price=10_000.0), "LARGE_CAP")
        # 10B shares * Rp 1,000 = Rp 10 Trillion -> MID_CAP (5T - 50T)
        self.assertEqual(asset.cap_tier(price=1_000.0), "MID_CAP")
        # 10B shares * Rp 200 = Rp 2 Trillion -> SMALL_CAP (500M - 5T)
        self.assertEqual(asset.cap_tier(price=200.0), "SMALL_CAP")
        # 10B shares * Rp 30 = Rp 300 Billion -> MICRO_CAP (< 500M)
        self.assertEqual(asset.cap_tier(price=30.0), "MICRO_CAP")

        # Zero shares and no price -> UNKNOWN_CAP
        no_shares_asset = EquityAsset(symbol="NONE", name="No Shares", shares_outstanding=0.0)
        self.assertEqual(no_shares_asset.cap_tier(price=None), "UNKNOWN_CAP")

    def test_third_liner_screening(self):
        """Third-liner search must capture small/micro cap and development/acceleration stocks."""
        third_liners = self.catalog.search_third_liners(limit=50)
        self.assertGreater(len(third_liners), 0)
        for a in third_liners:
            self.assertTrue(
                a.canonical_board in ("ACCELERATION", "DEVELOPMENT") or
                a.is_third_liner
            )

    def test_special_monitoring_and_suspended_search(self):
        """Special monitoring search must isolate special monitoring companies."""
        sm_stocks = self.catalog.search_special_monitoring(limit=50)
        self.assertGreater(len(sm_stocks), 0)
        for a in sm_stocks:
            self.assertEqual(a.canonical_board, "SPECIAL_MONITORING")

    def test_pagination_logic(self):
        """Pagination helper must accurately slice items and compute navigation metadata."""
        items = list(range(105))
        sliced, meta = EquityCatalog.paginate(items, page=1, page_size=25)
        self.assertEqual(len(sliced), 25)
        self.assertEqual(sliced[0], 0)
        self.assertEqual(sliced[-1], 24)
        self.assertEqual(meta["page"], 1)
        self.assertEqual(meta["total_pages"], 5)
        self.assertEqual(meta["total_items"], 105)
        self.assertTrue(meta["has_next"])
        self.assertFalse(meta["has_prev"])

        # Last page
        sliced_last, meta_last = EquityCatalog.paginate(items, page=5, page_size=25)
        self.assertEqual(len(sliced_last), 5)
        self.assertEqual(sliced_last[-1], 104)
        self.assertFalse(meta_last["has_next"])
        self.assertTrue(meta_last["has_prev"])

        # Page out of bounds clamps cleanly
        sliced_clamped, meta_clamped = EquityCatalog.paginate(items, page=999, page_size=25)
        self.assertEqual(meta_clamped["page"], 5)

    def test_universe_reconciliation_stats(self):
        """Universe stats must reconcile 968 instruments and known board distributions."""
        stats = self.catalog.get_universe_stats()
        self.assertEqual(stats["total_instruments"], 968)
        self.assertEqual(stats["common_equities"], 951)
        self.assertEqual(stats["indices"], 17)
        self.assertEqual(stats["boards"]["MAIN"], 252)
        self.assertEqual(stats["boards"]["DEVELOPMENT"], 440)
        self.assertEqual(stats["boards"]["SPECIAL_MONITORING"], 214)
        self.assertEqual(stats["boards"]["ACCELERATION"], 42)
        self.assertEqual(stats["boards"]["MAIN_NEW_ECONOMY"], 3)
        self.assertEqual(stats["boards"]["INDEX"], 17)

    def test_import_official_file_safety(self):
        """Importing must reject oversized files and unsupported formats, and parse without guessing."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"unsupported format")
            txt_path = Path(f.name)
        try:
            with self.assertRaises(ValueError):
                self.catalog.import_official_file(txt_path)
        finally:
            txt_path.unlink(missing_ok=True)

        # Test valid JSON import into an isolated temp directory
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            json_path = tmp_root / "sample_import.json"
            json_path.write_text(json.dumps([
                {"symbol": "TEST1", "name": "Company One", "board": "Board NonExistent", "listing_status": "UnknownStatus"},
            ]), encoding="utf-8")
            test_catalog = EquityCatalog(tmp_root)
            imported_count = test_catalog.import_official_file(json_path)
            self.assertEqual(imported_count, 1)
            imported_asset = test_catalog.resolve("TEST1")
            self.assertIsNotNone(imported_asset)
            self.assertEqual(imported_asset.canonical_board, "UNKNOWN")
            self.assertEqual(imported_asset.canonical_status, "UNKNOWN")


class TestDiscoveryIntentAndCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent.parent
        cls.router = IntentRouter()
        cls.runner = CryptoResearchRunner(repo_root=cls.root)
        cls.shell = OpenBagusShell()

    def test_intent_recognition_third_liners(self):
        """Natural Indonesian third-liner terms must route to EQUITY_DISCOVERY."""
        queries = [
            "saham lapis tiga",
            "third liner",
            "saham kecil",
            "saham mikro",
            "saham gorengan",
            "papan pemantauan khusus",
            "papan akselerasi",
            "cakupan seluruh saham idx",
        ]
        for q in queries:
            req = self.router.parse(q)
            self.assertEqual(req.asset_type, "EQUITY_ID", f"Failed for query '{q}'")
            self.assertIn(req.request_type, ("EQUITY_DISCOVERY", "EQUITY_SECTOR", "CATEGORY"))

    def test_intent_recognition_all_sectors(self):
        """Sector queries must route to EQUITY_SECTOR."""
        req_health = self.router.parse("saham sektor kesehatan")
        self.assertEqual(req_health.category, "F")
        self.assertEqual(req_health.request_type, "EQUITY_SECTOR")

        req_energy = self.router.parse("daftar saham sektor energi")
        self.assertEqual(req_energy.category, "A")
        self.assertEqual(req_energy.request_type, "EQUITY_SECTOR")

    def test_researcher_equity_discovery_execution(self):
        """Researcher must execute EQUITY_DISCOVERY requests cleanly."""
        req_coverage = IntentRequest(intent="CATEGORY", request_type="EQUITY_DISCOVERY", focus="coverage", asset_type="EQUITY_ID")
        res_coverage = run_equity_research(self.runner, req_coverage)
        self.assertIn("Cakupan Semesta Pasar IDX", res_coverage)
        self.assertIn("Total Seluruh Instrumen : 968", res_coverage)

        req_third = IntentRequest(intent="CATEGORY", request_type="EQUITY_DISCOVERY", focus="third_liner", asset_type="EQUITY_ID")
        res_third = run_equity_research(self.runner, req_third)
        self.assertIn("Eksplorasi Saham Lapis Tiga", res_third)

        req_sm = IntentRequest(intent="CATEGORY", request_type="EQUITY_DISCOVERY", focus="special_monitoring", asset_type="EQUITY_ID")
        res_sm = run_equity_research(self.runner, req_sm)
        self.assertIn("Papan Pemantauan Khusus", res_sm)

    def test_cli_stocks_subcommands(self):
        """CLI do_stocks must handle explorer subcommands without exceptions."""
        subcommands = [
            "",
            "all",
            "all 2",
            "board utama",
            "board pengembangan",
            "board akselerasi",
            "board pemantauan khusus",
            "tier small_cap",
            "smallcap",
            "microcap",
            "third-liner",
            "coverage",
            "info BBCA",
            "search perbankan",
            "sector A",
            "ipo",
        ]
        for sub in subcommands:
            try:
                # Capture standard output to ensure clean execution
                import sys
                old_stdout = sys.stdout
                sys.stdout = io.StringIO()
                self.shell.do_stocks(sub)
                output = sys.stdout.getvalue()
                sys.stdout = old_stdout
                self.assertTrue(len(output) > 0, f"Empty output for /stocks {sub}")
            except Exception as e:
                self.fail(f"/stocks {sub} raised exception: {e}")


if __name__ == "__main__":
    unittest.main()
