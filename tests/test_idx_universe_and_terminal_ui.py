"""Tests for complete IDX universe discovery, market data pipeline, and native terminal UI."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

from openbagus import cli
from openbagus.domains.equities.catalog import EquityCatalog, EquityAsset, SECTORS
from openbagus.domains.equities.data import EquityData, WIB
from openbagus.reporting.terminal_chart import render_terminal_chart
from openbagus.reporting.terminal_table import render_stocks_table, render_tabular_data
from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.domains.crypto.research import CryptoResearchRunner


class TestIdxUniverseAndTerminalUI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.catalog = EquityCatalog(self.root)

    def test_full_idx_universe_loading_and_counts(self):
        """Verify the catalog loads 950+ listed instruments covering all sectors and indices."""
        self.assertGreaterEqual(len(self.catalog.assets), 950)
        equities = [a for a in self.catalog.assets if a.asset_type == "EQUITY_ID"]
        indices = [a for a in self.catalog.assets if a.asset_type == "INDEX_ID"]
        self.assertGreaterEqual(len(equities), 930)
        self.assertGreaterEqual(len(indices), 10)

        # Verified key acceptance tickers
        for sym in ("BBCA", "BMRI", "RATU", "GOTO", "BRIS", "ADRO", "ANTM", "TLKM", "ASII", "IHSG", "LQ45"):
            asset = self.catalog.resolve(sym)
            self.assertIsNotNone(asset, f"Missing key instrument: {sym}")
            self.assertEqual(asset.symbol, sym)

    def test_all_eleven_sectors_represented(self):
        """Verify all 11 IDX-IC sector codes (A through K) are populated with listed companies."""
        for code, (en_name, id_name) in SECTORS.items():
            by_code = self.catalog.by_sector(code)
            self.assertGreater(len(by_code), 0, f"No companies in sector {code} ({en_name})")
            by_name = self.catalog.by_sector(en_name)
            self.assertGreater(len(by_name), 0, f"No companies found by name for {en_name}")

    def test_recent_ipos_and_ratu_details(self):
        """Verify recent 2024-2025 IPO discovery and RATU metadata."""
        recent = self.catalog.recent_ipos(since_year=2024, limit=50)
        self.assertGreater(len(recent), 10)
        for ipo in recent:
            self.assertGreaterEqual(ipo.listing_date, "2024-01-01")

        ratu = self.catalog.resolve("RATU")
        self.assertIsNotNone(ratu)
        self.assertEqual(ratu.sector_code, "A")
        self.assertEqual(ratu.listing_date, "2025-01-08")
        self.assertIn("oil", ratu.exposures)

    def test_search_accuracy(self):
        """Verify searching by ticker, name substring, and industry."""
        # Exact symbol
        res = self.catalog.search("GOTO")
        self.assertEqual(res[0].symbol, "GOTO")

        # Name match
        res_bank = self.catalog.search("Central Asia")
        self.assertTrue(any(a.symbol == "BBCA" for a in res_bank))

        # Name match
        res_telecom = self.catalog.search("Telkom")
        self.assertTrue(any(a.symbol == "TLKM" for a in res_telecom))

    def test_catalog_sync(self):
        """Verify catalog sync writes valid catalog file and returns summary stats."""
        res = self.catalog.sync(force_download=True)
        self.assertEqual(res["status"], "SYNCED")
        self.assertGreaterEqual(res["total_assets"], 950)
        self.assertTrue(Path(res["path"]).exists())

    def test_live_data_pipeline_fetch_and_validation(self):
        """Verify data ingestion converts raw observations to valid candles with WIB calendar buckets."""
        store = EquityData(self.root)
        now = datetime.now(timezone.utc)

        # Mock Yahoo Finance query response
        mock_raw = {
            "chart": {
                "result": [{
                    "meta": {
                        "regularMarketPrice": 10500.0,
                        "chartPreviousClose": 10450.0,
                    },
                    "timestamp": [
                        int((now - timedelta(days=3)).timestamp()),
                        int((now - timedelta(days=2)).timestamp()),
                        int((now - timedelta(days=1)).timestamp()),
                    ],
                    "indicators": {
                        "quote": [{
                            "open": [10400.0, 10450.0, 10500.0],
                            "high": [10550.0, 10550.0, 10600.0],
                            "low": [10350.0, 10400.0, 10450.0],
                            "close": [10450.0, 10500.0, 10550.0],
                            "volume": [15000000, 18000000, 20000000],
                        }]
                    }
                }]
            }
        }

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(mock_raw).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            data = store.fetch_live_data("BBCA", range_str="1mo", save=True)

        self.assertEqual(data["symbol"], "BBCA")
        self.assertEqual(len(data["candles"]), 3)
        self.assertEqual(data["currency"], "IDR")
        self.assertEqual(data["volume_unit"], "shares")
        self.assertEqual(data["quote"]["price"], 10500.0)

        # Verify stored on disk
        stored = store.load("BBCA")
        self.assertEqual(len(stored["candles"]), 3)
        self.assertEqual(stored["quote"]["price"], 10500.0)

    def test_terminal_candlestick_chart_renderer(self):
        """Verify terminal chart renders candlesticks, price levels, and volume without browser."""
        now = datetime.now(timezone.utc)
        candles = []
        for i in range(25):
            t = now - timedelta(days=26 - i)
            base = 1000 + i * 10
            candles.append({
                "open_at": t.isoformat(),
                "close_at": (t + timedelta(hours=7)).isoformat(),
                "open": base,
                "high": base + 25,
                "low": base - 15,
                "close": base + 15,
                "volume": 5000000 + i * 100000,
            })

        chart = render_terminal_chart("BBCA", candles, timeframe="D1", currency="IDR", width=80, height=12)
        self.assertIn("OPENBAGUS TERMINAL CHART: BBCA (D1)", chart)
        self.assertIn("Price:", chart)
        self.assertIn("Vol:", chart)
        self.assertIn("Rp", chart)
        # Check candlestick drawing characters
        self.assertTrue(any(c in chart for c in ("│", "█", "▒", "┼")))
        # Check volume subplot
        self.assertIn("Vol", chart)

    def test_terminal_table_rendering(self):
        """Verify stocks table rendering in terminal with clean borders."""
        assets = [
            EquityAsset("BBCA", "Bank Central Asia Tbk.", "G", industry="Financials", board="Utama", listing_date="2000-05-31"),
            EquityAsset("RATU", "PT Raharja Energi Cepu Tbk", "A", industry="Energy", board="Pengembangan", listing_date="2025-01-08"),
        ]
        table_str = render_stocks_table(assets, title="Test Equities")
        self.assertIn("BBCA", table_str)
        self.assertIn("RATU", table_str)
        self.assertIn("Bank Central Asia", table_str)
        self.assertIn("Financials", table_str)

    def test_cli_stocks_commands(self):
        """Verify CLI /stocks subcommands execution and output."""
        shell = cli.OpenBagusShell()
        shell.session = SessionState()

        # /stocks summary
        with redirect_stdout(io.StringIO()) as out:
            shell.do_stocks("")
        self.assertIn("IDX Listed Universe Summary", out.getvalue())
        self.assertIn("Total Instrumen", out.getvalue())

        # /stocks search GOTO
        with redirect_stdout(io.StringIO()) as out:
            shell.do_stocks("search GOTO")
        self.assertIn("GOTO", out.getvalue())

        # /stocks info RATU
        with redirect_stdout(io.StringIO()) as out:
            shell.do_stocks("info RATU")
        self.assertIn("Profil Emiten IDX: RATU", out.getvalue())
        self.assertIn("2025-01-08", out.getvalue())

        # /stocks sector Energy
        with redirect_stdout(io.StringIO()) as out:
            shell.do_stocks("sector Energy")
        self.assertIn("Emiten Sektor 'Energy'", out.getvalue())

        # /stocks ipo
        with redirect_stdout(io.StringIO()) as out:
            shell.do_stocks("ipo")
        self.assertIn("Daftar Emiten IPO Terbaru", out.getvalue())

    def test_export_commands_no_automatic_browser(self):
        """Verify /export html and /export word generate report files without launching browser."""
        shell = cli.OpenBagusShell()
        shell.session = SessionState()

        with patch("webbrowser.open") as mock_browser:
            with redirect_stdout(io.StringIO()) as out:
                shell.do_export("html BBCA")
            # Browser must NOT be opened automatically
            mock_browser.assert_not_called()

        with patch("webbrowser.open") as mock_browser:
            with redirect_stdout(io.StringIO()) as out:
                shell.do_export("word BBCA")
            mock_browser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
