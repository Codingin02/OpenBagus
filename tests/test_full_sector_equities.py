"""Tests for complete 11-sector IDX integration, ARA/ARB rules, and on-demand acquisition."""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from openbagus.domains.crypto.research import CryptoResearchRunner
from openbagus.domains.equities.catalog import EquityCatalog, SECTORS
from openbagus.domains.equities.data import EquityData
from openbagus.domains.equities.policy import EquityMarketPolicy
from openbagus.domains.equities.research import equity_context, render_equity, run_equity_research
from openbagus.intelligence.intent import IntentRouter, IntentRequest, SessionState
from openbagus.intelligence.local_language import LocalLanguageEngine
from openbagus.domains.crypto.quant import QuantEngine


class TestFullSectorEquities(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.no_llm = patch.object(LocalLanguageEngine, "is_available", return_value=False)
        self.no_llm.start()
        self.addCleanup(self.no_llm.stop)
        self.router = IntentRouter(repo_root=self.root)
        self.runner = CryptoResearchRunner(self.root)
        self.policy = EquityMarketPolicy(self.root)

    def test_all_eleven_sectors_coverage_and_context(self):
        catalog = self.runner.assets.equities
        expected_sample = {
            "A": "ADRO",  # Energy
            "B": "ANTM",  # Basic Materials
            "C": "ASII",  # Industrials
            "D": "ICBP",  # Consumer Non-Cyclicals
            "E": "MAPI",  # Consumer Cyclicals
            "F": "KLBF",  # Healthcare
            "G": "BBCA",  # Financials
            "H": "CTRA",  # Properties & Real Estate
            "I": "GOTO",  # Technology
            "J": "TLKM",  # Infrastructures
            "K": "BIRD",  # Transportation & Logistics
        }
        for code, sym in expected_sample.items():
            asset = catalog.resolve(sym)
            self.assertIsNotNone(asset, f"Asset {sym} in sector {code} should be resolvable")
            self.assertEqual(asset.sector_code, code)
            ctx = equity_context(asset, f"analisa {sym}")
            self.assertTrue(len(ctx) > 30, f"Sector {code} ({sym}) context should be substantive")

    def test_auto_rejection_limits_by_tier(self):
        # Tier 1: <= 200 (±35%)
        low, high = self.policy.auto_rejection_limits(100.0, board="MAIN")
        self.assertEqual(low, 65.0)
        self.assertEqual(high, 135.0)

        # Tier 2: 200 to 5000 (±25%)
        low, high = self.policy.auto_rejection_limits(1000.0, board="MAIN")
        self.assertEqual(low, 750.0)
        self.assertEqual(high, 1250.0)

        # Tier 3: > 5000 (±20%)
        low, high = self.policy.auto_rejection_limits(6000.0, board="MAIN")
        self.assertEqual(low, 4800.0)
        self.assertEqual(high, 7200.0)

        # Acceleration board (±35%, min price Rp 1)
        low, high = self.policy.auto_rejection_limits(10.0, board="ACCELERATION")
        self.assertEqual(low, 7.0)
        self.assertEqual(high, 13.0)

        # Special Monitoring / Watchlist / FCA (±10%, min price Rp 1)
        low, high = self.policy.auto_rejection_limits(50.0, board="WATCHLIST")
        self.assertEqual(low, 45.0)
        self.assertEqual(high, 55.0)

    def test_strict_candle_rejection_without_silent_mutation(self):
        store = EquityData(self.root)
        # Mock chart response with one inverted candle (low > high)
        inverted_chart = {
            "chart": {
                "result": [{
                    "meta": {"regularMarketPrice": 1000.0, "chartPreviousClose": 1000.0, "regularMarketTime": 1700000000},
                    "timestamp": [1700000000, 1700086400],
                    "indicators": {
                        "quote": [{
                            "open": [1000.0, 1010.0],
                            "high": [1050.0, 1000.0],  # Inverted: high 1000 < open 1010
                            "low": [950.0, 1020.0],   # Inverted: low 1020 > high 1000
                            "close": [1020.0, 1010.0],
                            "volume": [5000, 1000],
                        }]
                    }
                }]
            }
        }
        with patch("urllib.request.urlopen") as mock_open:
            import io
            mock_resp = unittest.mock.MagicMock()
            mock_resp.status = 200
            mock_resp.read.return_value = json.dumps(inverted_chart).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_open.return_value = mock_resp

            data = store.fetch_live_data("TEST", range_str="1mo", save=False)
            self.assertEqual(data.get("symbol"), "TEST")
            # Inverted candle must be discarded, only the 1 valid candle kept
            candles = data.get("candles", [])
            self.assertEqual(len(candles), 1)
            self.assertEqual(candles[0]["open"], 1000.0)
            self.assertEqual(candles[0]["high"], 1050.0)

    def test_catalog_provenance_and_sync_status(self):
        cat = EquityCatalog(self.root)
        self.assertIn("Dataset-Saham-IDX", cat.source_provenance)
        sync_res = cat.sync(force_download=True)
        self.assertEqual(sync_res["status"], "SYNCED")
        self.assertEqual(sync_res["sync_status"], "ONLINE_PROVIDER_SYNCED")
        self.assertEqual(sync_res["provenance"], cat.source_provenance)
        self.assertGreater(sync_res["total_assets"], 900)

    def test_official_file_import_csv(self):
        cat = EquityCatalog(self.root)
        csv_content = (
            "Kode Saham,Nama Perusahaan,Sektor,Papan Pencatatan,Tanggal Pencatatan,Jumlah Saham Beredar\n"
            "CUST,PT Custom Industri Tbk,Perindustrian,Utama,2024-05-10,500000000\n"
            "HLTH,PT Health Care Tbk,Kesehatan,Pengembangan,2023-01-15,300000000\n"
        )
        csv_path = self.root / "official_idx.csv"
        csv_path.write_text(csv_content, encoding="utf-8")
        imported = cat.import_official_file(csv_path)
        self.assertEqual(imported, 2)
        cust = cat.resolve("CUST")
        self.assertIsNotNone(cust)
        self.assertEqual(cust.sector_code, "C")
        self.assertEqual(cust.board, "MAIN")
        hlth = cat.resolve("HLTH")
        self.assertIsNotNone(hlth)
        self.assertEqual(hlth.sector_code, "F")
        self.assertEqual(cat.sync_status, "OFFICIAL_IMPORT_UPDATED")

    def test_on_demand_acquisition_in_research_flow(self):
        # When local data is missing, run_equity_research triggers load(auto_fetch=True)
        req = self.router.parse("analisa KLBF")
        self.assertEqual(req.asset, "KLBF")
        with patch.object(EquityData, "fetch_live_data") as mock_fetch:
            mock_fetch.return_value = {
                "symbol": "KLBF",
                "authorized_use": True,
                "source": "https://finance.yahoo.com/quote/KLBF.JK",
                "retrieved_at": "2026-01-05T09:00:00+07:00",
                "currency": "IDR",
                "volume_unit": "shares",
                "timeframe": "D1",
                "adjustment": "adjusted",
                "unresolved_corporate_actions": False,
                "listing_status": "ACTIVE",
                "board": "MAIN",
                "quote": {"price": 1500.0, "previous_close": 1500.0, "as_of": "2026-01-05T09:00:00+07:00", "delayed": False,
                          "price_limit_low": 1125.0, "price_limit_high": 1875.0},
                "fees": {"buy": 0.0015, "sell": 0.0025},
                "candles": [
                    {"open_at": f"2025-12-{i:02d}T09:00:00+07:00", "close_at": f"2025-12-{i:02d}T16:00:00+07:00",
                     "open": 1490.0, "high": 1520.0, "low": 1480.0, "close": 1500.0, "volume": 100000, "is_closed_candle": True}
                    for i in range(1, 26)
                ],
                "gaps": [],
            }
            res = self.runner.execute(req, SessionState())
            self.assertIn("KLBF", res)
            self.assertIn("IDX", res)
            mock_fetch.assert_called_once()

    def test_render_equity_sector_valuation_metrics(self):
        asset = self.runner.assets.equities.resolve("ICBP")
        data = {
            "symbol": "ICBP",
            "period": "2025",
            "period_type": "FY",
            "basis": "consolidated",
            "source": "https://www.idx.co.id/",
            "ratios": {
                "PER": 14.5,
                "PBV": 2.8,
                "ROE_pct": 19.3,
                "Operating_Margin_pct": 21.0,
                "Net_Margin_pct": 12.5,
                "Debt_to_Equity": 0.75,
            },
        }
        from openbagus.domains.crypto.research import ResearchPacket
        quant = QuantEngine().evaluate_equity("ICBP", {
            "symbol": "ICBP", "authorized_use": True, "source": "https://idx.co.id", "retrieved_at": "2026-01-05T09:00:00+07:00",
            "currency": "IDR", "volume_unit": "shares", "timeframe": "D1", "adjustment": "adjusted",
            "unresolved_corporate_actions": False, "listing_status": "ACTIVE", "board": "MAIN",
            "quote": {"price": 10000.0, "previous_close": 10000.0, "as_of": "2026-01-05T09:00:00+07:00",
                      "price_limit_low": 8000.0, "price_limit_high": 12000.0},
            "fees": {"buy": 0.0015, "sell": 0.0025},
            "candles": [{"open_at": f"2025-12-{i:02d}T09:00:00+07:00", "close_at": f"2025-12-{i:02d}T16:00:00+07:00",
                         "open": 9900.0, "high": 10100.0, "low": 9800.0, "close": 10000.0, "volume": 50000, "is_closed_candle": True}
                        for i in range(1, 26)],
        }, self.policy)
        packet = ResearchPacket("ICBP", "IDX CASH EQUITY", "D1", quant.price, quant.decision, quant.data_quality, quant.setup_quality,
                                regime=quant.regime, decision_reason=quant.decision_reason, reward_risk_str="1:2.0",
                                rr_gate_passed=True, entry_zone="Rp10,000", stop_price=9800.0, tp1=10400.0,
                                leverage_ceiling="-", fundamentals=data, currency="IDR", asset_type="EQUITY_ID")
        out = render_equity(packet, quant, asset, "valuasi ICBP", language="ID")
        self.assertIn("Price to Book (PBV): 2.80x", out)
        self.assertIn("Price to Earnings (PER): 14.50x", out)
        self.assertIn("ROE: 19.30%", out)
        self.assertIn("Operating Margin: 21.00%", out)
        self.assertIn("Debt to Equity (DER): 0.75x", out)

    def test_backtest_with_history_expansion(self):
        req = self.router.parse("backtest TLKM 5 tahun")
        self.assertEqual(req.request_type, "BACKTEST")
        self.assertEqual(req.asset, "TLKM")
        with patch.object(EquityData, "fetch_live_data") as mock_fetch:
            # 60 daily candles spanning 2021 to 2026
            candles = [
                {"open_at": f"2023-01-{i:02d}T09:00:00+07:00", "close_at": f"2023-01-{i:02d}T16:00:00+07:00",
                 "open": 3500.0 + i * 2, "high": 3550.0 + i * 2, "low": 3480.0 + i * 2, "close": 3520.0 + i * 2,
                 "volume": 200000, "is_closed_candle": True}
                for i in range(1, 30)
            ] + [
                {"open_at": f"2024-01-{i:02d}T09:00:00+07:00", "close_at": f"2024-01-{i:02d}T16:00:00+07:00",
                 "open": 3600.0 + i * 2, "high": 3650.0 + i * 2, "low": 3580.0 + i * 2, "close": 3620.0 + i * 2,
                 "volume": 200000, "is_closed_candle": True}
                for i in range(1, 30)
            ]
            mock_fetch.return_value = {
                "symbol": "TLKM", "authorized_use": True, "source": "https://finance.yahoo.com/quote/TLKM.JK",
                "retrieved_at": "2026-01-05T09:00:00+07:00", "currency": "IDR", "volume_unit": "shares", "timeframe": "D1",
                "adjustment": "adjusted", "unresolved_corporate_actions": False, "listing_status": "ACTIVE", "board": "MAIN",
                "quote": {"price": 3700.0, "previous_close": 3680.0, "as_of": "2026-01-05T09:00:00+07:00",
                          "price_limit_low": 2960.0, "price_limit_high": 4440.0},
                "fees": {"buy": 0.0015, "sell": 0.0025}, "candles": candles, "gaps": []
            }
            EquityData(self.root).store(mock_fetch.return_value, "TLKM")
            res = self.runner.execute(req, SessionState())
            self.assertIn("Total Trades", res)
            self.assertIn("Win Rate", res)


if __name__ == "__main__":
    unittest.main()
