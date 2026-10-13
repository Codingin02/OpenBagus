"""Autonomous Document Discovery and Local Intake Index.

Indexes public disclosure availability across all 11 IDX sectors and boards,
tracks missing fiscal periods, provides official retrieval guidance, and
monitors local inbox for user-assisted filings intake.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
from typing import Any

from openbagus.domains.equities.catalog import EquityCatalog, SECTORS
from openbagus.domains.equities.storage import FinancialStatementStorage

logger = logging.getLogger(__name__)

# Known Investor Relations portals for representative issuers across sectors
KNOWN_IR_PORTALS: dict[str, str] = {
    # Sector A (Energy)
    "ADRO": "https://www.adaro.com/investor-relations/reports-presentations/",
    "PTBA": "https://www.ptba.co.id/hubungan-investor/laporan-keuangan",
    "PGAS": "https://ir.pgas.co.id/financial-reports",
    "MEDC": "https://www.medcoenergi.com/en/investor-relations",
    # Sector B (Basic Materials)
    "ANTM": "https://www.antam.com/id/financial-reports",
    "INCO": "https://vale.com/indonesia/investors",
    "MDKA": "https://merdekacoppergold.com/investor-relations/",
    # Sector C (Industrials)
    "ASII": "https://www.astra.co.id/investor-relations/financial-report",
    "UNTR": "https://www.unitedtractors.com/investor-relations/",
    # Sector D (Consumer Non-Cyclicals)
    "ICBP": "https://www.indofoodcbp.com/investor-relation/financial-statements",
    "INDF": "https://www.indofood.com/investor-relation/financial-statements",
    "UNVR": "https://www.unilever.co.id/investor-relations/laporan-keuangan/",
    "MYOR": "https://www.mayora.com/investor-relations/financial-information/",
    # Sector E (Consumer Cyclicals)
    "ACES": "https://corporate.acehardware.co.id/id/investor-relations/laporan-keuangan",
    "MAPI": "https://www.map.co.id/investor-relations/financial-report/",
    # Sector F (Healthcare)
    "KLBF": "https://www.kalbe.co.id/investor-relations/financial-reports",
    "MIKA": "https://www.mitrakeluarga.com/investor-relations/financial-reports",
    "HEAL": "https://www.herminahospitals.com/id/investor-relations",
    # Sector G (Financials)
    "BBCA": "https://www.bca.co.id/id/tentang-bca/hubungan-investor/laporan-keuangan",
    "BBRI": "https://ir-bri.com/financial_reports.html",
    "BMRI": "https://www.bankmandiri.co.id/laporan-keuangan",
    "BBNI": "https://www.bni.co.id/id-id/beranda/tentang-bni/hubungan-investor/laporan-keuangan",
    # Sector H (Properties)
    "BSDE": "https://www.sinarmasland.com/investor-relations/bsde/financial-reports/",
    "CTRA": "https://ciputradevelopment.com/investor-relations/financial-reports/",
    # Sector I (Technology)
    "GOTO": "https://www.gotocompany.com/investor-relations/financials",
    "BUKK": "https://bukaka.com/investor-relations/financial-reports/",
    # Sector J (Infrastructures)
    "TLKM": "https://www.telkom.co.id/sites/about-telkom/id_ID/investor-relation",
    "ISAT": "https://ioh.co.id/portal/id/iohcorporate-investor-relations",
    "TOWR": "https://www.sarana-menara.com/investor-relations/financial-reports/",
    # Sector K (Transportation)
    "BIRD": "https://www.bluebirdgroup.com/investor-relations/financial-reports/",
    "SMDR": "https://www.samudera.id/id/investor-relations/financial-reports",
}


class DocumentDiscoveryManager:
    """Manages document discovery, local inbox intake, and filing completeness tracking."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.storage = FinancialStatementStorage(self.root)
        self.catalog = EquityCatalog(self.root)
        self.inbox_dir = self.root / "data" / "equities" / "inbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

    def get_issuer_discovery(self, symbol: str) -> dict[str, Any]:
        """Returns document status, missing periods, and official retrieval guidance for symbol."""
        clean_sym = symbol.strip().upper()
        asset = next((a for a in self.catalog.assets if a.symbol == clean_sym), None)

        available_periods = self.storage.list_periods(clean_sym)
        expected_recent = ["2022-FY", "2023-FY", "2024-Q1", "2024-H1", "2024-9M", "2024-FY"]
        missing_periods = [p for p in expected_recent if p not in available_periods]

        idx_official_url = f"https://www.idx.co.id/perusahaan-tercatat/laporan-keuangan-dan-tahunan/?kodeEmiten={clean_sym}"
        ir_portal = KNOWN_IR_PORTALS.get(clean_sym)

        return {
            "symbol": clean_sym,
            "name": asset.name if asset else clean_sym,
            "sector": asset.sector_or_category if asset else "UNKNOWN",
            "board": asset.canonical_board if asset else "UNKNOWN",
            "listing_status": asset.canonical_status if asset else "UNKNOWN",
            "available_periods": available_periods,
            "missing_periods": missing_periods,
            "idx_official_url": idx_official_url,
            "ir_portal_url": ir_portal,
            "inbox_directory": str(self.inbox_dir),
            "guidance": (
                f"Untuk memuat laporan {clean_sym} yang belum tersedia:\n"
                f"1. Unduh dokumen resmi (XBRL .zip, .xlsx, atau .pdf) dari {idx_official_url}\n"
                f"2. Simpan di folder inbox: {self.inbox_dir}\n"
                f"3. Jalankan: /data import financials {self.inbox_dir}/<nama_file> {clean_sym}"
            ),
        }

    def scan_inbox(self) -> list[Path]:
        """Discovers valid financial disclosure documents waiting in the inbox directory."""
        supported_exts = {".zip", ".xbrl", ".xml", ".xlsx", ".pdf", ".csv", ".json"}
        found: list[Path] = []
        if not self.inbox_dir.exists():
            return found

        for item in self.inbox_dir.iterdir():
            if item.is_file() and item.suffix.lower() in supported_exts:
                found.append(item)
        return found

    def get_market_coverage_matrix(self) -> dict[str, Any]:
        """Provides financial report coverage statistics across all 11 IDX sectors and boards."""
        summary = self.storage.get_coverage_summary()
        symbols_with_filings = set(summary["symbols"].keys())

        sector_stats: dict[str, dict[str, int]] = {}
        for code, (eng, ind) in SECTORS.items():
            sector_stats[eng] = {"total_issuers": 0, "covered_issuers": 0}

        board_stats: dict[str, dict[str, int]] = {
            "MAIN": {"total_issuers": 0, "covered_issuers": 0},
            "DEVELOPMENT": {"total_issuers": 0, "covered_issuers": 0},
            "ACCELERATION": {"total_issuers": 0, "covered_issuers": 0},
            "SPECIAL_MONITORING": {"total_issuers": 0, "covered_issuers": 0},
            "UNKNOWN": {"total_issuers": 0, "covered_issuers": 0},
        }

        for asset in self.catalog.assets:
            if asset.asset_type != "EQUITY_ID":
                continue
            sec_name = SECTORS.get(asset.sector_code, ("Other", "Lainnya"))[0]
            if sec_name in sector_stats:
                sector_stats[sec_name]["total_issuers"] += 1
                if asset.symbol in symbols_with_filings:
                    sector_stats[sec_name]["covered_issuers"] += 1

            b_name = asset.canonical_board
            if b_name in board_stats:
                board_stats[b_name]["total_issuers"] += 1
                if asset.symbol in symbols_with_filings:
                    board_stats[b_name]["covered_issuers"] += 1

        return {
            "total_issuers_in_catalog": len([a for a in self.catalog.assets if a.asset_type == "EQUITY_ID"]),
            "issuers_with_filings": len(symbols_with_filings),
            "total_statements_stored": summary["total_statements"],
            "by_sector": sector_stats,
            "by_board": board_stats,
        }
