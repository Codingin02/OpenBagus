"""Verified IDX identities with explicit, user-owned catalog expansion."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from datetime import date
from urllib.parse import urlsplit

from openbagus.core.guards import scan_text

SECTORS = {
    "A": ("Energy", "Energi"), "B": ("Basic Materials", "Barang Baku"),
    "C": ("Industrials", "Perindustrian"),
    "D": ("Consumer Non-Cyclicals", "Barang Konsumen Primer"),
    "E": ("Consumer Cyclicals", "Barang Konsumen Non-Primer"),
    "F": ("Healthcare", "Kesehatan"), "G": ("Financials", "Keuangan"),
    "H": ("Properties & Real Estate", "Properti & Real Estat"),
    "I": ("Technology", "Teknologi"), "J": ("Infrastructures", "Infrastruktur"),
    "K": ("Transportation & Logistics", "Transportasi & Logistik"),
}


def source_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        raise ValueError("Source must be a public HTTPS document URL without credentials/query")
    if not scan_text(value)["passed"]:
        raise ValueError("Unsafe source metadata")
    return value


@dataclass
class EquityAsset:
    symbol: str
    name: str
    sector_code: str = ""
    industry: str = ""
    source: str = ""
    effective_date: str = ""
    listing_status: str = "UNKNOWN"
    board: str = "UNKNOWN"
    asset_type: str = "EQUITY_ID"
    currency: str = "IDR"
    exchange_or_chain: str = "IDX"
    data_capabilities: list[str] = field(default_factory=lambda: ["permitted_import"])
    exposures: list[str] = field(default_factory=list)
    hierarchy: list[str] = field(default_factory=list)
    listing_date: str = ""
    shares_outstanding: float = 0.0

    @property
    def id(self) -> str:
        return f"IDX:{self.symbol}"

    @property
    def canonical_symbol(self) -> str:
        return self.symbol

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def categories(self) -> list[str]:
        return [SECTORS[self.sector_code][0]] if self.sector_code else ["IDX Index"]

    @property
    def sector_or_category(self) -> str:
        return self.categories[0]

    @property
    def rank(self) -> int:
        return 9999

    def matches(self, value: str) -> bool:
        v = value.strip()
        v_clean = re.sub(r"\b(pt|tbk)\b", "", v, flags=re.I).strip(" .").lower()
        name_clean = re.sub(r"\b(pt|tbk)\b", "", self.name, flags=re.I).strip(" .").lower()
        return (v.upper() in {self.symbol, self.id, f"{self.symbol}.JK"}
                or v.lower() == self.name.lower()
                or (bool(v_clean) and v_clean == name_clean))


class EquityCatalog:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "data/equities/catalog.json"
        self.assets: list[EquityAsset] = []
        # Seeds identify instruments, not today's listing/suspension status or the full IDX universe.
        seeds = [("BBCA", "Bank Central Asia", "G"), ("BBRI", "Bank Rakyat Indonesia", "G"),
                 ("BMRI", "Bank Mandiri", "G"), ("TLKM", "Telkom Indonesia", "J"),
                 ("ASII", "Astra International", "C"), ("ANTM", "Aneka Tambang", "B")]
        for symbol, name, sector in seeds:
            self.assets.append(EquityAsset(symbol, name, sector,
                source=f"https://www.idx.co.id/id/perusahaan-tercatat/profil-perusahaan-tercatat/{symbol}"))
        self.assets.append(EquityAsset("RATU", "PT Raharja Energi Cepu Tbk", "A",
            source="https://web.ksei.co.id/services/registered-securities/shares/lc/RATU",
            listing_date="2025-01-08", exposures=["oil", "gas"]))
        self.assets.append(EquityAsset("IHSG", "IDX Composite", asset_type="INDEX_ID",
            source="https://www.idx.co.id/id/produk/indeks/"))
        for symbol in ("LQ45", "IDX30", "IDXENERGY", "IDXBASIC", "IDXINDUST", "IDXNONCYC",
                       "IDXCYCLIC", "IDXHEALTH", "IDXFINANCE", "IDXPROPERT", "IDXTECHNO", "IDXINFRA", "IDXTRANS"):
            self.assets.append(EquityAsset(symbol, symbol, asset_type="INDEX_ID",
                source="https://www.idx.co.id/id/produk/indeks/"))
        antm = next((a for a in self.assets if a.symbol == "ANTM"), None)
        if antm:
            antm.exposures = ["nickel", "gold"]

        loaded = False
        if self.path.exists():
            try:
                rows = json.loads(self.path.read_text(encoding="utf-8"))
                if rows:
                    self._merge([self._validate(row) for row in rows])
                    loaded = True
            except (OSError, ValueError, TypeError, KeyError):
                pass
        if not loaded:
            bundled = Path(__file__).parent / "idx_universe.json"
            if bundled.exists():
                try:
                    rows = json.loads(bundled.read_text(encoding="utf-8"))
                    self._merge([self._validate(row) for row in rows])
                except (OSError, ValueError, TypeError, KeyError):
                    pass

    @staticmethod
    def _validate(row: dict) -> EquityAsset:
        symbol = str(row.get("symbol", "")).upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,14}", symbol):
            raise ValueError("Invalid IDX symbol")
        if row.get("sector_code", "") not in {*SECTORS, ""} or row.get("asset_type", "EQUITY_ID") not in {"EQUITY_ID", "INDEX_ID"}:
            raise ValueError("Invalid IDX classification")
        if not row.get("name") or not row.get("effective_date"):
            raise ValueError("Identity requires name and classification effective_date")
        date.fromisoformat(row["effective_date"])
        if row.get("currency", "IDR") != "IDR" or row.get("exchange_or_chain", "IDX") != "IDX":
            raise ValueError("Catalog accepts Indonesian IDR instruments only")
        if row.get("listing_status", "UNKNOWN") not in {"UNKNOWN", "ACTIVE", "SUSPENDED", "DELISTED"}:
            raise ValueError("Invalid listing status")
        hierarchy = row.get("hierarchy", [])
        if hierarchy and not all(isinstance(code, str) and code.startswith(row["sector_code"]) for code in hierarchy):
            raise ValueError("Hierarchy must use verified IDX-IC codes belonging to its sector")
        source_url(row.get("source", ""))
        text_content = " ".join(str(v) for v in row.values() if isinstance(v, str))
        if not scan_text(text_content)["passed"]:
            raise ValueError("Unsafe catalog metadata")
        import dataclasses
        valid_fields = {f.name for f in dataclasses.fields(EquityAsset)}
        clean_row = {k: v for k, v in row.items() if k in valid_fields}
        return EquityAsset(**clean_row)

    def _merge(self, assets: list[EquityAsset]) -> None:
        existing = {a.symbol: a for a in self.assets}
        existing.update({a.symbol: a for a in assets})
        self.assets = list(existing.values())

    def import_file(self, path: Path) -> int:
        if path.stat().st_size > 10_000_000:
            raise ValueError("Catalog exceeds import limit")
        if path.suffix.lower() == ".csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                for key in ("hierarchy", "exposures", "data_capabilities"):
                    if key in row:
                        row[key] = [s for s in row[key].split(";") if s]
        else:
            rows = json.loads(path.read_text(encoding="utf-8"))
        assets = [self._validate(row) for row in rows]
        self._merge(assets)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(a) for a in self.assets if a.effective_date], indent=2), encoding="utf-8")
        return len(assets)

    def resolve(self, term: str) -> EquityAsset | None:
        return next((a for a in self.assets if a.matches(term.strip())), None)

    def search(self, query: str, limit: int = 20) -> list[EquityAsset]:
        q = query.strip().lower()
        if not q:
            return self.assets[:limit]
        exact = [a for a in self.assets if a.symbol.lower() == q]
        starts = [a for a in self.assets if a.symbol.lower().startswith(q) and a not in exact]
        name_match = [a for a in self.assets if q in a.name.lower() and a not in exact and a not in starts]
        industry_match = [a for a in self.assets if q in a.industry.lower() and a not in exact and a not in starts and a not in name_match]
        results = exact + starts + name_match + industry_match
        return results[:limit]

    def by_sector(self, sector_query: str, limit: int = 50) -> list[EquityAsset]:
        sq = sector_query.strip().upper()
        if sq in SECTORS:
            return [a for a in self.assets if a.sector_code == sq][:limit]
        sq_lower = sector_query.strip().lower()
        matched_codes = set()
        for code, (en_name, id_name) in SECTORS.items():
            if sq_lower in en_name.lower() or sq_lower in id_name.lower():
                matched_codes.add(code)
        if matched_codes:
            return [a for a in self.assets if a.sector_code in matched_codes][:limit]
        return [a for a in self.assets if sq_lower in a.industry.lower()][:limit]

    def recent_ipos(self, since_year: int = 2024, limit: int = 30) -> list[EquityAsset]:
        cutoff = f"{since_year}-01-01"
        ipos = [a for a in self.assets if a.listing_date and a.listing_date >= cutoff and a.asset_type == "EQUITY_ID"]
        ipos.sort(key=lambda a: a.listing_date, reverse=True)
        return ipos[:limit]

    def sync(self, force_download: bool = False) -> dict:
        bundled = Path(__file__).parent / "idx_universe.json"
        if bundled.exists():
            rows = json.loads(bundled.read_text(encoding="utf-8"))
            validated = [self._validate(r) for r in rows]
            self._merge(validated)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps([asdict(a) for a in self.assets if a.effective_date], indent=2), encoding="utf-8")
        equities_count = sum(1 for a in self.assets if a.asset_type == "EQUITY_ID")
        indices_count = sum(1 for a in self.assets if a.asset_type == "INDEX_ID")
        return {
            "status": "SYNCED",
            "total_assets": len(self.assets),
            "equities_count": equities_count,
            "indices_count": indices_count,
            "path": str(self.path),
        }

