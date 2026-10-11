"""Unit tests for Indonesian Official Financial Data Integration."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbagus.cli import OpenBagusShell
from openbagus.data.indonesia_official import (
    BankIndonesiaAdapter,
    BPSAdapter,
    KemendagAdapter,
    OJKPublicAdapter,
    WorldBankAdapter,
    safe_parse_xml,
)
from openbagus.data.providers import ProviderRegistry
from openbagus.domains.equities.data import EquityData, read_tabular


class TestIndonesiaOfficialAdapters(unittest.TestCase):
    def test_safe_parse_xml(self) -> None:
        xml_text = "<root><item id='1'>Value</item></root>"
        root = safe_parse_xml(xml_text)
        self.assertEqual(root.tag, "root")
        self.assertEqual(root.find("item").text, "Value")

    def test_bank_indonesia_jisdor_latest_mock(self) -> None:
        sample_xml = b"""<?xml version="1.0" encoding="utf-8"?>
        <DataSet xmlns="http://tempuri.org/">
            <Table>
                <mts_subkursasing>USD</mts_subkursasing>
                <beli_subkursasing>16250.00</beli_subkursasing>
                <jual_subkursasing>16250.00</jual_subkursasing>
                <tgl_subkursasing>2026-10-09T00:00:00</tgl_subkursasing>
            </Table>
        </DataSet>"""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = sample_xml
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = BankIndonesiaAdapter.get_jisdor_latest()
            self.assertIsNotNone(res)
            self.assertEqual(res["rate"], 16250.0)
            self.assertEqual(res["currency"], "USD")
            self.assertEqual(res["date"], "2026-10-09")
            self.assertTrue(res["is_reference_only"])
            self.assertFalse(res["is_executable"])

    def test_bank_indonesia_jisdor_history_mock(self) -> None:
        sample_xml = b"""<?xml version="1.0" encoding="utf-8"?>
        <DataSet xmlns="http://tempuri.org/">
            <Table>
                <beli_subkursasing>16200.00</beli_subkursasing>
                <tgl_subkursasing>2026-10-08T00:00:00</tgl_subkursasing>
            </Table>
            <Table>
                <beli_subkursasing>16250.00</beli_subkursasing>
                <tgl_subkursasing>2026-10-09T00:00:00</tgl_subkursasing>
            </Table>
        </DataSet>"""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = sample_xml
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            points = BankIndonesiaAdapter.get_jisdor_history(days=5)
            self.assertEqual(len(points), 2)
            self.assertEqual(points[0]["value"], 16200.0)
            self.assertEqual(points[1]["value"], 16250.0)

    def test_bank_indonesia_transaction_rates_mock(self) -> None:
        sample_xml = b"""<?xml version="1.0" encoding="utf-8"?>
        <DataSet xmlns="http://tempuri.org/">
            <Table>
                <mts_subkurslokal>USD</mts_subkurslokal>
                <beli_subkurslokal>16150.00</beli_subkurslokal>
                <jual_subkurslokal>16350.00</jual_subkurslokal>
                <tgl_subkurslokal>2026-10-09</tgl_subkurslokal>
            </Table>
        </DataSet>"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = sample_xml
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            rates = BankIndonesiaAdapter.get_transaction_rates_latest()
            self.assertEqual(len(rates), 1)
            self.assertEqual(rates[0]["currency"], "USD")
            self.assertEqual(rates[0]["buy"], 16150.0)
            self.assertEqual(rates[0]["sell"], 16350.0)
            self.assertEqual(rates[0]["mid"], 16250.0)

    def test_bps_adapter_key_validation(self) -> None:
        # Invalid short key
        inv = BPSAdapter.validate_key("abc")
        self.assertFalse(inv["valid"])
        self.assertEqual(inv["status"], "INVALID_KEY_FORMAT")

        # Mock valid BPS response
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "OK", "data-availability": "available"}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp):
            val = BPSAdapter.validate_key("valid_bps_key_12345")
            self.assertTrue(val["valid"])
            self.assertEqual(val["status"], "VALIDATED")

    def test_world_bank_adapter_macro_mock(self) -> None:
        raw_wb = [
            {"page": 1, "pages": 1, "per_page": 5, "total": 2},
            [
                {"indicator": {"id": "FP.CPI.TOTL.ZG", "value": "Inflation"}, "country": {"value": "Indonesia"}, "date": "2024", "value": 2.57},
                {"indicator": {"id": "FP.CPI.TOTL.ZG", "value": "Inflation"}, "country": {"value": "Indonesia"}, "date": "2023", "value": 3.67},
            ],
        ]
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(raw_wb).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = WorldBankAdapter.get_indonesia_macro("FP.CPI.TOTL.ZG")
            self.assertEqual(len(res), 2)
            self.assertEqual(res[0]["date"], "2024")
            self.assertEqual(res[0]["value"], 2.57)

    def test_ojk_and_kemendag_benchmarks(self) -> None:
        ojk_bm = OJKPublicAdapter.get_benchmark_banking_metrics()
        self.assertEqual(ojk_bm["data_category"], "AGGREGATE_INDUSTRY_STATISTICS")
        self.assertGreater(ojk_bm["industry_nim_pct"], 0)
        self.assertGreater(ojk_bm["industry_car_pct"], 15.0)

        kem_bm = KemendagAdapter.get_staple_and_export_benchmarks()
        self.assertEqual(kem_bm["category"], "COMMODITY_AND_TRADE_EVIDENCE")
        self.assertIn("beras_medium", kem_bm["staple_prices_idr_kg"])
        self.assertIn("cpo_rotterdam_ton", kem_bm["export_commodities_usd"])


class TestTabularReaderAndAssistedImports(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_read_tabular_csv_and_json(self) -> None:
        csv_file = self.root / "test.csv"
        csv_file.write_text("Col1,Col2\nVal1,Val2\n", encoding="utf-8")
        rows = read_tabular(csv_file)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], ["Col1", "Col2"])

        json_file = self.root / "test.json"
        json_file.write_text(json.dumps([["A", "B"], ["1", "2"]]), encoding="utf-8")
        j_rows = read_tabular(json_file)
        self.assertEqual(j_rows, [["A", "B"], ["1", "2"]])

    def test_read_tabular_xlsx(self) -> None:
        xlsx_file = self.root / "test.xlsx"
        sheet_xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            b'<sheetData>'
            b'<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>100</v></c></row>'
            b'</sheetData></worksheet>'
        )
        shared_xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            b'<si><t>HeaderX</t></si>'
            b'</sst>'
        )
        with zipfile.ZipFile(xlsx_file, "w") as z:
            z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
            z.writestr("xl/sharedStrings.xml", shared_xml)

        rows = read_tabular(xlsx_file)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "HeaderX")
        self.assertEqual(rows[0][1], "100")

    def test_import_idx_trading_summary_csv(self) -> None:
        csv_content = """Kode Saham,Nama Saham,Sebelumnya,Pembukaan,Tertinggi,Terendah,Penutupan,Volume,Nilai
BBCA,Bank Central Asia,10000,10100,10200,10050,10150,50000000,507500000000
BMRI,Bank Mandiri,6500,6550,6600,6500,6575,30000000,197250000000
"""
        summary_path = self.root / "Ringkasan Saham 2026-10-09.csv"
        summary_path.write_text(csv_content, encoding="utf-8")

        store = EquityData(self.root)
        res = store.import_idx_trading_summary(summary_path)
        self.assertEqual(res["imported_tickers_count"], 2)
        self.assertEqual(res["date"], "2026-10-09")

        bbca = store.load("BBCA", auto_fetch=False)
        self.assertEqual(len(bbca["candles"]), 1)
        self.assertEqual(bbca["candles"][0]["close"], 10150.0)
        self.assertEqual(bbca["candles"][0]["volume"], 50000000.0)

    def test_import_financial_statement_csv(self) -> None:
        csv_content = """Periode,FY 2025
Satuan,Jutaan Rupiah
Basis,Konsolidasian
Pendapatan,67910000
Laba Usaha,14200000
Laba Bersih,9500000
Total Aset,120000000
Total Ekuitas,65000000
Total Liabilitas,55000000
Kas dan Setara Kas,15000000
Jumlah Saham Beredar,11660
"""
        stmt_path = self.root / "Financial_Statement_ICBP_2025.csv"
        stmt_path.write_text(csv_content, encoding="utf-8")

        store = EquityData(self.root)
        res = store.import_financial_statement(stmt_path, ticker="ICBP")
        self.assertEqual(res["symbol"], "ICBP")
        self.assertEqual(res["period"], "FY 2025")
        ratios = res["ratios"]
        self.assertAlmostEqual(ratios["Operating_Margin_pct"], (14200000 / 67910000) * 100.0, places=1)
        self.assertAlmostEqual(ratios["Net_Margin_pct"], (9500000 / 67910000) * 100.0, places=1)
        self.assertAlmostEqual(ratios["ROE_pct"], (9500000 / 65000000) * 100.0, places=1)
        self.assertAlmostEqual(ratios["Debt_to_Equity"], 55000000 / 65000000, places=2)

    def test_ojk_and_kemendag_file_imports(self) -> None:
        ojk_csv = self.root / "ojk_spi.csv"
        ojk_csv.write_text("Periode,2024-Q4\nNIM,4.58%\nNPL Gross,2.21%\nCAR,27.34%\n", encoding="utf-8")
        res_ojk = OJKPublicAdapter.import_statistics_file(ojk_csv)
        self.assertEqual(res_ojk["period"], "2024-Q4")
        self.assertEqual(res_ojk["data_category"], "AGGREGATE_INDUSTRY_STATISTICS")
        self.assertEqual(res_ojk["metrics"]["NIM"], 4.58)

        kem_csv = self.root / "kemendag_staples.csv"
        kem_csv.write_text("beras_medium,13600\nminyak_goreng_curah,15800\n", encoding="utf-8")
        res_kem = KemendagAdapter.import_trade_file(kem_csv)
        self.assertEqual(res_kem["items"]["beras_medium"], 13600.0)


class TestCliMacroAndDataCommands(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_cli_do_macro_and_do_data_sources(self) -> None:
        shell = OpenBagusShell()
        buf = io.StringIO()
        with redirect_stdout(buf):
            shell.do_macro("")
        out = buf.getvalue()
        self.assertIn("Ringkasan Makroekonomi & Pasar Indonesia", out)

        buf = io.StringIO()
        with redirect_stdout(buf):
            shell.do_data("sources indonesia")
        out_src = buf.getvalue()
        self.assertIn("Bank Indonesia", out_src)
        self.assertIn("BPS", out_src)
        self.assertIn("OJK SJKPublic", out_src)

    def test_providers_indonesia_and_free_views(self) -> None:
        reg = ProviderRegistry(self.root)
        idn_view = reg.format_providers_view(domain="indonesia")
        self.assertIn("INDONESIA OFFICIAL DATA & MARKET INFRASTRUCTURE", idn_view)
        self.assertIn("Bank Indonesia (wsKursBI Official)", idn_view)
        self.assertIn("World Bank Open Data (Indonesia Macro)", idn_view)

        free_view = reg.format_providers_view(domain="free")
        self.assertIn("PERMANENT FREE & ZERO-KEY DATA INFRASTRUCTURE", free_view)
        self.assertNotIn("Twelve Data", free_view)
        self.assertNotIn("Financial Modeling Prep", free_view)


if __name__ == "__main__":
    unittest.main()
